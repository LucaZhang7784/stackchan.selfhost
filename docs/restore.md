# StackChan Selfhost 恢复指南（2026-08-05 快照）

目标：在一台（重新部署的）电脑上，通过**刷固件 + 启动 Docker + 启动网关**，立即恢复到
2026-08-05 晚间的可用状态（DeepSeek + EdgeTTS 粤语女声 + 四 agent 语音指挥 + 平滑推流）。

## 一、前置条件
- Windows + Docker Desktop（linux 容器）
- Tailscale（本机在 tailnet 内，Funnel 443 → 本机 8090）
- Python 3.11 + pip（网关与 esptool 用）
- 机器人：M5Stack CoreS3 StackChan，USB 串口（本机通常 COM8）

## 二、服务端（Docker）
1. 把本目录 `server/` 放到目标机（内含 `.env` 真实密钥、`data/.config.yaml`、`data/warp-ca.crt`）。
2. 启动（两个 compose 一起，fusion 覆盖挂载所有补丁）：
   ```
   docker compose -f docker-compose.yml -f docker-compose.fusion.yml up -d --force-recreate
   ```
   - 首次会从 ghcr.nju.edu.cn 拉取 `xiaozhi-esp32-server:server_latest`、`web_latest`、
     `mcp-endpoint-server:latest`、redis、mysql 镜像。
   - 容器启动命令会执行 `update-ca-certificates` 信任 `warp-ca.crt`（企业 WARP 隧道必需，
     否则 EdgeTTS/DashScope 报 `CERTIFICATE_VERIFY_FAILED`）。
3. Tailscale Funnel（沿用原域名或新域名）：
   ```
   tailscale funnel 8090
   ```
   域名变化时需同步改：机器人配置里的 WebSocket URL、`gateway/config.json` 的 `ota_url`。

## 三、MCP 接入点（工具链）
- `mcp-endpoint-server`（:8004）已含在 compose 中。
- 它的 profile 指向融合网关：`http://localhost:8010/mcp` + Bearer token
  （参考 `mcp-toolkit-profile.json`；token 与 gateway `config.json` 的 `auth_token` 一致）。
- 启动顺序：先网关（8010）再 MCP 端点，服务端 LLM 才能拿到 11 个工具。

## 四、融合网关（host 进程）
1. 依赖：`pip install -r gateway/requirements.txt`
2. 按本机情况改 `gateway/config.json`：
   - `robot_mac`：机器人 MAC（YOUR_ROBOT_MAC）
   - `auth_token` / `push_secret`：与 `data/.config.yaml` 的 `fusion_secret` 保持一致
   - `ota_url` / `push_api_url`：指向本机 tailnet 域名与 `:8003/api/push`
3. 启动：
   ```
   python fusion_gateway.py --transport http --host 0.0.0.0 --port 8010
   ```
   托盘：`fusion_tray.ps1`（含网关/MCP/机器人状态监控）；自启：`install_autostart.ps1`。

## 五、机器人固件
1. 机器人在配置页设置 WebSocket 地址：`wss://<你的tailnet域名>/xiaozhi/v1/`（版本 v1）。
2. App-only 刷机（只更新应用，保留模型/资产分区）：
   ```
   python -m esptool --chip esp32s3 --port COM8 -b 460800 write_flash ^
     --flash_mode dio --flash_size 16MB --flash_freq 80m 0x410000 firmware\xiaozhi.bin
   ```
3. 全新机器完整刷（含 bootloader/分区/模型/资产）：
   ```
   python -m esptool --chip esp32s3 --port COM8 -b 460800 write_flash ^
     --flash_mode dio --flash_size 16MB --flash_freq 80m 0x0 firmware\merged-binary.bin
   ```

## 六、验证清单
- 网关：`GET http://127.0.0.1:8010/healthz`（Bearer token）返回 11 个工具。
- 服务端日志：`MCP接入点连接成功`；ASR `run-task JSON` 含
  `vocabulary_id: vocab-asong-*` 与 `language_hints: ["zh","en"]`。
- 唤醒 → 问答 → 播报连续无掐音 → LED 回暖橙。
- 推流：`/api/push` 播报完整，尾音不掐（固件 EOF：队列排空才切待机）。

## 七、关键文件
| 文件 | 作用 |
|---|---|
| `firmware/xiaozhi.bin` | 2026-08-05 v1.1-phase7.1 应用固件（手势切断+LED待机锁+EOF） |
| `server/docker-compose.yml` + `docker-compose.fusion.yml` | 服务端 + 全部补丁挂载 |
| `server/data/.config.yaml` | ASR 热词/纠错、LLM=DeepSeek、TTS=EdgeTTS 粤语 |
| `server-patch/` | 容器补丁（流式 TTS、batch pacing、ASR、fusion_push、sendAudioHandle） |
| `gateway/` | 融合网关 + 托盘（agent 工具链） |
| `SUMMARY-2026-08-05.md` | 当日进展与状态 |

