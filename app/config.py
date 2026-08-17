from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class DatabaseConfig:
    enabled: bool
    engine: str
    auth: str
    host: str
    port: int
    database: str
    username: str
    password: str
    odbc_driver: str
    query: str
    id_column: str
    batch_size: int
    connect_timeout_seconds: int


@dataclass(frozen=True)
class SerialConfig:
    port: str
    baudrate: int
    ack_timeout_seconds: float
    reconnect_delay_seconds: float
    startup_delay_seconds: float
    vid_pid: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeConfig:
    poll_interval_seconds: float
    retry_delay_seconds: float
    state_db: Path
    log_file: Path
    log_level: str
    log_max_bytes: int
    log_backup_count: int


@dataclass(frozen=True)
class AppConfig:
    path: Path
    database: DatabaseConfig
    serial: SerialConfig
    runtime: RuntimeConfig


def default_config_path() -> Path:
    program_data = os.environ.get("PROGRAMDATA")
    if program_data:
        service_path = Path(program_data) / "PLCBridge" / "config" / "config.ini"
        if service_path.is_file():
            return service_path
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    local = base / "config" / "config.ini"
    if local.is_file():
        return local
    wincc = base / "config" / "config.wincc.ini"
    return wincc if wincc.is_file() else base / "config" / "config.example.ini"


def _resolve_path(raw: str, config_path: Path) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(raw)))
    return expanded if expanded.is_absolute() else (config_path.parent / expanded).resolve()


def normalize_engine(raw: str) -> str:
    value = (raw or "sqlserver").strip().lower()
    aliases = {
        "sqlserver": "sqlserver",
        "sql server": "sqlserver",
        "mssql": "sqlserver",
        "mssqlserver": "sqlserver",
        "wincc": "sqlserver",
    }
    if value in {"mysql", "mariadb"}:
        raise ConfigurationError("MySQL is not supported. Use SQL Server (WinCC Tag Logging) with Windows auth.")
    engine = aliases.get(value)
    if engine is None:
        raise ConfigurationError(f"Unknown database engine: {raw}")
    return engine


def normalize_auth(raw: str, engine: str) -> str:
    value = (raw or "").strip().lower()
    if not value:
        return "windows"
    aliases = {
        "sql": "sql",
        "sqlserver": "sql",
        "password": "sql",
        "user": "sql",
        "windows": "windows",
        "trusted": "windows",
        "integrated": "windows",
        "sspi": "windows",
        "win": "windows",
    }
    auth = aliases.get(value)
    if auth is None:
        raise ConfigurationError(f"Unknown database auth: {raw}")
    return auth


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path).resolve() if path else default_config_path().resolve()
    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(config_path, encoding="utf-8"):
        raise ConfigurationError(f"Config file not found or unreadable: {config_path}")
    required = {"database", "serial", "runtime", "logging"}
    missing = required.difference(parser.sections())
    if missing:
        raise ConfigurationError(f"Missing config sections: {', '.join(sorted(missing))}")

    db = parser["database"]
    serial = parser["serial"]
    runtime = parser["runtime"]
    logging_cfg = parser["logging"]
    query = db.get("query", "").strip()
    enabled = db.getboolean("enabled", fallback=False)
    if enabled and (not query or "REPLACE_WITH" in query):
        raise ConfigurationError("Database is enabled but query is still a placeholder")
    if enabled and "%(last_id)s" not in query:
        raise ConfigurationError("Query must contain the %(last_id)s parameter")

    engine = normalize_engine(db.get("engine", "sqlserver"))
    auth = normalize_auth(db.get("auth", ""), engine)
    default_port = 0
    default_host = ".\\WINCC"

    vid_pid = tuple(
        item.strip().upper() for item in serial.get("vid_pid", "10C4:EA60").split(",") if item.strip()
    )
    result = AppConfig(
        path=config_path,
        database=DatabaseConfig(
            enabled=enabled,
            engine=engine,
            auth=auth,
            host=db.get("host", default_host).strip() or default_host,
            port=db.getint("port", default_port),
            database=db.get("database", "").strip(),
            username=db.get("username", ""),
            password=db.get("password", ""),
            odbc_driver=db.get("odbc_driver", "").strip(),
            query=query,
            id_column=db.get("id_column", "id").strip(),
            batch_size=db.getint("batch_size", 100),
            connect_timeout_seconds=db.getint("connect_timeout_seconds", 10),
        ),
        serial=SerialConfig(
            port=serial.get("port", "auto").strip(),
            baudrate=serial.getint("baudrate", 115200),
            ack_timeout_seconds=serial.getfloat("ack_timeout_seconds", 45),
            reconnect_delay_seconds=serial.getfloat("reconnect_delay_seconds", 5),
            startup_delay_seconds=serial.getfloat("startup_delay_seconds", 2),
            vid_pid=vid_pid,
        ),
        runtime=RuntimeConfig(
            poll_interval_seconds=runtime.getfloat("poll_interval_seconds", 5),
            retry_delay_seconds=runtime.getfloat("retry_delay_seconds", 10),
            state_db=_resolve_path(runtime.get("state_db", "../data/state.sqlite3"), config_path),
            log_file=_resolve_path(logging_cfg.get("file", "../logs/plcbridge.log"), config_path),
            log_level=logging_cfg.get("level", "INFO").upper(),
            log_max_bytes=logging_cfg.getint("max_bytes", 5_242_880),
            log_backup_count=logging_cfg.getint("backup_count", 5),
        ),
    )
    if result.database.batch_size < 1:
        raise ConfigurationError("batch_size must be at least 1")
    if not result.database.id_column:
        raise ConfigurationError("id_column may not be empty")
    if enabled and engine == "sqlserver" and "LIMIT" in query.upper():
        raise ConfigurationError("SQL Server queries must use TOP (%(batch_size)s), not LIMIT")
    return result
