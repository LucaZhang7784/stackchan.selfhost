# v1.1-phase7.1 刷机说明

> 2026-08-05 构建。基于 v1.0.8-selfhost 基线，包含 Phase 7.1 底层性能重构：
> 打断软刷新（零尾音/无 Pop）、500ms PSRAM 预录音（首字不丢）、WS 接收缓冲 4096、
> Neopixel 卡蓝灯修复。服务端需配套 `server/data/.config.yaml` + `server-patch/`（见 `docs/phase7.1.md`）。

### 打断尾音备选预案（DMA 6→3）
若刷机实测打断后仍有可闻微弱尾音，在
`reference/stackchan-xiaozhi-firmware/sdkconfig.defaults` 末尾加一行：

```ini
CONFIG_XIAOZHI_AUDIO_DMA_DESC_NUM=3
```

然后重跑 `firmware/build_fw_v111.ps1` 重新编译（默认 6，3 时 DMA 深度≈45ms）。

## 文件

| 文件 | 说明 |
|---|---|
| `merged-binary.bin` | 全量合并镜像（bootloader+ptable+ota+srmodels+app+assets），一键烧录 |
| `bootloader.bin` / `partition-table.bin` / `ota_data_initial.bin` | 分区/引导 |
| `srmodels.bin` / `generated_assets.bin` | SR 模型 / 内置资源 |
| `xiaozhi.bin` | 应用固件（app-only 升级用） |

## 方式一：全量烧录（首次/救砖）

```bash
python -m esptool --chip esp32s3 -p COM4 -b 460800 \
  --before default_reset --after hard_reset write_flash \
  --flash_mode dio --flash_size 16MB --flash_freq 80m \
  merged-binary.bin
```

## 方式二：app-only 升级（保留配置，推荐日常）

```bash
python -m esptool --chip esp32s3 -p COM4 -b 460800 \
  --before default_reset --after hard_reset write_flash \
  --flash_mode dio --flash_size 16MB --flash_freq 80m \
  0x410000 xiaozhi.bin
```

> `COM4` 换成实际串口。全量烧录前建议先 `erase_flash`。
> 回退：v1.0.8-selfhost（P7 前）二进制在 `../post-fw-v1.0.8-selfhost/`。
