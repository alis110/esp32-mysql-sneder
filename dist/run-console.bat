@echo off
cd /d "%~dp0"
REM Console test run (not Windows Service)
if exist "config\config.ini" (
  PLCBridge.exe --console --config "%~dp0config\config.ini"
) else if exist "..\config\config.wincc.ini" (
  PLCBridge.exe --console --config "%~dp0..\config\config.wincc.ini"
) else (
  PLCBridge.exe --console --config "%~dp0config\config.example.ini"
)
pause
