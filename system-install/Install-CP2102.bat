@echo off
REM Windows 7 32-bit: install Silicon Labs VCP 6.7 (not the Win10 Universal INF).
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Need Administrator for CP2102 driver...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo.
echo Plug the ESP32 with a DATA USB cable first.
echo Device Manager should show Other devices - CP2102... with a yellow mark.
echo.
pause

set INF=%~dp0drivers\cp2102-win7\slabvcp.inf
set PNP=%SystemRoot%\System32\pnputil.exe
if exist "%SystemRoot%\Sysnative\pnputil.exe" set PNP=%SystemRoot%\Sysnative\pnputil.exe

if exist "%INF%" if exist "%PNP%" (
  echo Adding Win7 driver: %INF%
  "%PNP%" -a "%INF%" -i
) else (
  echo Missing %INF%
)

set DRV=%~dp0drivers\cp2102-win7\CP210xVCPInstaller_x86.exe
if not exist "%DRV%" set DRV=%~dp0drivers\CP210xVCPInstaller_x86.exe
if exist "%DRV%" (
  echo Opening Silicon Labs installer - click Next / Install.
  start /wait "" "%DRV%"
) else (
  echo Missing CP210xVCPInstaller_x86.exe
  pause
  exit /b 1
)

echo.
echo If Device Manager still shows a yellow mark:
echo   1. Other devices - CP2102 - right-click Uninstall
echo   2. Unplug USB, wait 5 seconds, plug again
echo   3. Other devices - CP2102 - Update Driver
echo   4. Browse my computer - Let me pick - Have Disk
echo   5. Select this file:
echo      %INF%
echo.
echo Success = Ports (COM and LPT) - Silicon Labs CP210x USB to UART Bridge (COMx)
echo Then open Bridge Setup and click Setup ESP32.
echo.
pause
