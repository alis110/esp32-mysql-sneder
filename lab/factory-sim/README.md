# Factory lab (ROSHAN / CPUPC01)

This PC already has SQL Server instance **`.\WINCC`** (same name as the mill). These scripts restore the dump from `Roshan\bak` and run a fake mill API.

A full **Windows 7 32-bit VM** is not created here: that needs a licensed Win7 ISO. What is simulated instead:

| Factory (CPUPC01) | This lab |
|-------------------|----------|
| Win7 32-bit, user `CPUPC01\Operator` | This Windows user + **AlisBoard.exe** (Win7 x86 `/MT`, no install) |
| SQL `CPUPC01\WINCC` Windows Auth | **`.\WINCC`** Windows Auth (already running) |
| Live TLG / ALG / CC databases | Restored `.bak` with **original names** |
| Internet API (needs mill Wi-Fi) | Fake API `http://127.0.0.1:18773/api/plc-records` token `lab-token` |

Do **not** run this restore on the live mill PC.

## Local test (no Wi-Fi)

On this PC, **AlisBoard.exe** reads SQL and POSTs to the fake API itself. Leave SSID empty. ESP radio stays off. That is the mill PC path without internet.

```text
lab\factory-sim\run-full-test.bat
```

Then keep the fake API window open and run `esp32-s3\pack\AlisBoard.exe`.

1. Server `.\WINCC`, database `auto`, **Test SQL**.
2. API URL `http://127.0.0.1:18773/api/plc-records`, token `lab-token`.
3. Leave SSID / password empty.
4. Dashboard: http://127.0.0.1:18773/

Logs should show `SQL OK` then `PC API POST id=... HTTP 200`.

## Factory tomorrow (Win7 32-bit)

1. Plug the ESP32-S3. Drive **G:** appears. Run **AlisBoard.exe** (nothing to install).
2. SQL: `.\WINCC`, database `auto`, Windows Authentication, **Test SQL**.
3. When mill Wi-Fi is known: fill SSID + password, mill API URL + token, **Send to ESP32-S3**.
4. ESP scans for that SSID, connects, logs IP, then POSTs queued SQL rows to the mill API.

Do not put a SQL password in the UI. Do not restore `.bak` on the live PC.

## What the bak files are

| File | Restored as | Role |
|------|-------------|------|
| `CC_Kamran_F_25_12_03_14_08_36.bak` | same | WinCC config (Kamran_Fars / ROSHAN) |
| `CC_Kamran_F_25_12_03_14_08_36R.bak` | same | WinCC runtime catalog |
| `CPUPC01_WinCC#Roshan_ALG_...bak` | same | Alarm logging |
| `CPUPC01_WINCC#ROSHAN_TLG_F_...bak` | same | Tag Logging Fast |

Dump user on the bak header: **`CPUPC01\Operator`**. Instance: **`CPUPC01\WINCC`**.

`TagCompressed.BinValues` is proprietary. The seed script fills **`TagUncompressed`** with the same `Archive` tag names so AlisBoard can `SELECT` like production.

## Fake API only

```text
lab\factory-sim\start-fake-api.bat 18773
```

ESP / PC POST: `http://127.0.0.1:18773/api/plc-records`  
Header: `Authorization: Bearer lab-token`

## Re-seed SQL rows

```text
sqlcmd -S .\WINCC -E -i lab\factory-sim\seed-uncompressed.sql
```
