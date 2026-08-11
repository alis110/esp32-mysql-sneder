$log = "D:\work\kar-khane-ard\data\svc-install-log.txt"
"=== remove old ===" | Out-File $log
$exe = "C:\Program Files\PLCBridge\PLCBridge.exe"
# remove whatever is registered
sc.exe stop PLCBridge 2>> $log | Out-Null
sc.exe delete PLCBridge 2>> $log | Out-Null
Start-Sleep 2
# also try pywin32 remove via old python registration
$env:PYTHONPATH = "D:\work\kar-khane-ard"
& "D:\work\kar-khane-ard\.venv\Scripts\python.exe" "D:\work\kar-khane-ard\plcbridge.py" remove >> $log 2>&1
Start-Sleep 1
Copy-Item "D:\work\kar-khane-ard\dist\PLCBridge.exe" $exe -Force
$cfgDir = "C:\ProgramData\PLCBridge\config"
New-Item -ItemType Directory -Force -Path $cfgDir,"C:\ProgramData\PLCBridge\data","C:\ProgramData\PLCBridge\logs" | Out-Null
Copy-Item "D:\work\kar-khane-ard\dist\config\config.ini" "$cfgDir\config.ini" -Force
"=== install from EXE ===" | Out-File $log -Append
& $exe --startup auto install >> $log 2>&1
"EXIT=$LASTEXITCODE" | Out-File $log -Append
sc.exe config PLCBridge start= delayed-auto | Out-Null
sc.exe failure PLCBridge reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Null
sc.exe failureflag PLCBridge 1 | Out-Null
Start-Service PLCBridge
Start-Sleep 2
sc.exe query PLCBridge >> $log 2>&1
sc.exe qc PLCBridge >> $log 2>&1
Get-Service PLCBridge | Format-List Name,Status,StartType | Out-File $log -Append
