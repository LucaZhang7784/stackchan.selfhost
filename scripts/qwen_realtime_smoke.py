"""Qwen-Audio-3.0-Realtime 冒烟测试 (容器内运行)

用法:
  docker exec xiaozhi-esp32-server python /tmp/qwen_realtime_smoke.py --key <DashScopeKey> --wav <16k mono pcm/wav>
"""

import argparse
import asyncio
import base64
import io
import json
import sys
import time
import uuid
import wave


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--wav", required=True)
    ap.add_argument("--model", default="qwen-audio-3.0-realtime-flash")
    ap.add_argument("--format", default="pcm16", choices=["pcm", "pcm16"])
    ap.add_argument("--vad", default="smart_turn", choices=["smart_turn", "server_vad"])
    ap.add_argument("--manual", action="store_true", help="音频发完后手动 commit + response.create")
    args = ap.parse_args()

    import aiohttp

    with wave.open(args.wav, "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        rate = wf.getframerate()
        data = wf.readframes(wf.getnframes())
    print(f"wav: rate={rate} ch={ch} sw={sw} dur={round(len(data)/rate/2, 2)}s")

    url = f"wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={args.model}"
    async with aiohttp.ClientSession() as session:
        ws = await session.ws_connect(
            url, headers={"Authorization": f"Bearer {args.key}"}, heartbeat=20
        )
        await ws.send_str(
            json.dumps(
                {
                    "type": "session.update",
                    "event_id": uuid.uuid4().hex,
                    "session": {
                        "modalities": ["text", "audio"],
                        "voice": "longanqian",
                        "instructions": "你是测试助手, 每次只回复一句话。",
                        "input_audio_format": args.format,
                        "output_audio_format": "pcm",
                        "turn_detection": (
                            {"type": "smart_turn", "threshold": 0.1, "silence_duration_ms": 1500}
                            if args.vad == "smart_turn"
                            else {"type": "server_vad", "threshold": 0.2, "silence_duration_ms": 800}
                        ),
                    },
                }
            )
        )
        print(f"[ok] session.update sent (model={args.model}, fmt={args.format}, vad={args.vad})")

        packet_bytes = rate * 2 * 100 // 1000

        async def pump():
            for i in range(0, len(data) - len(data) % packet_bytes, packet_bytes):
                await ws.send_str(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "event_id": uuid.uuid4().hex,
                            "audio": base64.b64encode(data[i : i + packet_bytes]).decode(),
                        }
                    )
                )
                await asyncio.sleep(0.1)
            # smart_turn 需要尾部静音才能判停: 补 3s 静音
            silence = b"\x00\x00" * (rate // 10)  # 100ms
            for _ in range(30):
                await ws.send_str(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "event_id": uuid.uuid4().hex,
                            "audio": base64.b64encode(silence).decode(),
                        }
                    )
                )
                await asyncio.sleep(0.1)
            if args.manual:
                await ws.send_str(json.dumps({"type": "input_audio_buffer.commit"}))
                await ws.send_str(
                    json.dumps(
                        {
                            "type": "response.create",
                            "event_id": uuid.uuid4().hex,
                            "client_timestamp": int(time.time() * 1000),
                        }
                    )
                )
                print("[ok] manual commit + response.create sent")

        task = asyncio.create_task(pump())
        audio_deltas = 0
        transcript = ""
        seen = {}
        try:
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                try:
                    msg = await asyncio.wait_for(
                        ws.receive(), timeout=max(0.5, deadline - time.monotonic())
                    )
                except asyncio.TimeoutError:
                    break
                if msg.type == aiohttp.WSMsgType.CLOSE:
                    print(f"[close] code={msg.data} reason={msg.extra!r}")
                    break
                if msg.type == aiohttp.WSMsgType.CLOSED:
                    print(f"[closed] code={msg.data} reason={msg.extra!r}")
                    break
                if msg.type != aiohttp.WSMsgType.TEXT:
                    print(f"[ws-type] {msg.type}")
                    break
                data = json.loads(msg.data)
                t = data.get("type")
                seen[t] = seen.get(t, 0) + 1
                if t not in (
                    "session.created",
                    "session.updated",
                    "response.audio.delta",
                    "response.audio_transcript.delta",
                ):
                    print(f"[evt] {t} {str(data)[:120]}")
                if t in ("session.created", "session.updated"):
                    print(f"[event] {t}")
                elif t == "input_audio_buffer.speech_started":
                    print("[event] speech_started")
                elif t == "input_audio_buffer.speech_stopped":
                    print("[event] speech_stopped")
                elif t == "response.created":
                    print("[ok] response.created")
                elif t == "response.audio.delta":
                    audio_deltas += 1
                    if audio_deltas % 20 == 1:
                        print(f"[ok] audio.delta #{audio_deltas}")
                elif t == "response.audio_transcript.delta":
                    transcript += data.get("delta") or ""
                    print(f"[text] {transcript}")
                elif t == "response.done":
                    print("[ok] response.done")
                    break
                elif t == "error":
                    print(f"[error] {data}")
                    break
        finally:
            task.cancel()
            await ws.close()

        print(f"[event-count] {seen}")
        if audio_deltas > 0:
            print(f"[PASS] Qwen-Realtime 端到端音频返回正常 ({audio_deltas} deltas)")
        else:
            print("[NOTE] 未收到音频增量")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
