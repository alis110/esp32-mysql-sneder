@echo off
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
call :log "Root: %~dp0"

if "%SERVICEONLY%"=="0" (
  call :install_vcredist
  call :install_cp2102
)
call :install_service
call :log "DONE"
if "%NOPAUSE%"=="0" pause
endlocal
exit /b 0

:log
echo %~1
echo %~1>> "%LOG%"
goto :eof

:install_vcredist
set VC=
if exist "%~dp0vcredist\vc_redist.x86.exe" set "VC=%~dp0vcredist\vc_redist.x86.exe"
if not defined VC if exist "%~dp0tools\offline\vcredist\vc_redist.x86.exe" set "VC=%~dp0tools\offline\vcredist\vc_redist.x86.exe"
if not defined VC if exist "%~dp0..\tools\offline\vcredist\vc_redist.x86.exe" set "VC=%~dp0..\tools\offline\vcredist\vc_redist.x86.exe"
if not defined VC (
  call :log "VC++: installer not in this folder (skip)"
  goto :eof
)
call :log "VC++: %VC%"
"%VC%" /install /quiet /norestart
call :log "VC++ exit %errorlevel%"
goto :eof

:install_cp2102
set INF=
if exist "%~dp0drivers\cp2102-x86\silabser.inf" set "INF=%~dp0drivers\cp2102-x86\silabser.inf"
if not defined INF if exist "%~dp0tools\offline\cp2102\universal\silabser.inf" set "INF=%~dp0tools\offline\cp2102\universal\silabser.inf"
if not defined INF if exist "%~dp0..\tools\offline\cp2102\universal\silabser.inf" set "INF=%~dp0..\tools\offline\cp2102\universal\silabser.inf"
if defined INF (
  call :log "CP2102 INF: %INF%"
  pnputil -i -a "%INF%" >> "%LOG%" 2>&1
  call :log "pnputil exit %errorlevel%"
)

set DRV=
if /i "%PROCESSOR_ARCHITECTURE%"=="AMD64" (
  if exist "%~dp0drivers\CP210xVCPInstaller_x64.exe" set "DRV=%~dp0drivers\CP210xVCPInstaller_x64.exe"
)
if not defined DRV if exist "%~dp0drivers\CP210xVCPInstaller_x86.exe" set "DRV=%~dp0drivers\CP210xVCPInstaller_x86.exe"
if not defined DRV if exist "%~dp0tools\offline\cp2102\vcp-installer\CP210xVCPInstaller_x86.exe" set "DRV=%~dp0tools\offline\cp2102\vcp-installer\CP210xVCPInstaller_x86.exe"
if not defined DRV if exist "%~dp0..\tools\offline\cp2102\vcp-installer\CP210xVCPInstaller_x86.exe" set "DRV=%~dp0..\tools\offline\cp2102\vcp-installer\CP210xVCPInstaller_x86.exe"
if not defined DRV (
  call :log "CP2102 EXE: not found (INF step may be enough)"
  goto :eof
)
call :log "CP2102 EXE: %DRV%"
"%DRV%" /S
if errorlevel 1 (
  call :log "silent driver install failed, launching installer UI"
  "%DRV%"
)
call :log "CP2102 EXE done"
goto :eof

:find_bridge
set EXE=
if exist "%~dp0PLCBridge.exe" set "EXE=%~dp0PLCBridge.exe"
if not defined EXE if exist "%~dp0dist\PLCBridge.exe" set "EXE=%~dp0dist\PLCBridge.exe"
if not defined EXE if exist "%~dp0system-install\PLCBridge.exe" set "EXE=%~dp0system-install\PLCBridge.exe"
if not defined EXE if exist "%~dp0..\dist\PLCBridge.exe" set "EXE=%~dp0..\dist\PLCBridge.exe"
if not defined EXE if exist "%~dp0..\system-install\PLCBridge.exe" set "EXE=%~dp0..\system-install\PLCBridge.exe"
goto :eof

:find_setup
set SETUP=
if exist "%~dp0PLCBridgeSetup.exe" set "SETUP=%~dp0PLCBridgeSetup.exe"
if not defined SETUP if exist "%~dp0dist\PLCBridgeSetup.exe" set "SETUP=%~dp0dist\PLCBridgeSetup.exe"
if not defined SETUP if exist "%~dp0system-install\PLCBridgeSetup.exe" set "SETUP=%~dp0system-install\PLCBridgeSetup.exe"
if not defined SETUP if exist "%~dp0..\dist\PLCBridgeSetup.exe" set "SETUP=%~dp0..\dist\PLCBridgeSetup.exe"
if not defined SETUP if exist "%~dp0..\system-install\PLCBridgeSetup.exe" set "SETUP=%~dp0..\system-install\PLCBridgeSetup.exe"
goto :eof

:find_cfg
set CFG=
if exist "%~dp0config\config.ini" set "CFG=%~dp0config\config.ini"
if not defined CFG if exist "%~dp0..\config\config.ini" set "CFG=%~dp0..\config\config.ini"
if not defined CFG if exist "%~dp0config\config.wincc.ini" set "CFG=%~dp0config\config.wincc.ini"
if not defined CFG if exist "%~dp0..\config\config.wincc.ini" set "CFG=%~dp0..\config\config.wincc.ini"
goto :eof

:install_service
call :find_bridge
if not defined EXE (
  call :log "ERROR: PLCBridge.exe not found"
  goto :eof
)
call :find_setup
call :find_cfg
call :log "Bridge: %EXE%"

set INST=%ProgramFiles%\PLCBridge
if not exist "%INST%" mkdir "%INST%"
copy /Y "%EXE%" "%INST%\PLCBridge.exe" >> "%LOG%" 2>&1
if defined SETUP copy /Y "%SETUP%" "%INST%\PLCBridgeSetup.exe" >> "%LOG%" 2>&1

set PD=%ProgramData%\PLCBridge
if not exist "%PD%\config" mkdir "%PD%\config"
if not exist "%PD%\data" mkdir "%PD%\data"
if not exist "%PD%\logs" mkdir "%PD%\logs"

if defined CFG (
  copy /Y "%CFG%" "%PD%\config\config.ini" >> "%LOG%" 2>&1
  call :log "Config: %PD%\config\config.ini"
) else (
  call :log "WARNING: no config.ini found to copy"
)

call :log "Registering Windows service..."
sc stop PLCBridge >nul 2>&1
"%INST%\PLCBridge.exe" remove >nul 2>&1
sc delete PLCBridge >nul 2>&1
timeout /t 2 /nobreak >nul
"%INST%\PLCBridge.exe" --startup auto install >> "%LOG%" 2>&1
if errorlevel 1 (
  call :log "ERROR: service registration failed"
  goto :eof
)
sc config PLCBridge start= delayed-auto >nul
sc failure PLCBridge reset= 86400 actions= restart/5000/restart/15000/restart/60000 >nul
sc start PLCBridge >> "%LOG%" 2>&1
sc query PLCBridge >> "%LOG%" 2>&1
call :log "Service install finished. If SQL fails, set Log On to the factory Windows user (services.msc)."
goto :eof
