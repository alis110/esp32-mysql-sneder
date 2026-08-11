# Offline packs for factory Windows PCs (NO internet on site)

See **[MANIFEST.md](MANIFEST.md)** for the full file list.

## Install on factory PC

```text
tools\offline\Install-Offline.bat
```

Installs in order (all from local files):

1. **Visual C++ Redistributable** (needed by `PLCBridge.exe` / Setup)
2. **CP2102** Silicon Labs driver
3. **Portable PlatformIO** + ESP32 toolchains → `C:\PLCBridge\offline\`

Then open a **new** PowerShell and run `dist\PLCBridgeSetup.exe`.

## Optional: flash without compiling

```text
tools\offline\Upload-Prebuilt-Firmware.bat COM7
```

## Rebuild pack (PC with internet)

```powershell
cd tools\offline
powershell -ExecutionPolicy Bypass -File .\Prepare-OfflinePack.ps1
```

## Notes

- Keep the whole `tools\offline\` folder on the USB (~1.3 GB).
- Large toolchains are gitignored; they live on your prepared disk/USB.
- Small installers (`cp2102`, `vcredist`, scripts, `firmware-bin`) can ship with the repo.
