@echo off
cd /d "%~dp0\.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" lab\lab_app.py
) else (
  py -3 lab\lab_app.py
)
