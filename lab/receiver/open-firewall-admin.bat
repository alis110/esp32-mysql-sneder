@echo off
cd /d "%~dp0"
echo AlisBoard firewall: allow ESP32 on ports 80 and 18773
echo A UAC window will open - click YES to apply rules.
echo.
powershell -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File \"\"%~dp0open-firewall-80.ps1\"\"'"
echo.
echo Also make sure LAN relay is running:  lab\receiver\up.bat
pause
