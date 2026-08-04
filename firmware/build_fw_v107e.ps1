param(
    [string]$FirmwareName = "post-fw-v1.0.7g-selfhost",  # 输出目录名
    [string]$ProjectRoot = ""                            # 固件源码根 (默认取脚本同级 ../reference/stackchan-xiaozhi-firmware)
)
$ErrorActionPreference = "Continue"

# 以脚本所在目录为基准, 避免写死本机绝对路径
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$fwroot = Split-Path -Parent $here
if (-not $ProjectRoot) { $ProjectRoot = Join-Path $fwroot 'reference\stackchan-xiaozhi-firmware' }
$tmp = Join-Path $here 'build-tmp'
$out = Join-Path $here $FirmwareName
New-Item -ItemType Directory -Path $tmp,$out -Force | Out-Null

# 准备只读输入目录(排除 .git / managed_components)
$src = Join-Path $tmp 'src'
New-Item -ItemType Directory -Path $src -Force | Out-Null
robocopy $ProjectRoot $src /E /XD .git managed_components /NFL /NDL /NP /NJH | Out-Null

$log = Join-Path $tmp 'build.log'
Write-Host "Building (log: $log) ..."

# 构建在容器文件系统内进行(挂载仅用于只读输入 + 输出)
$cid = "stackchan_idf_build"
docker rm -f $cid 2>$null | Out-Null
$runOut = docker run -d --name $cid -v "${src}:/src:ro" -v "${out}:/out" `
    -v "$here\build_led_ci.sh:/build_ci.sh:ro" espressif/idf:v5.5.2 bash /build_ci.sh 2>&1
Write-Host "docker run -> $runOut"
$rc = docker wait $cid
docker logs $cid 2>&1 | Tee-Object -FilePath $log
docker rm -f $cid 2>&1 | Out-Null
if ($rc -ne "0") { Write-Host "BUILD FAILED (rc=$rc) - see $log"; exit $rc }

python -m esptool --chip esp32s3 merge_bin -o "$out\merged-binary.bin" `
    --flash_mode dio --flash_size 16MB --flash_freq 80m `
    0x0       "$out\bootloader.bin" `
    0x8000    "$out\partition-table.bin" `
    0xd000    "$out\ota_data_initial.bin" `
    0x10000   "$out\srmodels.bin" `
    0x410000  "$out\xiaozhi.bin" `
    0xa10000  "$out\generated_assets.bin"
Write-Host "BUILD DONE -> $out"
