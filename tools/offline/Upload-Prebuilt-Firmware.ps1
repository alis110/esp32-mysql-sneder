#Requires -Version 5.1
<#
.SYNOPSIS
  Flash prebuilt firmware.bin from the offline pack (no compile, no internet).
  Usage: .\Upload-Prebuilt-Firmware.ps1 COM7
#>
param(
  [Parameter(Mandatory = $false)]
  [string]$Port = ""
)

$Root = $PSScriptRoot
$esptool = Join-Path $Root "portable-python\Scripts\esptool.exe"
if (-not (Test-Path $esptool)) {
  $esptool = Join-Path $Root "portable-python\Scripts\esptool.py"
}
$fw = Join-Path $Root "firmware-bin\firmware.bin"
$boot = Join-Path $Root "firmware-bin\bootloader.bin"
$part = Join-Path $Root "firmware-bin\partitions.bin"

if (-not $Port) {
  Write-Host "Available serial ports:"
  Get-CimInstance Win32_SerialPort | Format-Table DeviceID, Name -AutoSize
  $Port = Read-Host "Enter COM port (e.g. COM7)"
}
if (-not $Port) { exit 1 }

if (-not (Test-Path $fw)) {
  Write-Host "Missing $fw — run Prepare-OfflinePack.ps1 on an online PC first." -ForegroundColor Red
  exit 1
}

$env:PLATFORMIO_CORE_DIR = Join-Path $Root "platformio-home"
$py = Join-Path $Root "portable-python\python.exe"

Write-Host "Flashing prebuilt firmware to $Port ..." -ForegroundColor Cyan
& $py -m esptool --chip esp32 --port $Port --baud 460800 write_flash -z `
  0x1000 $boot `
  0x8000 $part `
  0x10000 $fw

if ($LASTEXITCODE -eq 0) {
  Write-Host "Flash OK." -ForegroundColor Green
} else {
  Write-Host "Flash failed (code=$LASTEXITCODE). Is the COM free? Stop Bridge Service first." -ForegroundColor Red
}
Write-Host "Press Enter..."
[void][Console]::ReadLine()
