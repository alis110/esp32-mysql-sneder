from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

from .config import DatabaseConfig

logger = logging.getLogger("plcbridge.database")

_SYSTEM_DATABASES = frozenset({"master", "model", "msdb", "tempdb", "distribution"})
_ODBC_DRIVER_PREFERENCE = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server Native Client RDA 11.0",
    "SQL Server",
)


class RecordError(ValueError):
    pass


class DataSource(Protocol):
    def close(self) -> None: ...

    def fetch_after(self, last_id: int) -> list[dict[str, Any]]: ...

    def envelope(self, row: dict[str, Any]) -> dict[str, Any]: ...


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    raise TypeError(f"Unsupported database value: {type(value).__name__}")


def expand_query(query: str, last_id: int, batch_size: int) -> str:
    """Substitute integer placeholders. last_id and batch_size are coerced to int."""
    return query.replace("%(batch_size)s", str(int(batch_size))).replace("%(last_id)s", str(int(last_id)))


def envelope_row(row: dict[str, Any], id_column: str) -> dict[str, Any]:
    record_id = int(row[id_column])
    payload = json.loads(json.dumps(row, default=_json_default, ensure_ascii=False))
    return {
        "type": "data",
        "id": record_id,
        "idempotency_key": f"plc-record-{record_id}",
        "payload": payload,
    }


def validate_id_order(rows: list[dict[str, Any]], id_column: str, last_id: int) -> list[dict[str, Any]]:
    previous = last_id
    for row in rows:
        if id_column not in row:
            raise RecordError(f"Query result lacks id column '{id_column}'")
        try:
            record_id = int(row[id_column])
        except (TypeError, ValueError) as exc:
            raise RecordError("Record IDs must be integers") from exc
        if record_id <= previous:
            raise RecordError("Query results must be strictly ordered by increasing ID")
        previous = record_id
    return rows


def classify_wincc_database(name: str) -> str:
    """WinCC instance types seen on CPUPC01\\WINCC (ROSHAN / Kamran_Fars)."""
    upper = (name or "").upper()
    if "TLG_F" in upper:
        return "tlg_f"
    if "TLG_S" in upper:
        return "tlg_s"
    if "_ALG_" in upper or upper.endswith("_ALG") or "#ALG" in upper:
        return "alg"
    if upper.startswith("CC_"):
        return "cc_rt" if upper.endswith("R") else "cc_cs"
    return "other"


_KIND_ALIASES = {
    "tlg_f": "tlg_f",
    "fast": "tlg_f",
    "tlg": "tlg_f",
    "tlg_s": "tlg_s",
    "slow": "tlg_s",
    "alg": "alg",
    "alarm": "alg",
    "alarms": "alg",
    "cc_rt": "cc_rt",
    "rt": "cc_rt",
    "runtime": "cc_rt",
    "cc_cs": "cc_cs",
    "cs": "cc_cs",
    "config": "cc_cs",
}


def parse_wincc_database(name: str) -> tuple[str, str]:
    """Return (mode, kind_or_name). mode is 'auto' or 'name'."""
    raw = (name or "").strip()
    if not raw or raw.lower() in {"auto", "*"}:
        return "auto", "tlg_f"
    lower = raw.lower()
    if lower.startswith("auto:"):
        kind = _KIND_ALIASES.get(lower.split(":", 1)[1].strip(), "tlg_f")
        return "auto", kind
    return "name", raw


def pick_wincc_database(names: list[str], kind: str = "tlg_f") -> str | None:
    """Choose the current archive of the requested WinCC kind when segments rotate."""
    usable = [name for name in names if name and name not in _SYSTEM_DATABASES]
    if not usable:
        return None
    typed = [name for name in usable if classify_wincc_database(name) == kind]
    pool = typed or [name for name in usable if classify_wincc_database(name) != "other"] or usable
    return sorted(pool, key=_wincc_name_sort_key)[-1]


def _wincc_name_sort_key(name: str) -> tuple[str, str]:
    digits = re.findall(r"\d{8,}", name)
    return (digits[-1] if digits else "", name)


def is_auto_database(name: str) -> bool:
    return parse_wincc_database(name)[0] == "auto"


DEFAULT_WINCC_QUERY = """SELECT TOP (%(batch_size)s)
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
            + u.MS > %(last_id)s
        ORDER BY u.TimeStamp ASC, u.MS ASC, u.ValueID ASC"""


DEFAULT_ALG_QUERY = """SELECT TOP (%(batch_size)s)
        CAST(DATEDIFF(second, '19700101', DateTime) AS bigint) * 1000
            + Ms AS id,
        MsgNr,
        DateTime,
        Ms,
        State,
        Counter,
        RTRIM(Computername) AS Computername,
        RTRIM(Username) AS Username,
        RTRIM(Comment) AS Comment
        FROM MsArcLong
        WHERE CAST(DATEDIFF(second, '19700101', DateTime) AS bigint) * 1000
            + Ms > %(last_id)s
        ORDER BY DateTime ASC, Ms ASC, Counter ASC"""


def create_source(config: DatabaseConfig) -> DataSource:
    if config.engine != "sqlserver":
        raise RecordError(
            "MySQL is not supported. Use SQL Server (WinCC Tag Logging) with Windows auth."
        )
    return SqlServerSource(config)


def probe_database(config: DatabaseConfig) -> tuple[bool, str]:
    try:
        source = create_source(config)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    try:
        return True, source.probe()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    finally:
        source.close()


class SqlServerSource:
    """SQL Server / WinCC Tag Logging reader via ODBC (Windows or SQL auth)."""

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self._conn = None
        self._resolved_database = ""
        self._empty_uncompressed_warned = False

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    def _connect(self, database: str | None = None):
        import pyodbc

        target = self.config.database if database is None else database
        if target and is_auto_database(target):
            target = ""
        if self._conn is not None and database is None:
            try:
                self._conn.execute("SELECT 1")
                return self._conn
            except Exception:  # noqa: BLE001
                self.close()
        conn = pyodbc.connect(
            sqlserver_connection_string(self.config, target),
            timeout=self.config.connect_timeout_seconds,
            autocommit=True,
        )
        if database is None:
            self._conn = conn
            self._ensure_database()
        return conn

    def _ensure_database(self) -> None:
        if self._conn is None:
            return
        if not is_auto_database(self.config.database):
            self._resolved_database = self.config.database
            return
        if self._resolved_database:
            return
        names = list_sqlserver_databases(self._conn)
        _mode, kind = parse_wincc_database(self.config.database)
        chosen = pick_wincc_database(names, kind)
        if not chosen:
            raise RecordError("No SQL Server database found (set database= explicitly)")
        self._resolved_database = chosen
        self._conn.execute(f"USE {bracket_ident(chosen)}")
        logger.info("WinCC auto-selected %s database: %s", kind, chosen)

    def fetch_after(self, last_id: int) -> list[dict[str, Any]]:
        import pyodbc

        try:
            connection = self._connect()
            rows = self._fetch(connection, last_id)
        except pyodbc.Error:
            self.close()
            self._resolved_database = ""
            connection = self._connect()
            rows = self._fetch(connection, last_id)
        if not rows:
            self._warn_if_compressed_only(connection)
        return validate_id_order(rows, self.config.id_column, last_id)

    def _fetch(self, connection, last_id: int) -> list[dict[str, Any]]:
        sql = expand_query(self.config.query, last_id, self.config.batch_size)
        cursor = connection.cursor()
        try:
            cursor.execute(sql)
            columns = [col[0] for col in cursor.description] if cursor.description else []
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def _warn_if_compressed_only(self, connection) -> None:
        if self._empty_uncompressed_warned:
            return
        if "TagUncompressed" not in self.config.query:
            return
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM TagUncompressed")
            uncompressed = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM TagCompressed")
            compressed = int(cursor.fetchone()[0])
            cursor.close()
        except Exception:  # noqa: BLE001
            return
        if uncompressed == 0 and compressed > 0:
            self._empty_uncompressed_warned = True
            logger.warning(
                "WinCC TagUncompressed is empty (%s compressed blocks). "
                "Enable uncompressed tag logging in WinCC, or point query at another table. "
                "BinValues cannot be decoded with plain SQL.",
                compressed,
            )

    def envelope(self, row: dict[str, Any]) -> dict[str, Any]:
        return envelope_row(row, self.config.id_column)

    def probe(self) -> str:
        connection = self._connect()
        self._ensure_database()
        cursor = connection.cursor()
        cursor.execute("SELECT @@VERSION")
        version = str(cursor.fetchone()[0]).splitlines()[0].strip()
        names = list_sqlserver_databases(connection)
        counts: dict[str, int] = {}
        for name in names:
            kind = classify_wincc_database(name)
            if kind != "other":
                counts[kind] = counts.get(kind, 0) + 1
        winccish = [name for name in names if classify_wincc_database(name) != "other"]
        if is_auto_database(self.config.database):
            _mode, kind = parse_wincc_database(self.config.database)
            chosen = self._resolved_database or pick_wincc_database(names, kind)
        else:
            chosen = self._resolved_database or self.config.database
        parts = [
            f"SQL Server {self.config.host}"
            + (f",{self.config.port}" if self.config.port else "")
            + f" auth={self.config.auth}",
            version,
        ]
        if counts:
            parts.append("kinds " + ", ".join(f"{k}={n}" for k, n in sorted(counts.items())))
        if winccish:
            shown = ", ".join(winccish[:8])
            more = f" (+{len(winccish) - 8})" if len(winccish) > 8 else ""
            parts.append(f"WinCC DBs: {shown}{more}")
        if chosen:
            parts.append(f"using {chosen}")
            cursor.execute(f"USE {bracket_ident(chosen)}")
            tables = [row[0] for row in cursor.execute(
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
            )]
            if tables:
                parts.append("tables: " + ", ".join(tables[:20]))
            extra = _wincc_table_summary(cursor)
            if extra:
                parts.append(extra)
        cursor.close()
        return " | ".join(parts)


def bracket_ident(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def list_sqlserver_databases(connection) -> list[str]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' ORDER BY name"
        )
        return [str(row[0]) for row in cursor.fetchall()]
    finally:
        cursor.close()


def _wincc_table_summary(cursor) -> str:
    bits: list[str] = []
    for table in ("Archive", "TagUncompressed", "TagCompressed", "MsArcLong", "AlgCSDataENU"):
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {bracket_ident(table)}")
            bits.append(f"{table}={cursor.fetchone()[0]}")
        except Exception:  # noqa: BLE001
            pass
    try:
        cursor.execute("SELECT TOP 8 ValueID, RTRIM(ValueName) FROM Archive ORDER BY ValueID")
        tags = [f"{row[0]}:{_short_tag(row[1])}" for row in cursor.fetchall()]
        if tags:
            bits.append("tags " + ", ".join(tags))
    except Exception:  # noqa: BLE001
        pass
    try:
        cursor.execute("SELECT Value FROM ArchiveInfo WHERE Name = 'Version'")
        row = cursor.fetchone()
        if row:
            bits.append(f"WinCC ArchiveInfo={row[0]}")
    except Exception:  # noqa: BLE001
        pass
    if any(item.startswith("TagUncompressed=0") for item in bits) and any(
        item.startswith("TagCompressed=") and not item.startswith("TagCompressed=0") for item in bits
    ):
        bits.append("values are compressed - enable TagUncompressed or use WinCC OLE-DB")
    return " | ".join(bits)


def _short_tag(name: str) -> str:
    text = (name or "").strip()
    if "\\" in text:
        text = text.rsplit("\\", 1)[-1]
    return text[:40]


def choose_odbc_driver(preferred: str = "") -> str:
    import pyodbc

    installed = list(pyodbc.drivers())
    if preferred:
        if preferred in installed:
            return preferred
        raise RecordError(f"ODBC driver '{preferred}' is not installed. Available: {', '.join(installed) or 'none'}")
    for name in _ODBC_DRIVER_PREFERENCE:
        if name in installed:
            return name
    sql_drivers = [name for name in installed if "SQL Server" in name]
    if sql_drivers:
        return sql_drivers[0]
    raise RecordError(
        "No SQL Server ODBC driver found. Install 'ODBC Driver 13/17 for SQL Server' "
        f"(installed: {', '.join(installed) or 'none'})"
    )


def sqlserver_connection_string(config: DatabaseConfig, database: str = "") -> str:
    driver = choose_odbc_driver(config.odbc_driver)
    server = config.host.strip() or ".\\WINCC"
    if config.port:
        server = f"{server},{int(config.port)}"
    parts = [
        f"DRIVER={{{driver}}};",
        f"SERVER={server};",
        f"Connection Timeout={max(1, int(config.connect_timeout_seconds))};",
    ]
    if database and not is_auto_database(database):
        parts.append(f"DATABASE={database};")
    if config.auth == "windows":
        parts.append("Trusted_Connection=yes;")
    else:
        parts.append(f"UID={config.username};")
        parts.append(f"PWD={config.password};")
    if driver.startswith("ODBC Driver 1"):
        parts.append("Encrypt=no;TrustServerCertificate=yes;")
    return "".join(parts)
