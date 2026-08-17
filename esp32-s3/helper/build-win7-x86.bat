@echo off
REM Native 32-bit AlisBoard.exe — static CRT, no installer, no Python on the PC.
setlocal
cd /d "%~dp0"
set VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat
if not exist "%VCVARS%" (
  echo VS Build Tools x86 not found.
  exit /b 1
)
call "%VCVARS%" x86
if errorlevel 1 exit /b 1
rc /nologo /fo ..\pack\alisboard.res alisboard.rc
if errorlevel 1 exit /b 1
cl /nologo /O2 /MT /W3 /DWINVER=0x0501 /D_WIN32_WINNT=0x0501 /D_CRT_SECURE_NO_WARNINGS ^
  alisboard.c ..\pack\alisboard.res /Fe:..\pack\AlisBoard.exe /link /SUBSYSTEM:WINDOWS,5.01 /MACHINE:X86 ^
  odbc32.lib ws2_32.lib user32.lib gdi32.lib comctl32.lib advapi32.lib setupapi.lib
if errorlevel 1 exit /b 1
copy /Y START_HERE.txt ..\pack\START_HERE.txt >nul
echo Packed: esp32-s3\pack\AlisBoard.exe
echo Rebuild firmware so the USB disk contains this exe.
