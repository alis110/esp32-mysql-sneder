#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath,
    [string]$ConfigSource = "",
    [string]$SetupExePath = "",
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step([string]$Message) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message)
}

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "PLCBridge.exe not found: $ExePath"
}
$resolvedExe = (Resolve-Path -LiteralPath $ExePath).Path
Write-Step "Source EXE: $resolvedExe"

$installDir = Join-Path $env:ProgramFiles "PLCBridge"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
$installedExe = Join-Path $installDir "PLCBridge.exe"
Copy-Item -LiteralPath $resolvedExe -Destination $installedExe -Force
Write-Step "Installed binary: $installedExe"

if ($SetupExePath -and (Test-Path -LiteralPath $SetupExePath)) {
    Copy-Item -LiteralPath $SetupExePath -Destination (Join-Path $installDir "PLCBridgeSetup.exe") -Force
    Write-Step "Installed Setup UI beside service binary"
}

$programRoot = Join-Path $env:ProgramData "PLCBridge"
$configDir = Join-Path $programRoot "config"
$dataDir = Join-Path $programRoot "data"
$logsDir = Join-Path $programRoot "logs"
New-Item -ItemType Directory -Force -Path $configDir, $dataDir, $logsDir | Out-Null

$targetConfig = Join-Path $configDir "config.ini"
if ($ConfigSource -and (Test-Path -LiteralPath $ConfigSource)) {
    Copy-Item -LiteralPath $ConfigSource -Destination $targetConfig -Force
    Write-Step "Config installed: $targetConfig"
} elseif (-not (Test-Path -LiteralPath $targetConfig)) {
    $exampleCandidates = @(
        (Join-Path (Split-Path $PSScriptRoot -Parent) "config\config.example.ini"),
        (Join-Path (Split-Path $resolvedExe -Parent) "config\config.example.ini"),
        (Join-Path (Split-Path $resolvedExe -Parent) "config\config.ini")
    )
    $example = $exampleCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $example) { throw "No config source found." }
    Copy-Item -LiteralPath $example -Destination $targetConfig -Force
    Write-Step "Config created from example: $targetConfig"
} else {
    Write-Step "Keeping existing config: $targetConfig"
}

# Fully remove any previous registration.
$existing = Get-Service -Name "PLCBridge" -ErrorAction SilentlyContinue
if ($existing) {
    Write-Step "Removing previous service registration..."
    if ($existing.Status -ne "Stopped") {
        Stop-Service -Name "PLCBridge" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    try {
        & $installedExe remove
    } catch {
        Write-Step "EXE remove failed; trying sc delete"
    }
    sc.exe delete PLCBridge | Out-Null
    Start-Sleep -Seconds 2
}

Write-Step "Registering Windows service..."
& $installedExe --startup auto install
if ($LASTEXITCODE -ne 0) {
    throw "Service registration failed with exit code $LASTEXITCODE"
}

sc.exe config PLCBridge start= delayed-auto | Out-Null
sc.exe failure PLCBridge reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Null
sc.exe failureflag PLCBridge 1 | Out-Null
Write-Step "Startup=delayed-auto, recovery=restart configured"

if ($StartNow) {
    Write-Step "Starting service..."
    Start-Service -Name PLCBridge -ErrorAction Stop
    for ($i = 0; $i -lt 20; $i++) {
        $svc = Get-Service -Name PLCBridge
        if ($svc.Status -eq "Running") { break }
        Start-Sleep -Milliseconds 500
    }
    $svc = Get-Service -Name PLCBridge
    Write-Step ("Service status: {0}" -f $svc.Status)
    if ($svc.Status -ne "Running") {
        throw "Service installed but did not reach Running state (status=$($svc.Status))"
    }
}

Write-Step "OK Config: $targetConfig"
Write-Step "OK State:  $(Join-Path $dataDir 'state.sqlite3')"
Write-Step "OK Logs:   $(Join-Path $logsDir 'plcbridge.log')"
Write-Step "INSTALL_OK"
