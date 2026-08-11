# Factory PC tools (Windows)

## Offline pack (NO internet) — use this at the factory

```text
tools\offline\Install-Offline.bat
```

Installs from local files only:

1. Visual C++ Redistributable  
2. CP2102 driver  
3. Portable PlatformIO + ESP32 toolchains  

Inventory: [`offline/MANIFEST.md`](offline/MANIFEST.md)

## Rebuild pack (PC with internet)

```text
tools\offline\Prepare-OfflinePack.ps1
```

Then copy the whole `tools\offline\` folder (~1.3 GB) onto the USB with the project.
