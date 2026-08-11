from __future__ import annotations

import json
import logging
import time
from typing import Any

import serial
from serial.tools import list_ports

from .config import SerialConfig


class DeliveryError(RuntimeError):
    pass


class SerialBridge:
    def __init__(self, config: SerialConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._serial: serial.Serial | None = None

    def _find_port(self) -> str | None:
        if self.config.port.lower() != "auto":
            return self.config.port
        candidates = []
        for port in list_ports.comports():
            identity = f"{port.vid:04X}:{port.pid:04X}" if port.vid is not None and port.pid is not None else ""
            if identity in self.config.vid_pid:
                candidates.append(port.device)
        if len(candidates) > 1:
            self.logger.warning("Multiple matching serial devices; using %s", candidates[0])
        return candidates[0] if candidates else None

    def connect(self) -> bool:
        if self._serial and self._serial.is_open:
            return True
        self.close()
        port = self._find_port()
        if not port:
            self.logger.warning("ESP32 serial port not found")
            return False
        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=self.config.baudrate,
                timeout=1,
                write_timeout=5,
            )
            # Opening a CP2102 port commonly resets ESP32 through DTR/RTS.
            # Wait for firmware boot + optional Wi-Fi association ("ready" event).
            time.sleep(self.config.startup_delay_seconds)
            self._serial.reset_input_buffer()
            ready_deadline = time.monotonic() + max(12.0, self.config.startup_delay_seconds)
            while time.monotonic() < ready_deadline:
                line = self._serial.readline()
                if not line:
                    continue
                try:
                    text = line.decode("utf-8", errors="replace").strip()
                    reply = json.loads(text)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    continue
                if reply.get("type") == "event":
                    self.logger.info("ESP event: %s %s", reply.get("event"), reply.get("detail", ""))
                    if reply.get("event") == "ready":
                        break
            self.logger.info("Connected to ESP32 on %s", port)
            return True
        except serial.SerialException as exc:
            self.logger.warning("Serial connection failed: %s", exc)
            self.close()
            return False

    def close(self) -> None:
        if self._serial:
            try:
                self._serial.close()
            except serial.SerialException:
                pass
        self._serial = None

    def deliver(self, envelope: dict[str, Any]) -> None:
        if not self._serial or not self._serial.is_open:
            raise DeliveryError("serial_disconnected")
        record_id = str(envelope["id"])
        wire = (json.dumps(envelope, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self._serial.reset_input_buffer()
            self._serial.write(wire)
            self._serial.flush()
            self.logger.info("Sent record %s (%s bytes), waiting for ACK", record_id, len(wire))
            deadline = time.monotonic() + self.config.ack_timeout_seconds
            while time.monotonic() < deadline:
                line = self._serial.readline()
                if not line:
                    continue
                try:
                    text = line.decode("utf-8", errors="replace").strip()
                except UnicodeDecodeError:
                    self.logger.warning("Ignoring undecodable serial bytes")
                    continue
                if not text:
                    continue
                try:
                    reply = json.loads(text)
                except json.JSONDecodeError:
                    self.logger.warning("Ignoring non-JSON serial line: %s", text[:160])
                    continue
                msg_type = reply.get("type")
                if msg_type == "event":
                    self.logger.info(
                        "ESP event: %s %s",
                        reply.get("event"),
                        reply.get("detail", ""),
                    )
                    continue
                if str(reply.get("id")) != record_id:
                    self.logger.warning("Ignoring response for unexpected record ID: %s", text[:160])
                    continue
                if msg_type == "ack" and reply.get("status") == "success":
                    return
                if msg_type == "nack":
                    raise DeliveryError(str(reply.get("error", "esp_error")))
                self.logger.warning("Ignoring unexpected serial JSON: %s", text[:160])
            raise DeliveryError("ack_timeout")
        except (serial.SerialException, OSError) as exc:
            self.close()
            raise DeliveryError("serial_io_error") from exc
