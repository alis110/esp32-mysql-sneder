# Elevate remove-service.ps1 via UAC and write result for Setup UI.
param(
    [Parameter(Mandatory = $true)][string]$RemoveScript,
    [Parameter(Mandatory = $true)][string]$ResultFile,
    [switch]$RemoveFiles
)

$ErrorActionPreference = "Continue"
$tempLog = [System.IO.Path]::GetTempFileName()
$flags = "-RemoveFiles" 
if (-not $RemoveFiles) { $flags = "" }

try {
    $cmd = "& { & '$RemoveScript' $flags *>&1 | Tee-Object -FilePath '$tempLog'; exit `$LASTEXITCODE }"
    $p = Start-Process -FilePath "powershell.exe" -Verb RunAs -Wait -PassThru -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cmd
    )
    $code = if ($null -eq $p) { 1 } else { $p.ExitCode }
} catch {
    $code = 1
    $_ | Out-File -FilePath $tempLog -Encoding utf8 -Append
}

$lines = @("EXIT=$code")
if (Test-Path -LiteralPath $tempLog) {
    $lines += "----- uninstall output -----"
    $lines += Get-Content -LiteralPath $tempLog -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $tempLog -Force -ErrorAction SilentlyContinue
}
$svc = Get-Service -Name "PLCBridge" -ErrorAction SilentlyContinue
if ($svc) { $lines += "SERVICE=$($svc.Status)" } else { $lines += "SERVICE=missing" }
$lines | Set-Content -Path $ResultFile -Encoding utf8
exit $code
