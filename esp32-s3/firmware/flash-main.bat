@echo off
REM Flash main AlisBoard firmware (USB disk with AlisBoard.exe).
REM Run while COM11 (recovery) is visible.
setlocal
cd /d "%~dp0"
set PORT=COM11
if not "%~1"=="" set PORT=%~1
echo Flashing main AlisBoard firmware to %PORT% ...
pio run -e esp32-s3-from-recovery -t upload --upload-port %PORT%
if errorlevel 1 (
  echo FAILED
  pause
  exit /b 1
)
echo.
echo OK. Now IMPORTANT:
echo   1. Unplug the USB cable completely
echo   2. Wait 3 seconds
echo   3. Plug back in
echo   4. Open This PC — look for a removable drive (ALISBOARD)
echo      with AlisBoard.exe and START_HERE.txt
echo.
pause
