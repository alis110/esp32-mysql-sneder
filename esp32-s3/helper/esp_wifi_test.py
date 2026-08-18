#!/usr/bin/env python3
"""Write IN.JSON to ESP USB disk and wait for Wi-Fi + API hello in OUT.JSON."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

IN_SIZE = 2048
DEFAULTS = {
    "ssid": "Alis",
    "password": "Ali.s1380",
    "api_url": "http://192.168.100.18:18773/api/plc-records",
    "api_token": "lab-token",
}


def find_disk() -> Path:
    for letter in "GHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:/")
        if (root / "OUT.JSON").exists() or (root / "AlisBoard.exe").exists():
            return root
    raise SystemExit("ESP disk not found (plug USB, look for ALISBOARD drive)")


def write_in_json(root: Path, payload: dict) -> None:
    js = json.dumps({"command": "set_wifi", **payload}, separators=(",", ":"))
    data = js.encode("ascii")
    if len(data) > IN_SIZE - 1:
        raise SystemExit("IN.JSON too large")
    padded = data + b" " * (IN_SIZE - len(data))
    (root / "IN.JSON").write_bytes(padded)
    print(f"Wrote IN.JSON -> {root / 'IN.JSON'}")


def read_out(root: Path) -> dict:
    raw = (root / "OUT.JSON").read_bytes()
    start = raw.find(b"{")
    end = raw.rfind(b"}")
    if start < 0 or end < start:
        return {}
    return json.loads(raw[start : end + 1].decode("utf-8", "replace"))


def main() -> int:
    root = find_disk()
    print(f"ESP disk: {root}")
    write_in_json(root, DEFAULTS)
    deadline = time.time() + 90
    last_log = ""
    while time.time() < deadline:
        doc = read_out(root)
        wifi_ok = doc.get("wifi_ok") is True
        ip = doc.get("wifi_ip") or "0.0.0.0"
        api_detail = str(doc.get("api_detail") or "")
        esp_log = str(doc.get("esp_log") or "")
        if esp_log != last_log:
            print(esp_log.replace(" | ", "\n  "))
            last_log = esp_log
        if wifi_ok and ip not in ("0.0.0.0", ""):
            print(f"Wi-Fi OK: {ip} ssid={doc.get('wifi_ssid')}")
            if api_detail in ("200", "refused", "lost", "never", "-1"):
                if api_detail == "200":
                    print("API hello OK (HTTP 200)")
                    return 0
                print(f"Wi-Fi up but API detail={api_detail} - check lan_relay + firewall")
                return 1
        time.sleep(2)
    print("TIMEOUT - Wi-Fi or API did not come up in 90s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
