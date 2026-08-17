# Restore ROSHAN WinCC .bak onto local instance .\WINCC (lab only — never on the live factory PC).
# Names match CPUPC01\WINCC / CPUPC01\Operator backups.
$ErrorActionPreference = "Stop"
$BakDir = "D:\work\kar-khane-ard\Roshan\bak"
$DataDir = "D:\work\kar-khane-ard\Roshan\sql-data"
$Server = ".\WINCC"

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

function Sql([string]$q) {
    sqlcmd -S $Server -E -b -Q $q
    if ($LASTEXITCODE -ne 0) { throw "sqlcmd failed: $q" }
}

function Restore-Bak([string]$bakPath, [string]$dbName, [string]$mdfName, [string]$ldfName) {
    $safe = ($dbName -replace '[\\#]', '_')
    $mdf = Join-Path $DataDir "$safe.mdf"
    $ldf = Join-Path $DataDir "$safe.ldf"
    Write-Host "RESTORE [$dbName]"
    $q = @"
IF DB_ID(N'$dbName') IS NOT NULL
BEGIN
  ALTER DATABASE [$dbName] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
  DROP DATABASE [$dbName];
END
RESTORE DATABASE [$dbName] FROM DISK = N'$bakPath' WITH REPLACE,
  MOVE N'$mdfName' TO N'$mdf',
  MOVE N'$ldfName' TO N'$ldf';
ALTER DATABASE [$dbName] SET MULTI_USER;
"@
    Sql $q
}

Restore-Bak (Join-Path $BakDir "CC_Kamran_F_25_12_03_14_08_36.bak") `
    "CC_Kamran_F_25_12_03_14_08_36" "WinCC_SQL.mdf" "WinCC_SQL.ldf"

Restore-Bak (Join-Path $BakDir "CC_Kamran_F_25_12_03_14_08_36R.bak") `
    "CC_Kamran_F_25_12_03_14_08_36R" "WinCC_SQL.mdf" "WinCC_SQL.ldf"

Restore-Bak (Join-Path $BakDir "CPUPC01_WinCC#Roshan_ALG_202808130630_202808130730.bak") `
    "CPUPC01_WinCC#Roshan_ALG_202808130630_202808130730" "WinCC_data1" "WinCC_log1"

Restore-Bak (Join-Path $BakDir "CPUPC01_WINCC#ROSHAN_TLG_F_202412202030_202808081515.bak") `
    "CPUPC01_WINCC#ROSHAN_TLG_F_202412202030_202808081515" "WinCC_data1" "WinCC_log1"

# Short lab name would win AlisBoard auto-pick (ORDER BY name). Drop it after factory restore.
Sql @"
IF DB_ID(N'ROSHAN_TLG_F') IS NOT NULL
BEGIN
  ALTER DATABASE [ROSHAN_TLG_F] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
  DROP DATABASE [ROSHAN_TLG_F];
END
"@

Write-Host "Restored databases:"
sqlcmd -S $Server -E -Q "SET NOCOUNT ON; SELECT name FROM sys.databases WHERE name NOT IN ('master','model','msdb','tempdb') ORDER BY name;" -W -h-1
