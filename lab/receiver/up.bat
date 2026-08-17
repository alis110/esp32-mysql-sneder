@echo off
cd /d "%~dp0"
echo Building and starting AlisBoard mill API (API + MySQL + Adminer)...
docker compose up -d --build
if errorlevel 1 (
  echo Docker failed. Start Docker Desktop and run up.bat again.
  exit /b 1
)
echo.
echo Dashboard   http://127.0.0.1/
echo Dashboard   http://127.0.0.1:18773/
echo POST        http://127.0.0.1:18773/api/plc-records
echo Token       lab-token
echo MySQL       127.0.0.1:3307   user=root  password=lab
echo Adminer     http://127.0.0.1:8081/   system=MySQL server=mysql user=root password=lab
echo.
docker compose ps
