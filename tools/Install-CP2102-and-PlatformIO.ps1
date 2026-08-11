#Requires -Version 5.1
<#
.SYNOPSIS
  Helps install CP2102 (Silicon Labs) USB driver and PlatformIO Core (pio) on Windows factory PCs.
#>

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "firmware\platformio.ini"))) {
  # Running from dist\tools or similar — climb if needed
  if (Test-Path (Join-Path (Split-Path $Root) "firmware\platformio.ini")) {
    $Root = Split-Path $Root
  }
}

function Write-Step([string]$Msg) {
  Write-Host ""
  Write-Host "==> $Msg" -ForegroundColor Cyan
}

function Test-Cp2102Present {
  try {
    $ports = Get-CimInstance Win32_SerialPort -ErrorAction SilentlyContinue |
      Where-Object { $_.PNPDeviceID -match "VID_10C4.+PID_EA60|VID_10C4&PID_EA60" }
    return @($ports).Count -gt 0
  } catch {
    return $false
  }
}

function Test-Command([string]$Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

Write-Host "PLCBridge factory tools installer" -ForegroundColor Green
Write-Host "Repo/root: $Root"
Write-Host "This PC needs:"
Write-Host "  1) CP2102 driver  -> ESP appears as COMx"
Write-Host "  2) PlatformIO pio -> Setup ESP32 flash button works"
Write-Host ""

# ---------- CP2102 ----------
Write-Step "CP2102 Silicon Labs USB-UART driver (VID 10C4 / PID EA60)"

if (Test-Cp2102Present) {
  Write-Host "CP2102 already detected in Device Manager (good)." -ForegroundColor Green
  Get-CimInstance Win32_SerialPort |
    Where-Object { $_.PNPDeviceID -match "VID_10C4" } |
    Select-Object DeviceID, Name, PNPDeviceID |
    Format-Table -AutoSize
} else {
  Write-Host "No CP2102 COM port detected yet (board unplugged OR driver missing)." -ForegroundColor Yellow
}

$cpUrl = "https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers"
Write-Host "Official driver page:"
Write-Host "  $cpUrl"

if (Test-Command "winget") {
  Write-Host "Trying winget search for CP210 / Silicon Labs..."
  winget search "CP210" 2>$null
  winget search "Silicon Labs" 2>$null
  Write-Host "If winget lists a CP210x driver package, install it with:"
  Write-Host '  winget install --id <package-id-from-search>'
} else {
  Write-Host "winget not found — install the driver from the Silicon Labs page (ZIP / Universal Windows Driver)."
}

$open = Read-Host "Open Silicon Labs CP210x download page in browser? [Y/n]"
if ($open -notin @("n", "N")) {
  Start-Process $cpUrl
}

Write-Host ""
Write-Host "Manual CP2102 steps:"
Write-Host "  1. Download 'CP210x Universal Windows Driver'"
Write-Host "  2. Extract ZIP, install INF / run vendor setup"
Write-Host "  3. Plug ESP32 with a DATA USB cable"
Write-Host "  4. Device Manager -> Ports (COM & LPT) -> Silicon Labs CP210x (COMx)"
Write-Host "  5. Reboot if Windows still shows Unknown device"

# ---------- PlatformIO ----------
Write-Step "PlatformIO Core (pio) — required to flash ESP32 from Setup UI"

$pio = Get-Command pio -ErrorAction SilentlyContinue
if ($pio) {
  Write-Host ("pio already on PATH: " + $pio.Source) -ForegroundColor Green
  & pio --version
} else {
  Write-Host "pio not found on PATH." -ForegroundColor Yellow
}

$py = $null
foreach ($c in @("py", "python", "python3")) {
  if (Test-Command $c) { $py = $c; break }
}

if ($py) {
  Write-Host "Python launcher found: $py"
  $ans = Read-Host "Install/upgrade PlatformIO with pip now? [Y/n]"
  if ($ans -notin @("n", "N")) {
    & $py -3 -m pip install -U platformio
    if ($LASTEXITCODE -ne 0) {
      & $py -m pip install -U platformio
    }
  }
} else {
  Write-Host "Python not found on PATH." -ForegroundColor Yellow
  Write-Host "Install Python 3.11+ from https://www.python.org/downloads/windows/"
  Write-Host "  IMPORTANT: check 'Add python.exe to PATH'"
  $openPy = Read-Host "Open Python download page? [Y/n]"
  if ($openPy -notin @("n", "N")) {
    Start-Process "https://www.python.org/downloads/windows/"
  }
  Write-Host "After Python install, re-run this script to install PlatformIO."
}

# Common PlatformIO Scripts path
$pioScripts = Join-Path $env:USERPROFILE ".platformio\penv\Scripts"
if (Test-Path (Join-Path $pioScripts "pio.exe")) {
  Write-Host "Found pio.exe at: $pioScripts" -ForegroundColor Green
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  if ($userPath -notlike "*$pioScripts*") {
    Write-Host "Adding PlatformIO Scripts folder to User PATH..."
    [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $pioScripts), "User")
    $env:Path += ";" + $pioScripts
    Write-Host "PATH updated. Open a NEW terminal for all apps to see pio." -ForegroundColor Green
  }
}

Write-Step "Verify"
$pio2 = Get-Command pio -ErrorAction SilentlyContinue
if ($pio2) {
  & pio --version
  Write-Host "OK — Setup UI 'Setup ESP32' can flash when ESP is plugged in." -ForegroundColor Green
} else {
  Write-Host "pio still not visible in THIS window." -ForegroundColor Yellow
  Write-Host "Close PowerShell, open a new one, run:  pio --version"
  Write-Host "Docs: https://docs.platformio.org/en/latest/core/installation.html"
  $openPio = Read-Host "Open PlatformIO Core install docs? [Y/n]"
  if ($openPio -notin @("n", "N")) {
    Start-Process "https://docs.platformio.org/en/latest/core/installation.html"
  }
}

Write-Step "Done"
Write-Host "Next on factory PC:"
Write-Host "  1. Confirm COM port in Device Manager"
Write-Host "  2. Run dist\PLCBridgeSetup.exe"
Write-Host "  3. Check MySQL -> Setup ESP32 -> Install Service"
Write-Host ""
Write-Host "Note: PLCBridge.exe itself does NOT need Python — only flashing needs pio."
Write-Host "Press Enter to exit..."
[void][System.Console]::ReadLine()
