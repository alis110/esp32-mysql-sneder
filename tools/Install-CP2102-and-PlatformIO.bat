@echo off
setlocal
cd /d "%~dp0"
REM Works from repo\tools or when copied next to this bat under dist\
if exist "%~dp0Install-CP2102-and-PlatformIO.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-CP2102-and-PlatformIO.ps1"
) else if exist "%~dp0tools\Install-CP2102-and-PlatformIO.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Install-CP2102-and-PlatformIO.ps1"
) else if exist "%~dp0..\tools\Install-CP2102-and-PlatformIO.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\tools\Install-CP2102-and-PlatformIO.ps1"
) else (
  echo Could not find Install-CP2102-and-PlatformIO.ps1
  pause
  exit /b 1
)
endlocal
