#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [switch]$RemoveFiles
)

$ErrorActionPreference = "Continue"

Write-Host "Stopping PLCBridge..."
Stop-Service -Name PLCBridge -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$installedExe = Join-Path $env:ProgramFiles "PLCBridge\PLCBridge.exe"
if (Test-Path -LiteralPath $installedExe) {
    Write-Host "Unregistering via EXE remove..."
    & $installedExe remove 2>&1 | Out-Host
    Start-Sleep -Seconds 1
}

Write-Host "Deleting service (sc delete)..."
sc.exe delete PLCBridge | Out-Host
Start-Sleep -Seconds 2

$still = Get-Service -Name PLCBridge -ErrorAction SilentlyContinue
if ($still) {
    throw "Service still present after uninstall attempts."
}

if ($RemoveFiles) {
    $installDir = Join-Path $env:ProgramFiles "PLCBridge"
    if (Test-Path -LiteralPath $installDir) {
        Remove-Item -LiteralPath $installDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Removed $installDir"
    }
}

Write-Host "UNINSTALL_OK"
Write-Host "Note: config/state/logs kept under $env:ProgramData\PLCBridge (safe for reinstall)."
