# StackChan 自建链路 (stackchan.selfhost)

把 M5Stack CoreS3 StackChan 机器人接到**自建**的 xiaozhi-esp32-server 上,
通过 **Tailscale Funnel** 穿透局域网隔离, 实现低延迟语音对话 + 真·主动播报 +
语音指挥本机 4 个 AI agent (codex / claude / agy / pi)。

> 与云链路 (xiaozhi.me) 相互独立: 本仓库只含自建链路; 切换靠手动 app-only 刷固件。

## 架构

```
机器人 (CoreS3, 固件 v1.0.7g-selfhost)
  │ 语音走 Tailscale Funnel 443 (局域网 AP 隔离, 不能直连)
  ▼
Tailscale Funnel → funnel_proxy.py (8090) → xiaozhi-esp32-server (docker 8000/8003)
  │ ASR=阿里百炼 paraformer-realtime-v2 流式
  │ LLM=DeepSeek deepseek-v4-flash (关 reasoning)
  │ TTS=EdgeTTS 粤语 (+20%)
  │ 工具: 服务端 MCP → 融合网关 (8010, 11 个工具)
  ▼
融合网关 fusion_gateway.py → 4 个 agent (可见窗口执行, hooks 回流)
```

## 目录

| 目录 | 内容 |
|---|---|
| `server/` | xiaozhi-esp32-server docker-compose + funnel_proxy + 配置示例 |
| `server-patch/` | 容器补丁 (fusion_push 主动播报 / connection / http_server / LLM 禁思考) |
| `gateway/` | 融合网关 (MCP 工具) + 系统托盘 + 自启脚本 |
| `agents/` | 四 agent 的 hooks / 可见窗口执行脚本 |
| `firmware/` | v1.0.7g 固件 (bin) + 构建脚本 + 源码补丁 |
| `scripts/` | 连通性验证 |
| `prompt-阿松-v3.md` | 机器人系统提示词 |

## 快速开始

### 1. 服务器 (Docker)

```bash
cd server
# 准备配置
cp data/.config.yaml.example data/.config.yaml   # 填入 YOUR_* 占位符
cp .env.example .env                              # 填入密钥
docker compose -f docker-compose.yml -f ../server-patch.yml up -d
```

### 2. Funnel 代理

```powershell
# Tailscale 上启用 funnel 指向本机 8090, 然后:
python server/funnel_proxy.py
```

### 3. 网关

```powershell
cd gateway
cp config.json.example config.json   # 填入占位符
powershell -ExecutionPolicy Bypass -File run_gateway.ps1
```

### 4. 固件

刷入 `firmware/post-fw-v1.0.7g-selfhost/xiaozhi.bin` (app-only @ 0x410000),
或按 `firmware/patches/PATCHES.md` 用你自己的 OTA 地址重编译。

### 5. Prompt

把 `prompt-阿松-v3.md` 全文填入服务器 `data/.config.yaml` 的 `prompt:` 段 (示例已带)。

## 与云链路 (xiaozhi.me) 切换

两条链路配置相互独立, **切换=手动 app-only 刷固件**:

| 目标 | 刷入固件 |
|---|---|
| 自建链路 | `firmware/post-fw-v1.0.7g-selfhost/xiaozhi.bin` |
| 云链路 (xiaozhi.me) | 历史 `post-fw-v1.0.6-ttsbuf/xiaozhi.bin` (OTA 默认 api.tenclass.net) |

> 注意: 云固件无 OTA 地址守卫, 若 NVS 里残留过自建 wss 地址, 需先重新配网/清 NVS 的 wifi.ota_url。

## 已知限制

- 依赖本机在线 + Tailscale (PC/服务器关机则机器人不可用)。
- 设备端 AEC 不可用 (会导致 audio_input 死循环), 播报时靠关麦克风缓解回声。
- EdgeTTS 免费音色, 自然度有限。

## 参考与致谢

- [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) — 自建服务器
- [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) — 设备端固件上游
- [stackchan-claude-bridge](https://github.com/heavenchenggong/stackchan-claude-bridge) — 07.31 跑通基座来源
- [StackChan-HtSz](https://github.com/mo-hantang/StackChan-HtSz) — HtSz 固件 (主分支有 boot bug, 仅参考)
