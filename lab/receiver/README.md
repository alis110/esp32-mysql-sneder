# AlisBoard mill API

Docker stack that receives JSON from **AlisBoard.exe** (and optionally the ESP) and stores a MySQL replica of the mill SQL Server tables.

```text
AlisBoard.exe  POST /api/plc-records
        │
        ▼
api  :80 and :18773     dashboard + ingest
mysql  host :3307       replica databases/tables
adminer  :8081          browse MySQL
```

Token: `lab-token`  
Header: `Authorization: Bearer lab-token`

## Start / stop

Docker Desktop must be running.

```text
cd lab\receiver
up.bat
```

Stop: `down.bat`

| What | URL / address |
|------|----------------|
| Dashboard | http://127.0.0.1/ and http://127.0.0.1:18773/ |
| POST records | http://127.0.0.1:18773/api/plc-records |
| MySQL | `127.0.0.1:3307` user `root` password `lab` |
| Adminer | http://127.0.0.1:8081/ — system MySQL, server `mysql`, user `root`, password `lab` |

Win7 VM on Hyper-V Default Switch must use the **host** IP, not `127.0.0.1` inside the VM:

```text
http://172.21.80.1:18773/api/plc-records
```

ESP on mill Wi-Fi (Local LAN) uses the laptop Wi-Fi IP, e.g.:

```text
http://192.168.100.18:18773/api/plc-records
```

`up.bat` starts **lan_relay.py** so Wi-Fi/LAN clients reach Docker (Docker Desktop on Windows only reliably serves localhost). If the VM or ESP cannot connect, elevated PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\open-firewall-80.ps1
powershell -ExecutionPolicy Bypass -File .\test-lan.ps1
```

## Dashboard

Four columns: **Databases**, **Tables**, **Rows**, **Arrivals**.

- Click a database → tables → rows. Prev/Next pages the table.
- Arrivals is the live POST log. **Clear** empties that log only (MySQL data stays).
- Empty default schema `mill` is hidden until real replica databases exist.

## JSON

Both types go to `POST /api/plc-records`.

| `type` | Meaning |
|--------|---------|
| `data` | One tag sample (legacy ESP payload) |
| `sql_sync` | Batch: `database`, `table`, `columns`, `rows`, `watermark` |

`sql_sync` creates a MySQL database/table named after the SQL Server source (`#` becomes `_`) and inserts rows. Binary columns are not sent.

Idempotency: header `Idempotency-Key` (and the same key in JSON). A retry after power loss returns `duplicate: true` and does not insert again.

## Resume after power loss

The mill is the source of truth. AlisBoard must **not** crawl until this API answers.

| Method | Purpose |
|--------|---------|
| `GET /api/cursors.txt?rebuild=1` | Tab-separated `database`, `table`, `watermark`, `rows`. `rebuild=1` recomputes watermarks from data already in MySQL. |
| `GET /api/resume` | Same catalog as JSON. |
| `GET /api/cursors` | Cursor list (`?rebuild=1` optional). |
| `GET /api/status` | Dashboard snapshot. |
| `GET /api/health` | Liveness. |

Auth on cursor/resume routes: Bearer `lab-token`.

On API start, watermarks are rebuilt from replica tables so a lost `alis_meta.cursors` row does not cause a full resend.

## Files

| File | Role |
|------|------|
| `app.py` | HTTP API + dashboard |
| `replica.py` | MySQL/SQLite replica + cursors |
| `dashboard.html` | Mill UI |
| `docker-compose.yml` | api + mysql + adminer |
| `up.bat` / `down.bat` | Start / stop |

MySQL data lives in the Docker volume `mysql-data`. `data\` on disk is local SQLite fallback and is not committed.
