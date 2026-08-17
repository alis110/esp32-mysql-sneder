# Offline factory pack — inventory

Built for air-gapped Windows factory PCs. Run `Install-Offline.bat` on site.

## Components (all local files)

| Path | What | Approx size | Installed by |
|------|------|-------------|--------------|
| `vcredist\vc_redist.x64.exe` | MS VC++ 2015–2022 x64 (for EXE apps) | ~24 MB | Install-Offline |
| `vcredist\vc_redist.x86.exe` | MS VC++ 2015–2022 x86 | ~13 MB | Install-Offline |
| `cp2102\vcp-installer\` | Silicon Labs CP210x VCP installer | ~7 MB | Install-Offline |
| `cp2102\universal\` | CP210x Universal INF/SYS | ~0.3 MB | fallback |
| `portable-python\` | Python 3.11 embed + PlatformIO + esptool | ~100 MB+ | copied to `C:\PLCBridge\offline` |
| `platformio-wheels\` | pip wheels used to build portable PIO | varies | (build only) |
| `platformio-home\` | ESP32 platform + toolchains | ~1.1 GB | copied |
| `firmware-bin\` | Prebuilt `firmware.bin` / bootloader / partitions | ~1 MB | optional upload |
| `../../firmware/lib/ArduinoJson\` | Vendored library (no net for compile) | ~2 MB | used by Setup ESP32 |

## Factory steps

1. Copy **entire** project USB → e.g. `C:\PLCBridge\` (must include `tools\offline\` fully, ~1.3 GB).
2. Run `tools\offline\Install-Offline.bat`
3. New PowerShell: `pio --version`
4. `dist\PLCBridgeSetup.exe` → WinCC factory → Check DB → Setup ESP32 → Install Service

Optional without compile: `Upload-Prebuilt-Firmware.bat COM7`

## Rebuild on a PC with internet

```powershell
cd tools\offline
powershell -ExecutionPolicy Bypass -File .\Prepare-OfflinePack.ps1
```

## Not required on factory PC

- Docker
- Full Python installer (portable is enough for pio)
- Visual Studio / VS Code
- Internet
