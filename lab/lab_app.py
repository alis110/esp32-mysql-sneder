#!/usr/bin/env python3
"""Tiny PLCBridge setup panel — no Docker. Detect ESP/Wi-Fi, flash, test, install auto-start service."""

from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

ROOT = Path(__file__).resolve().parents[1]
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import DEFAULT_WINCC_QUERY

CP2102 = ("10C4", "EA60")
CH340 = ("1A86", "7523")
CH9102 = ("1A86", "55D4")
USB_UART = {CP2102, CH340, CH9102, ("0403", "6001")}  # FTDI
# Laptop Docker receiver on Wi-Fi Alissss (factory ESP posts here).
LAB_API_URL = "http://10.33.97.45/api/plc-records"
SECRETS_H = ROOT / "firmware" / "include" / "secrets.h"
LAB_CONFIG = ROOT / "config" / "config.lab.ini"
MOCK_API_PORT = 8089

# Filled by LabApp so the HTTP handler can push into the UI API Activity panel.
_API_LOG: queue.Queue[str] | None = None
_API_HIT_COUNT = 0
_API_HIT_LOCK = threading.Lock()
_API_LAST_HIT: str = ""


def _ts() -> str:
    return time.strftime("%H:%M:%S")


class _MockApiHandler(BaseHTTPRequestHandler):
    server_version = "PLCBridgeMockAPI/1.0"

    def do_POST(self) -> None:  # noqa: N802
        global _API_HIT_COUNT, _API_LAST_HIT
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":false,"error":"invalid_json"}')
            self._ui(f"[{_ts()}] BAD JSON from {self.client_address[0]}")
            return

        idem = self.headers.get("Idempotency-Key", "")
        auth = self.headers.get("Authorization", "")
        with _API_HIT_LOCK:
            _API_HIT_COUNT += 1
            n = _API_HIT_COUNT
            _API_LAST_HIT = _ts()
        pretty = json.dumps(payload, ensure_ascii=False, indent=2)
        auth_s = (auth[:28] + "…") if len(auth) > 28 else (auth or "-")
        self._ui(
            f"[{_ts()}] HIT #{n} ← {self.client_address[0]} {self.command} {self.path}\n"
            f"  Idempotency-Key: {idem or '-'}\n"
            f"  Authorization: {auth_s}\n"
            f"{pretty}\n"
            f"{'─' * 40}"
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"ok": True, "id": payload.get("id"), "idempotency_key": idem}).encode("utf-8")
        )

    def log_message(self, fmt: str, *args) -> None:
        self._ui(f"[{_ts()}] access {self.client_address[0]} — " + (fmt % args))

    @staticmethod
    def _ui(msg: str) -> None:
        if _API_LOG is not None:
            _API_LOG.put(msg)


def probe_api_url(url: str) -> tuple[bool, str]:
    """TCP reachability of API host:port from this PC (not ESP's Wi-Fi path)."""
    from urllib.parse import urlparse

    raw = (url or "").strip()
    if not raw:
        return False, "no URL"
    try:
        u = urlparse(raw)
        host = u.hostname
        if not host:
            return False, "bad URL"
        port = u.port or (443 if (u.scheme or "").lower() == "https" else 80)
        with socket.create_connection((host, port), timeout=2.0):
            return True, f"OK {host}:{port}"
    except OSError as exc:
        err = str(exc)
        if "10051" in err or "unreachable" in err.lower():
            return False, (
                f"FAIL this PC has no route to {host} "
                "(normal here — ESP uses Wi-Fi Alissss, not this PC)"
            )
        return False, f"FAIL {exc}"


def start_embedded_mock_api(port: int = MOCK_API_PORT) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("0.0.0.0", port), _MockApiHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="mock-api")
    thread.start()
    return httpd


def free_tcp_port(port: int) -> list[str]:
    """Kill Windows processes listening on TCP *port*. Returns human log lines."""
    notes: list[str] = []
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"],
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_create_no_window(),
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return [f"Could not list ports: {exc}"]

    pids: set[str] = set()
    suffix = f":{port}"
    for line in out.splitlines():
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[1]
        if not local.endswith(suffix):
            continue
        pid = parts[-1]
        if pid.isdigit() and int(pid) > 0:
            pids.add(pid)

    me = str(os.getpid())
    for pid in sorted(pids):
        if pid == me:
            continue
        try:
            r = subprocess.run(
                ["taskkill", "/PID", pid, "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_create_no_window(),
                check=False,
            )
            if r.returncode == 0:
                notes.append(f"Freed port {port} (stopped PID {pid})")
            else:
                err = (r.stderr or r.stdout or "").strip()
                notes.append(f"Could not stop PID {pid} on :{port}: {err or r.returncode}")
        except OSError as exc:
            notes.append(f"Could not stop PID {pid}: {exc}")
    if not pids:
        notes.append(f"No listener found on :{port}")
    return notes


def _create_no_window() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def local_ipv4() -> str:
    """Prefer a real LAN IPv4. Windows 7 has no Get-NetIPAddress (PowerShell 2)."""
    try:
        raw = subprocess.check_output(
            ["ipconfig"],
            text=True,
            encoding="oem",
            errors="replace",
            creationflags=_create_no_window(),
        )
        for line in raw.splitlines():
            low = line.lower()
            if "ipv4" not in low and "ip address" not in low:
                continue
            if ":" not in line:
                continue
            ip = line.split(":")[-1].strip()
            if ip.startswith("127.") or ip.startswith("169.254.") or not ip[:1].isdigit():
                continue
            return ip
    except (OSError, subprocess.CalledProcessError):
        pass
    try:
        raw = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-NetIPAddress -AddressFamily IPv4 |"
                " Where-Object {"
                "  $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and"
                "  $_.InterfaceAlias -match 'Wi-?Fi|WLAN|Ethernet'"
                " } | Sort-Object InterfaceMetric |"
                " Select-Object -First 1 -ExpandProperty IPAddress)",
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_create_no_window(),
        ).strip()
        if raw and raw[0].isdigit() and not raw.startswith("169.254."):
            return raw.splitlines()[0].strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        if not ip.startswith("169.254."):
            return ip
    except OSError:
        pass
    finally:
        sock.close()
    return "127.0.0.1"


def default_api_url() -> str:
    """ESP must reach the laptop API, not this PC's 127.0.0.1."""
    return LAB_API_URL


def list_esp_ports() -> list[dict]:
    from serial.tools import list_ports

    found = []
    for port in list_ports.comports():
        vid = f"{port.vid:04X}" if port.vid is not None else ""
        pid = f"{port.pid:04X}" if port.pid is not None else ""
        desc = (port.description or "") + " " + (port.hwid or "")
        desc_l = desc.lower()
        is_esp = (vid, pid) in USB_UART or any(
            token in desc_l
            for token in ("cp210", "silicon labs", "ch340", "ch910", "usb-serial", "usb serial")
        )
        if port.device and port.device.upper() in {"COM1"}:
            is_esp = False
        found.append(
            {
                "device": port.device,
                "description": port.description or "",
                "is_esp": is_esp,
            }
        )
    return found


def _netsh(*args: str) -> str:
    return subprocess.check_output(
        ["netsh", *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_create_no_window(),
    )


def wifi_status() -> dict:
    try:
        raw = _netsh("wlan", "show", "interfaces")
    except (OSError, subprocess.CalledProcessError):
        return {"state": "unknown", "ssid": "", "signal": ""}

    state = ssid = signal = ""
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in {"state", "وضعیت"}:
            state = value
        elif key == "ssid":
            ssid = value
        elif key in {"signal", "سیگنال"}:
            signal = value
    return {"state": state or "unknown", "ssid": ssid, "signal": signal}


def list_saved_wifi_profiles() -> list[str]:
    try:
        raw = _netsh("wlan", "show", "profiles")
    except (OSError, subprocess.CalledProcessError):
        return []
    profiles: list[str] = []
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key_l = key.strip().lower()
        if "profile" in key_l or "پروفایل" in key:
            name = value.strip()
            if name and name not in profiles:
                profiles.append(name)
    return profiles


def scan_wifi_networks() -> list[dict]:
    """Visible SSIDs nearby + saved profiles merged for selection."""
    by_ssid: dict[str, dict] = {}
    for name in list_saved_wifi_profiles():
        by_ssid[name] = {"ssid": name, "signal": "", "saved": True, "visible": False}

    try:
        # Trigger a scan; ignore failure on some adapters.
        subprocess.run(
            ["netsh", "wlan", "show", "networks", "mode=bssid"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_create_no_window(),
            check=False,
        )
        raw = _netsh("wlan", "show", "networks", "mode=bssid")
    except (OSError, subprocess.CalledProcessError):
        raw = ""

    current_ssid = ""
    current_signal = ""
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("SSID") and ":" in stripped and "BSSID" not in stripped.upper():
            if current_ssid:
                entry = by_ssid.setdefault(
                    current_ssid, {"ssid": current_ssid, "signal": "", "saved": False, "visible": True}
                )
                entry["visible"] = True
                if current_signal and (not entry["signal"] or current_signal > entry["signal"]):
                    entry["signal"] = current_signal
            _, value = stripped.split(":", 1)
            current_ssid = value.strip().strip('"')
            current_signal = ""
        elif current_ssid and ":" in stripped:
            key, value = stripped.split(":", 1)
            key_l = key.strip().lower()
            if key_l in {"signal", "سیگنال"}:
                current_signal = value.strip()
    if current_ssid:
        entry = by_ssid.setdefault(
            current_ssid, {"ssid": current_ssid, "signal": "", "saved": False, "visible": True}
        )
        entry["visible"] = True
        if current_signal:
            entry["signal"] = current_signal

    items = list(by_ssid.values())
    items.sort(key=lambda x: (not x["visible"], -(int(x["signal"].rstrip("%") or "0") if x["signal"] else -1), x["ssid"].lower()))
    return items


def wifi_password_for(ssid: str) -> str | None:
    if not ssid:
        return None
    try:
        raw = _netsh("wlan", "show", "profile", f"name={ssid}", "key=clear")
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key_l = key.strip().lower()
        if key_l in {"key content", "محتویات کلید", "محتوای کلید"} or "key content" in key_l:
            pwd = value.strip()
            return pwd or None
    return None


def ssid_display(item: dict) -> str:
    tags = []
    if item.get("visible"):
        tags.append(item["signal"] or "visible")
    if item.get("saved"):
        tags.append("saved")
    suffix = f"  ({', '.join(tags)})" if tags else ""
    return f"{item['ssid']}{suffix}"


WINCC_QUERY = DEFAULT_WINCC_QUERY

ENGINE_LABELS = {"sqlserver": "SQL Server (WinCC)"}
AUTH_LABELS = {"windows": "Windows (no password)", "sql": "SQL login (user/pass)"}


def _engine_key(label: str) -> str:
    return "sqlserver"


def _auth_key(label: str) -> str:
    raw = (label or "").strip().lower()
    if raw.startswith("windows") or raw in {"trusted", "integrated"}:
        return "windows"
    return "sql"


def wincc_ssms_host() -> str:
    """Same Server name SSMS shows: COMPUTER\\WINCC (e.g. CPUPC01\\WINCC)."""
    name = (os.environ.get("COMPUTERNAME") or "").strip()
    return f"{name}\\WINCC" if name else ".\\WINCC"


def sqlserver_probe(
    host: str,
    port: int,
    database: str,
    auth: str,
    user: str,
    password: str,
) -> tuple[bool, str]:
    from app.config import DatabaseConfig
    from app.database import probe_database

    cfg = DatabaseConfig(
        enabled=True,
        engine="sqlserver",
        auth=auth,
        host=host or ".\\WINCC",
        port=port,
        database=database or "auto",
        username=user,
        password=password,
        odbc_driver="",
        query=WINCC_QUERY,
        id_column="id",
        batch_size=1,
        connect_timeout_seconds=4,
    )
    return probe_database(cfg)


def write_secrets(ssid: str, password: str, api_url: str, api_token: str) -> Path:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    SECRETS_H.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_H.write_text(
        f'''#pragma once
#define WIFI_SSID "{esc(ssid)}"
#define WIFI_PASSWORD "{esc(password)}"
#define API_URL "{esc(api_url)}"
#define API_TOKEN "{esc(api_token)}"
#define ALLOW_INSECURE_TLS true
''',
        encoding="utf-8",
        newline="\n",
    )
    return SECRETS_H


def find_pio() -> str | None:
    found = shutil.which("pio") or shutil.which("platformio")
    if found:
        return found
    candidates = [
        ROOT / "tools" / "offline" / "portable-python" / "Scripts" / "pio.exe",
        Path(r"C:\PLCBridge\offline\portable-python\Scripts\pio.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "PLCBridge" / "offline" / "portable-python" / "Scripts" / "pio.exe",
    ]
    for path in candidates:
        if path.is_file():
            # Prefer bundled toolchains next to portable pio.
            home = path.parents[2] / "platformio-home"
            if not home.is_dir():
                home = Path(r"C:\PLCBridge\offline\platformio-home")
            if home.is_dir():
                os.environ.setdefault("PLATFORMIO_CORE_DIR", str(home))
            return str(path)
    return None


def send_test_record(port: str, baud: int, record_id: int, timeout: float = 45.0) -> tuple[bool, str]:
    import serial

    envelope = {
        "type": "data",
        "id": record_id,
        "idempotency_key": f"plc-record-{record_id}",
        "payload": {"temperature": 73.4, "note": "lab-test", "source": "lab_app"},
    }
    wire = (json.dumps(envelope, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    ser = serial.Serial(port=port, baudrate=baud, timeout=1, write_timeout=5)
    try:
        time.sleep(2.0)
        ser.reset_input_buffer()
        ser.write(wire)
        ser.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = ser.readline()
            if not line:
                continue
            try:
                reply = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if str(reply.get("id")) != str(record_id):
                continue
            if reply.get("type") == "ack" and reply.get("status") == "success":
                return True, json.dumps(reply, ensure_ascii=False)
            if reply.get("type") == "nack":
                return False, json.dumps(reply, ensure_ascii=False)
        return False, "ack_timeout"
    finally:
        ser.close()


def resolve_setup_exe() -> Path | None:
    candidates = [
        ROOT / "PLCBridgeSetup.exe",
        ROOT / "dist" / "PLCBridgeSetup.exe",
        ROOT / "system-install" / "PLCBridgeSetup.exe",
        Path(r"C:\Program Files\PLCBridge\PLCBridgeSetup.exe"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def startup_shortcut_path() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "PLCBridgeSetup.lnk"
    )


def ui_at_login_enabled() -> bool:
    return startup_shortcut_path().is_file()


def set_ui_at_login(enabled: bool) -> tuple[bool, str]:
    if not enabled:
        shortcut = startup_shortcut_path()
        try:
            if shortcut.is_file():
                shortcut.unlink()
            return True, "removed"
        except OSError as exc:
            return False, str(exc)

    target = resolve_setup_exe()
    if target is None:
        if (ROOT / "lab" / "lab_app.py").is_file():
            target = ROOT / "lab" / "lab_app.py"
        else:
            return False, "PLCBridgeSetup.exe not found"

    shortcut = startup_shortcut_path()
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    workdir = str(target.parent if target.suffix.lower() == ".exe" else ROOT)
    if target.suffix.lower() == ".exe":
        target_path = str(target)
        args = ""
    else:
        target_path = sys.executable
        args = str(target)

    # Escape for PowerShell single-quoted strings
    def q(s: str) -> str:
        return s.replace("'", "''")

    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{q(str(shortcut))}'); "
        f"$s.TargetPath = '{q(target_path)}'; "
        f"$s.Arguments = '{q(args)}'; "
        f"$s.WorkingDirectory = '{q(workdir)}'; "
        "$s.WindowStyle = 1; "
        "$s.Description = 'PLCBridge Setup UI'; "
        "$s.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            check=True,
            capture_output=True,
            text=True,
            creationflags=_create_no_window(),
        )
    except subprocess.CalledProcessError as exc:
        return False, exc.stderr or str(exc)
    return True, str(shortcut)


def find_pack_file(*relative: str) -> Path | None:
    """File next to the frozen EXE (USB pack) or under the repo root."""
    bases = [ROOT]
    if getattr(sys, "frozen", False):
        bases.insert(0, Path(sys.executable).resolve().parent)
    for base in bases:
        path = base.joinpath(*relative)
        if path.is_file():
            return path
    return None


def find_install_all_bat() -> Path | None:
    return (
        find_pack_file("Install-All.bat")
        or find_pack_file("tools", "Install-All.bat")
        or find_pack_file("system-install", "Install-All.bat")
        or find_pack_file("dist", "Install-All.bat")
    )


def find_uninstall_bat() -> Path | None:
    return (
        find_pack_file("Uninstall-Service.bat")
        or find_pack_file("system-install", "Uninstall-Service.bat")
        or find_pack_file("dist", "Uninstall-Service.bat")
    )


def find_esptool() -> Path | None:
    found = shutil.which("esptool") or shutil.which("esptool.exe")
    if found:
        return Path(found)
    return find_pack_file("esptool.exe")


def find_firmware_bin_dir() -> Path | None:
    for rel in (
        ("firmware-bin",),
        ("tools", "offline", "firmware-bin"),
    ):
        bases = [ROOT]
        if getattr(sys, "frozen", False):
            bases.insert(0, Path(sys.executable).resolve().parent)
        for base in bases:
            path = base.joinpath(*rel)
            if (path / "firmware.bin").is_file():
                return path
    return None


def flash_prebuilt_firmware(port: str) -> tuple[int, str]:
    """Flash firmware-bin with bundled esptool (no PlatformIO / no internet)."""
    tool = find_esptool()
    bindir = find_firmware_bin_dir()
    if not tool:
        return 1, "esptool.exe not found next to Setup."
    if not bindir:
        return 1, "firmware-bin\\firmware.bin not found."
    boot = bindir / "bootloader.bin"
    parts = bindir / "partitions.bin"
    fw = bindir / "firmware.bin"
    missing = [p.name for p in (boot, parts, fw) if not p.is_file()]
    if missing:
        return 1, "Missing in firmware-bin: " + ", ".join(missing)
    proc = subprocess.run(
        [
            str(tool),
            "--chip",
            "esp32",
            "--port",
            port,
            "--baud",
            "115200",
            "--before",
            "default_reset",
            "--after",
            "hard_reset",
            "--connect-attempts",
            "20",
            "--no-stub",
            "write_flash",
            "-z",
            "0x1000",
            str(boot),
            "0x8000",
            str(parts),
            "0x10000",
            str(fw),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=_create_no_window(),
    )
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, out[-2000:] if out else f"exit {proc.returncode}"


def elevate_and_wait(file_path: Path, args: str = "") -> tuple[int, str]:
    """UAC-elevate a .bat/.exe and wait. Works on Windows 7 PowerShell 2."""
    def q(s: str) -> str:
        return s.replace("'", "''")

    arg = f" -ArgumentList '{q(args)}'" if args.strip() else ""
    ps = (
        f"Start-Process -FilePath '{q(str(file_path))}'{arg} -Verb RunAs -Wait"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=_create_no_window(),
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except OSError as exc:
        return 1, str(exc)


def resolve_bridge_exe() -> Path | None:
    candidates = [
        ROOT / "PLCBridge.exe",
        ROOT / "dist" / "PLCBridge.exe",
        ROOT / "system-install" / "PLCBridge.exe",
        Path(r"C:\Program Files\PLCBridge\PLCBridge.exe"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


class LabApp(tk.Tk):
    # Light industrial palette (ttk — no heavy CSS/framework).
    _BG = "#F1F5F9"
    _CARD = "#FFFFFF"
    _BORDER = "#E2E8F0"
    _TEXT = "#0F172A"
    _MUTED = "#64748B"
    _ACCENT = "#0F766E"
    _ACCENT_HOVER = "#0D9488"
    _DANGER = "#B91C1C"
    _LOG_BG = "#F8FAFC"
    _OK = "#047857"
    _BAD = "#B91C1C"
    _FONT = ("Segoe UI", 9)
    _FONT_BOLD = ("Segoe UI", 9, "bold")
    _FONT_TITLE = ("Segoe UI", 12, "bold")
    _FONT_MONO = ("Consolas", 9)

    def __init__(self) -> None:
        super().__init__()
        self.title("PLCBridge Setup")
        self._fit_to_screen()
        self._log_q: queue.Queue[str] = queue.Queue()
        self._api_log_q: queue.Queue[str] = queue.Queue()
        self._esp_log_q: queue.Queue[str] = queue.Queue()
        self._mock_httpd: ThreadingHTTPServer | None = None
        self._bridge_proc: subprocess.Popen | None = None
        self._api_hits = 0
        self._esp_ser = None
        self._esp_reader_stop = threading.Event()
        self._esp_monitor_on = False
        self._status_snapshot: dict[str, str] = {}
        self._bridge_log_pos: dict[str, int] = {}
        self._live_busy = False
        global _API_LOG
        _API_LOG = self._api_log_q
        self._clip_menu = tk.Menu(self, tearoff=0)
        self._clip_menu.add_command(label="Cut", command=lambda: self._clip_action("cut"))
        self._clip_menu.add_command(label="Copy", command=lambda: self._clip_action("copy"))
        self._clip_menu.add_command(label="Paste", command=lambda: self._clip_action("paste"))
        self._clip_menu.add_separator()
        self._clip_menu.add_command(label="Select All", command=lambda: self._clip_action("select_all"))
        self._clip_menu.add_separator()
        self._clip_menu.add_command(label="Copy All Log", command=self._copy_log_all)
        self._apply_theme()
        self._build()
        self._enable_clipboard(self)
        self._bind_clipboard_widget(self.txt)
        self._bind_clipboard_widget(self.txt_api)
        self._bind_clipboard_widget(self.txt_esp)
        self._bind_clipboard_widget(self.txt_db)
        self.after(200, self._drain_log)
        self.after(200, self._drain_api_log)
        self.after(200, self._drain_esp_log)
        self.refresh_status(silent=False)
        self.after(4000, self._live_tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _fit_to_screen(self) -> None:
        """Win7 operator monitors are often 1024x768; Segoe Semibold is missing there."""
        self.update_idletasks()
        sw = int(self.winfo_screenwidth() or 1024)
        sh = int(self.winfo_screenheight() or 768)
        w = min(980, max(800, sw - 24))
        h = min(720, max(560, sh - 64))
        self.geometry(f"{w}x{h}+4+4")
        self.minsize(min(760, sw - 16), min(480, sh - 48))

    def _apply_theme(self) -> None:
        self.configure(bg=self._BG)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=self._FONT, background=self._BG, foreground=self._TEXT)
        style.configure("TFrame", background=self._BG)
        style.configure("Card.TFrame", background=self._CARD)
        style.configure(
            "TLabelframe",
            background=self._CARD,
            foreground=self._TEXT,
            bordercolor=self._BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label",
            background=self._CARD,
            foreground=self._MUTED,
            font=self._FONT_BOLD,
        )
        style.configure("TLabel", background=self._CARD, foreground=self._TEXT, font=self._FONT)
        style.configure("Muted.TLabel", background=self._CARD, foreground=self._MUTED, font=self._FONT)
        style.configure("Hint.TLabel", background=self._BG, foreground=self._MUTED, font=self._FONT)
        style.configure("Title.TLabel", background=self._BG, foreground=self._TEXT, font=self._FONT_TITLE)
        style.configure("Subtitle.TLabel", background=self._BG, foreground=self._MUTED, font=self._FONT)
        style.configure("Field.TLabel", background=self._CARD, foreground=self._MUTED, font=self._FONT)
        style.configure("StatusKey.TLabel", background=self._CARD, foreground=self._MUTED, font=self._FONT)
        style.configure("StatusVal.TLabel", background=self._CARD, foreground=self._TEXT, font=self._FONT)
        style.configure("Ok.TLabel", background=self._CARD, foreground=self._OK, font=self._FONT_BOLD)
        style.configure("Bad.TLabel", background=self._CARD, foreground=self._BAD, font=self._FONT_BOLD)
        style.configure("Warn.TLabel", background=self._CARD, foreground="#B45309", font=self._FONT)

        style.configure(
            "TEntry",
            fieldbackground="#FFFFFF",
            foreground=self._TEXT,
            bordercolor=self._BORDER,
            lightcolor=self._ACCENT,
            darkcolor=self._BORDER,
            insertcolor=self._TEXT,
            padding=2,
        )
        style.configure(
            "TCombobox",
            fieldbackground="#FFFFFF",
            foreground=self._TEXT,
            bordercolor=self._BORDER,
            arrowsize=12,
            padding=2,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#FFFFFF")],
            foreground=[("readonly", self._TEXT)],
        )
        style.configure("TCheckbutton", background=self._CARD, foreground=self._TEXT, font=self._FONT)
        style.map("TCheckbutton", background=[("active", self._CARD)])

        style.configure(
            "TButton",
            font=self._FONT,
            padding=(10, 5),
            background="#FFFFFF",
            foreground=self._TEXT,
            bordercolor=self._BORDER,
            lightcolor=self._BORDER,
            darkcolor=self._BORDER,
            focuscolor=self._ACCENT,
        )
        style.map(
            "TButton",
            background=[("active", "#F8FAFC"), ("pressed", "#E2E8F0")],
            bordercolor=[("active", self._ACCENT)],
        )
        style.configure(
            "Accent.TButton",
            font=self._FONT_BOLD,
            padding=(10, 4),
            background=self._ACCENT,
            foreground="#FFFFFF",
            bordercolor=self._ACCENT,
            lightcolor=self._ACCENT,
            darkcolor=self._ACCENT,
            focuscolor=self._ACCENT_HOVER,
        )
        style.map(
            "Accent.TButton",
            background=[("active", self._ACCENT_HOVER), ("pressed", "#115E59")],
            foreground=[("active", "#FFFFFF"), ("disabled", "#94A3B8")],
            bordercolor=[("active", self._ACCENT_HOVER)],
        )
        style.configure(
            "Flash.TButton",
            font=self._FONT_BOLD,
            padding=(12, 6),
            background="#0F766E",
            foreground="#FFFFFF",
            bordercolor="#0F766E",
            lightcolor="#0F766E",
            darkcolor="#0F766E",
            focuscolor=self._ACCENT_HOVER,
        )
        style.map(
            "Flash.TButton",
            background=[("active", "#0D9488"), ("pressed", "#115E59")],
            foreground=[("active", "#FFFFFF")],
            bordercolor=[("active", "#0D9488")],
        )
        style.configure(
            "Danger.TButton",
            font=self._FONT,
            padding=(10, 5),
            background="#FFFFFF",
            foreground=self._DANGER,
            bordercolor="#FECACA",
            lightcolor="#FECACA",
            darkcolor="#FECACA",
        )
        style.map(
            "Danger.TButton",
            background=[("active", "#FEF2F2"), ("pressed", "#FEE2E2")],
            bordercolor=[("active", self._DANGER)],
        )
        style.configure(
            "Ghost.TButton",
            font=self._FONT,
            padding=(8, 4),
            background=self._CARD,
            foreground=self._MUTED,
            bordercolor=self._BORDER,
        )
        style.map("Ghost.TButton", background=[("active", self._LOG_BG)])

    def _clip_target(self) -> tk.Misc | None:
        w = self.focus_get()
        if w is None:
            return None
        cls = w.winfo_class()
        if cls in {"Entry", "TEntry", "TCombobox", "Text"}:
            return w
        return None

    def _clip_action(self, action: str) -> None:
        w = self._clip_target()
        if w is None:
            return
        event = tk.Event()
        event.widget = w
        if action == "cut":
            self._clip_cut(event)
        elif action == "copy":
            self._clip_copy(event)
        elif action == "paste":
            self._clip_paste(event)
        elif action == "select_all":
            self._clip_select_all(event)

    def _clip_copy(self, event) -> str:
        w = event.widget
        try:
            if w.winfo_class() == "Text":
                try:
                    text = w.get("sel.first", "sel.last")
                except tk.TclError:
                    text = w.get("1.0", "end-1c")
            else:
                text = w.selection_get()
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
        except tk.TclError:
            pass
        return "break"

    def _clip_cut(self, event) -> str:
        self._clip_copy(event)
        w = event.widget
        try:
            if w.winfo_class() == "Text":
                w.delete("sel.first", "sel.last")
            else:
                w.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        return "break"

    def _clip_paste(self, event) -> str:
        w = event.widget
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return "break"
        try:
            if w.winfo_class() == "Text":
                try:
                    w.delete("sel.first", "sel.last")
                except tk.TclError:
                    pass
                w.insert("insert", text)
            else:
                try:
                    w.delete("sel.first", "sel.last")
                except tk.TclError:
                    pass
                w.insert("insert", text)
        except tk.TclError:
            pass
        return "break"

    def _clip_select_all(self, event) -> str:
        w = event.widget
        try:
            if w.winfo_class() == "Text":
                w.tag_add("sel", "1.0", "end-1c")
                w.mark_set("insert", "1.0")
                w.see("insert")
            else:
                w.selection_range(0, "end")
                w.icursor("end")
        except tk.TclError:
            pass
        return "break"

    def _show_clip_menu(self, event) -> None:
        try:
            event.widget.focus_set()
            self._clip_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._clip_menu.grab_release()

    def _bind_clipboard_widget(self, w: tk.Misc) -> None:
        for seq, handler in (
            ("<Control-c>", self._clip_copy),
            ("<Control-C>", self._clip_copy),
            ("<Control-Key-c>", self._clip_copy),
            ("<Control-Key-C>", self._clip_copy),
            ("<Control-Insert>", self._clip_copy),
            ("<Control-x>", self._clip_cut),
            ("<Control-X>", self._clip_cut),
            ("<Control-Key-x>", self._clip_cut),
            ("<Shift-Delete>", self._clip_cut),
            ("<Control-v>", self._clip_paste),
            ("<Control-V>", self._clip_paste),
            ("<Control-Key-v>", self._clip_paste),
            ("<Control-Key-V>", self._clip_paste),
            ("<Shift-Insert>", self._clip_paste),
            ("<Control-a>", self._clip_select_all),
            ("<Control-A>", self._clip_select_all),
            ("<Control-Key-a>", self._clip_select_all),
            ("<Control-Key-A>", self._clip_select_all),
        ):
            w.bind(seq, handler)
        w.bind("<Button-3>", self._show_clip_menu)

    def _copy_log_all(self) -> None:
        try:
            text = self.txt.get("1.0", "end-1c")
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
            self.log("Log copied to clipboard.")
        except tk.TclError as exc:
            self.log(f"Copy log failed: {exc}")

    def _clear_log(self) -> None:
        try:
            self.txt.delete("1.0", tk.END)
        except tk.TclError:
            pass
        self.log("Log cleared.")

    def _copy_esp_log(self) -> None:
        try:
            text = self.txt_esp.get("1.0", "end-1c")
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
            self.log("ESP32 log copied to clipboard.")
        except tk.TclError as exc:
            self.log(f"Copy ESP32 log failed: {exc}")

    def _clear_esp_log(self) -> None:
        try:
            self.txt_esp.delete("1.0", tk.END)
        except tk.TclError:
            pass

    def _copy_api_log(self) -> None:
        try:
            text = self.txt_api.get("1.0", "end-1c")
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
            self.log("API activity copied to clipboard.")
        except tk.TclError as exc:
            self.log(f"Copy API log failed: {exc}")

    def _clear_api_log(self) -> None:
        try:
            self.txt_api.delete("1.0", tk.END)
        except tk.TclError:
            pass

    def _api_log(self, msg: str) -> None:
        self._api_log_q.put(msg)

    def _drain_api_log(self) -> None:
        while True:
            try:
                msg = self._api_log_q.get_nowait()
            except queue.Empty:
                break
            self.txt_api.insert(tk.END, msg if msg.endswith("\n") else msg + "\n")
            self.txt_api.see(tk.END)
        self.after(120, self._drain_api_log)

    def _esp_log(self, msg: str) -> None:
        self._esp_log_q.put(msg)

    def _drain_esp_log(self) -> None:
        while True:
            try:
                msg = self._esp_log_q.get_nowait()
            except queue.Empty:
                break
            self.txt_esp.insert(tk.END, msg)
            if not msg.endswith("\n"):
                self.txt_esp.insert(tk.END, "\n")
            self.txt_esp.see(tk.END)
        self.after(120, self._drain_esp_log)

    def _set_esp_monitor_ui(self, running: bool, detail: str = "") -> None:
        self._esp_monitor_on = running
        if hasattr(self, "btn_esp_start"):
            state_start = tk.DISABLED if running else tk.NORMAL
            state_stop = tk.NORMAL if running else tk.DISABLED
            self.btn_esp_start.configure(state=state_start)
            self.btn_esp_stop.configure(state=state_stop)
        if hasattr(self, "lbl_esp_mon"):
            if running:
                self.lbl_esp_mon.configure(text=detail or "listening…")
            else:
                self.lbl_esp_mon.configure(text=detail or "stopped")

    def stop_esp_monitor(self, note: str | None = None) -> None:
        self._esp_reader_stop.set()
        ser = self._esp_ser
        self._esp_ser = None
        if ser is not None:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass
        self._set_esp_monitor_ui(False, note or "stopped")
        if note:
            self.log(note)

    def start_esp_monitor(self) -> None:
        if self._esp_monitor_on:
            self.log("ESP32 serial monitor already running.")
            return
        svc = self._service_state()
        if "RUNNING" in svc.upper():
            if not messagebox.askyesno(
                "ESP32 serial",
                "PLCBridge Service is RUNNING and usually holds the COM port.\n\n"
                "Stop the service and open ESP32 serial monitor?",
            ):
                return
            try:
                subprocess.run(
                    ["sc", "stop", "PLCBridge"],
                    capture_output=True,
                    text=True,
                    check=False,
                    creationflags=_create_no_window(),
                )
            except OSError as exc:
                self.log(f"Could not stop service: {exc}")
            time.sleep(1.0)

        port = self._esp_port()
        if not port:
            messagebox.showwarning("ESP32 serial", "ESP32 COM port not found. Plug USB or set COM Port.")
            return

        import serial

        self.stop_esp_monitor()
        self._esp_reader_stop.clear()
        try:
            ser = serial.Serial(
                port=port,
                baudrate=115200,
                timeout=0.25,
                write_timeout=1,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "ESP32 serial",
                f"Cannot open {port}:\n{exc}\n\nStop Bridge Service / close other serial tools first.",
            )
            return

        self._esp_ser = ser
        self._set_esp_monitor_ui(True, f"listening {port} @115200")
        self.log(f"ESP32 serial monitor started on {port}")
        self._esp_log(f"--- opened {port} @115200 ---\n")

        def reader() -> None:
            buf = ""
            try:
                while not self._esp_reader_stop.is_set():
                    try:
                        chunk = ser.read(256)
                    except Exception as exc:  # noqa: BLE001
                        self._esp_log(f"[serial error] {exc}\n")
                        break
                    if not chunk:
                        continue
                    try:
                        text = chunk.decode("utf-8", errors="replace")
                    except Exception:  # noqa: BLE001
                        text = repr(chunk)
                    buf += text
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        self._esp_log(line.rstrip("\r") + "\n")
                if buf.strip():
                    self._esp_log(buf)
            finally:
                try:
                    ser.close()
                except Exception:  # noqa: BLE001
                    pass
                if self._esp_ser is ser:
                    self._esp_ser = None
                self.after(0, lambda: self._set_esp_monitor_ui(False, "stopped"))

        threading.Thread(target=reader, daemon=True, name="esp-serial").start()

    def _on_close(self) -> None:
        try:
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        self.destroy()

    def _enable_clipboard(self, root: tk.Misc) -> None:
        editable = {"Entry", "TEntry", "TCombobox", "Text"}

        def walk(w: tk.Misc) -> None:
            if w.winfo_class() in editable:
                self._bind_clipboard_widget(w)
            for child in w.winfo_children():
                walk(child)

        walk(root)
        for cls_name in ("Text", "Entry", "TEntry", "TCombobox"):
            self.bind_class(cls_name, "<Control-c>", self._clip_copy)
            self.bind_class(cls_name, "<Control-v>", self._clip_paste)
            self.bind_class(cls_name, "<Control-x>", self._clip_cut)
            self.bind_class(cls_name, "<Control-a>", self._clip_select_all)

    def _style_text(self, widget: tk.Text) -> None:
        widget.configure(
            font=self._FONT_MONO,
            background=self._LOG_BG,
            foreground=self._TEXT,
            insertbackground=self._TEXT,
            relief=tk.FLAT,
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=self._BORDER,
            highlightcolor=self._ACCENT,
            padx=4,
            pady=2,
        )

    def _pair(
        self,
        parent: ttk.Frame,
        row: int,
        col: int,
        label: str,
        widget: tk.Misc,
    ) -> None:
        base = col * 2
        ttk.Label(parent, text=label, style='Field.TLabel').grid(
            row=row, column=base, sticky=tk.W, padx=(0, 6), pady=1
        )
        widget.grid(row=row, column=base + 1, sticky=tk.EW, padx=(0, 10), pady=1)

    def _on_root_wheel(self, event):
        widget = event.widget
        try:
            w = widget
            while w is not None:
                if w.winfo_class() == "Text":
                    return
                parent = w.winfo_parent()
                w = w.nametowidget(parent) if parent else None
        except (tk.TclError, KeyError):
            pass
        delta = int(-event.delta / 120) if getattr(event, "delta", 0) else 0
        if delta:
            self._root_canvas.yview_scroll(delta, "units")
        return "break"

    def _build(self) -> None:
        shell = ttk.Frame(self)
        shell.pack(fill=tk.BOTH, expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        self._root_canvas = tk.Canvas(shell, highlightthickness=0, bg=self._BG, bd=0)
        vsb = ttk.Scrollbar(shell, orient=tk.VERTICAL, command=self._root_canvas.yview)
        self._root_canvas.configure(yscrollcommand=vsb.set)
        self._root_canvas.grid(row=0, column=0, sticky=tk.NSEW)
        vsb.grid(row=0, column=1, sticky=tk.NS)

        frm = ttk.Frame(self._root_canvas, padding=(6, 4, 8, 8))
        self._root_win = self._root_canvas.create_window((0, 0), window=frm, anchor=tk.NW)

        def on_frm_cfg(_event=None) -> None:
            self._root_canvas.configure(scrollregion=self._root_canvas.bbox("all"))

        def on_can_cfg(event) -> None:
            self._root_canvas.itemconfigure(self._root_win, width=max(event.width, 1))

        frm.bind("<Configure>", on_frm_cfg)
        self._root_canvas.bind("<Configure>", on_can_cfg)

        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(4, weight=1)

        header = ttk.Frame(frm)
        header.grid(row=0, column=0, sticky=tk.EW, pady=(0, 4))
        ttk.Label(header, text='PLCBridge Setup', style='Title.TLabel').pack(side=tk.LEFT)
        ttk.Label(
            header,
            text='  ·  ESP32 · SQL Server (WinCC) · Service',
            style='Subtitle.TLabel',
        ).pack(side=tk.LEFT, pady=2)

        status = ttk.LabelFrame(frm, text=' Live status (auto-refresh) ', padding=(6, 4))
        status.grid(row=1, column=0, sticky=tk.EW, pady=(0, 4))
        status_grid = ttk.Frame(status, style='Card.TFrame')
        status_grid.pack(fill=tk.X)
        for c in range(4):
            status_grid.columnconfigure(c, weight=1)

        def status_cell(parent: ttk.Frame, r: int, c: int, key: str) -> ttk.Label:
            cell = ttk.Frame(parent, style='Card.TFrame', padding=(2, 0))
            cell.grid(row=r, column=c, sticky=tk.EW, padx=2, pady=0)
            ttk.Label(cell, text=key, style='StatusKey.TLabel').pack(anchor=tk.W)
            val = ttk.Label(cell, text='…', style='StatusVal.TLabel', wraplength=220)
            val.pack(anchor=tk.W)
            return val

        self.lbl_esp = status_cell(status_grid, 0, 0, 'ESP32 USB')
        self.lbl_wifi = status_cell(status_grid, 0, 1, 'PC Wi-Fi')
        self.lbl_api_target = status_cell(status_grid, 0, 2, 'Target API (from PC)')
        self.lbl_svc = status_cell(status_grid, 0, 3, 'Bridge Service')
        self.lbl_api = status_cell(status_grid, 1, 0, 'Mock API listener')
        self.lbl_ui_boot = status_cell(status_grid, 1, 1, 'UI at login')
        self.lbl_live = status_cell(status_grid, 1, 2, 'Watch')
        self.lbl_live.configure(text='every 4s · changes → App Log')

        db_box = ttk.Frame(status, style='Card.TFrame')
        db_box.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        ttk.Label(db_box, text='Database (scroll)', style='StatusKey.TLabel').pack(anchor=tk.W)
        self.txt_db = scrolledtext.ScrolledText(db_box, height=7, wrap=tk.WORD)
        self._style_text(self.txt_db)
        self.txt_db.pack(fill=tk.BOTH, expand=True)
        self.txt_db.insert('1.0', 'Click Check DB — same as SSMS: Windows Authentication, no password.')
        self.txt_db.configure(state=tk.DISABLED)


        cfg = ttk.LabelFrame(frm, text=' Settings ', padding=(6, 4))
        cfg.grid(row=2, column=0, sticky=tk.EW, pady=(0, 4))
        grid = ttk.Frame(cfg, style='Card.TFrame')
        grid.pack(fill=tk.X)
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)

        self.var_ssid = tk.StringVar()
        self.var_wifi_pass = tk.StringVar()
        self.var_show_wifi_pass = tk.BooleanVar(value=False)
        self.var_show_db_pass = tk.BooleanVar(value=False)
        self.var_api = tk.StringVar(value=default_api_url())
        self.var_token = tk.StringVar(value='lab-token')
        self.var_port = tk.StringVar(value='auto')
        self.var_engine = tk.StringVar(value=ENGINE_LABELS['sqlserver'])
        self.var_auth = tk.StringVar(value=AUTH_LABELS['windows'])
        self.var_db_host = tk.StringVar(value=wincc_ssms_host())
        self.var_db_port = tk.StringVar(value='0')
        self.var_db_name = tk.StringVar(value='auto')
        self.var_db_user = tk.StringVar(value='')
        self.var_db_pass = tk.StringVar(value='')
        self.var_db_query = tk.StringVar(value=WINCC_QUERY)
        self.var_id_column = tk.StringVar(value='id')
        self._wifi_items: list[dict] = []
        self._ssid_by_display: dict[str, str] = {}

        ssid_row = ttk.Frame(grid, style='Card.TFrame')
        self.cmb_ssid = ttk.Combobox(ssid_row, textvariable=self.var_ssid, width=18)
        self.cmb_ssid.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.cmb_ssid.bind('<<ComboboxSelected>>', self._on_ssid_selected)
        self.cmb_ssid.bind('<FocusOut>', lambda _e: self._fill_password_for_current_ssid())
        ttk.Button(ssid_row, text='Scan', width=6, command=self.scan_wifi).pack(side=tk.LEFT, padx=(4, 0))
        self._pair(grid, 0, 0, 'Wi-Fi SSID', ssid_row)
        self._pair(grid, 0, 1, 'COM Port', ttk.Entry(grid, textvariable=self.var_port, width=12))

        pass_row = ttk.Frame(grid, style='Card.TFrame')
        self.ent_wifi_pass = ttk.Entry(pass_row, textvariable=self.var_wifi_pass, show='*')
        self.ent_wifi_pass.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Checkbutton(
            pass_row, text='Show', variable=self.var_show_wifi_pass, command=self._toggle_wifi_pass
        ).pack(side=tk.LEFT, padx=(4, 0))
        self._pair(grid, 1, 0, 'Wi-Fi Pass', pass_row)
        self.cmb_engine = ttk.Combobox(
            grid,
            textvariable=self.var_engine,
            values=list(ENGINE_LABELS.values()),
            state='readonly',
            width=22,
        )
        self.cmb_engine.bind('<<ComboboxSelected>>', self._on_engine_selected)
        self._pair(grid, 1, 1, 'Engine', self.cmb_engine)

        self._pair(grid, 2, 0, 'API URL', ttk.Entry(grid, textvariable=self.var_api))
        self.cmb_auth = ttk.Combobox(
            grid,
            textvariable=self.var_auth,
            values=list(AUTH_LABELS.values()),
            state='readonly',
            width=22,
        )
        self.cmb_auth.bind('<<ComboboxSelected>>', lambda _e: self._toggle_auth_fields())
        self._pair(grid, 2, 1, 'Auth', self.cmb_auth)

        self._pair(grid, 3, 0, 'API Token', ttk.Entry(grid, textvariable=self.var_token, show='*'))
        self._pair(grid, 3, 1, 'Host', ttk.Entry(grid, textvariable=self.var_db_host))

        self._pair(grid, 4, 0, 'ID column', ttk.Entry(grid, textvariable=self.var_id_column, width=12))
        self._pair(grid, 4, 1, 'Port', ttk.Entry(grid, textvariable=self.var_db_port, width=12))

        self._pair(grid, 5, 0, 'Database', ttk.Entry(grid, textvariable=self.var_db_name))
        self.ent_db_user = ttk.Entry(grid, textvariable=self.var_db_user)
        self._pair(grid, 5, 1, 'User', self.ent_db_user)

        db_pass_row = ttk.Frame(grid, style='Card.TFrame')
        self.ent_db_pass = ttk.Entry(db_pass_row, textvariable=self.var_db_pass, show='*')
        self.ent_db_pass.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Checkbutton(
            db_pass_row, text='Show', variable=self.var_show_db_pass, command=self._toggle_db_pass
        ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(grid, text='Password', style='Field.TLabel').grid(
            row=6, column=0, sticky=tk.W, padx=(0, 6), pady=1
        )
        db_pass_row.grid(row=6, column=1, columnspan=3, sticky=tk.EW, pady=1)

        ttk.Label(grid, text='Query', style='Field.TLabel').grid(
            row=7, column=0, sticky=tk.NW, padx=(0, 6), pady=1
        )
        self.txt_query = tk.Text(grid, height=3, wrap=tk.WORD)
        self._style_text(self.txt_query)
        self.txt_query.grid(row=7, column=1, columnspan=3, sticky=tk.EW, pady=1)
        self.txt_query.insert('1.0', self.var_db_query.get())

        actions = ttk.LabelFrame(frm, text=' Actions ', padding=(6, 4))
        actions.grid(row=3, column=0, sticky=tk.EW, pady=(0, 4))

        row1 = ttk.Frame(actions, style='Card.TFrame')
        row1.pack(fill=tk.X, pady=(0, 2))
        for text_btn, cmd in (
            ('Refresh', self.refresh_status),
            ('Scan Wi-Fi', self.scan_wifi),
            ('Check DB', self.check_db),
            ('WinCC factory', self.apply_wincc_defaults),
            ('Start', self.start_service),
            ('Stop', self.stop_service),
        ):
            btn_style = 'Danger.TButton' if text_btn == 'Stop' else 'TButton'
            ttk.Button(row1, text=text_btn, style=btn_style, command=cmd).pack(side=tk.LEFT, padx=(0, 3))
        self.btn_mock_api = ttk.Button(row1, text='Mock API: OFF', command=self.toggle_mock_api)
        self.btn_mock_api.pack(side=tk.LEFT, padx=(0, 3))

        row2 = ttk.Frame(actions, style='Card.TFrame')
        row2.pack(fill=tk.X)
        ttk.Button(row2, text='Install All', command=self.install_all).pack(
            side=tk.LEFT, padx=(0, 3)
        )
        ttk.Button(
            row2, text='FLASH ESP32 NOW', style='Flash.TButton', command=self.setup_esp
        ).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(
            row2, text='Install Service', command=self.install_service
        ).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(
            row2, text='Uninstall', style='Danger.TButton', command=self.uninstall_service
        ).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(row2, text='UI at login', command=self.enable_ui_at_login).pack(
            side=tk.LEFT, padx=(0, 3)
        )
        ttk.Button(row2, text='Hide UI login', command=self.disable_ui_at_login).pack(side=tk.LEFT)

        log_panes = ttk.Panedwindow(frm, orient=tk.HORIZONTAL)
        log_panes.grid(row=4, column=0, sticky=tk.NSEW)

        def make_log_pane(title: str, hint: str):
            box = ttk.LabelFrame(log_panes, text=title, padding=(6, 4))
            box.rowconfigure(1, weight=1)
            box.columnconfigure(0, weight=1)
            bar = ttk.Frame(box, style='Card.TFrame')
            bar.grid(row=0, column=0, sticky=tk.EW, pady=(0, 3))
            txt = scrolledtext.ScrolledText(box, height=8, wrap=tk.WORD)
            self._style_text(txt)
            txt.grid(row=1, column=0, sticky=tk.NSEW)
            return box, bar, txt, hint

        log_box, log_bar, self.txt, _ = make_log_pane(' App Log ', '')
        ttk.Button(log_bar, text='Copy', style='Ghost.TButton', command=self._copy_log_all).pack(
            side=tk.LEFT
        )
        ttk.Button(log_bar, text='Clear', style='Ghost.TButton', command=self._clear_log).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        ttk.Label(log_bar, text='Setup · status changes · Bridge file', style='Muted.TLabel').pack(
            side=tk.LEFT, padx=8
        )

        api_box, api_bar, self.txt_api, _ = make_log_pane(' API Activity ', '')
        ttk.Button(api_bar, text='Copy', style='Ghost.TButton', command=self._copy_api_log).pack(
            side=tk.LEFT
        )
        ttk.Button(api_bar, text='Clear', style='Ghost.TButton', command=self._clear_api_log).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        ttk.Button(api_bar, text='Probe API', command=self.probe_target_api).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Label(api_bar, text='Mock POSTs · reachability', style='Muted.TLabel').pack(
            side=tk.LEFT, padx=8
        )

        esp_box = ttk.LabelFrame(log_panes, text=' ESP32 Serial ', padding=(6, 4))
        esp_box.rowconfigure(1, weight=1)
        esp_box.columnconfigure(0, weight=1)
        esp_bar = ttk.Frame(esp_box, style='Card.TFrame')
        esp_bar.grid(row=0, column=0, sticky=tk.EW, pady=(0, 3))
        self.btn_esp_start = ttk.Button(
            esp_bar, text='Start', style='Accent.TButton', command=self.start_esp_monitor
        )
        self.btn_esp_start.pack(side=tk.LEFT)
        self.btn_esp_stop = ttk.Button(
            esp_bar, text='Stop', style='Danger.TButton', command=lambda: self.stop_esp_monitor()
        )
        self.btn_esp_stop.pack(side=tk.LEFT, padx=(4, 0))
        self.btn_esp_stop.configure(state=tk.DISABLED)
        ttk.Button(esp_bar, text='Copy', style='Ghost.TButton', command=self._copy_esp_log).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(esp_bar, text='Clear', style='Ghost.TButton', command=self._clear_esp_log).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        self.lbl_esp_mon = ttk.Label(esp_bar, text='stopped', style='Muted.TLabel')
        self.lbl_esp_mon.pack(side=tk.LEFT, padx=8)
        self.txt_esp = scrolledtext.ScrolledText(esp_box, height=8, wrap=tk.WORD)
        self._style_text(self.txt_esp)
        self.txt_esp.grid(row=1, column=0, sticky=tk.NSEW)

        log_panes.add(log_box, weight=1)
        log_panes.add(api_box, weight=1)
        log_panes.add(esp_box, weight=1)

        self._toggle_auth_fields()
        self.after(100, self.scan_wifi)
        self.bind_all("<MouseWheel>", self._on_root_wheel)

    def _toggle_wifi_pass(self) -> None:
        self.ent_wifi_pass.configure(show="" if self.var_show_wifi_pass.get() else "*")

    def _toggle_db_pass(self) -> None:
        self.ent_db_pass.configure(show="" if self.var_show_db_pass.get() else "*")

    def _engine_value(self) -> str:
        return _engine_key(self.var_engine.get())

    def _auth_value(self) -> str:
        return _auth_key(self.var_auth.get())

    def _toggle_auth_fields(self) -> None:
        windows = self._auth_value() == "windows"
        state = tk.DISABLED if windows else tk.NORMAL
        self.ent_db_user.configure(state=state)
        self.ent_db_pass.configure(state=state)

    def _on_engine_selected(self, _event=None) -> None:
        self.var_engine.set(ENGINE_LABELS["sqlserver"])
        self._toggle_auth_fields()

    def apply_wincc_defaults(self) -> None:
        host = wincc_ssms_host()
        self.var_engine.set(ENGINE_LABELS["sqlserver"])
        self.var_auth.set(AUTH_LABELS["windows"])
        self.var_db_host.set(host)
        self.var_db_port.set("0")
        self.var_db_name.set("auto")
        self.var_db_user.set("")
        self.var_db_pass.set("")
        self.var_id_column.set("id")
        self._set_query(WINCC_QUERY)
        self._toggle_auth_fields()
        self.log(
            f"SSMS connection: Server={host}  Authentication=Windows  "
            "User=this Windows account  Password=none  database=auto (latest TLG_F)."
        )
        self.check_db()

    def check_db(self) -> None:
        """Probe SQL Server like SSMS (Windows auth, no password) and show the result."""
        self.var_auth.set(AUTH_LABELS["windows"])
        if not self.var_db_host.get().strip():
            self.var_db_host.set(wincc_ssms_host())
        self.var_db_user.set("")
        self.var_db_pass.set("")
        self._toggle_auth_fields()
        name = self.var_db_name.get().strip()
        if name.upper().startswith("CC_"):
            self.log(
                f"Database '{name}' is a WinCC CS/RT catalog, not Tag Logging. "
                "Switching to auto (newest TLG_F) so flow values can be read."
            )
            self.var_db_name.set("auto")
        self.refresh_status(silent=False)
        mysql_txt = self._status_snapshot.get("Database") or ""
        if mysql_txt.startswith("OK"):
            pd = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "PLCBridge" / "config" / "config.ini"
            try:
                self._write_bridge_config(pd)
                self.log(f"Saved for the Windows service: {pd}")
            except OSError as exc:
                self.log(f"Could not save service config: {exc}")
        else:
            self.log("Check DB failed. Confirm SSMS opens with Windows Authentication on this PC.")

    def _set_query(self, query: str) -> None:
        self.txt_query.delete("1.0", tk.END)
        self.txt_query.insert("1.0", query)

    def _selected_ssid(self) -> str:
        raw = self.var_ssid.get().strip()
        return self._ssid_by_display.get(raw, raw.split("  (")[0].strip())

    def _on_ssid_selected(self, _event=None) -> None:
        ssid = self._selected_ssid()
        self.var_ssid.set(ssid)
        self._fill_password_for_current_ssid()

    def _fill_password_for_current_ssid(self) -> None:
        ssid = self._selected_ssid()
        if not ssid:
            return
        pwd = wifi_password_for(ssid)
        if pwd:
            if self.var_wifi_pass.get() != pwd:
                self.var_wifi_pass.set(pwd)
                self.log(f"Wi-Fi password loaded from Windows profile: {ssid}")
            else:
                self.var_wifi_pass.set(pwd)
        else:
            if not self.var_wifi_pass.get():
                self.log(f"No saved password for '{ssid}' (enter manually if needed).")

    def scan_wifi(self) -> None:
        def run() -> None:
            self.log("Scanning Wi-Fi…")
            try:
                items = scan_wifi_networks()
                current = wifi_status().get("ssid") or ""

                def apply() -> None:
                    self._wifi_items = items
                    displays = []
                    self._ssid_by_display = {}
                    for item in items:
                        label = ssid_display(item)
                        displays.append(label)
                        self._ssid_by_display[label] = item["ssid"]
                        self._ssid_by_display[item["ssid"]] = item["ssid"]
                    self.cmb_ssid["values"] = displays
                    chosen = self._selected_ssid() or current
                    if chosen:
                        self.var_ssid.set(chosen)
                        self._fill_password_for_current_ssid()
                    visible = sum(1 for i in items if i.get("visible"))
                    saved = sum(1 for i in items if i.get("saved"))
                    self.log(f"Wi-Fi list: {visible} visible, {saved} saved profiles.")

                self.after(0, apply)
            except Exception as exc:  # noqa: BLE001
                self.log(f"Wi-Fi scan failed: {exc}")

        self._worker(run)

    def log(self, msg: str) -> None:
        self._log_q.put(msg)

    def _drain_log(self) -> None:
        while True:
            try:
                msg = self._log_q.get_nowait()
            except queue.Empty:
                break
            self.txt.insert(tk.END, msg + "\n")
            self.txt.see(tk.END)
        self.after(200, self._drain_log)

    def _worker(self, fn) -> None:
        threading.Thread(target=fn, daemon=True).start()

    def _esp_port(self) -> str | None:
        port = self.var_port.get().strip()
        if port and port.lower() != "auto":
            return port
        esp = next((p for p in list_esp_ports() if p["is_esp"]), None)
        return esp["device"] if esp else None

    def _service_state(self) -> str:
        try:
            out = subprocess.check_output(
                ["sc", "query", "PLCBridge"],
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_create_no_window(),
            )
        except subprocess.CalledProcessError:
            return "not installed"

        state = "installed"
        for line in out.splitlines():
            upper = line.upper()
            if "RUNNING" in upper:
                return "RUNNING (auto-start)"
            if "STOPPED" in upper:
                state = "STOPPED (installed)"
            if "START_PENDING" in upper:
                return "STARTING…"
            if "STOP_PENDING" in upper:
                return "STOPPING…"
        return state

    def _paint_status(self, label: ttk.Label, text: str, kind: str = "val") -> None:
        style = {"ok": "Ok.TLabel", "bad": "Bad.TLabel", "warn": "Warn.TLabel"}.get(kind, "StatusVal.TLabel")
        label.configure(text=text, style=style)

    def _paint_db_status(self, text: str, kind: str = "val") -> None:
        colors = {"ok": self._OK, "bad": self._BAD, "warn": "#B45309"}
        self.txt_db.configure(state=tk.NORMAL)
        self.txt_db.delete("1.0", tk.END)
        self.txt_db.insert("1.0", text.replace(" | ", "\n"))
        self.txt_db.configure(fg=colors.get(kind, self._TEXT), state=tk.DISABLED)
        self.txt_db.see("1.0")

    def _note_change(self, key: str, value: str, silent: bool) -> None:
        prev = self._status_snapshot.get(key)
        self._status_snapshot[key] = value
        if silent and prev is not None and prev != value:
            self.log(f"[{_ts()}] STATUS {key}: {prev} → {value}")

    def _bridge_log_candidates(self) -> list[Path]:
        paths = [
            Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "PLCBridge" / "logs" / "plcbridge.log",
            ROOT / "logs" / "plcbridge.log",
            ROOT / "logs" / "plcbridge-lab.log",
            ROOT / "dist" / "logs" / "plcbridge.log",
        ]
        seen: set[str] = set()
        out: list[Path] = []
        for p in paths:
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out

    def _tail_bridge_logs(self) -> None:
        for path in self._bridge_log_candidates():
            if not path.is_file():
                continue
            key = str(path)
            try:
                size = path.stat().st_size
                first = key not in self._bridge_log_pos
                pos = self._bridge_log_pos.get(key, max(0, size - 4096) if first else size)
                if size < pos:
                    pos = 0
                if size == pos:
                    self._bridge_log_pos[key] = size
                    continue
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(pos)
                    chunk = fh.read()
                    self._bridge_log_pos[key] = fh.tell()
                if not chunk.strip():
                    continue
                if first:
                    lines = chunk.splitlines()[-12:]
                    self.log(f"[{_ts()}] Bridge log ← {path.name}")
                    for line in lines:
                        self.log(line)
                else:
                    for line in chunk.splitlines():
                        if line.strip():
                            self.log(f"[bridge] {line}")
            except OSError:
                continue

    def _live_tick(self) -> None:
        if not self._live_busy:
            self._live_busy = True
            try:
                self.refresh_status(silent=True)
                self._tail_bridge_logs()
            except Exception as exc:  # noqa: BLE001
                self.log(f"Live watch error: {exc}")
            finally:
                self._live_busy = False
        self.after(4000, self._live_tick)

    def probe_target_api(self) -> None:
        url = self.var_api.get().strip()

        def run() -> None:
            ok, detail = probe_api_url(url)
            msg = f"[{_ts()}] Target API probe: {detail}  ({url})"
            self._api_log(msg)
            self.log(msg)

            def apply() -> None:
                self._paint_status(self.lbl_api_target, detail, "ok" if ok else "bad")

            self.after(0, apply)

        self._worker(run)

    def refresh_status(self, silent: bool = False) -> None:
        ports = list_esp_ports()
        esp = next((p for p in ports if p["is_esp"]), None)
        if esp:
            esp_txt = f"OK — {esp['device']} ({esp['description']})"
            self._paint_status(self.lbl_esp, esp_txt, "ok")
            if self.var_port.get() in {"", "auto"}:
                self.var_port.set(esp["device"])
        else:
            other = ", ".join(p["device"] for p in ports) or "none"
            esp_txt = f"not found — plug data USB + Refresh (now: {other})"
            self._paint_status(self.lbl_esp, esp_txt, "bad")
        self._note_change("ESP32", esp_txt, silent)

        wifi = wifi_status()
        wifi_txt = f"{wifi['state']} | {wifi['ssid'] or '-'} | {wifi['signal'] or '-'}"
        wifi_ok = "connected" in (wifi.get("state") or "").lower() or bool(wifi.get("ssid"))
        self._paint_status(self.lbl_wifi, wifi_txt, "ok" if wifi_ok else "warn")
        self._note_change("PC-WiFi", wifi_txt, silent)
        if wifi.get("ssid") and not self._selected_ssid():
            self.var_ssid.set(wifi["ssid"])
            self._fill_password_for_current_ssid()

        try:
            port = int(self.var_db_port.get().strip() or "0")
        except ValueError:
            port = 0
        ok, detail = sqlserver_probe(
            self.var_db_host.get().strip() or ".\\WINCC",
            port,
            self.var_db_name.get().strip() or "auto",
            self._auth_value(),
            self.var_db_user.get().strip(),
            self.var_db_pass.get(),
        )
        mysql_txt = f"{'OK' if ok else 'FAIL'} — {detail}"
        self._paint_db_status(mysql_txt, "ok" if ok else "bad")
        self._note_change("Database", mysql_txt, silent)

        api_ok, api_detail = probe_api_url(self.var_api.get().strip())
        self._paint_status(self.lbl_api_target, api_detail, "ok" if api_ok else "bad")
        self._note_change("Target-API", api_detail, silent)

        svc = self._service_state()
        if "RUNNING" in svc.upper():
            svc_kind = "ok"
        elif "STOP" in svc.upper() or "installed" in svc.lower():
            svc_kind = "warn"
        else:
            svc_kind = "bad"
        self._paint_status(self.lbl_svc, svc, svc_kind)
        self._note_change("Service", svc, silent)

        if ui_at_login_enabled():
            boot_txt = f"ON — {startup_shortcut_path().name}"
            self._paint_status(self.lbl_ui_boot, boot_txt, "ok")
        else:
            boot_txt = "OFF"
            self._paint_status(self.lbl_ui_boot, boot_txt, "warn")
        self._note_change("UI-login", boot_txt, silent)

        if self._mock_httpd is not None:
            with _API_HIT_LOCK:
                hits = _API_HIT_COUNT
                last = _API_LAST_HIT or "-"
            mock_txt = f"ON :{MOCK_API_PORT} · hits={hits} · last={last}"
            self._paint_status(self.lbl_api, mock_txt, "ok")
        else:
            mock_txt = "OFF — click Mock API to turn on"
            self._paint_status(self.lbl_api, mock_txt, "warn")
        self._note_change("Mock-API", mock_txt, silent)
        self._sync_mock_api_button()

        mon = "ESP serial ON" if self._esp_monitor_on else "ESP serial off"
        self._paint_status(
            self.lbl_live,
            f"live 4s · {mon}",
            "ok" if self._esp_monitor_on else "val",
        )

        if not silent:
            self.log(f"[{_ts()}] Status refreshed (ESP/SQL Server/API/Service).")
            self._api_log(
                f"[{_ts()}] Snapshot — Mock: {mock_txt} | Target: {api_detail} | SQL Server: {mysql_txt}"
            )

    def _sync_mock_api_button(self) -> None:
        if not hasattr(self, "btn_mock_api"):
            return
        if self._mock_httpd is not None:
            self.btn_mock_api.configure(text="Mock API: ON", style="Accent.TButton")
        else:
            self.btn_mock_api.configure(text="Mock API: OFF", style="TButton")

    def stop_mock_api(self) -> None:
        if self._mock_httpd is None:
            self.log("Mock API is already off.")
            self._sync_mock_api_button()
            self.refresh_status(silent=True)
            return
        httpd = self._mock_httpd
        self._mock_httpd = None

        def shutdown() -> None:
            try:
                httpd.shutdown()
            except Exception:  # noqa: BLE001
                pass
            try:
                httpd.server_close()
            except Exception:  # noqa: BLE001
                pass
            self.after(0, lambda: self._after_mock_stopped())

        threading.Thread(target=shutdown, daemon=True, name="mock-api-stop").start()
        self.log(f"[{_ts()}] Stopping Mock API on :{MOCK_API_PORT}…")

    def _after_mock_stopped(self) -> None:
        self._api_log(f"[{_ts()}] Mock API stopped (:{MOCK_API_PORT})")
        self.log(f"[{_ts()}] Mock API OFF")
        self._sync_mock_api_button()
        self.refresh_status(silent=True)

    def toggle_mock_api(self) -> None:
        if self._mock_httpd is not None:
            self.stop_mock_api()
        else:
            self.start_mock_api()

    def start_mock_api(self) -> None:
        if self._mock_httpd is not None:
            self.log("Mock API already ON — POSTs show in API Activity. Click again to turn OFF.")
            self._sync_mock_api_button()
            self.refresh_status(silent=True)
            return

        # Free leftover console/old Setup listeners so this window owns the port.
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            busy = probe.connect_ex(("127.0.0.1", MOCK_API_PORT)) == 0
            probe.close()
        except OSError:
            busy = False
        if busy:
            for note in free_tcp_port(MOCK_API_PORT):
                self.log(note)
            time.sleep(0.4)

        try:
            self._mock_httpd = start_embedded_mock_api(MOCK_API_PORT)
        except OSError as exc:
            # One more free+retry (race with TIME_WAIT / slow exit).
            for note in free_tcp_port(MOCK_API_PORT):
                self.log(note)
            time.sleep(0.6)
            try:
                self._mock_httpd = start_embedded_mock_api(MOCK_API_PORT)
            except OSError as exc2:
                self.log(f"Mock API failed to bind :{MOCK_API_PORT}: {exc2}")
                self._sync_mock_api_button()
                return

        lan = local_ipv4()
        self.var_api.set(f"http://{lan}:{MOCK_API_PORT}/api/plc-records")
        self.log(f"Mock API ON — listening 0.0.0.0:{MOCK_API_PORT}")
        self.log(f"ESP must POST to http://{lan}:{MOCK_API_PORT}/api/plc-records (same Wi-Fi)")
        self._api_log(f"[{_ts()}] Mock API ON — waiting for ESP POSTs on :{MOCK_API_PORT}")
        self.log("Click Mock API again to turn it OFF.")
        try:
            subprocess.run(
                [
                    "netsh",
                    "advfirewall",
                    "firewall",
                    "add",
                    "rule",
                    "name=PLCBridge Mock API 8089",
                    "dir=in",
                    "action=allow",
                    "protocol=TCP",
                    f"localport={MOCK_API_PORT}",
                ],
                capture_output=True,
                text=True,
                creationflags=_create_no_window(),
                check=False,
            )
        except OSError:
            pass
        self._sync_mock_api_button()
        self.refresh_status()

    def _release_com_for_flash(self) -> None:
        """Service and serial monitor both hold COM and block esptool reset."""
        self.stop_esp_monitor("ESP32 serial monitor stopped for flashing.")
        subprocess.run(
            ["sc", "stop", "PLCBridge"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=_create_no_window(),
        )
        time.sleep(2)

    def setup_esp(self) -> None:
        """Write Wi-Fi + API settings into firmware and flash the board in one step."""
        ssid = self._selected_ssid()
        password = self.var_wifi_pass.get()
        api_url = self.var_api.get().strip()
        pio = find_pio()
        esptool = find_esptool()
        bindir = find_firmware_bin_dir()
        if pio and (not ssid or not password):
            messagebox.showwarning("FLASH ESP32", "Select Wi-Fi SSID and password first (Scan).")
            return
        if not api_url:
            messagebox.showwarning("FLASH ESP32", "API URL is required.")
            return
        if ssid and ("5g" in ssid.lower() or "5ghz" in ssid.lower().replace(" ", "")):
            if not messagebox.askyesno(
                "Wi-Fi band",
                f"SSID '{ssid}' looks like 5GHz.\nESP32 only supports 2.4GHz.\nContinue anyway?",
            ):
                return
        if not pio and not (esptool and bindir):
            messagebox.showerror(
                "FLASH ESP32",
                "No flash tool found.\n\n"
                "On a PC with internet, install PlatformIO and use FLASH ESP32 NOW.\n"
                "On the factory USB pack, keep esptool.exe and firmware-bin\\ next to Setup.",
            )
            return
        port = self._esp_port()
        if not port:
            messagebox.showerror("FLASH ESP32", "ESP32 not found on USB.")
            return

        how = "PlatformIO" if pio else "esptool + firmware-bin"
        if not messagebox.askyesno(
            "FLASH ESP32 NOW",
            f"This WRITES firmware onto the ESP32 on {port}.\n\n"
            f"Tool: {how}\nWi-Fi in bin: Alissss (baked)\nAPI: {api_url}\n\n"
            "1. Click Yes\n"
            "2. Hold the BOOT button on the ESP32\n"
            "3. Keep holding until Connecting... finishes\n"
            "4. Then release BOOT\n\n"
            "The Bridge service will be stopped so COM is free.",
        ):
            return

        self._release_com_for_flash()

        def run() -> None:
            try:
                if pio:
                    path = write_secrets(
                        ssid, password, api_url, self.var_token.get().strip() or "lab-token"
                    )
                    self.log(f"Config written: {path}")
                    self.log(f"Flashing ESP32 on {port} (Wi-Fi={ssid}, API={api_url})…")
                    proc = subprocess.run(
                        [pio, "run", "-t", "upload", "--upload-port", port],
                        cwd=str(ROOT / "firmware"),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    if proc.stdout:
                        self.log(proc.stdout[-1800:])
                    if proc.stderr:
                        self.log(proc.stderr[-1200:])
                    if proc.returncode == 0:
                        self.log(
                            "ESP32 ready: joins Wi-Fi and waits for Bridge serial data → posts to API."
                        )
                        self.log("Tip: click Start on ESP32 Serial panel to watch boot / Wi-Fi logs.")
                    else:
                        self.log(f"FLASH ESP32 failed (code={proc.returncode}).")
                    return
                self.log(
                    f"Flashing prebuilt firmware-bin on {port}. "
                    "HOLD the BOOT button on the ESP32 now until Connecting finishes."
                )
                code, out = flash_prebuilt_firmware(port)
                if out:
                    self.log(out)
                if code == 0:
                    self.log("ESP32 flash OK (prebuilt bin). Click Start to run the Bridge service again.")
                else:
                    self.log(
                        "FLASH ESP32 failed. Hold BOOT on the board, click FLASH ESP32 NOW again, "
                        "release BOOT after Connecting...."
                    )
            except Exception as exc:  # noqa: BLE001
                self.log(f"FLASH ESP32 error: {exc}")

        self._worker(run)

    def _query_text(self) -> str:
        if hasattr(self, "txt_query"):
            return self.txt_query.get("1.0", "end-1c").strip()
        return self.var_db_query.get().strip()

    def _write_bridge_config(self, target: Path) -> None:
        engine = "sqlserver"
        auth = self._auth_value()
        port = self.var_db_port.get().strip() or "0"
        com = self.var_port.get().strip() or "auto"
        query = self._query_text().replace("\r\n", "\n")
        query_ini = "\n        ".join(query.split("\n"))
        host = self.var_db_host.get().strip() or wincc_ssms_host()
        database = self.var_db_name.get().strip() or "auto"
        content = f"""; Generated by PLCBridge Setup
[database]
enabled = true
engine = {engine}
auth = {auth}
host = {host}
port = {port}
database = {database}
username = {self.var_db_user.get().strip()}
password = {self.var_db_pass.get()}
id_column = {self.var_id_column.get().strip() or "id"}
batch_size = 1
connect_timeout_seconds = 5
query = {query_ini}

[serial]
port = {com}
vid_pid = 10C4:EA60
baudrate = 115200
ack_timeout_seconds = 90
reconnect_delay_seconds = 5
startup_delay_seconds = 3

[runtime]
poll_interval_seconds = 30
retry_delay_seconds = 15
state_db = ../data/state.sqlite3

[logging]
file = ../logs/plcbridge.log
level = INFO
max_bytes = 2097152
backup_count = 3
"""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")

    def _validate_install_inputs(self, title: str) -> bool:
        if not resolve_bridge_exe():
            messagebox.showerror(
                title,
                "PLCBridge.exe not found next to this app.\n"
                "Put PLCBridge.exe beside PLCBridgeSetup.exe.",
            )
            return False
        auth = self._auth_value()
        if not self.var_db_host.get().strip():
            messagebox.showwarning(title, "Set SQL Server host (same as SSMS, e.g. CPUPC01\\WINCC), then Check DB.")
            return False
        if auth == "sql" and not self.var_db_user.get().strip():
            messagebox.showwarning(title, "SQL login needs a username, or switch Auth to Windows.")
            return False
        if "%(last_id)s" not in self._query_text():
            messagebox.showwarning(title, "Query must contain %(last_id)s")
            return False
        if "LIMIT" in self._query_text().upper():
            messagebox.showwarning(title, "SQL Server query must use TOP (%(batch_size)s), not LIMIT.")
            return False
        return True

    def _write_install_config(self) -> Path:
        local_cfg = ROOT / "config" / "config.ini"
        local_cfg.parent.mkdir(parents=True, exist_ok=True)
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        self._write_bridge_config(local_cfg)
        return local_cfg

    def _wait_service_state(self, loops: int = 40) -> str:
        state = "not installed"
        for _ in range(loops):
            time.sleep(0.4)
            state = self._service_state()
            if "RUNNING" in state.upper() or "STOPPED" in state.upper():
                break
        return state

    def _log_install_result(self, bat: Path | None) -> None:
        paths = [ROOT / "data" / "install-all-result.txt", ROOT / "data" / "service-install-result.txt"]
        if bat is not None:
            paths.insert(0, bat.parent / "data" / "install-all-result.txt")
        seen: set[str] = set()
        for path in paths:
            key = str(path).lower()
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                self.log(text)

    def _finish_service_install(self, title: str, state: str) -> None:
        ok = "RUNNING" in state.upper() or "STOPPED" in state.upper()
        if ok:
            set_ui_at_login(True)
            self.log("Setup UI at login enabled.")
            self.after(
                0,
                lambda: messagebox.showinfo(
                    title,
                    f"PLCBridge installed successfully.\n\nStatus: {state}\n"
                    "Starts automatically after Windows reboot.",
                ),
            )
        else:
            self.after(
                0,
                lambda: messagebox.showerror(
                    title,
                    "Install did not complete.\n"
                    "If UAC was cancelled, try again and click Yes.",
                ),
            )
        self.after(0, self.refresh_status)

    def install_all(self) -> None:
        """VC++ runtime + CP2102 driver + Windows service, from files next to this EXE."""
        if not self._validate_install_inputs("Install All"):
            return
        bat = find_install_all_bat()
        if not bat:
            messagebox.showerror(
                "Install All",
                "Install-All.bat not found.\nKeep it next to PLCBridgeSetup.exe (USB pack) "
                "or under tools\\ in the repo.",
            )
            return
        if not messagebox.askyesno(
            "Install All",
            "Windows will show a UAC prompt — click Yes.\n\n"
            "This installs everything from this folder (no internet):\n"
            "  • Visual C++ x86 runtime\n"
            "  • CP2102 USB driver\n"
            "  • PLCBridge Windows service (auto-start)\n\n"
            "Continue?",
        ):
            return

        def run() -> None:
            try:
                cfg = self._write_install_config()
                self.log(f"Prepared config: {cfg}")
            except Exception as exc:  # noqa: BLE001
                self.log(f"Config write failed: {exc}")
                self.after(0, lambda: messagebox.showerror("Install All", f"Config write failed:\n{exc}"))
                return
            self.log("Install All: VC++ + CP2102 + service… confirm UAC with Yes.")
            code, out = elevate_and_wait(bat, "/nopause")
            if out.strip():
                self.log(out.strip())
            if code != 0:
                self.log(f"Installer exit {code}")
            self._log_install_result(bat)
            state = self._wait_service_state()
            self.log(f"Service state: {state}")
            self._finish_service_install("Install All", state)

        self._worker(run)

    def install_service(self) -> None:
        if not self._validate_install_inputs("Install Service"):
            return
        if not messagebox.askyesno(
            "Install Service",
            "Windows will show a UAC prompt — click Yes.\n\n"
            "This will fully install/start PLCBridge (boot auto-start + crash restart).\nContinue?",
        ):
            return

        bat = find_install_all_bat()
        script = ROOT / "service" / "install-service.ps1"
        elevate = ROOT / "service" / "elevate-install.ps1"

        def run() -> None:
            try:
                local_cfg = self._write_install_config()
                self.log(f"Prepared config: {local_cfg}")
            except Exception as exc:  # noqa: BLE001
                self.log(f"Config write failed: {exc}")
                self.after(0, lambda: messagebox.showerror("Service", f"Config write failed:\n{exc}"))
                return

            if bat:
                self.log("Installing service… confirm UAC with Yes.")
                code, out = elevate_and_wait(bat, "/nopause /service-only")
                if out.strip():
                    self.log(out.strip())
                if code != 0:
                    self.log(f"Installer exit {code}")
                self._log_install_result(bat)
            elif script.is_file() and elevate.is_file():
                exe = resolve_bridge_exe()
                result_file = ROOT / "data" / "service-install-result.txt"
                if result_file.is_file():
                    result_file.unlink()
                setup_exe = resolve_setup_exe()
                cmd = [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(elevate),
                    "-InstallScript",
                    str(script),
                    "-ExePath",
                    str(exe),
                    "-ConfigSource",
                    str(local_cfg),
                    "-ResultFile",
                    str(result_file),
                ]
                if setup_exe and setup_exe.suffix.lower() == ".exe":
                    cmd.extend(["-SetupExePath", str(setup_exe)])
                self.log("Installing service… confirm UAC with Yes.")
                try:
                    subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                except Exception as exc:  # noqa: BLE001
                    self.log(f"Elevation failed: {exc}")
                    self.after(0, lambda: messagebox.showerror("Service", f"Elevation failed:\n{exc}"))
                    return
                self._log_install_result(None)
            else:
                self.after(
                    0,
                    lambda: messagebox.showerror(
                        "Service",
                        "Missing Install-All.bat and service\\install-service.ps1.",
                    ),
                )
                return

            state = self._wait_service_state()
            self.log(f"Service state: {state}")
            self._finish_service_install("Service", state)

        self._worker(run)

    def uninstall_service(self) -> None:
        bat = find_uninstall_bat()
        script = ROOT / "service" / "remove-service.ps1"
        elevate = ROOT / "service" / "elevate-uninstall.ps1"
        if not bat and (not script.is_file() or not elevate.is_file()):
            messagebox.showerror("Uninstall", "Missing Uninstall-Service.bat and service\\remove-service.ps1.")
            return

        if self._service_state().lower().startswith("not installed"):
            messagebox.showinfo("Uninstall", "Service is not installed.")
            return

        if not messagebox.askyesno(
            "Uninstall Service",
            "Windows will show a UAC prompt — click Yes.\n\n"
            "This stops and removes the PLCBridge Windows service.\n"
            "Config/state/logs are kept so you can Install again.\nContinue?",
        ):
            return

        def run() -> None:
            result_file = ROOT / "data" / "service-uninstall-result.txt"
            (ROOT / "data").mkdir(parents=True, exist_ok=True)
            if result_file.is_file():
                try:
                    result_file.unlink()
                except OSError:
                    pass

            self.log("Uninstalling service… confirm UAC with Yes.")
            if bat:
                code, out = elevate_and_wait(bat, "/nopause")
                if out.strip():
                    self.log(out.strip())
                if code != 0:
                    self.log(f"Uninstall exit {code}")
            else:
                try:
                    subprocess.run(
                        [
                            "powershell",
                            "-NoProfile",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-File",
                            str(elevate),
                            "-RemoveScript",
                            str(script),
                            "-ResultFile",
                            str(result_file),
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                except Exception as exc:  # noqa: BLE001
                    self.log(f"Uninstall elevation failed: {exc}")
                    self.after(0, lambda: messagebox.showerror("Uninstall", str(exc)))
                    return

            state = "not installed"
            for _ in range(20):
                time.sleep(0.3)
                state = self._service_state()
                if "not installed" in state.lower():
                    break

            if result_file.is_file():
                self.log(result_file.read_text(encoding="utf-8", errors="replace").strip())
            self.log(f"Service state: {state}")

            if "not installed" in state.lower():
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Uninstall",
                        "Service removed.\nYou can click Install auto-start Service again anytime.",
                    ),
                )
            else:
                self.after(
                    0,
                    lambda: messagebox.showerror(
                        "Uninstall",
                        f"Service may still be present.\nStatus: {state}\nTry again with UAC Yes.",
                    ),
                )
            self.after(0, self.refresh_status)

        self._worker(run)

    def enable_ui_at_login(self) -> None:
        ok, detail = set_ui_at_login(True)
        if ok:
            self.log(f"Setup UI will open after Windows login: {detail}")
        else:
            self.log(f"Could not enable UI at login: {detail}")
        self.refresh_status()

    def disable_ui_at_login(self) -> None:
        ok, detail = set_ui_at_login(False)
        self.log("Setup UI at login disabled." if ok else f"Disable failed: {detail}")
        self.refresh_status()

    def start_service(self) -> None:
        def run() -> None:
            self.log("Starting service (may ask for Administrator)…")
            ps = (
                "Start-Process powershell -Verb RunAs -Wait "
                "-ArgumentList '-NoProfile','-Command','Start-Service PLCBridge'"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                check=False,
                creationflags=_create_no_window(),
            )
            self.after(0, self.refresh_status)

        self._worker(run)

    def stop_service(self) -> None:
        def run() -> None:
            self.log("Stopping service (may ask for Administrator)…")
            ps = (
                "Start-Process powershell -Verb RunAs -Wait "
                "-ArgumentList '-NoProfile','-Command','Stop-Service PLCBridge -Force'"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                check=False,
                creationflags=_create_no_window(),
            )
            self.after(0, self.refresh_status)

        self._worker(run)

    def destroy(self) -> None:
        self.stop_esp_monitor()
        if self._bridge_proc and self._bridge_proc.poll() is None:
            self._bridge_proc.terminate()
        if self._mock_httpd is not None:
            try:
                self._mock_httpd.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self._mock_httpd = None
        super().destroy()


def main() -> None:
    LabApp().mainloop()


if __name__ == "__main__":
    main()
