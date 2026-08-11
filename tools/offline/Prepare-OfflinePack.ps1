#Requires -Version 5.1
<#
.SYNOPSIS
  (ONLINE PC) Rebuild the complete offline pack for factory USB sticks.
#>
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root
Write-Host "Preparing FULL offline pack in $Root" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path cp2102, platformio-wheels, vcredist, firmware-bin | Out-Null

# --- VC++ ---
Write-Host "==> VC++ Redistributable"
Invoke-WebRequest "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile "vcredist\vc_redist.x64.exe"
Invoke-WebRequest "https://aka.ms/vs/17/release/vc_redist.x86.exe" -OutFile "vcredist\vc_redist.x86.exe"

# --- CP2102 ---
Write-Host "==> CP2102 drivers"
Invoke-WebRequest "https://www.silabs.com/documents/public/software/CP210x_Universal_Windows_Driver.zip" -OutFile "cp2102\CP210x_Universal_Windows_Driver.zip"
Invoke-WebRequest "https://www.silabs.com/documents/public/software/CP210x_Windows_Drivers.zip" -OutFile "cp2102\CP210x_Windows_Drivers.zip"
if (Test-Path cp2102\universal) { Remove-Item cp2102\universal -Recurse -Force }
if (Test-Path cp2102\vcp-installer) { Remove-Item cp2102\vcp-installer -Recurse -Force }
Expand-Archive cp2102\CP210x_Universal_Windows_Driver.zip -DestinationPath cp2102\universal -Force
Expand-Archive cp2102\CP210x_Windows_Drivers.zip -DestinationPath cp2102\vcp-installer -Force

# --- Portable Python + PIO + esptool ---
Write-Host "==> Portable Python 3.11"
$pyZip = "python-embed.zip"
Invoke-WebRequest "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip" -OutFile $pyZip
if (Test-Path portable-python) { Remove-Item portable-python -Recurse -Force }
Expand-Archive $pyZip -DestinationPath portable-python -Force
$pth = Get-ChildItem portable-python -Filter "python*._pth" | Select-Object -First 1
(Get-Content $pth.FullName) -replace "#import site", "import site" | Set-Content $pth.FullName
Add-Content $pth.FullName "Lib\site-packages"
Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile get-pip.py
& .\portable-python\python.exe get-pip.py --no-warn-script-location

Write-Host "==> pip download/install platformio + esptool==4.5.1"
& .\portable-python\python.exe -m pip download platformio "esptool==4.5.1" setuptools wheel -d platformio-wheels
& .\portable-python\python.exe -m pip install --no-index --find-links=platformio-wheels setuptools wheel platformio "esptool==4.5.1"

Write-Host "==> Copy PlatformIO packages/platforms"
$src = Join-Path $env:USERPROFILE ".platformio"
$env:PLATFORMIO_CORE_DIR = Join-Path $Root "platformio-home"
New-Item -ItemType Directory -Force -Path $env:PLATFORMIO_CORE_DIR | Out-Null
if (Test-Path (Join-Path $src "packages")) {
  if (Test-Path platformio-home\packages) { Remove-Item platformio-home\packages -Recurse -Force }
  if (Test-Path platformio-home\platforms) { Remove-Item platformio-home\platforms -Recurse -Force }
  robocopy (Join-Path $src "packages") "platformio-home\packages" /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  robocopy (Join-Path $src "platforms") "platformio-home\platforms" /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
} else {
  & .\portable-python\Scripts\pio.exe pkg install -g -p "espressif32@6.9.0"
}

$env:Path = (Resolve-Path "portable-python\Scripts").Path + ";" + $env:Path
Write-Host "==> Vendor ArduinoJson + build firmware bins"
$fw = Resolve-Path (Join-Path $Root "..\..\firmware") -ErrorAction SilentlyContinue
if (-not $fw) { $fw = Resolve-Path (Join-Path $Root "..\..\firmware") }
# tools/offline -> repo root is ../..
$RepoFirmware = Join-Path (Split-Path (Split-Path $Root)) "firmware"
if (-not (Test-Path $RepoFirmware)) { $RepoFirmware = Join-Path (Split-Path $Root -Parent) "firmware" }
# $Root = .../tools/offline -> parent tools -> parent repo
$RepoRoot = Split-Path (Split-Path $Root)
$RepoFirmware = Join-Path $RepoRoot "firmware"

Push-Location $RepoFirmware
if (-not (Test-Path "include\secrets.h")) {
  Copy-Item "include\secrets.example.h" "include\secrets.h" -Force
}
New-Item -ItemType Directory -Force -Path lib | Out-Null
& pio pkg install 2>$null
$aj = Get-ChildItem ".pio\libdeps" -Recurse -Directory -Filter "ArduinoJson" -EA SilentlyContinue | Select-Object -First 1
if ($aj -and -not (Test-Path "lib\ArduinoJson\src")) {
  if (Test-Path "lib\ArduinoJson") { Remove-Item "lib\ArduinoJson" -Recurse -Force }
  Copy-Item $aj.FullName "lib\ArduinoJson" -Recurse -Force
}
& pio run
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "pio run failed" }
Copy-Item ".pio\build\esp32dev\firmware.bin" (Join-Path $Root "firmware-bin\firmware.bin") -Force
Copy-Item ".pio\build\esp32dev\bootloader.bin" (Join-Path $Root "firmware-bin\bootloader.bin") -Force
Copy-Item ".pio\build\esp32dev\partitions.bin" (Join-Path $Root "firmware-bin\partitions.bin") -Force
Pop-Location

& .\portable-python\Scripts\pio.exe --version
$size = (Get-ChildItem $Root -Recurse -File -EA SilentlyContinue | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Offline pack ready: {0:N0} MB" -f $size) -ForegroundColor Green
Write-Host "Copy whole repo to USB. Factory: tools\offline\Install-Offline.bat"
