# StackChan Self-Hosted Link (stackchan.selfhost)

Connect an M5Stack CoreS3 StackChan robot to a **self-hosted** xiaozhi-esp32-server
behind a **Tailscale Funnel** (for isolated LANs), enabling low-latency voice chat,
**true interruptive push announcements**, and voice control of 4 local AI agents
(codex / claude / agy / pi).

> Independent from the xiaozhi.me cloud link. Switching between links = manual
> app-only firmware flash.

## Architecture

```
Robot (CoreS3, firmware v1.0.8-selfhost)
  │ voice via Tailscale Funnel 443 (LAN AP isolation, no direct access)
  ▼
Tailscale Funnel → funnel_proxy.py (8090) → xiaozhi-esp32-server (docker 8000/8003)
  │ ASR=Aliyun Bailian paraformer-realtime-v2 (streaming)
  │ LLM=DeepSeek deepseek-v4-flash (reasoning off)
  │ TTS=EdgeTTS Cantonese (+20%)
  │ Tools: server-side MCP → fusion gateway (8010, 11 tools)
  ▼
Fusion gateway → 4 agents (visible-window execution, hooks flow back)
```

## Quick Start

1. **Server**: `cd server; cp data/.config.yaml.example data/.config.yaml; docker compose -f docker-compose.yml -f ../server-patch.yml up -d`
2. **Funnel proxy**: enable Tailscale Funnel → local 8090, run `python server/funnel_proxy.py`
3. **Gateway**: `cd gateway; cp config.json.example config.json; powershell -File run_gateway.ps1`
4. **Firmware**: flash `firmware/post-fw-v1.0.8-selfhost/xiaozhi.bin` (app-only @ 0x410000),
   or rebuild with your own OTA URL per `firmware/patches/PATCHES.md`
5. **Prompt**: put `prompt-阿松-v3.md` content into the server `prompt:` section

## Changelog

### v1.0.8 (2026-08-04) — Wake reliability

- **Fixed "wake does nothing"**: when the warm channel is already open, the direct wake
  path returned early because `ContinueWakeWordInvoke` requires the `connecting` state →
  set state first, wake now always enters listening.
- **Fixed garbage wake words**: out-of-range `command_id` from a false model trigger
  caused an out-of-bounds read (e.g. "偷偷吓我" used as a wake word) → bounds check,
  only "阿松 / 你好小智" can wake.
- **Fixed LED state lock**: `led_manual_` no longer freezes listening-blue / speaking-green;
  manual color is only kept in standby.
- **Active broadcast**: codex task completion is actively pushed to the robot by default
  (`push_direct_done` in `gateway/config.json`; disable temporarily during wake tests).
- **Observability**: server ASR timing logs (`ASR 会话开始` → `ASR 识别耗时 X.XXs`).

## Known Limits

- Depends on this PC being online (Tailscale). Robot is unusable if the PC/server is off.
- Device-side AEC is disabled (it hangs audio_input); mic is turned off during broadcast
  to mitigate echo.
- EdgeTTS free voices have limited naturalness.

## Credits

- [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)
- [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)
- [stackchan-claude-bridge](https://github.com/heavenchenggong/stackchan-claude-bridge)
- [StackChan-HtSz](https://github.com/mo-hantang/StackChan-HtSz)
