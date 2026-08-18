# Allow Win7 VM / ESP32 to reach this laptop's AlisBoard API.
# Docker binds 127.0.0.1 only; lan_relay.py listens on 0.0.0.0:80 and :18773.
$ErrorActionPreference = "SilentlyContinue"
netsh advfirewall firewall delete rule name="AlisBoard mill API 80" | Out-Null
netsh advfirewall firewall delete rule name="AlisBoard mill API 18773" | Out-Null
netsh advfirewall firewall delete rule name="AlisBoard LAN relay 80" | Out-Null
netsh advfirewall firewall delete rule name="AlisBoard LAN relay 18773" | Out-Null
netsh advfirewall firewall add rule name="AlisBoard mill API 80" dir=in action=allow protocol=TCP localport=80 enable=yes profile=private,domain,public
netsh advfirewall firewall add rule name="AlisBoard mill API 18773" dir=in action=allow protocol=TCP localport=18773 enable=yes profile=private,domain,public
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($py) {
  netsh advfirewall firewall add rule name="AlisBoard LAN relay 80" dir=in action=allow protocol=TCP localport=80 program="$py" enable=yes profile=private,domain,public
  netsh advfirewall firewall add rule name="AlisBoard LAN relay 18773" dir=in action=allow protocol=TCP localport=18773 program="$py" enable=yes profile=private,domain,public
}
Write-Host "Firewall: inbound TCP 80 and 18773 allowed (Docker + LAN relay)"
