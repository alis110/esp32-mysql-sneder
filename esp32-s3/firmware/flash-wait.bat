@echo off
REM Hold BOOT through entire flash (~1 min). Tap RESET while holding BOOT.
setlocal
cd /d "%~dp0"
set PORT=%1
if "%PORT%"=="" set PORT=COM11
python flash_wait.py %PORT%
exit /b %ERRORLEVEL%
