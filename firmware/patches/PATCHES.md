# 固件补丁说明 (基于 07.31 已跑通基座)

本目录是相对上游 `reference/stackchan-xiaozhi-firmware` (heavenchenggong 系, 含「阿松」+ LED 补丁)
的全部本地改动文件, 用于在干净基座上重放。**不要用 HtSz 主分支** (有 boot bug)。

## 改动清单

| 文件 | 改动 |
|---|---|
| `sdkconfig.defaults` | OTA 默认地址=自建 Funnel; `USE_DEVICE_AEC` 不启用; 自定义唤醒词/阈值 |
| `main/Kconfig.projbuild` | (AEC 板型列表曾加 CoreS3 后回退 — 设备端 AEC 会导致 audio_input 死循环, 已废弃) |
| `main/application.cc` | 后台预热 WS 连接(2s/5s 退避 + 300s 无数据自愈); 播报时切 WiFi 高性能; 播报时关闭麦克风/唤醒词; 双击打断; OTA 地址守卫; **v1.0.8: 直连唤醒路径修复(通道已开时先置 connecting, 否则「唤醒无反应」)** |
| `main/application.h` | 预热连接成员 |
| `main/ota.cc` | **OTA 地址守卫**: NVS wifi.ota_url 非 http(s) 开头一律回退编译默认(防历史误配 wss://) |
| `main/audio/audio_service.{h,cc}` | 解码队列 2.4s→4.8s、播放余量 2→4、入队背压限时 2s(防 task_wdt 重启) |
| `main/audio/wake_words/custom_wake_word.{h,cc}` | 唤醒词「阿松/你好小智」; 检测窗口 3000→1500ms; 阈值下限 0.30; **v1.0.8: command_id 越界保护(模型误触发返回表外 id 时丢弃, 防「偷偷吓我」类垃圾唤醒词)** |
| `main/boards/m5stack-core-s3/m5stack_core_s3.cc` | 双击=打断(播报/聆听中), 空闲时双击/摸头可唤醒; **v1.0.8: LED 手动色不再锁死状态灯(聆听蓝/播报绿强制生效, 待机恢复手动色)** |
| `main/boards/m5stack-core-s3/cores3_audio_codec.cc` | 麦克风增益 42→36 |
| `main/protocols/protocol.h` | `OpenAudioChannel(bool silent)`; `IsStale()` |
| `main/protocols/websocket_protocol.{h,cc}` | silent 后台连接; 连接互斥锁; 空闲超时检测 |
| `main/protocols/mqtt_protocol.{h,cc}` | 签名同步 |

## 关键行为

- **唤醒/打断**: 空闲时 阿松 / 双击 / 摸头 均可唤醒; 播报中麦克风关闭(防自触发), 双击打断播报。
- **连接自愈**: 预热 WS 常驻, 服务器重启/会话回收后 2-40s 自动重连。
- **长播报**: WiFi 高性能 + 4.8s 缓冲 + 背压限时, 长文本完整播放。

## 构建

```powershell
# 需 Docker + espressif/idf:v5.5.2 (5.5.4 会黑屏)
powershell -ExecutionPolicy Bypass -File ..\build_fw_v108.ps1
# 刷机 (app-only @ 0x410000, 保留配置)
python -m esptool --chip esp32s3 -b 460800 --port COM8 --before default-reset --after hard-reset write-flash 0x410000 xiaozhi.bin
```
