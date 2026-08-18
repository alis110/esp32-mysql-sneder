@echo off
REM Win7: map the laptop ESP disk as G: forever (no password after host share is guest).
REM Copy this file into Startup:
REM   C:\Users\Operator\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\MAP_G.bat
set HOST=172.21.80.1
net use G: /delete /y >nul 2>&1
net use G: \\%HOST%\G /user:Guest "" /persistent:yes
if errorlevel 1 net use G: \\%HOST%\G /persistent:yes
if errorlevel 1 (
  echo Could not map \\%HOST%\G
  echo On the laptop run as Admin: lab\factory-sim\enable-vm-share.ps1
  pause
  exit /b 1
)
echo Mapped G: -^> \\%HOST%\G
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\MAP_G.bat" goto :done
copy /Y "%~f0" "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\MAP_G.bat" >nul
echo Also copied to Startup so it maps after every reboot.
:done
if exist G:\OPEN.bat start "" G:\OPEN.bat
exit /b 0
