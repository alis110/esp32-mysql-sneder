# PLCBridge — Windows 7 32-bit install pack (offline)

The factory PC has **no internet**. Copy **this whole folder** onto a USB stick. That is the entire install.

The EXEs are **32-bit**. 64-bit builds in `dist\` will not run on Windows 7 x86.

```text
SQL Server .\WINCC  →  PLCBridge (Windows service)  →  USB  →  ESP32  →  Wi-Fi Alissss  →  laptop API :80
```

Database login is the same as SSMS: `.\WINCC` with **Windows Authentication** — no SQL password.

---

## What must stay running on the laptop

Keep this laptop on Wi-Fi **Alissss** with Docker up. The ESP posts here:

| Item | Value |
|------|--------|
| Dashboard | http://10.33.97.45/ |
| ESP POST URL | http://10.33.97.45/api/plc-records |
| Token | `lab-token` |
| Wi-Fi SSID | `Alissss` (2.4 GHz) |

If the laptop DHCP address changes, run `ipconfig` and flash the ESP again with the new URL.

Start the API (on the laptop, before you test):

```text
lab\receiver\up.bat
```

Then open http://10.33.97.45/ — rows appear when the ESP sends.

---

## On the factory / other PC (this USB folder)

Python is **already inside** `PLCBridge.exe` / `PLCBridgeSetup.exe`. Do **not** install a separate Python.

Windows 7 needs two offline updates (in `updates\`). Copy this **whole folder** over the old one.

1. Right-click `Install-All.bat` → **Run as administrator**.
2. If it says **REBOOT**, restart Windows, then run `Install-All.bat` again.
3. Then `Open-Setup.bat` → **WinCC factory** (or **Check DB**) — same as SSMS: `CPUPC01\WINCC`, Windows Authentication, no password.
4. Plug the ESP with a **data** USB cable. If Device Manager shows **Other devices → CP2102** with a yellow mark, run `Install-CP2102.bat` as Administrator (the old pack used a Windows 10 driver that Windows 7 cannot use).
5. Success is **Ports (COM & LPT) → Silicon Labs CP210x USB to UART Bridge (COMx)** — not COM1 only.
6. In Setup, set Target API to `http://10.33.97.45/api/plc-records` → click the big teal **FLASH ESP32 NOW** (that is the only button that writes firmware onto the board).

If windows look huge: Control Panel → Display → **Smaller - 100%** (or 125%), log off, log on.

Do **not** keep `ucrtbase.dll` / `api-ms-win-crt-*.dll` next to the EXEs. Those were Win10 files and they caused `_socket: The parameter is incorrect`.

The bridge sends **one SQL row every 30 seconds** (`batch_size=1`) so the PC stays cool.

If Check DB works but the service cannot read SQL:

1. `services.msc` → **PLCBridge** → **Log On**
2. Set the factory Windows user (`Operator` on this PC), not Local System
3. Start the service

---

## Setup buttons

| Button | Action |
|--------|--------|
| **Install All** | VC++ + CP2102 Win7 driver + Windows service |
| **FLASH ESP32 NOW** | Writes firmware onto the ESP32 (the only flash button) |
| **WinCC factory** | Host=`COMPUTER\WINCC`, Windows auth, empty password, then Check DB |
| **Check DB** | Test SQL Server like SSMS (no password) |
| **Install Service** | Service only, after a config change |
| **Uninstall** | Removes the service; config/logs stay |

---

## Logs

`Run-Console.bat` runs the bridge without the service.

Service log: `C:\ProgramData\PLCBridge\logs\plcbridge.log`  
Config: `C:\ProgramData\PLCBridge\config\config.ini`

Windows 7 needs **SP1** plus the two `.msu` files in `updates\` (KB2533623 and KB2999226). Python is bundled in the EXEs — a separate Python install is not required.

---

## Check DB sees the database but no values

Flow values live in `TagUncompressed`. If that table is empty, numbers are in WinCC-compressed `TagCompressed` and a normal SQL `SELECT` cannot decode them. Enable uncompressed tag logging in WinCC.

Do **not** restore dump `.bak` files or attach dump `.mdf` files on the live WinCC PC.

---

## Folder contents (all local)

| File | Role |
|------|------|
| `PLCBridgeSetup.exe` | Setup UI — run installs from here |
| `PLCBridge.exe` | 32-bit bridge |
| `Install-All.bat` | Same as **Install All** |
| `esptool.exe` | Offline ESP flash |
| `config\config.wincc.ini` | SQL Server WinCC + Windows auth, slow poll |
| `vcredist\vc_redist.x86.exe` | VC++ x86 |
| `drivers\cp2102-win7\` | CP2102 VCP 6.7 for **Windows 7** (`slabvcp.inf`) |
| `Install-CP2102.bat` | Fix yellow-bang CP2102 (run as Admin, ESP plugged in) |
| `updates\` | KB2533623 + KB2999226 (Windows 7, offline) |
| `firmware-bin\` | Prebuilt ESP firmware (Alissss + laptop API) |
