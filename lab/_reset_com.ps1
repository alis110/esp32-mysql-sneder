pnputil /restart-device "USB\VID_10C4&PID_EA60\0001"
Start-Sleep 4
Get-PnpDevice | Where-Object { $_.FriendlyName -like "*CP210*" } | Format-Table Status, FriendlyName
Get-CimInstance Win32_SerialPort | Format-Table DeviceID, Name
