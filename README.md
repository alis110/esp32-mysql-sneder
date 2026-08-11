# ESP32 MySQL Sender (PLCBridge)

**Author:** [Ali Sadeghi](https://github.com/alis110) (`@alis110`) · `alisadeghi201@gmail.com`

A light, durable bridge that reads rows from a local Windows MySQL database and delivers them to a REST API through:

```text
MySQL  →  Python Bridge (Windows Service)  →  USB Serial  →  ESP32  →  Wi-Fi  →  HTTPS/HTTP API
```

Repository: [alis110/esp32-mysql-sneder](https://github.com/alis110/esp32-mysql-sneder)

This project **does not guess your schema**. You must set a real SQL query in the config. No data is read or sent until `enabled=true` and a valid query are configured.

---

## Contents

1. [What is included](#what-is-included)
2. [Requirements](#requirements)
3. [Factory Windows PC — install CP2102 + PlatformIO](#factory-windows-pc--install-cp2102--platformio)
4. [Quick start with ready EXEs](#quick-start-with-ready-exes)
5. [Setup UI (PLCBridgeSetup)](#setup-ui-plcbridgesetup)
6. [Local lab (Docker MySQL + Mock API)](#local-lab-docker-mysql--mock-api)
7. [Light MySQL query (low PC load)](#light-mysql-query-low-pc-load)
8. [ESP32 firmware](#esp32-firmware)
9. [Serial protocol](#serial-protocol)
10. [Run from Python source](#run-from-python-source)
11. [Build EXEs from source](#build-exes-from-source)
12. [Windows Service](#windows-service)
13. [Delivery guarantee and idempotency](#delivery-guarantee-and-idempotency)
14. [Project layout](#project-layout)
15. [Troubleshooting](#troubleshooting)
16. [Security](#security)

---

## What is included

| Component | Role |
|-----------|------|
| **PLCBridge.exe** | Bridge: reads MySQL, sends records to ESP over USB, commits progress in SQLite only after ACK |
| **PLCBridgeSetup.exe** | Setup UI: Wi-Fi, MySQL, Mock API, ESP flash, service install |
| **firmware/** | ESP32 PlatformIO app: receives JSON on Serial, POSTs to API over Wi-Fi, returns ACK/NACK |
| **service/** | Install/remove Windows Service (auto-start + crash recovery) |
| **lab/** | Docker MySQL, Mock API, lab helpers |

Designed for industrial PCs: **low load** — small batches, longer poll interval, only new rows via `id > last_id`.

---

## Requirements

### Hardware
- Windows 10/11 industrial PC
- ESP32-DevKitC (or compatible) + USB **data** cable (not charge-only)
- USB-UART chip **CP2102** (VID/PID `10C4:EA60`) — most common on DevKit boards
- **2.4 GHz** Wi-Fi for the ESP32 (classic ESP32 has no 5 GHz)

### Software on the factory Windows PC

| Software | Required? | Purpose |
|----------|-----------|---------|
| **CP2102 / Silicon Labs VCP driver** | **Yes** | Windows must create a `COMx` port for the ESP32 |
| **`PLCBridge.exe` + `PLCBridgeSetup.exe`** | **Yes** | Run bridge + setup UI (no Python needed for this) |
| **PlatformIO Core (`pio`)** | **Yes if you flash on this PC** | Compiles/uploads firmware (**Setup ESP32** button) |
| **Python 3.11+** | Only to install `pio` via pip, or to run from source | Not required to run the ready EXEs |
| Docker | Lab only | Local test MySQL |

**Important:** The Bridge EXE does **not** need Python.  
You need **PlatformIO (`pio`)** only when flashing the ESP32 on that machine. If you flash elsewhere first, the factory PC still needs the **CP2102 driver**.

Full installer helper: [`tools/Install-CP2102-and-PlatformIO.ps1`](tools/Install-CP2102-and-PlatformIO.ps1) (also under `dist/`).

---

## Factory Windows PC — install CP2102 + PlatformIO

Copy the whole project (or at least `dist/` + `tools/` + `firmware/`) to a USB stick, then onto the factory PC.

### Fast path — offline USB (recommended for factory with NO internet)

This repo can ship a full offline pack under `tools/offline/` (CP2102 driver + portable `pio` + ESP32 toolchains, ~1 GB+).

**On the factory PC:**

1. Copy the project from USB to e.g. `C:\PLCBridge\` (include the whole `tools\offline\` folder).
2. Run:

```text
tools\offline\Install-Offline.bat
```

3. Accept driver/UAC prompts, open a **new** PowerShell, verify:

```powershell
pio --version
Get-CimInstance Win32_SerialPort | Format-Table DeviceID, Name
```

4. Run `dist\PLCBridgeSetup.exe` → MySQL → **Setup ESP32** → **Install Service**.

Details: [`tools/offline/README.md`](tools/offline/README.md)

**Rebuild the offline pack** (only on a PC that HAS internet):

```powershell
cd tools\offline
powershell -ExecutionPolicy Bypass -File .\Prepare-OfflinePack.ps1
```

Then copy the updated `tools\offline\` onto the USB stick.

### Fast path (online helper, if the factory PC has internet)

1. Plug the PC into the internet **once** (driver + first PlatformIO toolchain download).
2. Run:

```powershell
cd C:\PLCBridge   # or wherever you copied the files
Set-ExecutionPolicy -Scope Process Bypass
.\dist\Install-CP2102-and-PlatformIO.bat
```

Or:

```powershell
.\tools\Install-CP2102-and-PlatformIO.ps1
```

3. Follow prompts:
   - Opens **Silicon Labs CP210x** driver page if needed  
   - Installs **PlatformIO** with pip when Python is available  
   - Adds `pio` to User PATH when found under `%USERPROFILE%\.platformio\penv\Scripts`
4. Open a **new** PowerShell and verify:

```powershell
pio --version
Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Name, PNPDeviceID
```

You want a port whose `PNPDeviceID` contains `VID_10C4` and `PID_EA60`.

### Manual: CP2102 driver (Silicon Labs)

1. Browser: [USB to UART Bridge VCP Drivers (Silicon Labs)](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers)  
2. Download **CP210x Universal Windows Driver**.  
3. Extract the ZIP → install (run the setup or install the `.inf` as Administrator).  
4. Connect ESP32 with a **data-capable** USB cable.  
5. Open **Device Manager**:
   - **Ports (COM & LPT)** → `Silicon Labs CP210x USB to UART Bridge (COMx)` = OK  
   - Yellow bang under **Other devices** = driver not installed  
6. Reboot if Windows still does not assign a COM port.

### Manual: PlatformIO (`pio`)

**A) Easiest if Python can be installed on the factory PC**

1. Install [Python 3.11+ for Windows](https://www.python.org/downloads/windows/)  
   - Enable **Add python.exe to PATH**  
2. In PowerShell:

```powershell
py -3 -m pip install -U platformio
pio --version
```

3. If `pio` is not found, add to User PATH:

```text
%USERPROFILE%\.platformio\penv\Scripts
```

Close and reopen the terminal, then `pio --version` again.

**B) PlatformIO docs**

- Core install: https://docs.platformio.org/en/latest/core/installation.html  
- Or install VS Code + **PlatformIO IDE** extension (also provides `pio`)

**First flash note:** PlatformIO downloads Espressif toolchains the first time (needs internet). Later flashes can be offline if packages are already cached under `%USERPROFILE%\.platformio\`.

### After tools are installed — factory run order

1. `dist\PLCBridgeSetup.exe`  
2. MySQL settings → **Check MySQL**  
3. Wi-Fi **2.4 GHz** + API URL → **Setup ESP32** (needs `pio` + CP2102)  
4. **Install Service** (Administrator)  
5. Confirm Service **Running**; use App Log / API Activity / ESP32 Serial panels to watch traffic  

More notes: [`tools/README.md`](tools/README.md)

---

## Quick start with ready EXEs

In `dist/`:

- `PLCBridgeSetup.exe` — setup panel
- `PLCBridge.exe` — bridge
- `Install-Service.bat` / `Uninstall-Service.bat`
- `Install-CP2102-and-PlatformIO.bat` — factory driver + `pio` helper
- `Open-Setup-UI.bat` / `run-console.bat`

### Recommended factory flow

1. Run `PLCBridgeSetup.exe`.
2. Fill MySQL settings → **Check MySQL**.
3. **Scan** 2.4 GHz Wi-Fi, confirm password, set **API URL** and token.
4. Plug ESP over USB → **Setup ESP32** (writes secrets + flashes).
5. **Install Service** once (UAC / Administrator).
6. Service starts at boot even if no user is logged in.

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
| **Refresh / Check MySQL** | Status for ESP, Wi-Fi, MySQL, Mock API, Service |
| **Scan Wi-Fi** | List SSIDs; fill saved Windows profile password when available |
| **Mock API** | Lab API on port `8089` inside this window; frees the port if another process holds it |
| **Setup ESP32** | Write `secrets.h` + PlatformIO upload |
| **Install / Uninstall Service** | Auto-start service (Admin required) |
| **Start / Stop** | Control installed service |
| **UI at login** | Startup shortcut so Setup opens after user login |
| **Copy / Clear** | Log clipboard / clear |

**Network tip:** set the Windows Wi-Fi profile to **Private** and allow the API port in the firewall (e.g. `8089` for lab) so the ESP can reach the PC.

More lab notes: [`lab/README.md`](lab/README.md)

---

## Local lab (Docker MySQL + Mock API)

Test without the factory database:

```powershell
cd lab
docker compose up -d
# In Setup: host=127.0.0.1 port=3307 db=plcbridge_lab user/pass=bridge
# Click Mock API, then Setup ESP32 with:
#   http://<PC-LAN-IP>:8089/api/plc-records
```

Lab sample config: [`config/config.lab.ini`](config/config.lab.ini)

A successful end-to-end run means:
1. Bridge reads `lab_events`
2. Sends rows to ESP on COM
3. ESP POSTs to Mock API over Wi-Fi
4. ACK returns and `last_success_id` advances
5. JSON hits appear in the Setup Log

---

## Light MySQL query (low PC load)

Never run `SELECT *` on a large table. Select only needed columns, only new IDs, with a small `LIMIT`.

Lab example:

```sql
SELECT id, temperature, note, created_at
FROM lab_events
WHERE id > %(last_id)s
ORDER BY id ASC
LIMIT %(batch_size)s
```

Required contract:

- `id_column` (default `id`) must be numeric, unique, and **strictly increasing**
- Query must use `> %(last_id)s` and `ORDER BY ... ASC`
- Prefer an index on that ID column
- Use `%(batch_size)s`

Light defaults used by this project:

| Setting | Suggested | Meaning |
|---------|-----------|---------|
| `batch_size` | `5` | At most 5 rows per poll |
| `poll_interval_seconds` | `10` | Poll MySQL every 10 seconds |
| `retry_delay_seconds` | `15` | Delay after errors |
| `connect_timeout_seconds` | `5` | Connect timeout |

Template: [`config/config.example.ini`](config/config.example.ini)  
Copy to `config/config.ini` (real config is gitignored).

Before production, inspect schema with a read-only user:

```sql
SHOW TABLES;
DESCRIBE your_table;
SHOW INDEX FROM your_table;
```

Create a MySQL account with **SELECT-only** rights on that table.

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

The Bridge updates `last_success_id` in SQLite with a durable transaction only after a matching `ack`. If MySQL, COM, ESP, Wi-Fi, or the API fails, the **same ID** is retried; later IDs do not jump ahead.

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

```powershell
.\build.bat
```

Outputs under `dist/`:
- `PLCBridge.exe`
- service scripts and helper bats

Build Setup UI separately:

```powershell
.\lab\build_setup.bat
```

PyInstaller specs in repo: `PLCBridge.spec`, `PLCBridgeSetup.spec`.

---

## Windows Service

From Setup (**Install Service**) or:

```powershell
# Administrator
Set-ExecutionPolicy -Scope Process Bypass
.\dist\Install-Service.bat
# or:
.\service\install-service.ps1
```

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
├── app/                      # Python bridge (MySQL, serial, state, service)
├── config/
│   ├── config.example.ini    # Production template
│   └── config.lab.ini        # Lab template (Docker)
├── firmware/                 # PlatformIO ESP32 project
│   ├── platformio.ini
│   ├── src/main.cpp
│   └── include/secrets.example.h
├── tools/                    # Factory: CP2102 + PlatformIO install helpers
│   ├── Install-CP2102-and-PlatformIO.ps1
│   ├── Install-CP2102-and-PlatformIO.bat
│   └── README.md
├── lab/                      # Setup UI + Docker + Mock API
├── service/                  # Windows Service install/remove
├── tests/
├── dist/                     # Ready EXEs + bats + tools copy
├── plcbridge.py
├── build.bat
├── requirements.txt
└── README.md
```

### Intentionally not in Git

| Path | Reason |
|------|--------|
| `config/config.ini` | Real MySQL credentials |
| `firmware/include/secrets.h` | Real Wi-Fi / API token |
| `.venv/` | Local virtualenv |
| `build/`, `firmware/.pio/` | Build artifacts |
| `data/*.sqlite3`, `logs/` | Runtime state and logs |

Copy from `*.example*` / `config.lab.ini` for local use.

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| ESP not found / no COM | Install **CP2102** driver; use data USB cable; check Device Manager for `10C4:EA60` |
| `pio` / Setup ESP32 fails | Install **PlatformIO** — run `dist\Install-CP2102-and-PlatformIO.bat` |
| `wifi_unavailable` / ACK timeout | Use a **2.4 GHz** SSID, not 5 GHz |
| `tcp_connect_failed` to API on PC | Private network profile + firewall allow for the API port |
| Mock API “port in use” | Click **Mock API** again (Setup frees the port) |
| Service / error 1063 on double-click EXE | Expected for SCM services; start via Service or `--console` |
| MySQL fail | Check host/port/user and `enabled=true`; lab usually uses port `3307` |
| No data flowing | Query must include `%(last_id)s`; check service log |

---

## Security

- Do not commit real secrets (`secrets.h` and `config.ini` are gitignored).
- Use a MySQL user with **SELECT** only.
- In production: HTTPS + real CA, `ALLOW_INSECURE_TLS=false`.
- Do not log API tokens or dump payloads to public request-bin services with real credentials.

---

## Usage note

Ready for factory deployment and local lab testing. Always validate the query and indexes with a read-only account before pointing at production MySQL.

---

## Author

| | |
|--|--|
| **Name** | Ali Sadeghi |
| **GitHub** | [@alis110](https://github.com/alis110) |
| **Email** | alisadeghi201@gmail.com |
| **Repository** | [alis110/esp32-mysql-sneder](https://github.com/alis110/esp32-mysql-sneder) |

Copyright © Ali Sadeghi. All rights reserved unless otherwise noted.
