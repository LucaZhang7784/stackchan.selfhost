# StackChan Self-Hosted Link (stackchan.selfhost)

Connect an M5Stack CoreS3 StackChan robot to a **self-hosted** xiaozhi-esp32-server
behind a **Tailscale Funnel** (for isolated LANs), enabling low-latency voice chat,
**true interruptive push announcements**, and voice control of 4 local AI agents
(codex / claude / agy / pi).

> Independent from the xiaozhi.me cloud link. Switching between links = manual
> app-only firmware flash.

## Architecture

```
Robot (CoreS3, firmware v1.0.7g-selfhost)
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
4. **Firmware**: flash `firmware/post-fw-v1.0.7g-selfhost/xiaozhi.bin` (app-only @ 0x410000),
   or rebuild with your own OTA URL per `firmware/patches/PATCHES.md`
5. **Prompt**: put `prompt-阿松-v3.md` content into the server `prompt:` section

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
