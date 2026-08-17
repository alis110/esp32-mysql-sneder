@echo off
setlocal
cd /d "%~dp0"
echo === 1. Restore WinCC bak onto .\WINCC ===
powershell -ExecutionPolicy Bypass -File "%~dp0restore-bak.ps1"
if errorlevel 1 goto :fail
echo.
echo === 2. Seed TagUncompressed (bak values are compressed) ===
sqlcmd -S ".\WINCC" -E -i "%~dp0seed-uncompressed.sql"
if errorlevel 1 goto :fail
echo.
echo === 3. Fake API on :18773 ===
start "AlisBoard fake API" cmd /k "%~dp0start-fake-api.bat" 18773
ping -n 3 127.0.0.1 >nul
echo.
echo === 4. Probe SQL + POST one JSON to fake API ===
python "%~dp0probe-and-post.py"
if errorlevel 1 goto :fail
echo.
echo OK. Open AlisBoard.exe, Test SQL against .\WINCC / auto
echo Browser dashboard: http://127.0.0.1:18773/
echo Keep the fake API window open.
goto :eof
:fail
echo FAILED
exit /b 1
