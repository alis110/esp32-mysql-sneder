"""Store AlisBoard/ESP sql_sync envelopes as SQL Server look-alike databases.

MySQL when MYSQL_HOST is set; otherwise one SQLite file per source database
with the same table and column names (lab stand-in for mill MySQL).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

_DATA = Path(os.environ.get("DATA_DIR") or (Path(__file__).resolve().parent / "data"))
REPLICA_DIR = Path(os.environ.get("REPLICA_DIR") or (_DATA / "replica"))
MYSQL_HOST = os.environ.get("MYSQL_HOST", "").strip()
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "lab")

_LOCK = threading.Lock()
_SQLITE: dict[str, sqlite3.Connection] = {}
_MYSQL = None
_MYSQL_ERR = ""


def mysql_ident(name: str) -> str:
    raw = (name or "db").strip() or "db"
    s = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if not s or s[0].isdigit():
        s = "d_" + s
    return s[:64]


def mysql_type(declared: str) -> str:
    t = (declared or "TEXT").upper()
    if t in {"INT", "INTEGER", "SMALLINT", "TINYINT", "BIGINT", "DOUBLE", "FLOAT", "REAL", "DECIMAL"}:
        return t if t != "INTEGER" else "INT"
    if "DATETIME" in t or "TIMESTAMP" in t or t == "DATE":
        return "DATETIME(3)"
    if t in {"BLOB", "LONGBLOB", "IMAGE", "VARBINARY"}:
        return "LONGBLOB"
    if t in {"TEXT", "NTEXT", "LONGTEXT"}:
        return "LONGTEXT"
    return "LONGTEXT"


def _mysql_conn():
    global _MYSQL, _MYSQL_ERR
    if not MYSQL_HOST:
        return None
    if _MYSQL is not None:
        try:
            _MYSQL.ping(reconnect=True)
            return _MYSQL
        except Exception as exc:  # noqa: BLE001
            _MYSQL_ERR = str(exc)
            _MYSQL = None
    try:
        import pymysql  # type: ignore
    except ImportError:
        _MYSQL_ERR = "pymysql not installed"
        return None
    try:
        _MYSQL = pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            charset="utf8mb4",
            autocommit=True,
        )
        _MYSQL_ERR = ""
        return _MYSQL
    except Exception as exc:  # noqa: BLE001
        _MYSQL_ERR = str(exc)
        _MYSQL = None
        return None


def wait_for_mysql(seconds: int = 90) -> bool:
    """Block until MySQL answers, or give up. No-op if MYSQL_HOST is empty."""
    import time

    if not MYSQL_HOST:
        return False
    deadline = time.time() + seconds
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        if _mysql_conn():
            print(f"MySQL ready at {MYSQL_HOST}:{MYSQL_PORT} (attempt {attempt})", flush=True)
            return True
        print(f"Waiting for MySQL {MYSQL_HOST}:{MYSQL_PORT} ({_MYSQL_ERR})", flush=True)
        time.sleep(2)
    print(f"MySQL not ready after {seconds}s; sqlite replica fallback", flush=True)
    return False


def backend_name() -> str:
    if _mysql_conn():
        return f"mysql {MYSQL_HOST}:{MYSQL_PORT}"
    if MYSQL_HOST:
        return f"sqlite replica (mysql failed: {_MYSQL_ERR})"
    return "sqlite replica (set MYSQL_HOST for MySQL)"


def _sqlite(db_file: Path) -> sqlite3.Connection:
    key = str(db_file)
    conn = _SQLITE.get(key)
    if conn is None:
        db_file.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_file, check_same_thread=False)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _alis_batches (
                idempotency_key TEXT PRIMARY KEY,
                received_at TEXT,
                src_table TEXT
            )
            """
        )
        conn.commit()
        _SQLITE[key] = conn
    return conn


def _ensure_mysql_db(conn, ident: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{ident}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS `{ident}`._alis_batches ("
            "idempotency_key VARCHAR(190) PRIMARY KEY,"
            "received_at VARCHAR(40),"
            "src_table VARCHAR(128)"
            ")"
        )


def _ensure_table_sqlite(conn: sqlite3.Connection, table: str, columns: list[dict]) -> None:
    ident = mysql_ident(table)
    cols_sql = []
    for col in columns:
        name = mysql_ident(str(col.get("name") or "col"))
        cols_sql.append(f'"{name}" TEXT')
    if not cols_sql:
        cols_sql.append('"row_json" TEXT')
    conn.execute(f'CREATE TABLE IF NOT EXISTS "{ident}" ({", ".join(cols_sql)})')
    conn.commit()


def _ensure_table_mysql(conn, db: str, table: str, columns: list[dict]) -> None:
    ident = mysql_ident(table)
    cols_sql = []
    for col in columns:
        name = mysql_ident(str(col.get("name") or "col"))
        cols_sql.append(f"`{name}` {mysql_type(str(col.get('mysql_type') or col.get('sql_type') or 'TEXT'))}")
    if not cols_sql:
        cols_sql.append("`row_json` LONGTEXT")
    with conn.cursor() as cur:
        cur.execute(f"CREATE TABLE IF NOT EXISTS `{db}`.`{ident}` ({', '.join(cols_sql)})")


def _watermark_of(envelope: dict, columns: list, rows: list) -> str:
    w = str(envelope.get("watermark") or "").strip()
    if w:
        return w
    if rows and columns:
        name = str((columns[0] or {}).get("name") or "")
        last = rows[-1]
        if isinstance(last, dict) and name:
            return str(last.get(name) or "")
        if isinstance(last, list) and last:
            return str(last[0] or "")
    return str(envelope.get("id") or "0")


def _catalog_sqlite() -> sqlite3.Connection:
    conn = _sqlite(REPLICA_DIR / "_catalog.sqlite3")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cursors (
            src_database TEXT NOT NULL,
            src_table TEXT NOT NULL,
            watermark TEXT NOT NULL DEFAULT '0',
            row_count INTEGER NOT NULL DEFAULT 0,
            mysql_database TEXT,
            mysql_table TEXT,
            updated_at TEXT,
            PRIMARY KEY (src_database, src_table)
        )
        """
    )
    conn.commit()
    return conn


def _wm_ge(have: str, other: str) -> bool:
    a, b = (have or "0").strip(), (other or "0").strip()
    if a == b:
        return True
    try:
        return float(a) >= float(b)
    except ValueError:
        return a >= b


def save_progress(src_db: str, src_table: str, watermark: str, rows_added: int, ident_db: str, ident_table: str) -> None:
    mysql = _mysql_conn()
    if mysql:
        with mysql.cursor() as cur:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS `alis_meta` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS `alis_meta`.`cursors` ("
                "src_database VARCHAR(190) NOT NULL,"
                "src_table VARCHAR(128) NOT NULL,"
                "watermark VARCHAR(190) NOT NULL DEFAULT '0',"
                "row_count BIGINT NOT NULL DEFAULT 0,"
                "mysql_database VARCHAR(64),"
                "mysql_table VARCHAR(64),"
                "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
                "PRIMARY KEY (src_database, src_table)"
                ")"
            )
            cur.execute(
                "INSERT INTO `alis_meta`.`cursors` "
                "(src_database, src_table, watermark, row_count, mysql_database, mysql_table) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE watermark=VALUES(watermark), "
                "row_count=row_count + VALUES(row_count), "
                "mysql_database=VALUES(mysql_database), mysql_table=VALUES(mysql_table)",
                (src_db, src_table, watermark or "0", int(rows_added or 0), ident_db, ident_table),
            )
        return
    conn = _catalog_sqlite()
    row = conn.execute(
        "SELECT row_count FROM cursors WHERE src_database=? AND src_table=?",
        (src_db, src_table),
    ).fetchone()
    total = int(rows_added or 0) + (int(row[0]) if row else 0)
    conn.execute(
        "INSERT INTO cursors (src_database, src_table, watermark, row_count, mysql_database, mysql_table, updated_at) "
        "VALUES (?,?,?,?,?,?, datetime('now')) "
        "ON CONFLICT(src_database, src_table) DO UPDATE SET "
        "watermark=excluded.watermark, row_count=?, mysql_database=excluded.mysql_database, "
        "mysql_table=excluded.mysql_table, updated_at=datetime('now')",
        (src_db, src_table, watermark or "0", total, ident_db, ident_table, total),
    )
    conn.commit()


def refresh_cursors_from_replica() -> int:
    """Set watermarks from data already in mill so a reboot does not resend rows."""
    updated = 0
    known = {(c.get("mysql_database") or mysql_ident(c["database"]), mysql_ident(c["table"])): c for c in _read_cursors()}
    mysql = _mysql_conn()
    if mysql:
        with mysql.cursor() as cur:
            cur.execute("SHOW DATABASES")
            dbs = [
                r[0]
                for r in cur.fetchall()
                if r[0] not in {"information_schema", "mysql", "performance_schema", "sys", "alis_meta"}
            ]
        for db in dbs:
            if db == "mill":
                continue
            with mysql.cursor() as cur:
                cur.execute(f"SHOW TABLES FROM `{db}`")
                tables = [r[0] for r in cur.fetchall() if r[0] != "_alis_batches"]
            for table in tables:
                with mysql.cursor() as cur:
                    cur.execute(f"SHOW COLUMNS FROM `{db}`.`{table}`")
                    cols = [r[0] for r in cur.fetchall()]
                    if not cols:
                        continue
                    cur.execute(f"SELECT COUNT(*), MAX(`{cols[0]}`) FROM `{db}`.`{table}`")
                    cnt, mx = cur.fetchone()
                prev = known.get((db, table))
                src_db = prev["database"] if prev else db
                src_table = prev["table"] if prev else table
                wm = "" if mx is None else str(mx)
                if not wm and not cnt:
                    wm = "0"
                save_progress(src_db, src_table, wm or "0", 0, db, table)
                updated += 1
        return updated
    REPLICA_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(REPLICA_DIR.glob("*.sqlite3")):
        if path.name.startswith("_"):
            continue
        conn = _sqlite(path)
        db = path.stem
        for (table,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='_alis_batches'"
        ):
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
            if not cols:
                continue
            row = conn.execute(f'SELECT COUNT(*), MAX("{cols[0]}") FROM "{table}"').fetchone()
            cnt, mx = (row[0], row[1]) if row else (0, None)
            prev = known.get((db, table))
            src_db = prev["database"] if prev else db
            src_table = prev["table"] if prev else table
            wm = "" if mx is None else str(mx)
            if not wm and not cnt:
                wm = "0"
            save_progress(src_db, src_table, wm or "0", 0, db, table)
            updated += 1
    return updated


def list_cursors() -> list[dict[str, Any]]:
    return _read_cursors()


def _read_cursors() -> list[dict[str, Any]]:
    mysql = _mysql_conn()
    if mysql:
        with mysql.cursor() as cur:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS `alis_meta` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS `alis_meta`.`cursors` ("
                "src_database VARCHAR(190) NOT NULL,"
                "src_table VARCHAR(128) NOT NULL,"
                "watermark VARCHAR(190) NOT NULL DEFAULT '0',"
                "row_count BIGINT NOT NULL DEFAULT 0,"
                "mysql_database VARCHAR(64),"
                "mysql_table VARCHAR(64),"
                "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
                "PRIMARY KEY (src_database, src_table)"
                ")"
            )
            cur.execute(
                "SELECT src_database, src_table, watermark, row_count, mysql_database, mysql_table "
                "FROM `alis_meta`.`cursors` ORDER BY src_database, src_table"
            )
            return [
                {
                    "database": r[0],
                    "table": r[1],
                    "watermark": r[2],
                    "rows": r[3],
                    "mysql_database": r[4],
                    "mysql_table": r[5],
                }
                for r in cur.fetchall()
            ]
    conn = _catalog_sqlite()
    out = []
    for r in conn.execute(
        "SELECT src_database, src_table, watermark, row_count, mysql_database, mysql_table FROM cursors "
        "ORDER BY src_database, src_table"
    ):
        out.append(
            {
                "database": r[0],
                "table": r[1],
                "watermark": r[2],
                "rows": r[3],
                "mysql_database": r[4],
                "mysql_table": r[5],
            }
        )
    return out


def cursors_txt() -> str:
    lines = []
    for item in list_cursors():
        lines.append(
            f"{item['database']}\t{item['table']}\t{item['watermark']}\t{item['rows']}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def apply_sql_sync(envelope: dict, idem: str) -> dict[str, Any]:
    """Insert a sql_sync batch. Returns {ok, duplicate, database, table, rows}."""
    src_db = str(envelope.get("database") or "")
    src_table = str(envelope.get("table") or "")
    columns = envelope.get("columns") or []
    rows = envelope.get("rows") or []
    if not src_db or not src_table:
        return {"ok": False, "error": "missing_database_or_table"}
    if not isinstance(columns, list) or not isinstance(rows, list):
        return {"ok": False, "error": "bad_columns_or_rows"}
    ident_db = mysql_ident(src_db)
    ident_table = mysql_ident(src_table)
    key = idem or str(envelope.get("idempotency_key") or "")
    if not key:
        key = f"sql-sync-{ident_db}-{ident_table}-{envelope.get('id')}"

    with _LOCK:
        mysql = _mysql_conn()
        if mysql:
            _ensure_mysql_db(mysql, ident_db)
            with mysql.cursor() as cur:
                cur.execute(
                    f"SELECT 1 FROM `{ident_db}`._alis_batches WHERE idempotency_key=%s",
                    (key,),
                )
                if cur.fetchone():
                    wm = _watermark_of(envelope, columns, rows)
                    save_progress(src_db, src_table, wm, 0, ident_db, ident_table)
                    return {
                        "ok": True,
                        "duplicate": True,
                        "database": src_db,
                        "mysql_database": ident_db,
                        "table": src_table,
                        "watermark": wm,
                        "rows": 0,
                    }
            _ensure_table_mysql(mysql, ident_db, src_table, columns)
            col_names = [mysql_ident(str(c.get("name") or "col")) for c in columns]
            if rows and col_names:
                placeholders = ",".join(["%s"] * len(col_names))
                col_sql = ",".join(f"`{c}`" for c in col_names)
                sql = f"INSERT INTO `{ident_db}`.`{ident_table}` ({col_sql}) VALUES ({placeholders})"
                values = []
                for row in rows:
                    if isinstance(row, dict):
                        values.append([None if row.get(c.get("name")) is None else str(row.get(c.get("name"))) for c in columns])
                    elif isinstance(row, list):
                        values.append([None if i >= len(row) or row[i] is None else str(row[i]) for i in range(len(col_names))])
                    else:
                        values.append([str(row)] + [None] * (len(col_names) - 1))
                with mysql.cursor() as cur:
                    cur.executemany(sql, values)
                    cur.execute(
                        f"INSERT INTO `{ident_db}`._alis_batches (idempotency_key, received_at, src_table) "
                        "VALUES (%s, NOW(), %s)",
                        (key, src_table),
                    )
            wm = _watermark_of(envelope, columns, rows)
            save_progress(src_db, src_table, wm, len(rows), ident_db, ident_table)
            return {
                "ok": True,
                "duplicate": False,
                "database": src_db,
                "mysql_database": ident_db,
                "table": src_table,
                "watermark": wm,
                "rows": len(rows),
                "backend": backend_name(),
            }

        path = REPLICA_DIR / f"{ident_db}.sqlite3"
        conn = _sqlite(path)
        exists = conn.execute(
            "SELECT 1 FROM _alis_batches WHERE idempotency_key=?", (key,)
        ).fetchone()
        if exists:
            wm = _watermark_of(envelope, columns, rows)
            save_progress(src_db, src_table, wm, 0, ident_db, ident_table)
            return {
                "ok": True,
                "duplicate": True,
                "database": src_db,
                "mysql_database": ident_db,
                "table": src_table,
                "watermark": wm,
                "rows": 0,
            }
        _ensure_table_sqlite(conn, src_table, columns)
        col_names = [mysql_ident(str(c.get("name") or "col")) for c in columns]
        if rows and col_names:
            placeholders = ",".join(["?"] * len(col_names))
            col_sql = ",".join(f'"{c}"' for c in col_names)
            sql = f'INSERT INTO "{ident_table}" ({col_sql}) VALUES ({placeholders})'
            values = []
            for row in rows:
                if isinstance(row, dict):
                    values.append(
                        [None if row.get(c.get("name")) is None else str(row.get(c.get("name"))) for c in columns]
                    )
                elif isinstance(row, list):
                    values.append(
                        [None if i >= len(row) or row[i] is None else str(row[i]) for i in range(len(col_names))]
                    )
                else:
                    values.append([str(row)] + [None] * (len(col_names) - 1))
            conn.executemany(sql, values)
        conn.execute(
            "INSERT INTO _alis_batches (idempotency_key, received_at, src_table) VALUES (?, datetime('now'), ?)",
            (key, src_table),
        )
        conn.commit()
        wm = _watermark_of(envelope, columns, rows)
        save_progress(src_db, src_table, wm, len(rows), ident_db, ident_table)
        return {
            "ok": True,
            "duplicate": False,
            "database": src_db,
            "mysql_database": ident_db,
            "table": src_table,
            "watermark": wm,
            "rows": len(rows),
            "backend": backend_name(),
        }


def replica_overview() -> dict[str, Any]:
    dbs: list[dict[str, Any]] = []
    mysql = _mysql_conn()
    if mysql:
        with mysql.cursor() as cur:
            cur.execute("SHOW DATABASES")
            names = [
                r[0]
                for r in cur.fetchall()
                if r[0] not in {"information_schema", "mysql", "performance_schema", "sys", "alis_meta"}
            ]
        for name in names:
            tables = []
            with mysql.cursor() as cur:
                cur.execute(f"SHOW TABLES FROM `{name}`")
                tnames = [r[0] for r in cur.fetchall() if r[0] != "_alis_batches"]
            for t in tnames:
                with mysql.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) FROM `{name}`.`{t}`")
                    n = cur.fetchone()[0]
                tables.append({"name": t, "rows": n})
            dbs.append({"name": name, "tables": tables})
        dbs = [d for d in dbs if d["tables"] or d["name"] != "mill"]
        return {"backend": backend_name(), "databases": dbs}

    REPLICA_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(REPLICA_DIR.glob("*.sqlite3")):
        if path.name.startswith("_"):
            continue
        conn = _sqlite(path)
        tables = []
        for (tname,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='_alis_batches'"
        ):
            n = conn.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
            tables.append({"name": tname, "rows": n})
        dbs.append({"name": path.stem, "tables": tables})
    return {"backend": backend_name(), "databases": dbs}


def table_preview(db_name: str, table_name: str, limit: int = 80, offset: int = 0) -> dict[str, Any]:
    ident_db = mysql_ident(db_name)
    ident_table = mysql_ident(table_name)
    if ident_table.startswith("_"):
        return {"ok": False, "error": "hidden_table"}
    limit = max(1, min(int(limit or 80), 200))
    offset = max(0, int(offset or 0))
    mysql = _mysql_conn()
    if mysql:
        with mysql.cursor() as cur:
            cur.execute(f"SHOW TABLES FROM `{ident_db}`")
            names = [r[0] for r in cur.fetchall()]
            if ident_table not in names:
                return {"ok": False, "error": "table_not_found"}
            cur.execute(f"SHOW COLUMNS FROM `{ident_db}`.`{ident_table}`")
            columns = [r[0] for r in cur.fetchall()]
            cur.execute(f"SELECT COUNT(*) FROM `{ident_db}`.`{ident_table}`")
            total = int(cur.fetchone()[0])
            col_sql = ", ".join(f"`{c}`" for c in columns) if columns else "*"
            cur.execute(
                f"SELECT {col_sql} FROM `{ident_db}`.`{ident_table}` LIMIT %s OFFSET %s",
                (limit, offset),
            )
            rows = [dict(zip(columns, r)) for r in cur.fetchall()]
        return {
            "ok": True,
            "database": ident_db,
            "table": ident_table,
            "columns": columns,
            "total": total,
            "limit": limit,
            "offset": offset,
            "rows": rows,
        }

    path = REPLICA_DIR / f"{ident_db}.sqlite3"
    if not path.is_file():
        return {"ok": False, "error": "database_not_found"}
    conn = _sqlite(path)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if ident_table not in tables:
        return {"ok": False, "error": "table_not_found"}
    columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{ident_table}")')]
    total = conn.execute(f'SELECT COUNT(*) FROM "{ident_table}"').fetchone()[0]
    q = f'SELECT * FROM "{ident_table}" LIMIT ? OFFSET ?'
    raw = conn.execute(q, (limit, offset)).fetchall()
    rows = [dict(zip(columns, r)) for r in raw]
    return {
        "ok": True,
        "database": ident_db,
        "table": ident_table,
        "columns": columns,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "rows": rows,
    }
