# StackChan 自部署 server（xiaozhi-esp32-server 单模块 + MCP 接入点）

替代 xiaozhi.me 云端。HtSz 固件 → 本 server → MCP 接入点 → bridge → Codex。

## 组成

| 容器 | 端口 | 职责 |
|------|------|------|
| xiaozhi-esp32-server | 8000(WS) / 8003(HTTP+OTA+视觉) | 语音链路 ASR→LLM→TTS，OTA 下发 |
| mcp-endpoint-server | 8004 | MCP 接入点：bridge 与 server 都连它，工具聚合路由 |

## 模型选型

- **LLM**：MiMo mimo-v2.5-pro（token-plan 端点）｜备选 DeepSeek（改 `data/.config.yaml` 的 `selected_module.LLM` 一行切换）
- **VLLM**：MiMo mimo-v2.5（拍照识物）
- **ASR**：Qwen3-ASR-Flash（阿里百炼，zh/en/ja/yue + 自动语种检测）
- **TTS**：EdgeTTS（免费四语种）

## 使用

```bash
cd server
docker compose up -d
docker logs -f xiaozhi-esp32-server
```

### 首次启动后要做的两件事

1. **拿 MCP 接入点 token**：`docker logs mcp-endpoint-server` 找到
   `单模块部署MCP接入点: ws://...:8004/mcp_endpoint/mcp/?token=XXX`，
   把 token 回填到 `data/.config.yaml` 的 `mcp_endpoint`，然后 `docker compose restart xiaozhi-esp32-server`
2. **回填设备 MAC**：刷机后把 StackChan 真实 MAC 填到 `data/.config.yaml` 的
   `server.auth.allowed_devices`（替换占位 `11:22:33:44:55:66`）

## 密钥

`.env` 注入 `MIMO_API_KEY` / `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY`。
`.env` 与 `data/` 已加入 `.gitignore`，不入库。

## 网络

- LAN 地址 `10.31.28.184` 写死在 `data/.config.yaml`（OTA 下发用）。换网络环境需改。
- 公司网 AP 隔离场景：装 Tailscale 后把上面两个地址换成 Tailscale IP。
