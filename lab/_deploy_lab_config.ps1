Copy-Item "D:\work\kar-khane-ard\config\config.ini" "C:\ProgramData\PLCBridge\config\config.ini" -Force
Remove-Item "C:\ProgramData\PLCBridge\data\state.sqlite3*" -Force -ErrorAction SilentlyContinue
"STATE_CLEARED" | Out-File "D:\work\kar-khane-ard\data\lab-ready.txt"
