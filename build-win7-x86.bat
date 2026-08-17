@echo off
setlocal
cd /d "%~dp0"

REM Build 32-bit EXEs for Windows 7 x86 using Python 3.8.
REM Output: system-install\PLCBridge.exe  PLCBridgeSetup.exe  esptool.exe

set PY38=%~dp0.py38-win32\python.exe
if not exist "%PY38%" (
  echo Missing .py38-win32\python.exe
  echo Run: download/install Python 3.8.10 Windows x86 into .py38-win32
  exit /b 1
)

if not exist ".venv38-x86\Scripts\python.exe" "%PY38%" -m venv .venv38-x86
if errorlevel 1 exit /b 1

call .venv38-x86\Scripts\activate.bat
python -m pip install -U pip
pip install -r requirements-win7.txt
if errorlevel 1 exit /b 1

python -c "import struct,sys; assert struct.calcsize('P')*8==32, 'venv is not 32-bit'"
if errorlevel 1 exit /b 1

python -m unittest discover -s tests -v
if errorlevel 1 exit /b 1

if not exist "system-install" mkdir "system-install"
if not exist "_win7build" mkdir "_win7build"

pyinstaller --noconfirm --clean --onefile --name PLCBridge ^
  --hidden-import win32timezone --hidden-import pyodbc ^
  --distpath system-install --workpath _win7build\bridge --specpath _win7build ^
  plcbridge.py
if errorlevel 1 exit /b 1

pyinstaller --noconfirm --onefile --windowed --name PLCBridgeSetup ^
  --hidden-import serial --hidden-import serial.tools.list_ports --hidden-import pyodbc ^
  --distpath system-install --workpath _win7build\setup --specpath _win7build ^
  lab\lab_app.py
if errorlevel 1 exit /b 1

pyinstaller --noconfirm --onefile --console --name esptool ^
  --collect-data esptool --hidden-import esptool --hidden-import reedsolo --hidden-import bitstring ^
  --distpath system-install --workpath _win7build\esptool --specpath _win7build ^
  tools\esptool_main.py
if errorlevel 1 exit /b 1

call :copy_pack
echo.
echo 32-bit pack ready: system-install\
dir system-install\*.exe
endlocal
goto :eof

:copy_pack
if not exist "system-install\config" mkdir "system-install\config"
copy /Y "config\config.wincc.ini" "system-install\config\config.wincc.ini" >nul
copy /Y "config\config.example.ini" "system-install\config\config.example.ini" >nul
copy /Y "config\config.wincc.ini" "system-install\config\config.ini" >nul
if not exist "system-install\vcredist" mkdir "system-install\vcredist"
copy /Y "tools\offline\vcredist\vc_redist.x86.exe" "system-install\vcredist\vc_redist.x86.exe" >nul
if not exist "system-install\drivers" mkdir "system-install\drivers"
copy /Y "tools\offline\cp2102\vcp-installer\CP210xVCPInstaller_x86.exe" "system-install\drivers\CP210xVCPInstaller_x86.exe" >nul
REM Win7 VCP 6.7 (slabvcp.inf). Do not use Universal silabser.inf on Windows 7.
xcopy /E /I /Y "tools\offline\cp2102\vcp-installer" "system-install\drivers\cp2102-win7\" >nul
copy /Y "tools\offline\cp2102\vcp-installer\CP210xVCPInstaller_x86.exe" "system-install\drivers\cp2102-win7\CP210xVCPInstaller_x86.exe" >nul
xcopy /E /I /Y "tools\offline\cp2102\universal\x86" "system-install\drivers\cp2102-x86\" >nul
copy /Y "tools\offline\cp2102\universal\silabser.inf" "system-install\drivers\cp2102-x86\" >nul
if exist "tools\offline\cp2102\universal\silabser.cat" copy /Y "tools\offline\cp2102\universal\silabser.cat" "system-install\drivers\cp2102-x86\" >nul
copy /Y "tools\Install-All.bat" "system-install\Install-All.bat" >nul
copy /Y "tools\Install-CP2102.bat" "system-install\Install-CP2102.bat" >nul
if not exist "system-install\firmware-bin" mkdir "system-install\firmware-bin"
copy /Y "tools\offline\firmware-bin\*.bin" "system-install\firmware-bin\" >nul
if not exist "system-install\firmware\include" mkdir "system-install\firmware\include"
copy /Y "firmware\include\secrets.example.h" "system-install\firmware\include\" >nul
if not exist "system-install\updates" mkdir "system-install\updates"
copy /Y "tools\offline\updates\*.msu" "system-install\updates\" >nul
goto :eof
