from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class StateStore:
    """Durable high-water mark. Writes are transactional and flushed by SQLite."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self._lock = threading.Lock()
        with self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS bridge_state (name TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def last_success_id(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM bridge_state WHERE name = 'last_success_id'"
            ).fetchone()
        return int(row[0]) if row else 0

    def mark_success(self, record_id: int) -> None:
        record_id = int(record_id)
        with self._lock, self._connection:
            current = self._connection.execute(
                "SELECT value FROM bridge_state WHERE name = 'last_success_id'"
            ).fetchone()
            if current and record_id < int(current[0]):
                raise ValueError("Refusing to move durable state backwards")
            self._connection.execute(
                "INSERT INTO bridge_state(name, value) VALUES('last_success_id', ?) "
                "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                (str(record_id),),
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
