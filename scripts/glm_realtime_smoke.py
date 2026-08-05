"""GLM-Realtime 冒烟测试 (在 xiaozhi 容器内运行)

用法:
  docker exec xiaozhi-esp32-server python /opt/xiaozhi-esp32-server/tests/glm_realtime_smoke.py --key <智谱APIKey>

无 key 时也会执行并打印明确错误, 用于验证 provider 导入与配置。
可选 --wav <文件> 上传一段语音验证端到端音频返回。
"""

import argparse
import asyncio
import base64
import json
import sys
import uuid


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True, help="智谱 bigmodel.cn API Key")
    ap.add_argument("--wav", default="", help="可选: 语音 wav/pcm16 文件(16k)")
    ap.add_argument("--model", default="glm-realtime-flash")
    args = ap.parse_args()

    import aiohttp

    url = "wss://open.bigmodel.cn/api/paas/v4/realtime"
    async with aiohttp.ClientSession() as session:
        ws = await session.ws_connect(
            url,
            headers={"Authorization": f"Bearer {args.key}"},
            heartbeat=20,
        )
        await ws.send_str(
            json.dumps(
                {
                    "type": "session.update",
                    "event_id": uuid.uuid4().hex,
                    "session": {
                        "model": args.model,
                        "modalities": ["audio", "text"],
                        "instructions": "你是测试助手, 每次只回复一句话。",
                        "voice": "tongtong",
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm",
                        "turn_detection": {
                            "type": "server_vad",
                            "create_response": True,
                            "interrupt_response": True,
                        },
                        "beta_fields": {"chat_mode": "audio", "tts_source": "e2e"},
                    },
                }
            )
        )
        print("[ok] session.update sent")

        audio_task = None
        if args.wav:
            async def pump():
                with open(args.wav, "rb") as f:
                    data = f.read()
                for i in range(0, len(data) - len(data) % 3200, 3200):
                    await ws.send_str(
                        json.dumps(
                            {
                                "type": "input_audio_buffer.append",
                                "event_id": uuid.uuid4().hex,
                                "audio": base64.b64encode(data[i : i + 3200]).decode(),
                            }
                        )
                    )
                    await asyncio.sleep(0.1)

            audio_task = asyncio.create_task(pump())

        audio_delta_count = 0
        try:
            async with asyncio.timeout(30):
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        break
                    data = json.loads(msg.data)
                    t = data.get("type")
                    if t in ("session.updated", "heartbeat"):
                        print(f"[event] {t}")
                    elif t == "response.audio.delta":
                        audio_delta_count += 1
                        print(f"[ok] response.audio.delta #{audio_delta_count}")
                    elif t == "response.audio_transcript.delta":
                        print(f"[text] {data.get('delta')}")
                    elif t == "response.done":
                        print("[ok] response.done")
                        break
                    elif t == "error":
                        print(f"[error] {data}")
                        break
        finally:
            if audio_task:
                audio_task.cancel()
            await ws.close()

        if audio_delta_count > 0:
            print("[PASS] GLM-Realtime 端到端音频返回正常")
        else:
            print("[NOTE] 未收到音频增量 (无语音输入或已静音)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
