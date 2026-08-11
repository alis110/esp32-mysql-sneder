@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0tools\Install-CP2102-and-PlatformIO.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Install-CP2102-and-PlatformIO.ps1"
) else (
  echo Missing dist\tools\Install-CP2102-and-PlatformIO.ps1
  pause
  exit /b 1
)
endlocal
