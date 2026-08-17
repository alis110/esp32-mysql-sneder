# Lab / Setup UI

Lab and setup tools that ship with the main project. Full architecture and production docs are in the root [`README.md`](../README.md).

## Run

```powershell
# From repo root
.\lab\run_lab.bat
# Or after build:
.\dist\PLCBridgeSetup.exe
```

## SQL Server / WinCC

Setup defaults to SQL Server `.\WINCC` with **Windows authentication**. Click **WinCC factory** then **Check DB**.

There is no MySQL in this project. On the factory PC, WinCC already has `*TLG_F*` / `*TLG_S*` databases attached — do not attach dump `.mdf` files.

## Mock API

In Setup, click **Mock API** (port `8089`) for a quick local loop. For the real ESP-over-Wi-Fi test, use the Docker receiver on **port 80** instead: [`receiver/README.md`](receiver/README.md).

```text
.\lab\receiver\up.bat
```

Dashboard: http://10.33.97.45/  (laptop + ESP on Wi-Fi **Alissss**)

Optional firewall helper for the old Mock API port:

```powershell
.\lab\open_firewall_8089.ps1
```

Set the Windows network profile to **Private** so the ESP can reach the PC LAN IP.

## End-to-end test order

1. Setup → **WinCC factory** → **Check DB**
2. Scan Wi-Fi (2.4 GHz) + Mock API
3. Setup ESP32
4. **Install All** (or Install Service)
5. API hits should appear in the Log

## Helper files

| File | Purpose |
|------|---------|
| `lab_app.py` | Setup UI source |
| `mock_api.py` | Standalone console Mock API (optional; prefer the in-UI button) |
| `build_setup.bat` | Build `PLCBridgeSetup.exe` |
| `finish_local_lab.bat` | Lab finish helper |
| `diag_serial.py` | Serial diagnostics |
