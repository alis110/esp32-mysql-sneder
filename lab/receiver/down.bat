@echo off
cd /d "%~dp0"
if exist lan_relay.pid (
  for /f %%i in (lan_relay.pid) do taskkill /PID %%i /F >nul 2>&1
  del lan_relay.pid >nul 2>&1
)
REM Stops containers only. Keeps the mysql-data volume (replica databases stay).
REM Do NOT add -v. Do not run docker volume prune.
docker compose down
