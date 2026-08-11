from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path

from .config import AppConfig, load_config
from .database import MySQLSource
from .logger import configure_logging
from .serial_bridge import DeliveryError, SerialBridge
from .state import StateStore


class BridgeApplication:
    def __init__(self, config: AppConfig, stop_event: threading.Event | None = None):
        self.config = config
        self.stop_event = stop_event or threading.Event()
        self.logger = configure_logging(config.runtime)
        self.state = StateStore(config.runtime.state_db)
        self.source = MySQLSource(config.database)
        self.serial = SerialBridge(config.serial, self.logger)

    def _wait(self, seconds: float) -> bool:
        return self.stop_event.wait(seconds)

    def run(self) -> None:
        self.logger.info("PLCBridge starting with config %s", self.config.path)
        if not self.config.database.enabled:
            self.logger.error("Database is disabled; edit config and set enabled=true after defining the real query")
            return
        try:
            while not self.stop_event.is_set():
                try:
                    last_id = self.state.last_success_id()
                    rows = self.source.fetch_after(last_id)
                    if not rows:
                        self._wait(self.config.runtime.poll_interval_seconds)
                        continue
                    for row in rows:
                        if self.stop_event.is_set():
                            break
                        envelope = self.source.envelope(row)
                        record_id = int(envelope["id"])
                        delivered = False
                        while not delivered and not self.stop_event.is_set():
                            if not self.serial.connect():
                                self._wait(self.config.serial.reconnect_delay_seconds)
                                continue
                            try:
                                self.serial.deliver(envelope)
                                self.state.mark_success(record_id)
                                self.logger.info("Record %s acknowledged and committed", record_id)
                                delivered = True
                            except DeliveryError as exc:
                                self.logger.warning("Record %s not delivered: %s", record_id, exc)
                                if str(exc) in {"serial_disconnected", "serial_io_error", "ack_timeout"}:
                                    self.serial.close()
                                self._wait(self.config.runtime.retry_delay_seconds)
                except Exception:
                    self.logger.exception("Bridge cycle failed; retrying")
                    self.serial.close()
                    self._wait(self.config.runtime.retry_delay_seconds)
        finally:
            self.serial.close()
            self.state.close()
            self.logger.info("PLCBridge stopped")


def run_console(config_path: str | Path | None = None) -> None:
    config = load_config(config_path)
    stop_event = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: stop_event.set())
        except (OSError, ValueError):
            pass
    BridgeApplication(config, stop_event).run()
