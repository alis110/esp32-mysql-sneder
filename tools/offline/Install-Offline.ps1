#Requires -Version 5.1
<#
.SYNOPSIS
  OFFLINE factory install — no internet required.
  Installs: VC++ Redistributable, CP2102 driver, portable PlatformIO + ESP32 toolchains.
#>

$ErrorActionPreference = "Continue"
$OfflineRoot = $PSScriptRoot
if (-not (Test-Path (Join-Path $OfflineRoot "cp2102"))) {
  Write-Host "Run this script from tools\offline\" -ForegroundColor Red
  exit 1
}

$TargetRoot = "C:\PLCBridge\offline"
$is64 = [Environment]::Is64BitOperatingSystem

Write-Host "=====================================================" -ForegroundColor Green
Write-Host " PLCBridge OFFLINE factory installer (no internet)" -ForegroundColor Green
Write-Host "====================================================="
Write-Host "Source : $OfflineRoot"
Write-Host "Install: $TargetRoot"
Write-Host ""

# ---------- 1) Visual C++ Redistributable (for PLCBridge EXEs) ----------
Write-Host "==> 1/4  Microsoft Visual C++ Redistributable" -ForegroundColor Cyan
$vc = if ($is64) {
  Join-Path $OfflineRoot "vcredist\vc_redist.x64.exe"
} else {
  Join-Path $OfflineRoot "vcredist\vc_redist.x86.exe"
}
if (Test-Path $vc) {
  Write-Host "Installing $vc (quiet)..."
  Start-Process -FilePath $vc -ArgumentList "/install", "/passive", "/norestart" -Wait
  Write-Host "VC++ Redistributable done."
} else {
  Write-Host "WARNING: $vc missing — PLCBridge.exe may fail on clean Windows." -ForegroundColor Yellow
}

# ---------- 2) CP2102 ----------
Write-Host "==> 2/4  CP2102 Silicon Labs USB-UART driver" -ForegroundColor Cyan
$vcp64 = Join-Path $OfflineRoot "cp2102\vcp-installer\CP210xVCPInstaller_x64.exe"
$vcp86 = Join-Path $OfflineRoot "cp2102\vcp-installer\CP210xVCPInstaller_x86.exe"
$inf = Join-Path $OfflineRoot "cp2102\universal\silabser.inf"
$installer = if ($is64) { $vcp64 } else { $vcp86 }

if (Test-Path $installer) {
  Write-Host "Running: $installer"
  Write-Host "(Accept UAC / driver prompts.)"
  Start-Process -FilePath $installer -Wait
} elseif (Test-Path $inf) {
  Write-Host "Trying INF install via pnputil (Admin)..."
  Start-Process pnputil.exe -ArgumentList "/add-driver `"$inf`" /install" -Verb RunAs -Wait
} else {
  Write-Host "CP2102 installer not found." -ForegroundColor Red
}
Write-Host "Plug ESP32 with a DATA USB cable; check Device Manager -> Ports (COM & LPT)."
Write-Host ""

# ---------- 3) Portable PlatformIO + toolchains ----------
Write-Host "==> 3/4  Portable PlatformIO + ESP32 toolchains" -ForegroundColor Cyan
$srcPy = Join-Path $OfflineRoot "portable-python"
$srcHome = Join-Path $OfflineRoot "platformio-home"
if (-not (Test-Path $srcPy) -or -not (Test-Path $srcHome)) {
  Write-Host "Missing portable-python or platformio-home." -ForegroundColor Red
  Write-Host "On a PC WITH internet run: tools\offline\Prepare-OfflinePack.ps1" -ForegroundColor Yellow
  Write-Host "Press Enter to exit..."
  [void][Console]::ReadLine()
  exit 1
}

New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
Write-Host "Copying portable-python..."
robocopy $srcPy (Join-Path $TargetRoot "portable-python") /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
Write-Host "Copying platformio-home (~1 GB)..."
robocopy $srcHome (Join-Path $TargetRoot "platformio-home") /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

$fwSrc = Join-Path $OfflineRoot "firmware-bin"
if (Test-Path $fwSrc) {
  robocopy $fwSrc (Join-Path $TargetRoot "firmware-bin") /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
}

$pioExe = Join-Path $TargetRoot "portable-python\Scripts\pio.exe"
$scripts = Join-Path $TargetRoot "portable-python\Scripts"
$coreDir = Join-Path $TargetRoot "platformio-home"
if (-not (Test-Path $pioExe)) {
  Write-Host "pio.exe missing after copy" -ForegroundColor Red
  exit 1
}

# ---------- 4) PATH env ----------
Write-Host "==> 4/4  Register User PATH + PLATFORMIO_CORE_DIR" -ForegroundColor Cyan
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if ($userPath -notlike "*$scripts*") {
  [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $scripts), "User")
  Write-Host "PATH += $scripts"
} else {
  Write-Host "PATH already OK"
}
[Environment]::SetEnvironmentVariable("PLATFORMIO_CORE_DIR", $coreDir, "User")
$env:Path = $scripts + ";" + $env:Path
$env:PLATFORMIO_CORE_DIR = $coreDir

Write-Host ""
Write-Host "Verify:" -ForegroundColor Green
& $pioExe --version
Write-Host "PLATFORMIO_CORE_DIR=$coreDir"
Write-Host ""
Write-Host "DONE. Open a NEW PowerShell window, then:" -ForegroundColor Green
Write-Host "  pio --version"
Write-Host "  Get-CimInstance Win32_SerialPort | ft DeviceID,Name"
Write-Host ""
Write-Host "Next: run dist\PLCBridgeSetup.exe"
Write-Host "  Check MySQL -> Setup ESP32 -> Install Service"
Write-Host ""
Write-Host "Optional prebuilt flash (if Setup compile fails):"
Write-Host "  tools\offline\Upload-Prebuilt-Firmware.bat COMx"
Write-Host ""
Write-Host "Press Enter to exit..."
[void][Console]::ReadLine()
