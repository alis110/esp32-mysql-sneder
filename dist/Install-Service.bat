@echo off
:: One-click elevated full install
cd /d "%~dp0"
set EXE=%~dp0PLCBridge.exe
set SETUP=%~dp0PLCBridgeSetup.exe
set CFG=%~dp0config\config.ini
set SCRIPT=%~dp0service\install-service.ps1
if not exist "%EXE%" (
  echo PLCBridge.exe missing.
  pause
  exit /b 1
)
if not exist "%CFG%" (
  if exist "%~dp0config\config.wincc.ini" copy /Y "%~dp0config\config.wincc.ini" "%CFG%" >nul
  if exist "%~dp0config\config.example.ini" if not exist "%CFG%" copy /Y "%~dp0config\config.example.ini" "%CFG%" >nul
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%SCRIPT%','-ExePath','%EXE%','-ConfigSource','%CFG%','-SetupExePath','%SETUP%','-StartNow'"
echo.
sc query PLCBridge
pause
