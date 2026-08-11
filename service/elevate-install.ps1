# Elevates install-service.ps1 via UAC and writes a result file for the Setup UI.
param(
    [Parameter(Mandatory = $true)][string]$InstallScript,
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$ConfigSource,
    [Parameter(Mandatory = $true)][string]$ResultFile,
    [string]$SetupExePath = ""
)

$ErrorActionPreference = "Continue"
$argList = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $InstallScript,
    "-ExePath", $ExePath,
    "-ConfigSource", $ConfigSource,
    "-StartNow"
)
if ($SetupExePath) {
    $argList += @("-SetupExePath", $SetupExePath)
}

$tempLog = [System.IO.Path]::GetTempFileName()
try {
    # Capture elevated process output by wrapping in a command that tees to a temp file.
    $inner = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command",
        "& { & '$InstallScript' -ExePath '$ExePath' -ConfigSource '$ConfigSource' -StartNow" +
        $(if ($SetupExePath) { " -SetupExePath '$SetupExePath'" } else { "" }) +
        " *>&1 | Tee-Object -FilePath '$tempLog'; exit `$LASTEXITCODE }"
    )

    $p = Start-Process -FilePath "powershell.exe" -Verb RunAs -Wait -PassThru -ArgumentList $inner
    $code = if ($null -eq $p) { 1 } else { $p.ExitCode }
} catch {
    $code = 1
    $_ | Out-File -FilePath $tempLog -Encoding utf8 -Append
}

$lines = @()
$lines += "EXIT=$code"
if (Test-Path -LiteralPath $tempLog) {
    $lines += "----- installer output -----"
    $lines += Get-Content -LiteralPath $tempLog -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $tempLog -Force -ErrorAction SilentlyContinue
}
$svc = Get-Service -Name "PLCBridge" -ErrorAction SilentlyContinue
if ($svc) {
    $lines += "SERVICE=$($svc.Status)"
    $lines += "START_TYPE=$($svc.StartType)"
} else {
    $lines += "SERVICE=missing"
}
$lines | Set-Content -Path $ResultFile -Encoding utf8
exit $code
