# Lab / Setup UI

Lab and setup tools that ship with the main project. Full architecture and production docs are in the root [`README.md`](../README.md).

## Run

```powershell
# From repo root
.\lab\run_lab.bat
# Or after build:
.\dist\PLCBridgeSetup.exe
```

## Docker MySQL (lab)

```powershell
cd lab
docker compose up -d
```

- Host: `127.0.0.1`
- Port: `3307`
- DB / user / pass: `plcbridge_lab` / `bridge` / `bridge`
- Sample table: `lab_events` (from `init.sql`)

## Mock API

In Setup, click **Mock API** (port `8089`). If the port is busy, Setup frees it and ESP POSTs appear in the same window Log.

Optional firewall helper:

```powershell
.\lab\open_firewall_8089.ps1
```

Set the Windows network profile to **Private** so the ESP can reach the PC LAN IP.

## End-to-end test order

1. Start Docker MySQL
2. Setup → Check MySQL
3. Scan Wi-Fi (2.4 GHz) + Mock API
4. Setup ESP32
5. Install / Start Service
6. API hits should appear in the Log

## Helper files

| File | Purpose |
|------|---------|
| `lab_app.py` | Setup UI source |
| `mock_api.py` | Standalone console Mock API (optional; prefer the in-UI button) |
| `build_setup.bat` | Build `PLCBridgeSetup.exe` |
| `finish_local_lab.bat` | Lab finish helper |
| `diag_serial.py` | Serial diagnostics |
| `docker-compose.yml` + `init.sql` | Lab MySQL |
