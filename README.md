# StackChan 自建链路 (stackchan.selfhost)

把 M5Stack CoreS3 StackChan 机器人接到**自建**的 xiaozhi-esp32-server 上,
通过 **Tailscale Funnel** 穿透局域网隔离, 实现低延迟语音对话 + 真·主动播报 +
语音指挥本机 4 个 AI agent (codex / claude / agy / pi)。

> 与云链路 (xiaozhi.me) 相互独立: 本仓库只含自建链路; 切换靠手动 app-only 刷固件。

## 架构

```
机器人 (CoreS3, 固件 v1.1-phase7.1)
  │ 语音走 Tailscale Funnel 443 (局域网 AP 隔离, 不能直连)
  ▼
Tailscale Funnel → funnel_proxy.py (8090) → xiaozhi-esp32-server (docker 8000/8003)
  │ ASR=阿里百炼 paraformer-realtime-v2 流式
  │ LLM=DeepSeek deepseek-v4-flash (关 reasoning)
  │ TTS=EdgeTTS 粤语 (+20%) 流式 + 3 帧 Batch Pacing 平滑推流
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
| `firmware/` | v1.0.8 固件 (bin) + 构建脚本 + 源码补丁 |
| `scripts/` | 连通性验证 |
| `prompt-阿松-v3.md` | 机器人系统提示词 |

## 快速开始

### 1. 服务器 (Docker)

```bash
cd server
# 准备配置
cp data/.config.yaml.example data/.config.yaml   # 填入 YOUR_* 占位符
cp .env.example .env                              # 填入密钥
# 注意: fusion 覆盖挂载所有容器补丁(server-patch), 必须一起启动
docker compose -f docker-compose.yml -f docker-compose.fusion.yml up -d --force-recreate
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

刷入 `firmware/post-fw-v1.1-phase7.1/xiaozhi.bin` (app-only @ 0x410000),
或按 `firmware/patches/PATCHES.md` 用你自己的 OTA 地址重编译。

> 恢复/迁移到新机器的完整步骤见 **`docs/restore.md`**;
> 当日进展总结见 **`docs/summary-2026-08-05.md`**。

### 5. Prompt

把 `prompt-阿松-v3.md` 全文填入服务器 `data/.config.yaml` 的 `prompt:` 段 (示例已带)。

## 与云链路 (xiaozhi.me) 切换

两条链路配置相互独立, **切换=手动 app-only 刷固件**:

| 目标 | 刷入固件 |
|---|---|
| 自建链路 | `firmware/post-fw-v1.1-phase7.1/xiaozhi.bin` |
| 云链路 (xiaozhi.me) | 历史 `post-fw-v1.0.6-ttsbuf/xiaozhi.bin` (OTA 默认 api.tenclass.net) |

> 注意: 云固件无 OTA 地址守卫, 若 NVS 里残留过自建 wss 地址, 需先重新配网/清 NVS 的 wifi.ota_url。

## 更新日志

### v1.1-phase7.1 (2026-08-05) — 平滑推流闭环 + ASR 识别增强

- **回退实时语音**: 弃用 Qwen-Audio-Realtime/GLM, LLM=DeepSeek deepseek-v4-flash,
  TTS=EdgeTTS zh-HK-HiuGaaiNeural 粤语女声 (+20%)。
- **ASR 识别增强**: DashScope 热词表 `vocab-asong-*` (31 词) + `language_hints: ["zh","en"]`
  + 同音纠错 (可头大/扣代码/扣德斯→Codex, 难体怪物体→Antigravity 等)。
- **平滑推流**: 服务端 `sendAudioHandle.py` 3 帧 Batch Pacing (每 180ms 让出 10ms) +
  LAST 后 20ms 再发 stop; 固件 EOF 机制 (`MarkPlaybackEof` → 队列排空才切待机),
  实测推送播报尾音完整不掐、LED 不提前变暖橙。
- **手势切断**: BMI270 摇晃/抱起、SI12T 摸头、滑动 100% 不再进 LLM (仅本地动画)。
- **Prompt 铁律**: 「X 在做什么」→ agent_status (禁 agent_pending 答状态);
  让 agent 做事必须同轮调 agent_query。
- 修复 edge.py 预热 `wait_for` 语法错误; `sendAudioHandle.py` 纳入补丁挂载管线。

### v1.0.9 (2026-08-05) — 实时语音 (P7-1) + 链路稳定性 (P7-2)

- **实时语音链路**: 新增 **Qwen-Audio-3.0-Realtime** provider (阿里百炼),
  端到端语音替代 ASR→LLM→TTS 三段式; 语义 VAD (smart_turn) 自动判停;
  支持网关 MCP 工具调用、双击打断、屏幕双向显示 (用户转写 + 回复文本)。
  切换: `selected_module.LLM = QwenAudioRealtimeLLM` (回退 DeepSeekLLM 无需刷固件)。
- **弃用 GLM-Realtime**: 实测判停不可靠 (aiohttp 客户端问题 + 服务端 VAD 缺陷),
  相关代码/配置已移除。
- **修 4 个真坑**: ① aiohttp 客户端导致实时 API VAD 不触发 → 改用 websockets 库;
  ② websockets 14 无 `.closed` 属性 → 用 `close_code` 判断; ③ 播报无声 →
  回复前补发 `tts start`; ④ 设备连接每 60-90s 被断 → Funnel 代理 aiohttp
  `heartbeat=30` 对不回 pong 的 ESP32 强制断开 → 设备侧改为 `heartbeat=None`。
- **服务端 WS ping 显式化**: `ping_interval=15s`, 及时探测半开连接。

### v1.0.8 (2026-08-04) — 唤醒可靠性

- **修复「唤醒无反应」**: 预热通道已打开时, 唤醒直连路径因 `ContinueWakeWordInvoke` 要求
  `connecting` 状态而直接返回 → 先置状态再直连, 唤醒必进聆听。
- **修复垃圾唤醒词**: 唤醒模型误触发返回命令表外的 `command_id` 时会越界读内存
  (曾把「偷偷吓我」当唤醒词) → 越界保护, 只认命令表内「阿松/你好小智」。
- **修复 LED 状态灯锁死**: `led_manual_` 一旦置位, 聆听蓝/播报绿永久失效 →
  活跃状态强制状态色, 手动色仅待机保持。
- **主动播报**: codex 完成任务后默认主动推送给机器人播报
  (`gateway/config.json` 的 `push_direct_done`; 做唤醒测试时可临时关闭, 避免队列干扰)。
- **可观测性**: 服务器 ASR 增加耗时日志 (`ASR 会话开始` → `ASR 识别耗时 X.XXs`)。

### v1.0.8 追加修复 (2026-08-04~05 实测迭代)

- **唤醒词回声拦截**: 唤醒后「阿松」被 ASR 识别成用户消息导致抢答 →
  服务器在 ASR 结果处拦截唤醒词(含去标点匹配); 唤醒词手势 detect 一律只进聆听。
- **27s ASR 延迟**: 手动聆听模式的结果要等 stop 信号才触发 → 收到首个最终结果立即回复。
- **「聆听后 ~12s 断连」**: DashScope ASR 握手卡住(默认 10s 超时)拖死设备连接 →
  连接加 5s 超时 + 后台建立, 不再阻塞设备连接处理循环。
- **前几个字识别不全**: 唤醒后 VAD 抑制 2s→1s; ASR 连接期间缓存的音频全量回放
  (原来只回放最后 600ms, 开头 1~2s 全丢)。
- **触摸任务卡死**: 手势唤醒在定时器任务里直接调协议/状态机 → 改为 Schedule 到主任务。
- **双击卡蓝灯**: 双击唤醒改 auto 聆听模式, 回复完自动回待机。
- **托盘稳定性**: 图标按状态缓存(修复 GDI 句柄泄漏导致 GetHicon 崩溃) +
  新增 `StackChan-FusionTrayWatchdog` 计划任务每 5 分钟自恢复。

### v1.0.7 (2026-08-03) — 四 agent 接入 + 主动播报

- 4 个 agent (codex/claude/agy/pi) hooks 回流, 唤醒优先播报队列。
- 预热 WS 常驻 + 300s 自愈; 播报关麦克风防自触发; 双击/摸头打断与唤醒。

## 已知限制

- 依赖本机在线 + Tailscale (PC/服务器关机则机器人不可用)。
- 设备端 AEC 不可用 (会导致 audio_input 死循环), 播报时靠关麦克风缓解回声。
- EdgeTTS 免费音色, 自然度有限。

## 参考与致谢

- [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) — 自建服务器
- [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) — 设备端固件上游
- [stackchan-claude-bridge](https://github.com/heavenchenggong/stackchan-claude-bridge) — 07.31 跑通基座来源
- [StackChan-HtSz](https://github.com/mo-hantang/StackChan-HtSz) — HtSz 固件 (主分支有 boot bug, 仅参考)
