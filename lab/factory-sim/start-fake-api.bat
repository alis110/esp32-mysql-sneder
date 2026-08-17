@echo off
REM Starts the Docker mill API in lab\receiver (same stack as up.bat).
cd /d "%~dp0..\receiver"
call up.bat
