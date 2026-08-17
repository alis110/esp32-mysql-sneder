@echo off
cd /d "%~dp0"
if exist "%ProgramData%\PLCBridge\config\config.ini" (
  PLCBridge.exe --console --config "%ProgramData%\PLCBridge\config\config.ini"
) else (
  PLCBridge.exe --console --config "%~dp0config\config.wincc.ini"
)
pause
