"""GLM-Realtime 实时语音 LLM (智谱 bigmodel.cn)

端到端语音对话: 设备 PCM(16k) -> input_audio_buffer.append ->
GLM-Realtime(server VAD 自动断句/打断) -> response.audio.delta(24k PCM)
-> 重采样 16k -> opus -> 设备。

选择 GLM-Realtime 的原因 (2026-08 调研):
- DeepSeek / Kimi / MiMo 无官方 realtime 语音 API;
- 智谱官方 WebSocket 实时音视频 API, 支持打断与 function calling;
- 协议与 OpenAI Realtime 同构, 价格: glm-realtime-flash 0.18 元/分钟。

用法: .config.yaml 中 selected_module.LLM = GLMRealtimeLLM 并填写
LLM.GLMRealtimeLLM.api_key (https://bigmodel.cn 申请)。
"""

import asyncio
import base64
import json
import time
import uuid

import aiohttp
import numpy as np
import opuslib_next

from config.logger import setup_logging
from core.providers.llm.base import LLMProviderBase
from core.providers.tts.dto.dto import SentenceType

TAG = __name__
logger = setup_logging()

DEFAULT_URL = "wss://open.bigmodel.cn/api/paas/v4/realtime"
DEVICE_SAMPLE_RATE = 16000
GLM_SAMPLE_RATE = 24000
OPUS_FRAME = 960  # 60ms @16k


class StreamingResampler:
    """24k -> 16k 流式线性插值重采样 (保留全缓冲, 位置连续, 无边界毛刺)。"""

    def __init__(self, in_rate=GLM_SAMPLE_RATE, out_rate=DEVICE_SAMPLE_RATE):
        self.step = in_rate / out_rate
        self._buf = b""
        self._out_count = 0

    def reset(self):
        self._buf = b""
        self._out_count = 0

    def feed(self, pcm16: bytes) -> bytes:
        if not pcm16:
            return b""
        self._buf += pcm16
        n_in = len(self._buf) // 2
        if n_in < 2:
            return b""
        n_out = int((n_in - 1) / self.step) + 1
        if n_out <= self._out_count:
            return b""
        y = np.frombuffer(self._buf, dtype="<i2").astype(np.float32)
        positions = np.arange(self._out_count, n_out) * self.step
        out = np.interp(positions, np.arange(n_in), y).astype("<i2").tobytes()
        self._out_count = n_out
        return out


class LLMProvider(LLMProviderBase):
    """GLM-Realtime 实时语音 provider (不实现文本 response 接口, 仅实时链路)。"""

    is_realtime = True

    def __init__(self, config):
        self.api_key = str(config.get("api_key") or "")
        self.base_url = str(config.get("base_url") or DEFAULT_URL)
        self.model = str(config.get("model") or "glm-realtime-flash")
        self.voice = str(config.get("voice") or "tongtong")
        self.instructions = str(config.get("instructions") or "")
        self.tools_enabled = bool(config.get("tools", True))
        self.temperature = float(config.get("temperature", 0.7))
        self.conn = None
        self._session = None
        self._ws = None
        self._task = None
        self._closing = False
        self._reconnect_attempts = 0
        self._sentence_id = None
        self._resampler = StreamingResampler()
        self._opus = opuslib_next.Encoder(DEVICE_SAMPLE_RATE, 1, "voip")
        self._transcript = ""
        self._tool_queue = []
        self._response_in_progress = False
        self._emotion_done = False
        self._tools_refresh_task = None

    # ---- 文本接口占位 (实时模式下不会走 chat()) ----
    def response(self, session_id, dialogue):
        return iter(())

    def response_with_functions(self, session_id, dialogue, functions=None):
        return iter(())

    # ---- 生命周期 ----
    async def start(self, conn):
        """在连接的事件循环中启动实时会话 (由 connection.py 调用)。"""
        self.conn = conn
        self._closing = False
        self._sentence_id = uuid.uuid4().hex
        conn.sentence_id = self._sentence_id
        self._task = asyncio.create_task(self._run())
        return self._task

    async def stop(self):
        self._closing = True
        if self._tools_refresh_task and not self._tools_refresh_task.done():
            self._tools_refresh_task.cancel()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        await self._cleanup_ws()

    def resync_sentence_id(self):
        """fusion_push 播放结束后恢复实时链路 sentence_id, 避免后续音频被丢弃。"""
        if self.conn and self._sentence_id:
            self.conn.sentence_id = self._sentence_id

    async def cancel(self):
        """打断: 取消当前响应并清空输入缓冲 (双击/推送触发)。"""
        if self._ws and not self._ws.closed:
            try:
                await self._ws.send_str(
                    json.dumps(
                        {
                            "type": "response.cancel",
                            "event_id": uuid.uuid4().hex,
                        }
                    )
                )
                await self._ws.send_str(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.clear",
                            "event_id": uuid.uuid4().hex,
                        }
                    )
                )
            except Exception as e:
                logger.bind(tag=TAG).debug(f"cancel 发送失败: {e}")
        self._resampler.reset()
        self._transcript = ""
        self._tool_queue = []
        self._response_in_progress = False
        if self.conn:
            self.conn.client_abort = False  # 打断已被 GLM 侧消费

    # ---- 音频上行 ----
    async def send_audio(self, pcm_frame: bytes):
        if self._ws is None or self._ws.closed or not pcm_frame:
            return
        if getattr(self.conn, "client_abort", False):
            return
        try:
            await self._ws.send_str(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "event_id": uuid.uuid4().hex,
                        "audio": base64.b64encode(pcm_frame).decode("ascii"),
                    }
                )
            )
        except Exception as e:
            logger.bind(tag=TAG).debug(f"上传音频失败: {e}")

    # ---- 主循环 ----
    async def _run(self):
        while not self._closing:
            try:
                await self._connect_and_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.bind(tag=TAG).error(f"GLM-Realtime 连接异常: {e}")
            if self._closing:
                break
            self._reconnect_attempts += 1
            if self._reconnect_attempts > 5:
                logger.bind(tag=TAG).error("GLM-Realtime 连续重连失败, 停止重连")
                break
            delay = min(2**self._reconnect_attempts, 15)
            logger.bind(tag=TAG).info(f"GLM-Realtime {delay}s 后重连 (第 {self._reconnect_attempts} 次)")
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break

    async def _connect_and_loop(self):
        if not self.api_key:
            logger.bind(tag=TAG).error("GLM-Realtime 未配置 api_key, 无法连接")
            return
        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(
                self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                heartbeat=20,
            )
            self._reconnect_attempts = 0
            await self._send_session_update()
            logger.bind(tag=TAG).info(f"GLM-Realtime 已连接: {self.model}")
            # 延迟刷新工具列表 (MCP 工具初始化可能晚于首帧音频)
            self._tools_refresh_task = asyncio.create_task(self._refresh_tools_later())
            async for msg in self._ws:
                if self._closing:
                    break
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        await self._handle_message(json.loads(msg.data))
                    except Exception as e:
                        logger.bind(tag=TAG).warning(f"GLM 消息处理失败: {e}")
                elif msg.type in (
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSE,
                ):
                    logger.bind(tag=TAG).warning(f"GLM WS 断开: {msg.type}")
                    break
        finally:
            await self._cleanup_ws()

    async def _cleanup_ws(self):
        try:
            if self._ws and not self._ws.closed:
                await self._ws.close()
        except Exception:
            pass
        self._ws = None
        try:
            if self._session:
                await self._session.close()
        except Exception:
            pass
        self._session = None

    async def _send_session_update(self):
        instructions = (
            self.instructions
            or getattr(self.conn, "prompt", None)
            or "你是阿松, 桌面陪伴 AI, 活泼可爱、口语自然, 每次回复 1-2 句话, 不超过 50 字, 适合语音朗读。"
        )
        payload = {
            "type": "session.update",
            "event_id": uuid.uuid4().hex,
            "client_timestamp": int(time.time() * 1000),
            "session": {
                "model": self.model,
                "modalities": ["audio", "text"],
                "instructions": instructions,
                "voice": self.voice,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm",
                "turn_detection": {
                    "type": "server_vad",
                    "create_response": True,
                    "interrupt_response": True,
                },
                "temperature": self.temperature,
                "max_response_output_tokens": "inf",
                "beta_fields": {"chat_mode": "audio", "tts_source": "e2e"},
            },
        }
        tools = self._collect_tools()
        if tools:
            payload["session"]["tools"] = tools
        await self._ws.send_str(json.dumps(payload, ensure_ascii=False))

    def _collect_tools(self):
        if not self.tools_enabled or self.conn is None:
            return []
        handler = getattr(self.conn, "func_handler", None)
        if handler is None:
            return []
        try:
            return list(handler.get_functions())
        except Exception as e:
            logger.bind(tag=TAG).warning(f"获取工具列表失败: {e}")
            return []

    async def _refresh_tools_later(self):
        """连接 8s 后若工具列表已就绪且当前为空, 补发 session.update。"""
        try:
            await asyncio.sleep(8)
            if self._closing or self._ws is None or self._ws.closed:
                return
            tools = self._collect_tools()
            if tools:
                await self._send_session_update()
                logger.bind(tag=TAG).info(f"GLM-Realtime 工具已注入: {len(tools)} 个")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.bind(tag=TAG).debug(f"延迟注入工具失败: {e}")

    # ---- 下行消息处理 ----
    async def _handle_message(self, data: dict):
        msg_type = data.get("type")
        if msg_type in ("session.created", "session.updated", "heartbeat", "conversation.created"):
            return
        if msg_type == "error":
            err = data.get("error") or {}
            logger.bind(tag=TAG).error(f"GLM error: {err.get('code')} {err.get('message')}")
            return
        if msg_type == "response.created":
            self._response_in_progress = True
            self._transcript = ""
            self._tool_queue = []
            self._emotion_done = False
            self._resampler.reset()
            if self.conn and self.conn.tts:
                self.conn.tts.tts_audio_queue.put(
                    (SentenceType.FIRST, None, "", self._sentence_id)
                )
            return
        if msg_type == "response.audio.delta":
            delta = data.get("delta")
            if not delta:
                return
            pcm = base64.b64decode(delta)
            out = self._resampler.feed(pcm)
            if out:
                self._push_opus(out)
            return
        if msg_type == "response.audio_transcript.delta":
            delta = data.get("delta") or ""
            if delta:
                self._transcript += delta
                if not self._emotion_done and self.conn:
                    self._emotion_done = True
                    try:
                        from core.utils import textUtils

                        asyncio.run_coroutine_threadsafe(
                            textUtils.get_emotion(self, self._transcript[:30]),
                            self.conn.loop,
                        )
                    except Exception:
                        pass
            return
        if msg_type == "response.function_call_arguments.done":
            self._tool_queue.append(
                {
                    "name": data.get("name"),
                    "arguments": data.get("arguments") or "{}",
                    "event_id": data.get("event_id"),
                }
            )
            return
        if msg_type == "response.done":
            await self._finish_response()
            return
        if msg_type in (
            "input_audio_buffer.speech_started",
            "input_audio_buffer.speech_stopped",
            "input_audio_buffer.committed",
            "input_audio_buffer.cleared",
        ):
            return

    def _push_opus(self, pcm16: bytes):
        if not self.conn or not self.conn.tts:
            return
        n = len(pcm16)
        frame_bytes = OPUS_FRAME * 2
        for i in range(0, n - n % frame_bytes, frame_bytes):
            try:
                packet = self._opus.encode(pcm16[i : i + frame_bytes], OPUS_FRAME)
            except Exception as e:
                logger.bind(tag=TAG).debug(f"opus 编码失败: {e}")
                continue
            self.conn.tts.tts_audio_queue.put(
                (SentenceType.MIDDLE, packet, self._transcript, self._sentence_id)
            )

    async def _finish_response(self):
        self._response_in_progress = False
        if self._tool_queue:
            await self._run_tools()
            return
        if self.conn and self.conn.tts:
            text = self._transcript or ""
            self.conn.tts.tts_audio_queue.put(
                (SentenceType.LAST, [], text, self._sentence_id)
            )
        self._resampler.reset()
        self._transcript = ""

    async def _run_tools(self):
        """执行 GLM 请求的工具调用, 结果回传后触发新一轮回复。"""
        if not self.conn or not self._tool_queue:
            return
        outputs = []
        for call in self._tool_queue:
            name = call.get("name")
            args = call.get("arguments") or "{}"
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {"raw": args}
            try:
                result = await self.conn.func_handler.handle_llm_function_call(
                    self.conn, {"name": name, "arguments": args}
                )
                outputs.append(
                    {"name": name, "output": getattr(result, "response", str(result))}
                )
            except Exception as e:
                logger.bind(tag=TAG).error(f"工具 {name} 执行失败: {e}")
                outputs.append({"name": name, "output": f"error: {e}"})
        self._tool_queue = []
        if self._ws is None or self._ws.closed:
            return
        for o in outputs:
            try:
                await self._ws.send_str(
                    json.dumps(
                        {
                            "type": "conversation.item.create",
                            "event_id": uuid.uuid4().hex,
                            "item": {
                                "type": "function_call_output",
                                "output": o["output"],
                            },
                        },
                        ensure_ascii=False,
                    )
                )
            except Exception as e:
                logger.bind(tag=TAG).warning(f"回传工具结果失败: {e}")
                return
        try:
            await self._ws.send_str(
                json.dumps(
                    {
                        "type": "response.create",
                        "event_id": uuid.uuid4().hex,
                        "client_timestamp": int(time.time() * 1000),
                    }
                )
            )
        except Exception as e:
            logger.bind(tag=TAG).warning(f"触发续答失败: {e}")
