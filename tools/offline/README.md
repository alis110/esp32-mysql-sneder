# Offline packs for factory Windows PCs (NO internet at site)

## What is here

| Folder / file | Purpose | Internet at factory? |
|---------------|---------|----------------------|
| `cp2102\` | Silicon Labs CP210x driver (ZIP + extracted INF/EXE) | **No** |
| `portable-python\` | Portable Python 3.11 + PlatformIO (`pio`) | **No** |
| `platformio-wheels\` | pip wheels used to build portable PIO | (already installed) |
| `platformio-home\` | ESP32 toolchains / frameworks (~1 GB) | **No** |
| `Install-Offline.bat` | One-click install on factory PC | **No** |
| `Prepare-OfflinePack.ps1` | Rebuild this pack on a PC **with** internet | Yes (dev machine) |

## Factory PC (no internet)

1. Copy the whole project USB stick to e.g. `C:\PLCBridge\` (must include `tools\offline\` fully).
2. Run:

```text
tools\offline\Install-Offline.bat
```

3. Accept Windows driver / UAC prompts.
4. Open a **new** PowerShell:

```powershell
pio --version
Get-CimInstance Win32_SerialPort | Format-Table DeviceID, Name
```

5. Run `dist\PLCBridgeSetup.exe` → **Setup ESP32**.

Installer copies tools to `C:\PLCBridge\offline\` and sets:

- User `PATH` → `C:\PLCBridge\offline\portable-python\Scripts`
- User `PLATFORMIO_CORE_DIR` → `C:\PLCBridge\offline\platformio-home`

## Rebuild pack (on a PC with internet)

```powershell
cd tools\offline
powershell -ExecutionPolicy Bypass -File .\Prepare-OfflinePack.ps1
```

## Notes

- `platformio-home` is large (~1 GB). Keep it on the USB; it is gitignored.
- `cp2102` driver files are small and can stay in git.
- Bridge EXEs still do not need Python; `pio` is only for flashing.
