@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0tools\offline\Install-Offline.bat" (
  call "%~dp0tools\offline\Install-Offline.bat"
) else if exist "%~dp0..\tools\offline\Install-Offline.bat" (
  call "%~dp0..\tools\offline\Install-Offline.bat"
) else (
  echo Offline pack not found: tools\offline\
  echo On a PC with internet run: tools\offline\Prepare-OfflinePack.ps1
  echo Then copy tools\offline onto the USB stick.
  pause
  exit /b 1
)
endlocal
