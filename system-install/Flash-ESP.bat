@echo off
cd /d "%~dp0"
set PORT=%1
if "%PORT%"=="" (
  echo Usage: Flash-ESP.bat COM3
  echo Close Setup / stop the service first so the COM port is free.
  pause
  exit /b 1
)
if not exist "%~dp0esptool.exe" (
  echo Missing esptool.exe
  pause
  exit /b 1
)
if not exist "%~dp0firmware-bin\firmware.bin" (
  echo Missing firmware-bin\firmware.bin
  pause
  exit /b 1
)
echo Stopping PLCBridge service so COM is free...
sc stop PLCBridge >nul 2>&1
ping -n 3 127.0.0.1 >nul
echo Hold BOOT on the ESP32, then press a key to flash.
pause
echo Flashing ESP32 on %PORT% ...
"%~dp0esptool.exe" --chip esp32 --port %PORT% --baud 115200 --before default_reset --after hard_reset --connect-attempts 20 --no-stub write_flash -z 0x1000 "%~dp0firmware-bin\bootloader.bin" 0x8000 "%~dp0firmware-bin\partitions.bin" 0x10000 "%~dp0firmware-bin\firmware.bin"
if errorlevel 1 (
  echo Flash failed. Hold BOOT, run this bat again, release BOOT after Connecting.
  pause
  exit /b 1
)
echo Flash OK.
pause
