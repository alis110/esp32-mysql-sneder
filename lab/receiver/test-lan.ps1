# Quick check: LAN/Wi-Fi path to mill API (ESP uses 192.168.100.18:18773).
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$wifiIp = (
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceAlias -match "Wi-Fi|Wireless" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress
)
if (-not $wifiIp) { $wifiIp = "192.168.100.18" }

Write-Host "Wi-Fi IP: $wifiIp"
Write-Host "Checking listeners..."
netstat -ano | findstr ":18773.*LISTEN"
netstat -ano | findstr ":80.*LISTEN"

function Test-Health($url) {
    try {
        $null = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
        Write-Host "OK  $url -> 200"
        return $true
    } catch {
        Write-Host "FAIL $url -> $($_.Exception.Message)"
        return $false
    }
}

$ok = $true
if (-not (Test-Health "http://127.0.0.1:18773/health")) { $ok = $false }
if (-not (Test-Health "http://${wifiIp}:18773/health")) { $ok = $false }
if (-not (Test-Health "http://172.21.80.1:18773/health")) { $ok = $false }

$body = '{"type":"data","id":0,"idempotency_key":"lan-test","payload":{"TagName":"LAN.Test","RealValue":"1"}}'
$tmp = Join-Path $env:TEMP "alis-lan-test.json"
Set-Content -Path $tmp -Value $body -NoNewline
try {
    $post = (curl.exe -s -w "`nHTTP %{http_code}" --connect-timeout 5 -X POST "http://${wifiIp}:18773/api/plc-records" `
        -H "Content-Type: application/json" -H "Authorization: Bearer lab-token" `
        -H "Idempotency-Key: lan-test" --data-binary "@$tmp" 2>&1 | Out-String).Trim()
    Write-Host "POST $wifiIp : $post"
    if ($post -notmatch 'HTTP 200\s*$') { $ok = $false }
} catch {
    Write-Host "POST failed: $($_.Exception.Message)"
    $ok = $false
} finally {
    Remove-Item $tmp -ErrorAction SilentlyContinue
}

if (-not (Test-Path "lan_relay.pid")) {
    Write-Host "WARN: lan_relay.pid missing (relay may still be starting)"
}

if ($ok) {
    Write-Host "`nLAN test PASSED"
    exit 0
}
Write-Host "`nLAN test FAILED - run up.bat and open-firewall-80.ps1 as admin"
exit 1
