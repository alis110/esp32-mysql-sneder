# ESP32 WinCC Sender (PLCBridge)

**Author:** [Ali Sadeghi](https://github.com/alis110) (`@alis110`) · `alisadeghi201@gmail.com`

A light, durable bridge that reads rows from Siemens WinCC Tag Logging on SQL Server and delivers them to a REST API through:

```text
SQL Server (WinCC)  →  Python Bridge (Windows Service)  →  USB Serial  →  ESP32  →  Wi-Fi  →  HTTPS/HTTP API
```

Repository: [alis110/esp32-mysql-sneder](https://github.com/alis110/esp32-mysql-sneder)

This project **does not guess your schema**. You must set a real SQL query in the config. No data is read or sent until `enabled=true` and a valid query are configured.

---

## Contents

1. [What is included](#what-is-included)
2. [Requirements](#requirements)
3. [Factory install (offline USB)](#factory-install-offline-usb)
4. [Quick start with ready EXEs](#quick-start-with-ready-exes)
5. [Setup UI (PLCBridgeSetup)](#setup-ui-plcbridgesetup)
6. [Factory: WinCC 7 + SQL Server](#factory-wincc-7--sql-server)
7. [Local lab (Mock API)](#local-lab-mock-api)
8. [Light query (low PC load)](#light-query-low-pc-load)
9. [ESP32 firmware](#esp32-firmware)
10. [Serial protocol](#serial-protocol)
11. [Run from Python source](#run-from-python-source)
12. [Build EXEs from source](#build-exes-from-source)
13. [Windows Service](#windows-service)
14. [Delivery guarantee and idempotency](#delivery-guarantee-and-idempotency)
15. [Project layout](#project-layout)
16. [Troubleshooting](#troubleshooting)
17. [Security](#security)

---

## What is included

| Component | Role |
|-----------|------|
| **PLCBridge.exe** | Bridge: reads SQL Server / WinCC, sends records to ESP over USB, commits progress in SQLite only after ACK |
| **PLCBridgeSetup.exe** | Setup UI: Check DB, **Install All** (VC++ + CP2102 + service), ESP flash |
| **firmware/** | ESP32 PlatformIO app: receives JSON on Serial, POSTs to API over Wi-Fi, returns ACK/NACK |
| **service/** | Install/remove Windows Service (auto-start + crash recovery) |
| **lab/** | Setup UI, Mock API, lab helpers |

Designed for industrial PCs: **low load** — small batches, longer poll interval, only new rows via `id > last_id`.

---

## Requirements

### Hardware
- Factory PC: **Windows 7 32-bit** (or Windows 10/11). Ready EXEs must be built **32-bit** for Win7 x86; a 64-bit Python 3.12 build will not run there.
- ESP32-DevKitC (or compatible) + USB **data** cable (not charge-only)
- USB-UART chip **CP2102** (VID/PID `10C4:EA60`) — most common on DevKit boards
- **2.4 GHz** Wi-Fi for the ESP32 (classic ESP32 has no 5 GHz)

### Software on the factory Windows PC

| Software | Required? | Purpose |
|----------|-----------|---------|
| **`PLCBridgeSetup.exe` + `PLCBridge.exe`** | **Yes** | One UI: Check DB, Install All, flash |
| **CP2102 / Silicon Labs VCP driver** | **Yes** | Windows must create a `COMx` port for the ESP32 — **Install All** installs it from the USB pack |
| **Visual C++ x86 runtime** | **Yes** on Win7 | **Install All** installs `vcredist` from the USB pack |
| **PlatformIO Core (`pio`)** | Only on a laptop that **compiles** firmware | Not needed on the factory PC |
| **Python 3.11+** | Only to run from source or install `pio` | Not required to run the ready EXEs |
| **SQL Server ODBC driver** | **Yes** | Connects to WinCC (`.\WINCC`) with Windows auth |

**Important:** The factory PC has **no internet**. Use the 32-bit USB pack in [`system-install/`](system-install/README.md). Flash the ESP on a laptop first, then on site click **Install All** in Setup.

---

## Factory install (offline USB)

The factory WinCC PC is **Windows 7 32-bit** and offline. Copy **only** the `system-install\` folder onto a USB stick. Do not expect downloads, pip, or PlatformIO on site. Do **not** restore dump `.bak` files or attach dump `.mdf` files — live WinCC already has its segment databases.

### On the laptop (has internet) before you go

1. Know the factory **2.4 GHz** Wi-Fi SSID/password and the API URL.
2. Plug the ESP32 here, run Setup, set Wi-Fi + API, click **Setup ESP32** (needs PlatformIO on this laptop).
3. Take the flashed board and the USB folder to the factory.

### On the factory PC

1. Run `Open-Setup.bat` (or `PLCBridgeSetup.exe`).
2. **WinCC factory** → **Check DB**.
3. Click **Install All** and accept UAC.

That one button, from files already on the stick, installs:

- Visual C++ x86
- CP2102 USB driver
- PLCBridge Windows service (auto-start after reboot)

If Check DB works but the service cannot read SQL Server: `services.msc` → **PLCBridge** → **Log On** → factory Windows user (for example `CPUPC01\Operator`), not Local System.

Full stick contents: [`system-install/README.md`](system-install/README.md).

### Optional: rewrite ESP firmware from the stick

**Setup ESP32** on the factory PC uses bundled `esptool.exe` + `firmware-bin\` (same Wi-Fi/API that were baked on the laptop). Stop the service and close the serial monitor first so COM is free.

### Laptop-only: PlatformIO (compile firmware)

Only if you need to change Wi-Fi/API and rebuild firmware. Not for the factory PC.

```powershell
py -3 -m pip install -U platformio
cd firmware
pio run -t upload
```

An optional large offline PIO pack still lives under `tools/offline/` for lab machines; the factory USB pack does **not** need it.

---

## Quick start with ready EXEs

Factory (Win7 32-bit, no internet): use **`system-install\`** — see [Factory install](#factory-install-offline-usb).

Lab / Windows 10+ 64-bit: `dist\`

- `PLCBridgeSetup.exe` — setup panel
- `PLCBridge.exe` — bridge
- `Install-All.bat` — same as the **Install All** button (VC++ + driver + service when those files are present)

### Recommended factory flow

1. Flash the ESP on a laptop (**Setup ESP32**).
2. On the factory PC run `system-install\PLCBridgeSetup.exe`.
3. **WinCC factory** → **Check DB**.
4. **Install All** once (UAC / Administrator).
5. Service starts at boot even if no user is logged in.

Runtime paths after service install:

| Item | Path |
|------|------|
| EXE | `C:\Program Files\PLCBridge\PLCBridge.exe` |
| Config | `C:\ProgramData\PLCBridge\config\config.ini` |
| State | `C:\ProgramData\PLCBridge\data\state.sqlite3` |
| Log | `C:\ProgramData\PLCBridge\logs\plcbridge.log` |

---

## Setup UI (PLCBridgeSetup)

```powershell
.\dist\PLCBridgeSetup.exe
# or from source:
.\lab\run_lab.bat
```

| Button | Action |
|--------|--------|
| **Refresh / Check DB** | Status for ESP, Wi-Fi, SQL Server / WinCC, Mock API, Service |
| **WinCC factory** | Fill SQL Server `.\WINCC`, Windows auth, `database=auto`, TagUncompressed query |
| **Scan Wi-Fi** | List SSIDs; fill saved Windows profile password when available |
| **Mock API** | Lab API on port `8089` inside this window; frees the port if another process holds it |
| **Setup ESP32** | Write `secrets.h` + PlatformIO upload when `pio` exists; otherwise flash bundled `firmware-bin` with `esptool` |
| **Install All** | UAC: VC++ x86 + CP2102 driver + Windows service from local files |
| **Install / Uninstall Service** | Service only (reinstall after config change) |
| **Start / Stop** | Control installed service |
| **UI at login** | Startup shortcut so Setup opens after user login |
| **Copy / Clear** | Log clipboard / clear |

**Network tip:** set the Windows Wi-Fi profile to **Private** and allow the API port in the firewall (e.g. `8089` for lab) so the ESP can reach the PC.

More lab notes: [`lab/README.md`](lab/README.md)

---

## Factory: WinCC 7 + SQL Server

The ROSHAN dump under `Roshan/` is **Siemens WinCC 7.0.0.3** on SQL Server `CPUPC01\WINCC` (same as `.\WINCC` on that PC). There is no MySQL.

Factory backups in `Roshan/bak/` cover every WinCC database type on that instance:

| Type | Example name | What is in it | Readable with SQL? |
|------|----------------|---------------|--------------------|
| Tag Logging Fast | `..._TLG_F_<start>_<end>` | 11 PWC10 flow tags, `TagCompressed` blocks | Values only if `TagUncompressed` is filled |
| Tag Logging Slow | `..._TLG_S_<start>_<end>` | Same tag list, usually no value rows | Config only in the dumps |
| Alarm Logging | `..._ALG_<start>_<end>` | Message catalog `AlgCSDataENU`; events in `MsArcLong` | Events yes when `MsArcLong` has rows |
| Config (CS) | `CC_Kamran_F_...` | ~42k tags, S7 connection `192.168.0.10`, PDE archive setup | Catalog yes, not live values |
| Runtime (RT) | `CC_Kamran_F_...R` | `AMH`/`AMT` = list of all TLG/ALG segments | Segment index, not flow numbers |

| What | Detail |
|------|--------|
| Instance | `.\WINCC` / `CPUPC01\WINCC` |
| Project / PC | ROSHAN (runtime name) / Kamran_Fars (CS) on `CPUPC01` |
| PLC | SIMATIC S7, `IP,192.168.0.10` |
| Logged tags | 11 flow tags, scan **1 second** (Scale `A_4002` archive factor 1; others factor 10) |
| `database=` | `auto` or `auto:tlg_f` (newest Fast); `auto:alg` for alarms; `auto:tlg_s` / `auto:cc_rt` / `auto:cc_cs` |
| Auth | Windows integrated (no password) |

**On the factory PC, do not restore dump `.bak` / attach dump `.mdf` files.** WinCC already has the live segment databases. The bridge follows the newest matching name when you use `database=auto`.

Template: [`config/config.wincc.ini`](config/config.wincc.ini)

### What this dump can and cannot give you

- **Flow values:** `TagUncompressed` (`ValueID`, `TimeStamp`, `MS`, `RealValue`, `Quality`, `Flags`). The dump stores samples in `TagCompressed.BinValues` (proprietary). A normal `SELECT` cannot return flowrates until uncompressed logging is enabled in WinCC.
- **Alarms:** newest `*ALG*` database, table `MsArcLong`. Set `database=auto:alg` and the alarm query commented in `config.wincc.ini`. This dump’s one-hour ALG segment had **0** `MsArcLong` rows; the live current segment on site should have events.
- **Tag catalog:** CS database `MCPTVARIABLEDESC` / `PDE#TAGs` (11 archived flow tags). Runtime `AMH` is only an index of archive files (65k+ ALG segments historically), not the alarm text stream.
- User Archives (`UA#*`) are empty in this project.

If `TagUncompressed` is empty on site, enable uncompressed logging in WinCC Tag Logging, **or** query `MsArcLong` for alarms. WinCC Information Server / Connectivity Pack OLE-DB (`WinCCOLEDBProvider.1`) can decompress `TagCompressed` if you need historical flow.

### Windows Service account

Windows auth uses the **process identity**. Setup UI runs as your Windows user (works with `-E`). The service defaults to `LocalSystem`, which SQL Server may reject. If Check DB works but the service does not:

1. Set the `PLCBridge` service to run as the factory Windows user, or
2. Grant that Windows login (or `NT AUTHORITY\SYSTEM`) rights in SQL Server, or
3. Switch `auth=sql` and fill username/password.

---

## Local lab (Mock API)

Test the ESP → API path without a production HTTP endpoint.

**Preferred (this laptop, Wi-Fi Alissss):** Docker receiver on port 80 — dashboard plus SQLite store.

```text
.\lab\receiver\up.bat
```

Open http://10.33.97.45/  · ESP POST http://10.33.97.45/api/plc-records  · token `lab-token`  
Details: [`lab/receiver/README.md`](lab/receiver/README.md)

**Optional in-UI Mock API** (port `8089`): click **Mock API** in Setup.

Lab sample config: [`config/config.lab.ini`](config/config.lab.ini)

A successful end-to-end run means:
1. Bridge reads `TagUncompressed` from the newest `*TLG_F*` database
2. Sends rows to ESP on COM (one row every 30 seconds)
3. ESP POSTs to the laptop API over Wi-Fi **Alissss**
4. ACK returns and `last_success_id` advances
5. Rows appear on the port-80 dashboard

---

## Light query (low PC load)

Never run `SELECT *` on a large table. Select only needed columns, only new IDs, with a small batch.

**SQL Server / WinCC:** use `TOP (%(batch_size)s)`, not `LIMIT`. See [`config/config.wincc.ini`](config/config.wincc.ini).

Required contract:

- `id_column` (default `id`) must be numeric, unique, and **strictly increasing**
- Query must use `> %(last_id)s` and `ORDER BY ... ASC`
- Prefer an index on that ID column
- Use `%(batch_size)s`

Light defaults used by this project:

| Setting | Suggested | Meaning |
|---------|-----------|---------|
| `batch_size` | `1` | One row per poll (keeps the PC cool) |
| `poll_interval_seconds` | `30` | Poll the database every 30 seconds |
| `retry_delay_seconds` | `20` | Delay after errors |
| `connect_timeout_seconds` | `5` | Connect timeout |

Template: [`config/config.example.ini`](config/config.example.ini)  
WinCC factory: [`config/config.wincc.ini`](config/config.wincc.ini)  
Copy to `config/config.ini` (real config is gitignored).

Before production, inspect schema with a Windows login that has SELECT rights.

SQL Server / WinCC:

```sql
SELECT name FROM sys.databases WHERE state_desc = 'ONLINE';
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE';
```

Or click **Check DB** in Setup — it lists WinCC databases and tables.

Use **SELECT-only** rights on the tables you query.

---

## ESP32 firmware

1. Install PlatformIO.
2. Copy `firmware/include/secrets.example.h` → `secrets.h` and fill:

```cpp
#define WIFI_SSID "Your-2.4GHz-SSID"
#define WIFI_PASSWORD "..."
#define API_URL "https://your.api/endpoint"
#define API_TOKEN "..."
#define ALLOW_INSECURE_TLS false   // lab only: true for HTTP / quick tests
```

3. Flash:

```powershell
cd firmware
pio run -t upload
pio device monitor -b 115200
```

Or use Setup → **Setup ESP32**.

Firmware behavior:
- JSON lines up to 16 KiB
- Wi-Fi reconnect
- HTTP timeout / retry
- ~60s watchdog
- HTTP 2xx → ACK
- Most 4xx (except 408/429) are not retried internally; the Bridge retries later

TLS: lab can use `ALLOW_INSECURE_TLS true` or plain HTTP. For production, embed the issuing CA in `ROOT_CA` and keep insecure mode off.

---

## Serial protocol

One UTF-8 JSON object per line + `\n`:

```json
{"type":"data","id":15230,"idempotency_key":"plc-record-15230","payload":{"temperature":73.4}}
{"type":"ack","id":15230,"status":"success"}
{"type":"nack","id":15230,"error":"wifi_unavailable"}
```

The Bridge updates `last_success_id` in SQLite with a durable transaction only after a matching `ack`. If SQL Server, COM, ESP, Wi-Fi, or the API fails, the **same ID** is retried; later IDs do not jump ahead.

---

## Run from Python source

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config\config.example.ini config\config.ini
# Edit config.ini: enabled=true + real query
python plcbridge.py --config config\config.ini
```

Serial settings:

```ini
[serial]
port = auto
vid_pid = 10C4:EA60
```

Or pin a port: `port = COM7`

List ports:

```powershell
Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Name, PNPDeviceID
```

Unit tests:

```powershell
python -m unittest discover -s tests -v
```

---

## Build EXEs from source

64-bit (this PC / lab):

```powershell
.\build.bat
```

32-bit Windows 7 pack (factory USB):

```powershell
.\build-win7-x86.bat
```

Output: `system-install\PLCBridge.exe`, `PLCBridgeSetup.exe`, `esptool.exe`, plus drivers, vcredist, `Install-All.bat`.

PyInstaller specs in repo: `PLCBridge.spec`, `PLCBridgeSetup.spec`.

---

## Windows Service

From Setup (**Install All** or **Install Service**) or `system-install\Install-All.bat`.

Service details:
- Name: `PLCBridge`
- Startup: Automatic (delayed)
- Recovery: restart after crash
- Default account: `LocalSystem`

Remove:

```powershell
.\dist\Uninstall-Service.bat
```

Config / state / logs intentionally remain under `ProgramData` so the resume point is not wiped.

Console mode on the installed EXE:

```powershell
& "C:\Program Files\PLCBridge\PLCBridge.exe" --console --config "C:\ProgramData\PLCBridge\config\config.ini"
```

---

## Delivery guarantee and idempotency

Delivery model: **at-least-once**.

If the API accepts a record but the ACK never reaches the Bridge, the same message is sent again. To avoid duplicates, the API must treat:

```http
Idempotency-Key: plc-record-15230
```

as unique and answer repeated requests with 2xx without creating a second row.

Without API-side idempotency, you cannot simultaneously guarantee “never lost” and “never duplicated” in a distributed system.

---

## Project layout

```text
esp32-mysql-sneder/
├── app/                      # Python bridge (SQL Server, serial, state, service)
├── config/
│   ├── config.example.ini    # Factory template (SQL Server / WinCC, Windows auth)
│   ├── config.wincc.ini      # Same WinCC 7 / SQL Server template
│   └── config.lab.ini        # Local test against .\WINCC + Mock API
├── firmware/                 # PlatformIO ESP32 project
│   ├── platformio.ini
│   ├── src/main.cpp
│   └── include/secrets.example.h
├── tools/                    # Install-All.bat + optional lab PIO helpers
├── lab/                      # Setup UI + Docker lab API (port 80)
│   └── receiver/             # ESP JSON receiver + dashboard
├── service/                  # Windows Service install/remove (Win10 path)
├── system-install/           # 32-bit offline USB pack for Win7 factory
├── tests/
├── dist/                     # 64-bit ready EXEs
├── plcbridge.py
├── build.bat
├── build-win7-x86.bat
├── requirements.txt
└── README.md
```

### Intentionally not in Git

| Path | Reason |
|------|--------|
| `config/config.ini` | Real database credentials |
| `firmware/include/secrets.h` | Real Wi-Fi / API token |
| `.venv/` | Local virtualenv |
| `build/`, `firmware/.pio/` | Build artifacts |
| `data/*.sqlite3`, `logs/` | Runtime state and logs |

Copy from `*.example*` / `config.lab.ini` for local use.

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| ESP not found / no COM | **Install All** (CP2102 from the USB pack); data USB cable; Device Manager `10C4:EA60` |
| Setup ESP32 on factory PC | Uses `esptool` + `firmware-bin`; bake Wi-Fi on a laptop with PlatformIO first |
| `wifi_unavailable` / ACK timeout | Use a **2.4 GHz** SSID, not 5 GHz |
| `tcp_connect_failed` to API on PC | Private network profile + firewall allow for the API port |
| Mock API “port in use” | Click **Mock API** again (Setup frees the port) |
| Service / error 1063 on double-click EXE | Expected for SCM services; start via Service or `--console` |
| SQL Server / WinCC fail | Host `.\WINCC`, Windows auth, **Check DB**; service account (see WinCC section) |
| TagUncompressed empty | Values are in compressed `BinValues`; enable uncompressed logging or change query |
| No data flowing | Query must include `%(last_id)s`; SQL Server must use `TOP`, not `LIMIT`; check service log |

---

## Security

- Do not commit real secrets (`secrets.h` and `config.ini` are gitignored).
- Use a database user with **SELECT** only (or a Windows login with read rights).
- In production: HTTPS + real CA, `ALLOW_INSECURE_TLS=false`.
- Do not log API tokens or dump payloads to public request-bin services with real credentials.

---

## Usage note

Ready for factory deployment and local lab testing. Always validate the query and indexes with a read-only Windows login before pointing at production SQL Server.

---

## Author

| | |
|--|--|
| **Name** | Ali Sadeghi |
| **GitHub** | [@alis110](https://github.com/alis110) |
| **Email** | alisadeghi201@gmail.com |
| **Repository** | [alis110/esp32-mysql-sneder](https://github.com/alis110/esp32-mysql-sneder) |

Copyright © Ali Sadeghi. All rights reserved unless otherwise noted.
