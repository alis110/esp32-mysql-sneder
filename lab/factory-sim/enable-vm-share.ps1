# Unlock Alis_lap\user and let the Win7 VM map \\172.21.80.1\G without a password.
# Run as Administrator (UAC). Does not delete MySQL volumes.
$ErrorActionPreference = 'Stop'

net user user /active:yes | Out-Null
net user guest /active:yes | Out-Null
net accounts /lockoutthreshold:0 | Out-Null

New-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' -Name everyoneincludesanonymous -PropertyType DWord -Value 1 -Force | Out-Null
New-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' -Name LimitBlankPasswordUse -PropertyType DWord -Value 0 -Force | Out-Null
New-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters' -Name RestrictNullSessAccess -PropertyType DWord -Value 0 -Force | Out-Null
New-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\LanmanWorkstation\Parameters' -Name AllowInsecureGuestAuth -PropertyType DWord -Value 1 -Force | Out-Null

$shares = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters' -Name NullSessionShares -ErrorAction SilentlyContinue
$have = @()
if ($shares -and $shares.NullSessionShares) { $have = @($shares.NullSessionShares) }
if ($have -notcontains 'G') { $have += 'G' }
if ($have -notcontains 'vm-media') { $have += 'vm-media' }
New-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters' -Name NullSessionShares -PropertyType MultiString -Value $have -Force | Out-Null

Grant-SmbShareAccess -Name G -AccountName Everyone -AccessRight Full -Force | Out-Null
Grant-SmbShareAccess -Name G -AccountName Guest -AccessRight Full -Force -ErrorAction SilentlyContinue | Out-Null
Grant-SmbShareAccess -Name vm-media -AccountName Everyone -AccessRight Full -Force | Out-Null

netsh advfirewall firewall set rule group='File and Printer Sharing' new enable=Yes | Out-Null

Write-Host 'OK. Account user is unlocked. Share G is guest/Everyone Full.'
Write-Host 'In the Win7 VM run MAP_G.bat once from the DVD / vm-media.'
Write-Host 'After that G: comes up at every logon. No password dialog.'
net user user | Select-String -Pattern 'active'
Get-SmbShareAccess -Name G | Format-Table -AutoSize
