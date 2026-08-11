@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 exit /b 1

call .venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 exit /b 1

python -m unittest discover -s tests -v
if errorlevel 1 exit /b 1

pyinstaller --noconfirm --clean --onefile --name PLCBridge --hidden-import win32timezone plcbridge.py
if errorlevel 1 exit /b 1

REM Setup UI (windowed)
pyinstaller --noconfirm --onefile --windowed --name PLCBridgeSetup ^
  --hidden-import serial --hidden-import serial.tools.list_ports --hidden-import mysql.connector ^
  lab\lab_app.py
if errorlevel 1 exit /b 1

if not exist "dist\config" mkdir "dist\config"
copy /Y "config\config.example.ini" "dist\config\config.example.ini" >nul
if not exist "dist\service" mkdir "dist\service"
copy /Y "service\install-service.ps1" "dist\service\install-service.ps1" >nul
copy /Y "service\remove-service.ps1" "dist\service\remove-service.ps1" >nul
if not exist "dist\firmware\src" mkdir "dist\firmware\src"
if not exist "dist\firmware\include" mkdir "dist\firmware\include"
copy /Y "firmware\platformio.ini" "dist\firmware\" >nul
copy /Y "firmware\src\main.cpp" "dist\firmware\src\" >nul
copy /Y "firmware\include\secrets.example.h" "dist\firmware\include\" >nul

if not exist "dist\tools" mkdir "dist\tools"
copy /Y "tools\Install-CP2102-and-PlatformIO.ps1" "dist\tools\" >nul
copy /Y "tools\Install-CP2102-and-PlatformIO.bat" "dist\tools\" >nul
copy /Y "tools\README.md" "dist\tools\" >nul

> "dist\Install-CP2102-and-PlatformIO.bat" (
  echo @echo off
  echo setlocal
  echo cd /d "%%~dp0"
  echo if exist "%%~dp0tools\Install-CP2102-and-PlatformIO.ps1" ^(
  echo   powershell -NoProfile -ExecutionPolicy Bypass -File "%%~dp0tools\Install-CP2102-and-PlatformIO.ps1"
  echo ^) else ^(
  echo   echo Missing dist\tools\Install-CP2102-and-PlatformIO.ps1
  echo   pause
  echo   exit /b 1
  echo ^)
  echo endlocal
)

echo Build completed:
echo   dist\PLCBridge.exe
echo   dist\PLCBridgeSetup.exe
echo   dist\Install-CP2102-and-PlatformIO.bat
endlocal
