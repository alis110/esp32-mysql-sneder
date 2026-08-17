"""WinCC Tag Logging helpers — Windows Authentication only. No SQL password."""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

SYSTEM_DATABASES = frozenset({"master", "model", "msdb", "tempdb", "distribution"})
ODBC_PREFERENCE = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server Native Client RDA 11.0",
    "SQL Server",
)

QUERY_TLG_F = """SELECT TOP ({batch_size})
        CAST(DATEDIFF(second, '19700101', u.TimeStamp) AS bigint) * 1000
            + u.MS AS id,
        u.ValueID,
        RTRIM(a.ValueName) AS TagName,
        u.TimeStamp,
        u.MS,
        u.RealValue,
        u.Quality,
        u.Flags
        FROM TagUncompressed u
        LEFT JOIN Archive a ON a.ValueID = u.ValueID
        WHERE CAST(DATEDIFF(second, '19700101', u.TimeStamp) AS bigint) * 1000
            + u.MS > {after_id}
        ORDER BY u.TimeStamp ASC, u.MS ASC, u.ValueID ASC"""

QUERY_ALG = """SELECT TOP ({batch_size})
        CAST(DATEDIFF(second, '19700101', DateTime) AS bigint) * 1000
            + Ms AS id,
        MsgNr, DateTime, Ms, State, Counter,
        RTRIM(Computername) AS Computername,
        RTRIM(Username) AS Username,
        RTRIM(Comment) AS Comment
        FROM MsArcLong
        WHERE CAST(DATEDIFF(second, '19700101', DateTime) AS bigint) * 1000
            + Ms > {after_id}
        ORDER BY DateTime ASC, Ms ASC, Counter ASC"""

ALLOWED = {
    "tlg_f": QUERY_TLG_F,
    "tlg_s": QUERY_TLG_F,
    "alg": QUERY_ALG,
}


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value)


def windows_user() -> str:
    domain = (os.environ.get("USERDOMAIN") or "").strip()
    name = (os.environ.get("USERNAME") or "").strip()
    if domain and name:
        return f"{domain}\\{name}"
    return name or "unknown"


def classify(name: str) -> str:
    upper = (name or "").upper()
    if "TLG_F" in upper:
        return "tlg_f"
    if "TLG_S" in upper:
        return "tlg_s"
    if "_ALG_" in upper or "#ALG" in upper:
        return "alg"
    if upper.startswith("CC_"):
        return "cc_rt" if upper.endswith("R") else "cc_cs"
    return "other"


def pick_database(names: list[str], kind: str = "tlg_f") -> str | None:
    usable = [n for n in names if n and n not in SYSTEM_DATABASES]
    if not usable:
        return None
    typed = [n for n in usable if classify(n) == kind]
    pool = typed or [n for n in usable if classify(n) != "other"] or usable
    return sorted(pool, key=lambda n: (re.findall(r"\d{8,}", n)[-1:] or [""])[0] + n)[-1]


def choose_driver() -> str:
    import pyodbc

    installed = list(pyodbc.drivers())
    for name in ODBC_PREFERENCE:
        if name in installed:
            return name
    sql = [n for n in installed if "SQL Server" in n]
    if sql:
        return sql[0]
    raise RuntimeError("No SQL Server ODBC driver installed")


def conn_str(server: str, database: str = "") -> str:
    driver = choose_driver()
    server = (server or ".\\WINCC").strip()
    parts = [
        f"DRIVER={{{driver}}};",
        f"SERVER={server};",
        "Connection Timeout=5;",
        "Trusted_Connection=yes;",
    ]
    if database and database.lower() not in {"", "auto", "*"} and not database.lower().startswith("auto:"):
        parts.append(f"DATABASE={database};")
    if driver.startswith("ODBC Driver 1"):
        parts.append("Encrypt=no;TrustServerCertificate=yes;")
    return "".join(parts)


def bracket(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def parse_db(name: str) -> tuple[str, str]:
    raw = (name or "").strip()
    if not raw or raw.lower() in {"auto", "*"}:
        return "auto", "tlg_f"
    if raw.lower().startswith("auto:"):
        kind = raw.split(":", 1)[1].strip().lower()
        return "auto", {"fast": "tlg_f", "tlg": "tlg_f", "slow": "tlg_s", "alarm": "alg"}.get(kind, kind)
    return "name", raw


def connect(server: str, database: str):
    import pyodbc

    mode, kind_or_name = parse_db(database)
    target = "" if mode == "auto" else kind_or_name
    conn = pyodbc.connect(conn_str(server, target), timeout=5, autocommit=True)
    resolved = target
    if mode == "auto":
        cur = conn.cursor()
        cur.execute("SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' ORDER BY name")
        names = [str(r[0]) for r in cur.fetchall()]
        cur.close()
        chosen = pick_database(names, kind_or_name)
        if not chosen:
            conn.close()
            raise RuntimeError("No WinCC database found")
        conn.execute(f"USE {bracket(chosen)}")
        resolved = chosen
    return conn, resolved


def rows_as_dicts(cursor) -> list[dict[str, Any]]:
    cols = [c[0] for c in cursor.description] if cursor.description else []
    out = []
    for row in cursor.fetchall():
        item = {}
        for key, val in zip(cols, row):
            item[key] = json.loads(json.dumps(val, default=json_default))
        out.append(item)
    return out


def probe(server: str, database: str) -> dict[str, Any]:
    conn, resolved = connect(server, database)
    try:
        cur = conn.cursor()
        cur.execute("SELECT @@VERSION")
        version = str(cur.fetchone()[0]).splitlines()[0].strip()
        cur.execute("SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' ORDER BY name")
        names = [str(r[0]) for r in cur.fetchall() if classify(str(r[0])) != "other"]
        extra = []
        try:
            cur.execute("SELECT COUNT(*) FROM TagUncompressed")
            extra.append(f"TagUncompressed={cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM TagCompressed")
            extra.append(f"TagCompressed={cur.fetchone()[0]}")
        except Exception:
            pass
        cur.close()
        return {
            "ok": True,
            "windows_user": windows_user(),
            "sql_connected": True,
            "server": server,
            "database": resolved,
            "version": version,
            "wincc_dbs": names[:12],
            "detail": " | ".join(extra),
        }
    finally:
        conn.close()


def run_query(query_id: str, server: str, database: str, after_id: int, batch_size: int) -> dict[str, Any]:
    qid = (query_id or "tlg_f").strip().lower()
    if qid not in ALLOWED:
        return {"ok": False, "error": "unknown_query_id", "allowed": sorted(ALLOWED)}
    db = database
    if parse_db(database)[0] == "auto":
        if qid == "alg":
            db = "auto:alg"
        elif qid == "tlg_s":
            db = "auto:tlg_s"
    sql = ALLOWED[qid].format(batch_size=max(1, min(int(batch_size), 20)), after_id=int(after_id))
    conn, resolved = connect(server, db)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = rows_as_dicts(cur)
        cur.close()
        return {
            "ok": True,
            "windows_user": windows_user(),
            "sql_connected": True,
            "server": server,
            "database": resolved,
            "query_id": qid,
            "rows": rows,
        }
    finally:
        conn.close()
