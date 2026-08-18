#!/usr/bin/env python3
"""Lightweight lab API: accept ESP32 PLCBridge JSON and show a dashboard on :80."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from replica import (
    apply_sql_sync,
    backend_name,
    cursors_txt,
    list_cursors,
    refresh_cursors_from_replica,
    replica_overview,
    table_preview,
    wait_for_mysql,
    wipe_all,
)

DATA_DIR = Path(os.environ.get("DATA_DIR") or (Path(__file__).resolve().parent / "data"))
DB_PATH = DATA_DIR / "records.sqlite3"
API_TOKEN = os.environ.get("API_TOKEN", "lab-token")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))

_LOCK = threading.Lock()
_LAST_POST: dict | None = None
_EVENTS: list[dict] = []
_INGEST_DOWN = False
DASH_PATH = Path(__file__).with_name("dashboard.html")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def dashboard_html() -> str:
    return DASH_PATH.read_text(encoding="utf-8")


def push_event(kind: str, ip: str, summary: str, envelope: dict, duplicate: bool = False) -> None:
    item = {
        "at": utc_now(),
        "ip": ip,
        "kind": kind,
        "summary": summary,
        "duplicate": duplicate,
        "envelope": envelope,
    }
    with _LOCK:
        _EVENTS.insert(0, item)
        del _EVENTS[200:]


def recent_events(limit: int = 80) -> list[dict]:
    limit = max(1, min(limit, 200))
    with _LOCK:
        return list(_EVENTS[:limit])


def clear_events() -> None:
    with _LOCK:
        _EVENTS.clear()


def wipe_everything() -> dict:
    global _LAST_POST, _INGEST_DOWN
    with _LOCK:
        _INGEST_DOWN = True
    result = wipe_all()
    with _LOCK:
        DB.execute("DELETE FROM records")
        DB.commit()
        _EVENTS.clear()
        _LAST_POST = None
    result["records_cleared"] = True
    result["ingest_paused"] = True
    return result


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            record_id INTEGER PRIMARY KEY,
            idempotency_key TEXT UNIQUE,
            received_at TEXT NOT NULL,
            client_ip TEXT,
            tag_name TEXT,
            value_id TEXT,
            ts TEXT,
            ms TEXT,
            real_value TEXT,
            quality TEXT,
            flags TEXT,
            payload_json TEXT NOT NULL,
            envelope_json TEXT
        )
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(records)")}
    if "envelope_json" not in cols:
        conn.execute("ALTER TABLE records ADD COLUMN envelope_json TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_records_received ON records(received_at DESC)"
    )
    conn.commit()
    return conn


DB = connect()


def payload_field(payload: dict, *names: str) -> str:
    lower = {str(k).lower(): v for k, v in payload.items()}
    for name in names:
        if name.lower() in lower and lower[name.lower()] is not None:
            return str(lower[name.lower()])
    return ""


def insert_record(envelope: dict, idem: str, client_ip: str) -> tuple[bool, int]:
    """Return (inserted, record_id). False means duplicate idempotency key."""
    record_id = int(envelope["id"])
    payload = envelope.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    row = (
        record_id,
        idem or f"plc-record-{record_id}",
        utc_now(),
        client_ip,
        payload_field(payload, "TagName", "tag_name", "ValueName"),
        payload_field(payload, "ValueID", "value_id"),
        payload_field(payload, "TimeStamp", "timestamp", "DateTime"),
        payload_field(payload, "MS", "ms"),
        payload_field(payload, "RealValue", "real_value", "Value"),
        payload_field(payload, "Quality", "quality"),
        payload_field(payload, "Flags", "flags"),
        json.dumps(payload, ensure_ascii=False, default=str),
        json.dumps(envelope, ensure_ascii=False, default=str),
    )
    with _LOCK:
        try:
            DB.execute(
                """
                INSERT INTO records (
                    record_id, idempotency_key, received_at, client_ip,
                    tag_name, value_id, ts, ms, real_value, quality, flags,
                    payload_json, envelope_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
            DB.commit()
            return True, record_id
        except sqlite3.IntegrityError:
            DB.rollback()
            return False, record_id


def stats() -> dict:
    with _LOCK:
        total = DB.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        last = DB.execute(
            "SELECT received_at, client_ip, tag_name, real_value FROM records "
            "ORDER BY received_at DESC LIMIT 1"
        ).fetchone()
        tags = DB.execute(
            "SELECT COUNT(DISTINCT tag_name) FROM records WHERE tag_name != ''"
        ).fetchone()[0]
        last_post = _LAST_POST
        ingest_down = _INGEST_DOWN
    out = {
        "ok": True,
        "total": total,
        "unique_tags": tags,
        "last": None,
        "last_post": last_post,
        "ingest_paused": ingest_down,
        "replica": replica_overview(),
        "cursors": list_cursors(),
        "backend": backend_name(),
    }
    if last:
        out["last"] = {
            "received_at": last["received_at"],
            "client_ip": last["client_ip"],
            "tag_name": last["tag_name"],
            "real_value": last["real_value"],
        }
    return out


def recent(limit: int = 80) -> list[dict]:
    limit = max(1, min(limit, 300))
    with _LOCK:
        rows = DB.execute(
            "SELECT record_id, idempotency_key, received_at, client_ip, tag_name, "
            "value_id, ts, ms, real_value, quality, flags, payload_json, envelope_json "
            "FROM records ORDER BY received_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        payload_raw = item.pop("payload_json")
        envelope_raw = item.pop("envelope_json")
        try:
            item["payload"] = json.loads(payload_raw)
        except (TypeError, json.JSONDecodeError):
            item["payload"] = payload_raw
        if envelope_raw:
            try:
                item["envelope"] = json.loads(envelope_raw)
            except json.JSONDecodeError:
                item["envelope"] = envelope_raw
        else:
            item["envelope"] = {
                "type": "data",
                "id": item["record_id"],
                "idempotency_key": item["idempotency_key"],
                "payload": item["payload"],
            }
        items.append(item)
    return items


class Handler(BaseHTTPRequestHandler):
    server_version = "PLCBridgeLabAPI/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"{utc_now()} {self.client_address[0]} {fmt % args}", flush=True)

    def _send(self, code: int, body: dict | str, content_type: str = "application/json") -> None:
        if isinstance(body, dict):
            raw = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        else:
            raw = body
        self.send_response(code)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _auth_ok(self) -> bool:
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {API_TOKEN}" or auth == API_TOKEN

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path)
        if path.path in ("/", "/index.html"):
            self._send(200, dashboard_html(), "text/html")
            return
        if path.path == "/api/status":
            self._send(200, stats())
            return
        if path.path == "/api/records":
            qs = parse_qs(path.query)
            limit = int((qs.get("limit") or ["80"])[0])
            self._send(200, {"ok": True, "records": recent(limit)})
            return
        if path.path == "/api/events":
            qs = parse_qs(path.query)
            limit = int((qs.get("limit") or ["80"])[0])
            self._send(200, {"ok": True, "events": recent_events(limit)})
            return
        if path.path == "/api/table":
            qs = parse_qs(path.query)
            db = (qs.get("db") or [""])[0]
            table = (qs.get("table") or [""])[0]
            limit = int((qs.get("limit") or ["80"])[0])
            offset = int((qs.get("offset") or ["0"])[0])
            if not db or not table:
                self._send(400, {"ok": False, "error": "db_and_table_required"})
                return
            result = table_preview(db, table, limit, offset)
            self._send(200 if result.get("ok") else 404, result)
            return
        if path.path in ("/health", "/api/health"):
            self._send(200, {"ok": True})
            return
        if path.path == "/api/cursors":
            if not self._auth_ok():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            qs = parse_qs(path.query)
            rebuilt = 0
            if (qs.get("rebuild") or ["0"])[0] in ("1", "true", "yes"):
                rebuilt = refresh_cursors_from_replica()
            self._send(200, {"ok": True, "rebuilt": rebuilt, "cursors": list_cursors()})
            return
        if path.path == "/api/resume":
            if not self._auth_ok():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            rebuilt = refresh_cursors_from_replica()
            self._send(
                200,
                {"ok": True, "rebuilt": rebuilt, "backend": backend_name(), "cursors": list_cursors()},
            )
            return
        if path.path == "/api/cursors.txt":
            if not self._auth_ok():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            qs = parse_qs(path.query)
            if (qs.get("rebuild") or ["0"])[0] in ("1", "true", "yes"):
                refresh_cursors_from_replica()
            self._send(200, cursors_txt(), "text/plain")
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        global _INGEST_DOWN
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/events/clear":
            clear_events()
            self._send(200, {"ok": True})
            return
        if path == "/api/ingest/stop":
            with _LOCK:
                _INGEST_DOWN = True
            self._send(200, {"ok": True, "ingest_paused": True})
            return
        if path == "/api/ingest/start":
            with _LOCK:
                _INGEST_DOWN = False
            self._send(200, {"ok": True, "ingest_paused": False})
            return
        if path == "/api/wipe":
            self._send(200, wipe_everything())
            return
        if path not in ("/api/plc-records", "/api/plc-record", "/api/sql-sync"):
            self._send(404, {"ok": False, "error": "not_found"})
            return
        if not self._auth_ok():
            self._send(401, {"ok": False, "error": "unauthorized"})
            return
        with _LOCK:
            paused = _INGEST_DOWN
        if paused:
            push_event("stop", self.client_address[0], "HTTP 500 ingest stopped", {"error": "ingest_stopped"})
            self._send(500, {"ok": False, "error": "ingest_stopped"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 8_000_000:
            self._send(413, {"ok": False, "error": "too_large"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            envelope = json.loads(raw.decode("utf-8") if raw else "{}")
        except json.JSONDecodeError:
            self._send(400, {"ok": False, "error": "invalid_json"})
            return
        if not isinstance(envelope, dict):
            self._send(400, {"ok": False, "error": "invalid_envelope"})
            return
        idem = self.headers.get("Idempotency-Key") or str(envelope.get("idempotency_key") or "")
        env_type = str(envelope.get("type") or "")
        global _LAST_POST
        if env_type == "sql_sync" or envelope.get("table"):
            result = apply_sql_sync(envelope, idem)
            if not result.get("ok"):
                self._send(400, result)
                return
            with _LOCK:
                _LAST_POST = {
                    "at": utc_now(),
                    "id": envelope.get("id") or 0,
                    "ip": self.client_address[0],
                    "duplicate": bool(result.get("duplicate")),
                    "envelope": envelope,
                }
            print(
                f"{utc_now()} sql_sync db={result.get('database')} table={result.get('table')} "
                f"rows={result.get('rows')} dup={result.get('duplicate')} from={self.client_address[0]}",
                flush=True,
            )
            push_event(
                "sql_sync",
                self.client_address[0],
                f"{result.get('database')}.{result.get('table')} +{result.get('rows')} "
                f"after={result.get('watermark') or ''}",
                envelope,
                bool(result.get("duplicate")),
            )
            self._send(200, result)
            return
        if envelope.get("id") is None or envelope.get("payload") is None:
            self._send(400, {"ok": False, "error": "invalid_envelope"})
            return
        try:
            int(envelope["id"])
        except (TypeError, ValueError):
            self._send(400, {"ok": False, "error": "bad_id"})
            return
        inserted, record_id = insert_record(envelope, idem, self.client_address[0])
        with _LOCK:
            _LAST_POST = {
                "at": utc_now(),
                "id": record_id,
                "ip": self.client_address[0],
                "duplicate": not inserted,
                "envelope": envelope,
            }
        print(
            f"{utc_now()} POST id={record_id} inserted={inserted} "
            f"from={self.client_address[0]} idem={idem}",
            flush=True,
        )
        print(json.dumps(envelope, ensure_ascii=False, indent=2), flush=True)
        payload = envelope.get("payload") or {}
        tag = payload.get("TagName") or payload.get("tag_name") or ""
        val = payload.get("RealValue") or payload.get("real_value") or ""
        push_event(
            "data",
            self.client_address[0],
            f"{tag} = {val}".strip(" ="),
            envelope,
            not inserted,
        )
        self._send(
            200,
            {
                "ok": True,
                "id": record_id,
                "idempotency_key": idem,
                "duplicate": not inserted,
            },
        )


def main() -> None:
    wait_for_mysql(90)
    rebuilt = refresh_cursors_from_replica()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"AlisBoard mill API on http://{HOST}:{PORT}/", flush=True)
    print(f"POST {HOST}:{PORT}/api/plc-records  token={API_TOKEN}", flush=True)
    print(f"Tag SQLite {DB_PATH}", flush=True)
    print(f"Replica {backend_name()}  resume tables={rebuilt}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
