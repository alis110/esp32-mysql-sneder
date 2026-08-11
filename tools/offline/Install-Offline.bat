@echo off
setlocal
cd /d "%~dp0"
echo.
echo OFFLINE install (no internet needed)
echo  - CP2102 driver from local files
echo  - Portable PlatformIO + ESP32 toolchains
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Offline.ps1"
endlocal
