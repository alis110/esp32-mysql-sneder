@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Upload-Prebuilt-Firmware.ps1" %*
endlocal
