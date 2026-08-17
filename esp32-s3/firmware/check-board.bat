@echo off
setlocal
cd /d "%~dp0"
echo.
echo === AlisBoard: is the ESP32-S3 connected? ===
echo.
echo NOW (normal mode — old firmware, NO USB disk yet):
python -c "import serial.tools.list_ports as p; r=list(p.comports()); print('  COM ports:', len(r)); [print('   ',i.device,' VID=%04X PID=%04X'% (i.vid,i.pid), i.description) for i in r if i.vid]"
echo.
echo --- IMPORTANT ---
echo   - USB DRIVE only appears AFTER we flash the NEW firmware successfully.
echo   - During flash (BOOT+RESET) you will NOT see a drive — that is NORMAL.
echo   - Right now COM8 = board is ON and connected. Upload fails because it is
echo     not in download mode yet.
echo.
echo NEXT: do BOOT + RESET, then press a key here...
echo   1. Hold BOOT
echo   2. Press RESET once (while holding BOOT)
echo   3. Keep holding BOOT, press a key below
echo.
pause
echo.
echo AFTER BOOT+RESET (download mode):
python -c "import serial.tools.list_ports as p; r=list(p.comports()); print('  COM ports:', len(r)); [print('   ',i.device,' VID=%04X PID=%04X'% (i.vid,i.pid), i.description) for i in r if i.vid]; print('  (if empty or different COM — use that port for flash)')"
echo.
echo Open Device Manager and look for:
echo   - USB JTAG/serial debug unit
echo   - a new COM port
echo.
echo Then run:  flash-manual.bat COMx
echo.
pause
