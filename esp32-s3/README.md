# AlisBoard (ESP32-S3)

Plug the ESP32-S3 into the mill PC. Windows mounts a USB disk. Run **AlisBoard.exe** from that disk. Nothing is installed on Windows.

```text
Mill PC  (Windows 7 x86, current Windows user)
  SQL Server  .\WINCC   Windows Authentication, no SQL password
  AlisBoard.exe         portable, on the USB disk
        │  HTTP JSON (same payload as ESP Wi-Fi)
        ▼
Mill API  (lab\receiver)  →  MySQL replica
ESP32-S3
  USB disk with AlisBoard.exe  (required)
  Wi-Fi POST                   (optional, slow, not for backfill)
```

## On the mill PC

1. Plug the board into a **data** USB port (not a charge-only cable, not a hub if you can avoid it).
2. A removable disk named **ALISBOARD** appears (often `G:`).
3. Double-click **OPEN.bat** or **AlisBoard.exe**. Keep the window running.
4. Browser does **not** open by itself. Use **Open browser** only if you want `http://127.0.0.1:48123`.
5. Leave **Server** as `.\WINCC` and **Database** as `all`.
6. Set **API URL** to the mill API, for example:
   - same PC: `http://127.0.0.1:18773/api/plc-records`
   - Win7 VM → this laptop: `http://172.21.80.1:18773/api/plc-records`
7. Token: `lab-token`. SSID can stay empty.

SQL uses the logged-in Windows user. Do not type a SQL password. Do not install Python, Visual C++, or a Windows service on the mill PC.

### What AlisBoard sends

| Phase | What happens |
|-------|----------------|
| Start | Asks the mill API which databases/tables already exist. Does not crawl until the API answers. |
| Backfill | Old WinCC archives first (date in the database name). If there is no date, order is random until the newest is found. |
| Live | Newest archive of each kind (TLG_F, TLG_S, ALG, CC), every **4 seconds**. |
| Restart | After power loss, ESP reset, or PC reboot: resume from MySQL watermarks. Duplicate batches are ignored. |

ESP Wi-Fi is optional. The PC does the SQL crawl. The ESP must **not** dump whole databases over Wi-Fi.

**Exit** stops the program. The window **X** only hides it.

## Build (this PC)

```text
esp32-s3\helper\build-win7-x86.bat
```

Produces `esp32-s3\pack\AlisBoard.exe` (32-bit, static CRT). Rebuild firmware so the USB disk contains that exe.

## Flash ESP32-S3

The USB disk image is generated at build time from `pack\AlisBoard.exe`. Copying a large exe onto `G:` does **not** survive an ESP reset.

1. Eject the ALISBOARD disk if Windows shows it.
2. Hold **BOOT**, tap **RESET (EN)**, keep holding BOOT.
3. From `esp32-s3\firmware`:

```text
python flash_wait.py COM11
```

Use the COM port shown in Device Manager (often COM11, VID `303A`). Release BOOT when writing starts.

If the port is USB-JTAG (`PID 1001`), this often works without BOOT:

```text
pio run -e esp32-s3-from-recovery -t upload --upload-port COM11
```

Then **unplug**, wait **5 seconds**, plug back in. Open the ALISBOARD disk.

Details: `firmware\FLASH_MANUAL.txt`.

If the disk appears and vanishes every few seconds: unplug 5 seconds, use a rear USB port, reflash. Eject only the mass-storage disk, not the JTAG COM device.

## Folders

| Path | Role |
|------|------|
| `helper\alisboard.c` | Portable Win32 UI + SQL crawl + HTTP to mill |
| `helper\build-win7-x86.bat` | Build AlisBoard.exe |
| `helper\gen_msc.py` | FAT image baked into firmware |
| `firmware\` | ESP32-S3 TinyUSB mass-storage firmware |
| `pack\` | Local build output (exe, OPEN.bat). Do not treat this as the mill USB disk. |

## Do not

- Put a SQL password in the UI
- Send Windows credentials to the ESP
- Restore WinCC `.bak` / attach `.mdf` on the live mill PC
- Install anything on the mill PC
- Use ESP Wi-Fi for the historical backfill
