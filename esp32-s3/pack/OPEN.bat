@echo off
REM Do not cd - Win7 cmd cannot use UNC paths like \\host\g
if not exist "%~dp0AlisBoard.exe" (
  echo AlisBoard.exe not found next to OPEN.bat
  pause
  exit /b 1
)
start "" "%~dp0AlisBoard.exe" --show
