#!/usr/bin/env python3
"""Probe .\\WINCC like AlisBoard.exe and POST one row to the fake API."""
from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request

import pyodbc

SERVER = r".\WINCC"
API = os.environ.get("FAKE_API", "http://127.0.0.1:18773/api/plc-records")
TOKEN = os.environ.get("API_TOKEN", "lab-token")
QUERY = """
SELECT TOP (1)
    CAST(DATEDIFF(second, '19700101', u.TimeStamp) AS bigint) * 1000 + u.MS AS id,
    u.ValueID,
    RTRIM(a.ValueName) AS TagName,
    CONVERT(varchar(23), u.TimeStamp, 126) AS TimeStamp,
    u.MS, u.RealValue, u.Quality, u.Flags
FROM TagUncompressed u
LEFT JOIN Archive a ON a.ValueID = u.ValueID
WHERE CAST(DATEDIFF(second, '19700101', u.TimeStamp) AS bigint) * 1000 + u.MS > 0
ORDER BY u.TimeStamp ASC, u.MS ASC, u.ValueID ASC
"""


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def connect():
    last = None
    for drv in (
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
    ):
        cs = (
            f"DRIVER={{{drv}}};SERVER={SERVER};Trusted_Connection=yes;"
            "Encrypt=no;TrustServerCertificate=yes;Connection Timeout=5;"
        )
        try:
            return pyodbc.connect(cs, autocommit=True)
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise SystemExit(f"ODBC connect failed: {last}")


def main() -> int:
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sys.databases WHERE state_desc='ONLINE' ORDER BY name")
    dbs = [r[0] for r in cur.fetchall()]
    tlg = [n for n in dbs if "TLG_F" in n.upper()]
    print("instance     .\\WINCC  (Windows Authentication)")
    print("databases   ", ", ".join(dbs))
    if not tlg:
        print("FAIL: no TLG_F database")
        return 1
    db = tlg[-1]
    print("auto TLG_F  ", db)
    cur.execute(f"USE [{db}]")
    cur.execute(QUERY)
    row = cur.fetchone()
    if not row:
        print("FAIL: TagUncompressed empty — run seed-uncompressed.sql")
        return 1
    cols = [c[0] for c in cur.description]
    payload = {k: row[i] for i, k in enumerate(cols)}
    for k, v in list(payload.items()):
        if hasattr(v, "isoformat"):
            payload[k] = v.isoformat(sep=" ")
        elif isinstance(v, bytes):
            payload[k] = v.decode("ascii", "replace").strip()
    rid = int(payload["id"])
    env = {
        "type": "data",
        "id": rid,
        "idempotency_key": f"plc-record-{rid}",
        "payload": payload,
    }
    print("SQL row     ", json.dumps(payload, default=str, ensure_ascii=False))
    body = json.dumps(env, default=str).encode("utf-8")
    req = urllib.request.Request(
        API,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}",
            "Idempotency-Key": env["idempotency_key"],
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print("API POST    ", resp.status, resp.read().decode("utf-8", "replace"))
    except urllib.error.URLError as exc:
        print("API skip    ", exc, "— run start-fake-api.bat <port> then retry")
        print(f"ESP should POST to {API}")
        return 0
    dashboard = API.replace("/api/plc-records", "/")
    print(f"dashboard   {dashboard}")
    print(f"ESP URL     {API}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
