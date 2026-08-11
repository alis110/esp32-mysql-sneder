#Requires -Version 5.1
<#
.SYNOPSIS
  (ONLINE PC only) Re-download/build the offline pack for factory USB sticks.
#>
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

Write-Host "Preparing offline pack in $Root" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path cp2102, platformio-wheels | Out-Null

# CP2102
Write-Host "==> CP2102 drivers"
$u1 = "https://www.silabs.com/documents/public/software/CP210x_Universal_Windows_Driver.zip"
$u2 = "https://www.silabs.com/documents/public/software/CP210x_Windows_Drivers.zip"
Invoke-WebRequest $u1 -OutFile "cp2102\CP210x_Universal_Windows_Driver.zip"
Invoke-WebRequest $u2 -OutFile "cp2102\CP210x_Windows_Drivers.zip"
if (Test-Path cp2102\universal) { Remove-Item cp2102\universal -Recurse -Force }
if (Test-Path cp2102\vcp-installer) { Remove-Item cp2102\vcp-installer -Recurse -Force }
Expand-Archive cp2102\CP210x_Universal_Windows_Driver.zip -DestinationPath cp2102\universal -Force
Expand-Archive cp2102\CP210x_Windows_Drivers.zip -DestinationPath cp2102\vcp-installer -Force

# Portable Python
Write-Host "==> Portable Python 3.11 embeddable"
$pyZip = "python-embed.zip"
Invoke-WebRequest "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip" -OutFile $pyZip
if (Test-Path portable-python) { Remove-Item portable-python -Recurse -Force }
Expand-Archive $pyZip -DestinationPath portable-python -Force
$pth = Get-ChildItem portable-python -Filter "python*._pth" | Select-Object -First 1
(Get-Content $pth.FullName) -replace "#import site", "import site" | Set-Content $pth.FullName
Add-Content $pth.FullName "Lib\site-packages"
Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile get-pip.py
& .\portable-python\python.exe get-pip.py --no-warn-script-location

Write-Host "==> PlatformIO wheels + install into portable Python"
& .\portable-python\python.exe -m pip download platformio -d platformio-wheels
& .\portable-python\python.exe -m pip install --no-index --find-links=platformio-wheels platformio

Write-Host "==> Copy PlatformIO toolchains from this PC cache"
$src = Join-Path $env:USERPROFILE ".platformio"
if (-not (Test-Path (Join-Path $src "packages"))) {
  Write-Host "No ~/.platformio packages yet — installing espressif32 once (needs internet)..."
  $env:PLATFORMIO_CORE_DIR = (Join-Path $Root "platformio-home")
  New-Item -ItemType Directory -Force -Path $env:PLATFORMIO_CORE_DIR | Out-Null
  & .\portable-python\Scripts\pio.exe pkg install -g -p "espressif32@6.9.0"
} else {
  if (Test-Path platformio-home) { Remove-Item platformio-home -Recurse -Force }
  New-Item -ItemType Directory -Force -Path platformio-home | Out-Null
  robocopy (Join-Path $src "packages") "platformio-home\packages" /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  robocopy (Join-Path $src "platforms") "platformio-home\platforms" /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if (Test-Path (Join-Path $src "appstate.json")) {
    Copy-Item (Join-Path $src "appstate.json") platformio-home\ -Force
  }
}

$env:PLATFORMIO_CORE_DIR = (Resolve-Path platformio-home).Path
& .\portable-python\Scripts\pio.exe --version
& .\portable-python\Scripts\pio.exe pkg list -g

$size = (Get-ChildItem $Root -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Offline pack ready: {0:N0} MB under tools\offline" -f $size) -ForegroundColor Green
Write-Host "Copy the whole repo (or at least tools\offline + dist + firmware) to USB."
Write-Host "On factory PC run: tools\offline\Install-Offline.bat"
