#!/usr/bin/env python3
"""End-to-end: IN.JSON Wi-Fi config, QUEUE.JSON sql_sync, wait for ESP POST."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

IN_SIZE = 2048
QUEUE_SIZE = 8192
WIFI = {
    "ssid": "Alis",
    "password": "Ali.s1380",
    "api_url": "http://192.168.100.18:18773/api/plc-records",
    "api_token": "lab-token",
}
SYNC = {
    "type": "sql_sync",
    "source": "e2e_test",
    "database": "e2e_db",
    "table": "e2e_tbl",
    "columns": [{"name": "id", "mysql_type": "TEXT"}],
    "rows": [{"id": "1"}],
    "watermark": "1",
    "mode": "crawl",
    "id": 999001,
    "idempotency_key": "e2e-test-999001",
}


def find_disk() -> Path:
    for letter in "GHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:/")
        if (root / "OUT.JSON").exists() or (root / "AlisBoard.exe").exists():
            return root
    raise SystemExit("FAIL: ESP USB disk not found")


def pad_file(path: Path, data: bytes, size: int) -> None:
    if len(data) > size:
        raise SystemExit(f"FAIL: {path.name} too large ({len(data)} > {size})")
    padded = data + b" " * (size - len(data))
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 0x1
        FILE_SHARE_WRITE = 0x2
        OPEN_ALWAYS = 4
        FILE_ATTRIBUTE_NORMAL = 0x80
        FILE_FLAG_WRITE_THROUGH = 0x80000000
        handle = kernel32.CreateFileW(
            str(path),
            GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_WRITE_THROUGH,
            None,
        )
        if handle == wintypes.HANDLE(-1).value:
            raise SystemExit(f"FAIL: cannot open {path}")
        try:
            written = wintypes.DWORD(0)
            buf = ctypes.create_string_buffer(padded)
            if not kernel32.WriteFile(handle, buf, len(padded), ctypes.byref(written), None):
                raise SystemExit(f"FAIL: WriteFile {path.name}")
            kernel32.FlushFileBuffers(handle)
        finally:
            kernel32.CloseHandle(handle)
    else:
        path.write_bytes(padded)


def read_out(root: Path) -> dict:
    path = root / "OUT.JSON"
    if not path.exists():
        return {}
    raw = path.read_bytes()
    start = raw.find(b"{")
    end = raw.rfind(b"}")
    if start < 0 or end < start:
        return {}
    return json.loads(raw[start : end + 1].decode("ascii", "replace"))


def api_ok(host: str = "192.168.100.18") -> bool:
    try:
        req = urllib.request.Request(f"http://{host}:18773/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main() -> int:
    print("=== AlisBoard ESP E2E test ===")
    if not api_ok("127.0.0.1"):
        print("FAIL: API not up on 127.0.0.1:18773 - run lab/receiver/up.bat")
        return 1
    if not api_ok("192.168.100.18"):
        print("WARN: host Wi-Fi IP 192.168.100.18 not reachable from this PC")
        print("      ESP will likely get 'refused' until firewall is open")
        print("      Run lab/receiver/open-firewall-admin.bat as Administrator")

    root = find_disk()
    print(f"ESP disk: {root}")

    in_js = json.dumps({"command": "set_wifi", **WIFI}, separators=(",", ":")).encode("ascii")
    pad_file(root / "IN.JSON", in_js, IN_SIZE)
    print("Wrote IN.JSON (Wi-Fi + API URL)")

    sync_js = json.dumps(SYNC, separators=(",", ":")).encode("ascii")
    pad_file(root / "QUEUE.JSON", sync_js, QUEUE_SIZE)
    print(f"Wrote QUEUE.JSON sql_sync ({len(sync_js)} bytes)")

    deadline = time.time() + 120
    last_log = ""
    while time.time() < deadline:
        doc = read_out(root)
        esp_log = str(doc.get("esp_log") or "")
        if esp_log != last_log:
            for line in esp_log.split(" | "):
                line = "".join(c for c in line if 32 <= ord(c) < 127)
                if line.strip():
                    print(f"  ESP: {line.strip()}")
            last_log = esp_log
        if "sql_sync POST ok" in esp_log:
            print("PASS: ESP posted sql_sync via Wi-Fi")
            return 0
        if "API fail refused" in esp_log:
            print("FAIL: ESP API refused - open firewall on host (open-firewall-admin.bat)")
            return 1
        time.sleep(2)

    print("FAIL: timeout waiting for sql_sync POST ok")
    return 1


if __name__ == "__main__":
    sys.exit(main())
