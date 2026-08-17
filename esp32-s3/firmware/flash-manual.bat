@echo off
setlocal
cd /d "%~dp0"
echo.
echo === AlisBoard manual flash ===
echo.
echo 1. Eject the AlisBoard USB disk in Windows (if shown).
echo 2. Hold BOOT, press RESET once, keep holding BOOT.
echo 3. Press any key here, then release BOOT when upload starts.
echo.
pause
set PORT=COM8
if not "%~1"=="" set PORT=%~1
echo Using port %PORT% ...
pio run -t upload --upload-port %PORT%
if errorlevel 1 (
  echo.
  echo FAILED. Try:
  echo   - BOOT + RESET again, then run this script
  echo   - Check Device Manager for a different COM port
  echo   - flash-manual.bat COM9
  echo.
  pause
  exit /b 1
)
echo.
echo OK — unplug and replug USB; the AlisBoard disk should appear.
pause
