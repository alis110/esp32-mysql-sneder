from __future__ import annotations

import json
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import mysql.connector
from mysql.connector.connection import MySQLConnection

from .config import DatabaseConfig


class RecordError(ValueError):
    pass


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    raise TypeError(f"Unsupported database value: {type(value).__name__}")


class MySQLSource:
    """Lightweight MySQL reader: one long-lived connection, tiny batches via config."""

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self._conn: MySQLConnection | None = None

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    def _connect(self) -> MySQLConnection:
        if self._conn is not None:
            try:
                self._conn.ping(reconnect=True, attempts=1, delay=0)
                return self._conn
            except Exception:  # noqa: BLE001
                self.close()
        self._conn = mysql.connector.connect(
            host=self.config.host,
            port=self.config.port,
            database=self.config.database,
            user=self.config.username,
            password=self.config.password,
            connection_timeout=self.config.connect_timeout_seconds,
            autocommit=True,
            # Keep handshake/CPU low on factory PCs.
            buffered=True,
        )
        return self._conn

    def fetch_after(self, last_id: int) -> list[dict[str, Any]]:
        try:
            connection = self._connect()
            with closing(connection.cursor(dictionary=True)) as cursor:
                cursor.execute(
                    self.config.query,
                    {"last_id": last_id, "batch_size": self.config.batch_size},
                )
                rows = list(cursor.fetchall())
        except mysql.connector.Error:
            self.close()
            connection = self._connect()
            with closing(connection.cursor(dictionary=True)) as cursor:
                cursor.execute(
                    self.config.query,
                    {"last_id": last_id, "batch_size": self.config.batch_size},
                )
                rows = list(cursor.fetchall())

        previous = last_id
        for row in rows:
            if self.config.id_column not in row:
                raise RecordError(f"Query result lacks id column '{self.config.id_column}'")
            try:
                record_id = int(row[self.config.id_column])
            except (TypeError, ValueError) as exc:
                raise RecordError("Record IDs must be integers") from exc
            if record_id <= previous:
                raise RecordError("Query results must be strictly ordered by increasing ID")
            previous = record_id
        return rows

    def envelope(self, row: dict[str, Any]) -> dict[str, Any]:
        record_id = int(row[self.config.id_column])
        # Round-trip through JSON to normalize dates, Decimal and binary values.
        payload = json.loads(json.dumps(row, default=_json_default, ensure_ascii=False))
        return {
            "type": "data",
            "id": record_id,
            "idempotency_key": f"plc-record-{record_id}",
            "payload": payload,
        }
