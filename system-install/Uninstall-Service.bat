@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set NOPAUSE=0
echo %*| find /i "/nopause" >nul && set NOPAUSE=1

net session >nul 2>&1
if %errorlevel% neq 0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs -Wait"
  exit /b
)
echo Stopping and removing PLCBridge service...
sc stop PLCBridge >nul 2>&1
if exist "%ProgramFiles%\PLCBridge\PLCBridge.exe" "%ProgramFiles%\PLCBridge\PLCBridge.exe" remove >nul 2>&1
sc delete PLCBridge >nul 2>&1
echo Config/state/logs kept in %ProgramData%\PLCBridge
sc query PLCBridge
if "%NOPAUSE%"=="0" pause
endlocal
