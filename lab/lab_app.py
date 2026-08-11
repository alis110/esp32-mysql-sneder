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
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

ROOT = Path(__file__).resolve().parents[1]
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CP2102 = ("10C4", "EA60")
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
    """Prefer real LAN/Wi-Fi IPv4 (ESP must reach this). Skip localhost / APIPA / virtual NICs."""
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


def list_esp_ports() -> list[dict]:
    from serial.tools import list_ports

    found = []
    for port in list_ports.comports():
        vid = f"{port.vid:04X}" if port.vid is not None else ""
        pid = f"{port.pid:04X}" if port.pid is not None else ""
        found.append(
            {
                "device": port.device,
                "description": port.description or "",
                "is_esp": (vid, pid) == CP2102,
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


def mysql_probe(host: str, port: int, database: str, user: str, password: str) -> tuple[bool, str]:
    try:
        import mysql.connector
    except ImportError:
        return False, "mysql connector missing"
    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            database=database or None,
            user=user,
            password=password,
            connection_timeout=4,
        )
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        extra = ""
        try:
            cur.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM lab_events")
            count, max_id = cur.fetchone()
            extra = f" | lab_events rows={count} max_id={max_id}"
        except Exception:  # noqa: BLE001
            pass
        cur.close()
        conn.close()
        return True, f"connected {host}:{port}/{database or ''}{extra}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


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
    return shutil.which("pio") or shutil.which("platformio")


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


def resolve_bridge_exe() -> Path | None:
    candidates = [
        ROOT / "PLCBridge.exe",
        ROOT / "dist" / "PLCBridge.exe",
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
    _FONT_BOLD = ("Segoe UI Semibold", 9)
    _FONT_TITLE = ("Segoe UI Semibold", 12)
    _FONT_MONO = ("Consolas", 9)

    def __init__(self) -> None:
        super().__init__()
        self.title("PLCBridge Setup")
        self.geometry("1120x720")
        self.minsize(900, 620)
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
        self.after(200, self._drain_log)
        self.after(200, self._drain_api_log)
        self.after(200, self._drain_esp_log)
        self.refresh_status(silent=False)
        self.after(4000, self._live_tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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
        style.configure("Hint.TLabel", background=self._BG, foreground=self._MUTED, font=("Segoe UI", 8))
        style.configure("Title.TLabel", background=self._BG, foreground=self._TEXT, font=self._FONT_TITLE)
        style.configure("Subtitle.TLabel", background=self._BG, foreground=self._MUTED, font=self._FONT)
        style.configure("Field.TLabel", background=self._CARD, foreground=self._MUTED, font=self._FONT)
        style.configure("StatusKey.TLabel", background=self._CARD, foreground=self._MUTED, font=("Segoe UI", 8))
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
            padding=(8, 3),
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

    def _build(self) -> None:
        frm = ttk.Frame(self, padding=(10, 6, 10, 8))
        frm.pack(fill=tk.BOTH, expand=True)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(4, weight=1)

        header = ttk.Frame(frm)
        header.grid(row=0, column=0, sticky=tk.EW, pady=(0, 4))
        ttk.Label(header, text='PLCBridge Setup', style='Title.TLabel').pack(side=tk.LEFT)
        ttk.Label(
            header,
            text='  ·  ESP32 · MySQL · Service',
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
            val = ttk.Label(cell, text='…', style='StatusVal.TLabel', wraplength=200)
            val.pack(anchor=tk.W)
            return val

        self.lbl_esp = status_cell(status_grid, 0, 0, 'ESP32 USB')
        self.lbl_wifi = status_cell(status_grid, 0, 1, 'PC Wi-Fi')
        self.lbl_mysql = status_cell(status_grid, 0, 2, 'MySQL')
        self.lbl_api_target = status_cell(status_grid, 0, 3, 'Target API (from PC)')
        self.lbl_api = status_cell(status_grid, 1, 0, 'Mock API listener')
        self.lbl_svc = status_cell(status_grid, 1, 1, 'Bridge Service')
        self.lbl_ui_boot = status_cell(status_grid, 1, 2, 'UI at login')
        self.lbl_live = status_cell(status_grid, 1, 3, 'Watch')
        self.lbl_live.configure(text='every 4s · changes → App Log')


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
        self.var_api = tk.StringVar(value=f'http://{local_ipv4()}:8089/api/plc-records')
        self.var_token = tk.StringVar(value='lab-token')
        self.var_port = tk.StringVar(value='auto')
        self.var_db_host = tk.StringVar(value='127.0.0.1')
        self.var_db_port = tk.StringVar(value='3307')
        self.var_db_name = tk.StringVar(value='plcbridge_lab')
        self.var_db_user = tk.StringVar(value='bridge')
        self.var_db_pass = tk.StringVar(value='bridge')
        self.var_db_query = tk.StringVar(
            value=(
                "SELECT id, temperature, note, created_at FROM lab_events "
                "WHERE id > %(last_id)s ORDER BY id ASC LIMIT %(batch_size)s"
            )
        )
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
        self._pair(grid, 1, 1, 'MySQL Host', ttk.Entry(grid, textvariable=self.var_db_host))

        self._pair(grid, 2, 0, 'API URL', ttk.Entry(grid, textvariable=self.var_api))
        self._pair(grid, 2, 1, 'MySQL Port', ttk.Entry(grid, textvariable=self.var_db_port, width=12))

        self._pair(grid, 3, 0, 'API Token', ttk.Entry(grid, textvariable=self.var_token, show='*'))
        self._pair(grid, 3, 1, 'Database', ttk.Entry(grid, textvariable=self.var_db_name))

        self._pair(grid, 4, 0, 'ID column', ttk.Entry(grid, textvariable=self.var_id_column, width=12))
        self._pair(grid, 4, 1, 'MySQL User', ttk.Entry(grid, textvariable=self.var_db_user))

        db_pass_row = ttk.Frame(grid, style='Card.TFrame')
        self.ent_db_pass = ttk.Entry(db_pass_row, textvariable=self.var_db_pass, show='*')
        self.ent_db_pass.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Checkbutton(
            db_pass_row, text='Show', variable=self.var_show_db_pass, command=self._toggle_db_pass
        ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(grid, text='MySQL Pass', style='Field.TLabel').grid(
            row=5, column=0, sticky=tk.W, padx=(0, 6), pady=1
        )
        db_pass_row.grid(row=5, column=1, columnspan=3, sticky=tk.EW, pady=1)

        ttk.Label(grid, text='Query', style='Field.TLabel').grid(
            row=6, column=0, sticky=tk.NW, padx=(0, 6), pady=1
        )
        self.txt_query = tk.Text(grid, height=2, wrap=tk.WORD)
        self._style_text(self.txt_query)
        self.txt_query.grid(row=6, column=1, columnspan=3, sticky=tk.EW, pady=1)
        self.txt_query.insert('1.0', self.var_db_query.get())

        actions = ttk.LabelFrame(frm, text=' Actions ', padding=(6, 4))
        actions.grid(row=3, column=0, sticky=tk.EW, pady=(0, 4))

        row1 = ttk.Frame(actions, style='Card.TFrame')
        row1.pack(fill=tk.X, pady=(0, 2))
        for text_btn, cmd in (
            ('Refresh', self.refresh_status),
            ('Scan Wi-Fi', self.scan_wifi),
            ('Mock API', self.start_mock_api),
            ('Check MySQL', self.refresh_status),
            ('Start', self.start_service),
            ('Stop', self.stop_service),
        ):
            btn_style = 'Danger.TButton' if text_btn == 'Stop' else 'TButton'
            ttk.Button(row1, text=text_btn, style=btn_style, command=cmd).pack(side=tk.LEFT, padx=(0, 3))

        row2 = ttk.Frame(actions, style='Card.TFrame')
        row2.pack(fill=tk.X)
        ttk.Button(row2, text='Setup ESP32', style='Accent.TButton', command=self.setup_esp).pack(
            side=tk.LEFT, padx=(0, 3)
        )
        ttk.Button(
            row2, text='Install Service', style='Accent.TButton', command=self.install_service
        ).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(
            row2, text='Uninstall', style='Danger.TButton', command=self.uninstall_service
        ).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(row2, text='UI at login', command=self.enable_ui_at_login).pack(
            side=tk.LEFT, padx=(0, 3)
        )
        ttk.Button(row2, text='Hide UI login', command=self.disable_ui_at_login).pack(side=tk.LEFT)
        ttk.Button(row2, text='CP2102 + PIO tools', command=self.open_factory_tools).pack(
            side=tk.LEFT, padx=(12, 0)
        )

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

        self.after(100, self.scan_wifi)

    def _toggle_wifi_pass(self) -> None:
        self.ent_wifi_pass.configure(show="" if self.var_show_wifi_pass.get() else "*")

    def _toggle_db_pass(self) -> None:
        self.ent_db_pass.configure(show="" if self.var_show_db_pass.get() else "*")

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
            esp_txt = f"not found (ports: {other})"
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
            port = int(self.var_db_port.get().strip() or "3306")
        except ValueError:
            port = 3306
        if self.var_db_user.get().strip():
            ok, detail = mysql_probe(
                self.var_db_host.get().strip() or "127.0.0.1",
                port,
                self.var_db_name.get().strip(),
                self.var_db_user.get().strip(),
                self.var_db_pass.get(),
            )
            mysql_txt = f"{'OK' if ok else 'FAIL'} — {detail}"
            self._paint_status(self.lbl_mysql, mysql_txt, "ok" if ok else "bad")
        else:
            mysql_txt = "enter user/db above"
            self._paint_status(self.lbl_mysql, mysql_txt, "warn")
        self._note_change("MySQL", mysql_txt, silent)

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
            mock_txt = "off — press Mock API (lab)"
            self._paint_status(self.lbl_api, mock_txt, "warn")
        self._note_change("Mock-API", mock_txt, silent)

        mon = "ESP serial ON" if self._esp_monitor_on else "ESP serial off"
        self._paint_status(
            self.lbl_live,
            f"live 4s · {mon}",
            "ok" if self._esp_monitor_on else "val",
        )

        if not silent:
            self.log(f"[{_ts()}] Status refreshed (ESP/MySQL/API/Service).")
            self._api_log(
                f"[{_ts()}] Snapshot — Mock: {mock_txt} | Target: {api_detail} | MySQL: {mysql_txt}"
            )

    def start_mock_api(self) -> None:
        if self._mock_httpd is not None:
            self.log("Mock API already running — POSTs show in API Activity panel.")
            self.refresh_status()
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
                return

        lan = local_ipv4()
        self.var_api.set(f"http://{lan}:{MOCK_API_PORT}/api/plc-records")
        self.log(f"Mock API listening on 0.0.0.0:{MOCK_API_PORT}")
        self.log(f"ESP must POST to http://{lan}:{MOCK_API_PORT}/api/plc-records (same Wi-Fi)")
        self._api_log(f"[{_ts()}] Mock API listening — waiting for ESP POSTs on :{MOCK_API_PORT}")
        self.log("API hits appear in the middle panel: API Activity.")
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
        self.refresh_status()

    def setup_esp(self) -> None:
        """Write Wi-Fi + API settings into firmware and flash the board in one step."""
        ssid = self._selected_ssid()
        password = self.var_wifi_pass.get()
        api_url = self.var_api.get().strip()
        if not ssid or not password:
            messagebox.showwarning("Setup ESP32", "Select Wi-Fi SSID and password first (Scan).")
            return
        if not api_url:
            messagebox.showwarning("Setup ESP32", "API URL is required.")
            return
        if "5g" in ssid.lower() or "5ghz" in ssid.lower().replace(" ", ""):
            if not messagebox.askyesno(
                "Wi-Fi band",
                f"SSID '{ssid}' looks like 5GHz.\nESP32 only supports 2.4GHz.\nContinue anyway?",
            ):
                return
        pio = find_pio()
        if not pio:
            messagebox.showerror("Setup ESP32", "PlatformIO (pio) not in PATH.")
            return
        port = self._esp_port()
        if not port:
            messagebox.showerror("Setup ESP32", "ESP32 not found on USB.")
            return

        # Flash needs exclusive COM access.
        self.stop_esp_monitor("ESP32 serial monitor stopped for flashing.")

        def run() -> None:
            try:
                path = write_secrets(ssid, password, api_url, self.var_token.get().strip() or "lab-token")
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
                    self.log("ESP32 ready: joins Wi-Fi and waits for Bridge serial data → posts to API.")
                    self.log("Tip: click Start on ESP32 Serial panel to watch boot / Wi-Fi logs.")
                else:
                    self.log(f"Setup ESP32 failed (code={proc.returncode}).")
            except Exception as exc:  # noqa: BLE001
                self.log(f"Setup ESP32 error: {exc}")

        self._worker(run)

    def _query_text(self) -> str:
        if hasattr(self, "txt_query"):
            return self.txt_query.get("1.0", "end-1c").strip()
        return self.var_db_query.get().strip()

    def _write_bridge_config(self, target: Path) -> None:
        port = self.var_db_port.get().strip() or "3306"
        com = self.var_port.get().strip() or "auto"
        query = self._query_text().replace("\r\n", "\n")
        # Indent multiline query for ini readability
        query_ini = "\n        ".join(query.split("\n"))
        content = f"""; Generated by PLCBridge Setup
[database]
enabled = true
host = {self.var_db_host.get().strip() or "127.0.0.1"}
port = {port}
database = {self.var_db_name.get().strip()}
username = {self.var_db_user.get().strip()}
password = {self.var_db_pass.get()}
id_column = {self.var_id_column.get().strip() or "id"}
batch_size = 5
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
poll_interval_seconds = 10
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

    def install_service(self) -> None:
        exe = resolve_bridge_exe()
        if not exe:
            messagebox.showerror(
                "Service",
                "PLCBridge.exe not found next to this app.\nPut PLCBridge.exe beside PLCBridgeSetup.exe (dist folder).",
            )
            return
        script = ROOT / "service" / "install-service.ps1"
        elevate = ROOT / "service" / "elevate-install.ps1"
        if not script.is_file() or not elevate.is_file():
            messagebox.showerror("Service", f"Missing install scripts under:\n{ROOT / 'service'}")
            return
        if not self.var_db_user.get().strip() or not self.var_db_name.get().strip():
            messagebox.showwarning("Service", "Fill MySQL settings first, then Check MySQL.")
            return
        if "%(last_id)s" not in self._query_text():
            messagebox.showwarning("Service", "MySQL Query must contain %(last_id)s")
            return

        if not messagebox.askyesno(
            "Install Service",
            "Windows will show a UAC prompt — click Yes.\n\n"
            "This will fully install/start PLCBridge (boot auto-start + crash restart).\nContinue?",
        ):
            return

        def run() -> None:
            local_cfg = ROOT / "config" / "config.ini"
            result_file = ROOT / "data" / "service-install-result.txt"
            try:
                local_cfg.parent.mkdir(parents=True, exist_ok=True)
                (ROOT / "data").mkdir(parents=True, exist_ok=True)
                self._write_bridge_config(local_cfg)
                self.log(f"Prepared config: {local_cfg}")
                if result_file.is_file():
                    result_file.unlink()
            except Exception as exc:  # noqa: BLE001
                self.log(f"Config write failed: {exc}")
                self.after(0, lambda: messagebox.showerror("Service", f"Config write failed:\n{exc}"))
                return

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
                subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            except Exception as exc:  # noqa: BLE001
                self.log(f"Elevation failed: {exc}")
                self.after(0, lambda: messagebox.showerror("Service", f"Elevation failed:\n{exc}"))
                return

            # Wait until Windows reports the service.
            state = "not installed"
            for _ in range(30):
                time.sleep(0.4)
                state = self._service_state()
                if "RUNNING" in state.upper() or "STOPPED" in state.upper():
                    break

            if result_file.is_file():
                self.log(result_file.read_text(encoding="utf-8", errors="replace").strip())
            self.log(f"Service state: {state}")

            ok = "RUNNING" in state.upper() or "STOPPED" in state.upper()
            if ok:
                set_ui_at_login(True)
                self.log("Setup UI at login enabled.")
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Service",
                        f"PLCBridge installed successfully.\n\nStatus: {state}\n"
                        "Starts automatically after Windows reboot.",
                    ),
                )
            else:
                self.after(
                    0,
                    lambda: messagebox.showerror(
                        "Service",
                        "Install did not complete.\n"
                        "If UAC was cancelled, try again and click Yes.\n"
                        "Or run dist\\Install-Service.bat",
                    ),
                )
            self.after(0, self.refresh_status)

        self._worker(run)

    def uninstall_service(self) -> None:
        script = ROOT / "service" / "remove-service.ps1"
        elevate = ROOT / "service" / "elevate-uninstall.ps1"
        if not script.is_file() or not elevate.is_file():
            messagebox.showerror("Uninstall", f"Missing scripts under:\n{ROOT / 'service'}")
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

    def open_factory_tools(self) -> None:
        """Launch CP2102 + PlatformIO install helper (factory Windows PCs)."""
        candidates = [
            ROOT / "tools" / "Install-CP2102-and-PlatformIO.ps1",
            ROOT / "dist" / "tools" / "Install-CP2102-and-PlatformIO.ps1",
            Path(sys.executable).resolve().parent / "tools" / "Install-CP2102-and-PlatformIO.ps1",
        ]
        script = next((p for p in candidates if p.is_file()), None)
        readme = ROOT / "tools" / "README.md"
        if not readme.is_file():
            readme = Path(sys.executable).resolve().parent / "tools" / "README.md"

        msg = (
            "Factory PC needs:\n"
            "  • CP2102 Silicon Labs driver (ESP → COMx)\n"
            "  • PlatformIO (pio) to flash ESP32\n\n"
            "Python is NOT required to run PLCBridge.exe.\n"
            "pio is only needed for the Setup ESP32 flash step.\n\n"
        )
        if script:
            msg += f"Launch installer script?\n{script}"
            if messagebox.askyesno("CP2102 + PlatformIO", msg):
                try:
                    subprocess.Popen(
                        [
                            "powershell",
                            "-NoProfile",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-File",
                            str(script),
                        ],
                    )
                    self.log(f"Opened factory tools installer: {script}")
                except OSError as exc:
                    self.log(f"Could not start installer: {exc}")
                    messagebox.showerror("CP2102 + PlatformIO", str(exc))
        else:
            msg += (
                "Installer script not found next to this app.\n"
                "Copy the tools\\ folder from the USB stick, or open the Silicon Labs / PlatformIO pages from README."
            )
            messagebox.showinfo("CP2102 + PlatformIO", msg)
            try:
                webbrowser.open("https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers")
                webbrowser.open("https://docs.platformio.org/en/latest/core/installation.html")
            except Exception:  # noqa: BLE001
                pass
        if readme.is_file():
            self.log(f"Factory tools notes: {readme}")

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
