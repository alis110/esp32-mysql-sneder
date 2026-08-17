@echo off
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Need Administrator...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo Use Install-All.bat instead. It installs KB2533623 + KB2999226 + VC++.
if exist "%~dp0Install-All.bat" "%~dp0Install-All.bat"
exit /b
