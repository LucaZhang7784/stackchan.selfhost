"""Qwen-Realtime 测试 (官方 demo 同款 websockets 库 + 任务异常可见化)。"""

import argparse
import asyncio
import base64
import json
import sys
import time
import uuid
import wave

import websockets


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--wav", required=True)
    ap.add_argument("--model", default="qwen-audio-3.0-realtime-flash")
    ap.add_argument("--manual", action="store_true")
    args = ap.parse_args()

    with wave.open(args.wav, "rb") as wf:
        rate = wf.getframerate()
        data = wf.readframes(wf.getnframes())

    url = f"wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={args.model}"
    async with websockets.connect(
        url, additional_headers={"Authorization": f"Bearer {args.key}"}
    ) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "event_id": uuid.uuid4().hex,
                    "session": {
                        "modalities": ["text", "audio"],
                        "voice": "longanqian",
                        "instructions": "你是测试助手, 每次只回复一句话。",
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm",
                        "turn_detection": {
                            "type": "smart_turn",
                            "threshold": 0.1,
                            "silence_duration_ms": 1500,
                        },
                    },
                }
            )
        )
        print("[ok] session.update sent")

        packet_bytes = rate * 2 * 100 // 1000
        sent = 0
        pump_done = asyncio.Event()

        async def pump():
            nonlocal sent
            try:
                audio = data + b"\x00\x00" * (rate // 10) * 20  # 语音 + 2s 静音
                for i in range(0, len(audio) - len(audio) % packet_bytes, packet_bytes):
                    await ws.send(
                        json.dumps(
                            {
                                "type": "input_audio_buffer.append",
                                "event_id": uuid.uuid4().hex,
                                "audio": base64.b64encode(
                                    audio[i : i + packet_bytes]
                                ).decode(),
                            }
                        )
                    )
                    sent += 1
                    await asyncio.sleep(0.1)
                if args.manual:
                    await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    await ws.send(
                        json.dumps(
                            {
                                "type": "response.create",
                                "event_id": uuid.uuid4().hex,
                                "client_timestamp": int(time.time() * 1000),
                            }
                        )
                    )
                    print("[ok] manual commit + response.create sent")
                print(f"[pump] done, sent {sent} chunks")
            except Exception as e:
                print(f"[pump] EXC {type(e).__name__}: {e}")
            finally:
                pump_done.set()

        task = asyncio.create_task(pump())
        seen = {}
        audio_deltas = 0
        try:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(), timeout=max(0.5, deadline - time.monotonic())
                    )
                except asyncio.TimeoutError:
                    if pump_done.is_set():
                        break
                    continue
                except websockets.exceptions.ConnectionClosed as e:
                    print(f"[closed] code={e.rcvd.code if e.rcvd else e.code} reason={e.rcvd.reason if e.rcvd else ''}")
                    break
                data = json.loads(raw)
                t = data.get("type")
                seen[t] = seen.get(t, 0) + 1
                if t not in ("session.created", "session.updated", "response.audio.delta"):
                    print(f"[evt] {t} {str(data)[:100]}")
                if t == "response.audio.delta":
                    audio_deltas += 1
                elif t == "response.done":
                    print("[ok] response.done")
                    break
                elif t == "error":
                    print(f"[error] {data}")
                    break
        finally:
            task.cancel()

        print(f"[sent] {sent} chunks | [event-count] {seen} | audio_deltas={audio_deltas}")
        if audio_deltas > 0:
            print("[PASS] 端到端音频返回正常")
        else:
            print("[NOTE] 未收到音频增量")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
