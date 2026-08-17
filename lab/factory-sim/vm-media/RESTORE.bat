@echo off
setlocal
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "DATA=C:\WinCCData"
set "SERVER=.\WINCC"
if not exist "%DATA%" mkdir "%DATA%"

echo Using bak folder: %HERE%
echo SQL instance: %SERVER%
echo Data folder: %DATA%
echo.

sqlcmd -S %SERVER% -E -Q "SELECT @@SERVERNAME, SYSTEM_USER" -b
if errorlevel 1 (
  echo SQL .\WINCC is not running. Install SQL Server with instance name WINCC first.
  pause
  exit /b 1
)

call :restore "%HERE%\CC_Kamran_F_25_12_03_14_08_36.bak" "CC_Kamran_F_25_12_03_14_08_36" "WinCC_SQL.mdf" "WinCC_SQL.ldf"
if errorlevel 1 goto :fail
call :restore "%HERE%\CC_Kamran_F_25_12_03_14_08_36R.bak" "CC_Kamran_F_25_12_03_14_08_36R" "WinCC_SQL.mdf" "WinCC_SQL.ldf"
if errorlevel 1 goto :fail
call :restore "%HERE%\CPUPC01_WinCC#Roshan_ALG_202808130630_202808130730.bak" "CPUPC01_WinCC#Roshan_ALG_202808130630_202808130730" "WinCC_data1" "WinCC_log1"
if errorlevel 1 goto :fail
call :restore "%HERE%\CPUPC01_WINCC#ROSHAN_TLG_F_202412202030_202808081515.bak" "CPUPC01_WINCC#ROSHAN_TLG_F_202412202030_202808081515" "WinCC_data1" "WinCC_log1"
if errorlevel 1 goto :fail

echo.
echo Databases:
sqlcmd -S %SERVER% -E -Q "SET NOCOUNT ON; SELECT name FROM sys.databases WHERE name NOT IN ('master','model','msdb','tempdb') ORDER BY name;" -W -h-1
echo.
echo Now run: sqlcmd -S .\WINCC -E -i "%HERE%\seed-uncompressed.sql"
pause
exit /b 0

:fail
echo RESTORE FAILED
pause
exit /b 1

:restore
set "BAK=%~1"
set "DB=%~2"
set "MDFNAME=%~3"
set "LDFNAME=%~4"
set "SAFE=%DB:#=_%"
set "SAFE=%SAFE:\=_%"
echo RESTORE [%DB%]
sqlcmd -S %SERVER% -E -b -Q "IF DB_ID(N'%DB%') IS NOT NULL BEGIN ALTER DATABASE [%DB%] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [%DB%]; END"
sqlcmd -S %SERVER% -E -b -Q "RESTORE DATABASE [%DB%] FROM DISK = N'%BAK%' WITH REPLACE, MOVE N'%MDFNAME%' TO N'%DATA%\%SAFE%.mdf', MOVE N'%LDFNAME%' TO N'%DATA%\%SAFE%.ldf'; ALTER DATABASE [%DB%] SET MULTI_USER;"
if errorlevel 1 exit /b 1
exit /b 0
