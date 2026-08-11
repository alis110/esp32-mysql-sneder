netsh advfirewall set allprofiles firewallpolicy blockinbound,allowoutbound
netsh advfirewall firewall delete rule name="PLCBridge Mock API 8089"
netsh advfirewall firewall delete rule name="PLCBridge Mock API 8089 LAN"
netsh advfirewall firewall add rule name="PLCBridge Mock API 8089" dir=in action=allow protocol=TCP localport=8089 enable=yes profile=private,domain
"HARDENED" | Out-File d:\work\kar-khane-ard\data\fw_ok.txt
