@echo off
REM Flash larger USB disk (AlisBoard.exe + START_HERE + JSON). Hold BOOT, tap RESET, release after Connecting...
setlocal
cd /d "%~dp0"
set PORT=%1
if "%PORT%"=="" set PORT=COM11
echo Flashing to %PORT% ...
pio run -e esp32-s3-from-recovery -t upload --upload-port %PORT%
if errorlevel 1 (
  echo.
  echo FAILED. Put board in download mode: hold BOOT, press RESET, keep BOOT until "Connecting..."
  exit /b 1
)
echo.
echo Done. Unplug USB, wait 5 sec, replug. Drive G: should be ~320 KB with AlisBoard.exe inside.
exit /b 0
