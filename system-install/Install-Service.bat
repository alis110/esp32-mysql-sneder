@echo off
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Need Administrator to install the Windows service...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

if not exist "%~dp0PLCBridge.exe" (
  echo PLCBridge.exe missing.
  pause
  exit /b 1
)

set INST=%ProgramFiles%\PLCBridge
if not exist "%INST%" mkdir "%INST%"
copy /Y "%~dp0PLCBridge.exe" "%INST%\PLCBridge.exe" >nul
if exist "%~dp0PLCBridgeSetup.exe" copy /Y "%~dp0PLCBridgeSetup.exe" "%INST%\PLCBridgeSetup.exe" >nul

set PD=%ProgramData%\PLCBridge
if not exist "%PD%\config" mkdir "%PD%\config"
if not exist "%PD%\data" mkdir "%PD%\data"
if not exist "%PD%\logs" mkdir "%PD%\logs"

if not exist "%PD%\config\config.ini" (
  if exist "%~dp0config\config.ini" (
    copy /Y "%~dp0config\config.ini" "%PD%\config\config.ini" >nul
  ) else (
    copy /Y "%~dp0config\config.wincc.ini" "%PD%\config\config.ini" >nul
  )
  echo Config created: %PD%\config\config.ini
) else (
  echo Keeping existing config: %PD%\config\config.ini
)

echo Removing previous service if present...
sc stop PLCBridge >nul 2>&1
"%INST%\PLCBridge.exe" remove >nul 2>&1
sc delete PLCBridge >nul 2>&1
timeout /t 2 /nobreak >nul

echo Registering PLCBridge service...
"%INST%\PLCBridge.exe" --startup auto install
if errorlevel 1 (
  echo Service registration failed.
  pause
  exit /b 1
)

sc config PLCBridge start= delayed-auto >nul
sc failure PLCBridge reset= 86400 actions= restart/5000/restart/15000/restart/60000 >nul
sc start PLCBridge
echo.
sc query PLCBridge
echo.
echo IMPORTANT: if Check DB works in Setup but the service cannot read SQL Server,
echo set the service Log On account to the factory Windows user (e.g. CPUPC01\Operator).
echo   services.msc  -^> PLCBridge  -^> Log On
echo.
pause
