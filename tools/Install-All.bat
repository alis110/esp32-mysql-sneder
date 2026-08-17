@echo off
REM Windows 7 cmd: ASCII only. Do not use labels named find_*.
setlocal EnableExtensions
cd /d "%~dp0"

set NOPAUSE=0
set SERVICEONLY=0
echo %*| find /i "/nopause" >nul && set NOPAUSE=1
echo %*| find /i "/service-only" >nul && set SERVICEONLY=1

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting Administrator...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs -Wait"
  exit /b
)

if not exist "%~dp0data" mkdir "%~dp0data"
set LOG=%~dp0data\install-all-result.txt
echo PLCBridge install %DATE% %TIME% > "%LOG%"
echo Root: %~dp0
echo Root: %~dp0>> "%LOG%"

REM Win10 ucrtbase.dll next to the EXE breaks _socket on Windows 7.
del /Q "%~dp0api-ms-win-crt-*.dll" "%~dp0ucrtbase.dll" >nul 2>&1
if exist "%ProgramFiles%\PLCBridge" del /Q "%ProgramFiles%\PLCBridge\api-ms-win-crt-*.dll" "%ProgramFiles%\PLCBridge\ucrtbase.dll" >nul 2>&1
echo Removed side-by-side Win10 CRT DLLs.
echo Removed side-by-side Win10 CRT DLLs>> "%LOG%"

if /i "%SERVICEONLY%"=="1" goto do_service

set NEEDREBOOT=0

if not exist "%~dp0updates\Windows6.1-KB2533623-x86.msu" goto skip_kb253
echo Installing KB2533623 (needed for Python on Windows 7)...
echo KB2533623>> "%LOG%"
start /wait wusa.exe "%~dp0updates\Windows6.1-KB2533623-x86.msu" /quiet /norestart
set WU=%errorlevel%
echo wusa KB2533623 exit %WU%
echo wusa KB2533623 exit %WU%>> "%LOG%"
if "%WU%"=="3010" set NEEDREBOOT=1
:skip_kb253

if not exist "%~dp0updates\Windows6.1-KB2999226-x86.msu" goto skip_kb299
echo Installing KB2999226 (Universal C Runtime)...
echo KB2999226>> "%LOG%"
start /wait wusa.exe "%~dp0updates\Windows6.1-KB2999226-x86.msu" /quiet /norestart
set WU=%errorlevel%
echo wusa KB2999226 exit %WU%
echo wusa KB2999226 exit %WU%>> "%LOG%"
if "%WU%"=="3010" set NEEDREBOOT=1
:skip_kb299

if not exist "%~dp0vcredist\vc_redist.x86.exe" goto skip_vc
echo Installing VC++ x86 (progress window may open)...
echo VC++>> "%LOG%"
start /wait "" "%~dp0vcredist\vc_redist.x86.exe" /install /passive /norestart
set WU=%errorlevel%
echo VC++ exit %WU%
echo VC++ exit %WU%>> "%LOG%"
if "%WU%"=="3010" set NEEDREBOOT=1
:skip_vc

REM Win7 needs VCP 6.7 slabvcp.inf (NTx86.6.1). Universal silabser.inf is Win10-only.
set INF=%~dp0drivers\cp2102-win7\slabvcp.inf
if not exist "%INF%" set INF=%~dp0drivers\cp2102-x86\silabser.inf
set PNP=%SystemRoot%\System32\pnputil.exe
if exist "%SystemRoot%\Sysnative\pnputil.exe" set PNP=%SystemRoot%\Sysnative\pnputil.exe
if exist "%INF%" if exist "%PNP%" (
  echo CP2102 INF %INF%
  echo CP2102 INF %INF%>> "%LOG%"
  "%PNP%" -a "%INF%" -i >> "%LOG%" 2>&1
)
set DRV=%~dp0drivers\cp2102-win7\CP210xVCPInstaller_x86.exe
if not exist "%DRV%" set DRV=%~dp0drivers\CP210xVCPInstaller_x86.exe
if exist "%DRV%" (
  echo CP2102 EXE
  echo CP2102 EXE %DRV%>> "%LOG%"
  start /wait "" "%DRV%" /S
  echo CP2102 done
)

if "%NEEDREBOOT%"=="1" goto need_reboot
goto do_service

:need_reboot
echo.
echo REBOOT this PC now, then run Install-All.bat again.
echo REBOOT required>> "%LOG%"
if "%NOPAUSE%"=="0" pause
endlocal
exit /b 3010

:do_service
set EXE=%~dp0PLCBridge.exe
if not exist "%EXE%" (
  echo ERROR: PLCBridge.exe missing
  if "%NOPAUSE%"=="0" pause
  exit /b 1
)
set SETUP=
if exist "%~dp0PLCBridgeSetup.exe" set SETUP=%~dp0PLCBridgeSetup.exe
set CFG=%~dp0config\config.ini
if not exist "%CFG%" set CFG=%~dp0config\config.wincc.ini

set INST=%ProgramFiles%\PLCBridge
if not exist "%INST%" mkdir "%INST%"
copy /Y "%EXE%" "%INST%\PLCBridge.exe" >> "%LOG%" 2>&1
if defined SETUP copy /Y "%SETUP%" "%INST%\PLCBridgeSetup.exe" >> "%LOG%" 2>&1
del /Q "%INST%\api-ms-win-crt-*.dll" "%INST%\ucrtbase.dll" >nul 2>&1

set PD=%ProgramData%\PLCBridge
if not exist "%PD%\config" mkdir "%PD%\config"
if not exist "%PD%\data" mkdir "%PD%\data"
if not exist "%PD%\logs" mkdir "%PD%\logs"
if exist "%CFG%" (
  copy /Y "%CFG%" "%PD%\config\config.ini" >> "%LOG%" 2>&1
  echo Config: %PD%\config\config.ini
)

echo Registering Windows service...
sc stop PLCBridge >nul 2>&1
"%INST%\PLCBridge.exe" remove >nul 2>&1
sc delete PLCBridge >nul 2>&1
ping -n 3 127.0.0.1 >nul

echo Creating service with sc.exe ...
sc create PLCBridge binPath= "%INST%\PLCBridge.exe" start= auto DisplayName= "PLC WinCC to ESP32 Bridge"
if errorlevel 1 (
  echo sc create failed, trying EXE install...
  "%INST%\PLCBridge.exe" install
)
sc description PLCBridge "WinCC Tag Logging to ESP32 bridge"
sc config PLCBridge start= delayed-auto
sc failure PLCBridge reset= 86400 actions= restart/5000/restart/15000/restart/60000
echo Starting service...
sc start PLCBridge
sc query PLCBridge
echo.
echo If SQL fails: services.msc - PLCBridge - Log On - Operator
echo DONE>> "%LOG%"
if "%NOPAUSE%"=="0" pause
endlocal
exit /b 0
