@echo off
cd /d "%~dp0"
echo Building and starting AlisBoard mill API (API + MySQL + Adminer)...
docker compose up -d --build
if errorlevel 1 (
  echo Docker failed. Start Docker Desktop and run up.bat again.
  exit /b 1
)

echo Waiting for API health...
set /a N=0
:wait_api
curl.exe -s -o NUL -w "%%{http_code}" http://127.0.0.1:18773/health | findstr /x "200" >nul
if not errorlevel 1 goto api_ok
set /a N+=1
if %N% GEQ 30 (
  echo API did not become healthy on 127.0.0.1:18773
  exit /b 1
)
ping -n 3 127.0.0.1 >nul
goto wait_api

:api_ok
echo Starting LAN relay (Wi-Fi / ESP -^> localhost Docker)...
if exist lan_relay.pid (
  for /f %%i in (lan_relay.pid) do taskkill /PID %%i /F >nul 2>&1
  del lan_relay.pid >nul 2>&1
)
start "AlisBoard LAN relay" /MIN python lan_relay.py
ping -n 3 127.0.0.1 >nul
curl.exe -s -o NUL -w "LAN relay check: %%{http_code}\n" http://127.0.0.1:18773/health
for /f "tokens=*" %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -match 'Wi-Fi' } | Select-Object -First 1).IPAddress"') do set WIFI=%%i
if defined WIFI curl.exe -s -o NUL -w "Wi-Fi path: %%{http_code}\n" http://%WIFI%:18773/health

echo.
echo IMPORTANT: ESP needs LAN relay on 0.0.0.0:18773. If ESP says refused, run up.bat again.
echo.
echo Dashboard   http://127.0.0.1/
echo Dashboard   http://127.0.0.1:18773/
echo POST        http://127.0.0.1:18773/api/plc-records
echo Token       lab-token
echo.
echo VM (Local test)   http://172.21.80.1:18773/api/plc-records
echo ESP (Local LAN)   http://192.168.100.18:18773/api/plc-records  ^(your Wi-Fi IP^)
echo.
echo If ESP/VM cannot connect, run open-firewall-80.ps1 as Administrator.
echo Test LAN path:  powershell -ExecutionPolicy Bypass -File .\test-lan.ps1
echo.
docker compose ps
exit /b 0
