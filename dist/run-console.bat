@echo off
cd /d "%~dp0"
REM Console test run (not Windows Service)
if exist "config\config.ini" (
  PLCBridge.exe --console --config "%~dp0config\config.ini"
) else if exist "..\config\config.lab.ini" (
  PLCBridge.exe --console --config "%~dp0..\config\config.lab.ini"
) else (
  PLCBridge.exe --console --config "%~dp0config\config.example.ini"
)
pause
