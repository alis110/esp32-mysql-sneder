@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q
if errorlevel 1 exit /b 1

REM Windowed setup UI EXE
pyinstaller --noconfirm --clean --onefile --windowed --name PLCBridgeSetup ^
  --hidden-import serial --hidden-import serial.tools.list_ports --hidden-import pyodbc ^
  --add-data "lab\mock_api.py;lab" ^
  --add-data "service;service" ^
  --add-data "firmware\include\secrets.example.h;firmware\include" ^
  --add-data "config\config.example.ini;config" ^
  lab\lab_app.py
if errorlevel 1 exit /b 1

if not exist "dist\service" mkdir "dist\service"
copy /Y "service\install-service.ps1" "dist\service\" >nul
copy /Y "service\remove-service.ps1" "dist\service\" >nul
if not exist "dist\config" mkdir "dist\config"
copy /Y "config\config.example.ini" "dist\config\" >nul
if exist "config\config.wincc.ini" copy /Y "config\config.wincc.ini" "dist\config\config.ini" >nul
copy /Y "tools\Install-All.bat" "dist\Install-All.bat" >nul

echo.
echo Built: dist\PLCBridgeSetup.exe
endlocal
