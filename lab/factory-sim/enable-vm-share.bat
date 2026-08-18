@echo off
REM Right-click - Run as administrator
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable-vm-share.ps1"
pause
