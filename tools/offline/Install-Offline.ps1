#Requires -Version 5.1
<#
.SYNOPSIS
  OFFLINE factory install: CP2102 driver + portable PlatformIO (no internet).
  Run from the USB / copied project folder on the factory Windows PC.
#>

$ErrorActionPreference = "Continue"
$OfflineRoot = $PSScriptRoot
if (-not (Test-Path (Join-Path $OfflineRoot "cp2102"))) {
  Write-Host "Run this script from tools\offline\" -ForegroundColor Red
  exit 1
}

$TargetRoot = "C:\PLCBridge\offline"
Write-Host "PLCBridge OFFLINE factory tools" -ForegroundColor Green
Write-Host "Source : $OfflineRoot"
Write-Host "Install: $TargetRoot"
Write-Host ""
Write-Host "This PC does NOT need internet."
Write-Host ""

# ---------- 1) CP2102 ----------
Write-Host "==> 1/3  CP2102 Silicon Labs driver (local files)" -ForegroundColor Cyan
$vcp64 = Join-Path $OfflineRoot "cp2102\vcp-installer\CP210xVCPInstaller_x64.exe"
$vcp86 = Join-Path $OfflineRoot "cp2102\vcp-installer\CP210xVCPInstaller_x86.exe"
$inf = Join-Path $OfflineRoot "cp2102\universal\silabser.inf"

$is64 = [Environment]::Is64BitOperatingSystem
$installer = if ($is64) { $vcp64 } else { $vcp86 }

if (Test-Path $installer) {
  Write-Host "Running: $installer"
  Write-Host "(Windows may show a UAC / Driver install prompt — accept it.)"
  Start-Process -FilePath $installer -Wait
} elseif (Test-Path $inf) {
  Write-Host "EXE installer missing; trying INF install (needs Admin)..."
  Start-Process pnputil.exe -ArgumentList "/add-driver `"$inf`" /install" -Verb RunAs -Wait
} else {
  Write-Host "CP2102 files not found under cp2102\" -ForegroundColor Red
}

Write-Host "After install: plug ESP32 (data USB) and check Device Manager -> Ports (COM & LPT)."
Write-Host ""

# ---------- 2) Copy portable PlatformIO ----------
Write-Host "==> 2/3  Copy portable Python + PlatformIO + toolchains" -ForegroundColor Cyan
$srcPy = Join-Path $OfflineRoot "portable-python"
$srcHome = Join-Path $OfflineRoot "platformio-home"
if (-not (Test-Path $srcPy) -or -not (Test-Path $srcHome)) {
  Write-Host "Missing portable-python or platformio-home under tools\offline\" -ForegroundColor Red
  Write-Host "On a PC WITH internet, run: tools\offline\Prepare-OfflinePack.ps1" -ForegroundColor Yellow
  Write-Host "Press Enter to exit..."
  [void][Console]::ReadLine()
  exit 1
}

New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
Write-Host "Copying portable-python (may take a minute)..."
robocopy $srcPy (Join-Path $TargetRoot "portable-python") /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
Write-Host "Copying platformio-home toolchains (~1 GB, please wait)..."
robocopy $srcHome (Join-Path $TargetRoot "platformio-home") /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

$pioExe = Join-Path $TargetRoot "portable-python\Scripts\pio.exe"
$scripts = Join-Path $TargetRoot "portable-python\Scripts"
$coreDir = Join-Path $TargetRoot "platformio-home"

if (-not (Test-Path $pioExe)) {
  Write-Host "pio.exe missing after copy" -ForegroundColor Red
  exit 1
}

# ---------- 3) PATH + PLATFORMIO_CORE_DIR ----------
Write-Host "==> 3/3  Register PATH + PLATFORMIO_CORE_DIR (User)" -ForegroundColor Cyan
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if ($userPath -notlike "*$scripts*") {
  [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $scripts), "User")
  Write-Host "Added to User PATH: $scripts"
} else {
  Write-Host "PATH already contains portable Scripts"
}
[Environment]::SetEnvironmentVariable("PLATFORMIO_CORE_DIR", $coreDir, "User")
$env:Path = $scripts + ";" + $env:Path
$env:PLATFORMIO_CORE_DIR = $coreDir

Write-Host ""
Write-Host "Verify:" -ForegroundColor Green
& $pioExe --version
Write-Host "PLATFORMIO_CORE_DIR=$coreDir"
Write-Host ""
Write-Host "DONE. Close this window, open a NEW PowerShell, then:" -ForegroundColor Green
Write-Host "  pio --version"
Write-Host "  Get-CimInstance Win32_SerialPort | ft DeviceID,Name"
Write-Host ""
Write-Host "Then run:  dist\PLCBridgeSetup.exe  ->  Setup ESP32"
Write-Host "Press Enter to exit..."
[void][Console]::ReadLine()
