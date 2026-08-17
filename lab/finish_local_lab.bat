@echo off
cd /d D:\work\kar-khane-ard
echo === Local lab finish ===
echo SQL Server WinCC + Mock API :8089  Bridge service
echo.
echo Waiting for ESP32 (CP2102)... Please unplug/replug USB if needed.
:wait
for /f "usebackq delims=" %%i in (`".\.venv\Scripts\python.exe" -c "from serial.tools import list_ports; ps=[p.device for p in list_ports.comports() if p.vid==0x10C4]; print(ps[0] if ps else '')"`) do set COM=%%i
if "%COM%"=="" (
  timeout /t 2 >nul
  goto wait
)
echo Found %COM%
echo Flashing firmware (Wi-Fi=Alis, API=http://192.168.100.18:8089/api/plc-records)...
cd firmware
pio run -t upload --upload-port %COM%
if errorlevel 1 (
  echo Flash failed
  pause
  exit /b 1
)
cd ..
echo Starting Bridge service...
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile','-Command','Start-Service PLCBridge'"
timeout /t 5 >nul
echo.
echo === Bridge log ===
powershell -NoProfile -Command "Get-Content 'C:\ProgramData\PLCBridge\logs\plcbridge.log' -Tail 30 -ErrorAction SilentlyContinue"
echo.
echo === Mock API log ===
powershell -NoProfile -Command "Get-Content 'D:\work\kar-khane-ard\logs\mock-api-out.txt' -Tail 40 -ErrorAction SilentlyContinue"
echo.
echo Done. New WinCC rows should appear in mock-api-out.txt
pause
