#!/usr/bin/env python3
"""AlisBoard.exe — portable. Does not install anything on Windows.

Double-click from the ESP mass-storage drive. Uses the current Windows user
for SQL Server (Trusted_Connection). Bundled: Python, pyodbc, pyserial, UI.
"""
from __future__ import annotations

import json
import queue
import socket
import sys
import threading
import time
import tkinter as tk
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from wincc import probe, run_query, windows_user  # noqa: E402

LISTEN_HOSTS = ("127.0.0.1", "192.168.77.2")
LISTEN_PORT = 48123
ESP_VID = 0x303A

_LOG: queue.Queue[str] = queue.Queue()
_SERIAL_LOCK = threading.Lock()
_SER = None
_SER_PORT = ""


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    _LOG.put(line)
    print(line, flush=True)


def handle_payload(body: dict) -> dict:
    cmd = (body.get("command") or body.get("query_id") or "").strip().lower()
    server = (body.get("server") or ".\\WINCC").strip()
    database = (body.get("database") or "auto").strip()
    if cmd in {"", "probe", "status", "test"}:
        return probe(server, database)
    if cmd == "query":
        return run_query(
            str(body.get("query_id") or "tlg_f"),
            server,
            database,
            int(body.get("after_id") or 0),
            int(body.get("batch_size") or 1),
        )
    return {"ok": False, "error": "unknown_command"}


class Handler(BaseHTTPRequestHandler):
    server_version = "AlisBoard/1.0"

    def log_message(self, fmt: str, *args) -> None:
        log(f"{self.client_address[0]} {fmt % args}")

    def _send(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/", "/v1/status", "/health"):
            self._send(
                200,
                {"ok": True, "helper": "1.0.0", "windows_user": windows_user(), "listen": LISTEN_PORT},
            )
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path not in ("/v1/query", "/v1/status", "/query"):
            self._send(404, {"ok": False, "error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, {"ok": False, "error": "invalid_json"})
            return
        if not isinstance(body, dict):
            self._send(400, {"ok": False, "error": "invalid_json"})
            return
        if path.endswith("status") and not body.get("command"):
            body["command"] = "probe"
        try:
            result = handle_payload(body)
        except Exception as exc:  # noqa: BLE001
            self._send(200, {"ok": False, "error": str(exc), "windows_user": windows_user()})
            return
        self._send(200, result)


def start_http() -> None:
    bound = False
    for host in LISTEN_HOSTS:
        try:
            httpd = ThreadingHTTPServer((host, LISTEN_PORT), Handler)
        except OSError as exc:
            log(f"HTTP {host}:{LISTEN_PORT} skipped ({exc})")
            continue
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        log(f"HTTP {host}:{LISTEN_PORT}")
        bound = True
    if not bound:
        httpd = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        log(f"HTTP 0.0.0.0:{LISTEN_PORT}")


def find_esp_port() -> str | None:
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for item in list_ports.comports():
        if item.vid == ESP_VID:
            return item.device
    return None


def serial_write(obj: dict) -> None:
    global _SER
    line = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    with _SERIAL_LOCK:
        if _SER is None:
            raise RuntimeError("ESP not on USB")
        _SER.write(line)


def serial_loop() -> None:
    global _SER, _SER_PORT
    try:
        import serial
    except ImportError:
        log("serial module missing")
        return
    while True:
        try:
            found = find_esp_port()
            if found != _SER_PORT:
                with _SERIAL_LOCK:
                    if _SER is not None:
                        try:
                            _SER.close()
                        except Exception:
                            pass
                        _SER = None
                    _SER_PORT = found or ""
                    if found:
                        _SER = serial.Serial(found, 115200, timeout=1, dsrdtr=False, rtscts=False)
                        log(f"ESP USB {found}")
            ser = _SER
            if ser is None:
                time.sleep(1.5)
                continue
            with _SERIAL_LOCK:
                line = ser.readline()
            if not line:
                continue
            text = line.decode("utf-8", errors="replace").strip()
            if text.startswith("{"):
                try:
                    body = json.loads(text)
                except json.JSONDecodeError:
                    log(text)
                    continue
                if isinstance(body, dict) and (body.get("command") in {"query", "probe", "status", "test"} or body.get("query_id")):
                    req_id = body.get("id")
                    try:
                        result = handle_payload(body)
                    except Exception as exc:  # noqa: BLE001
                        result = {"ok": False, "error": str(exc), "windows_user": windows_user()}
                    result["id"] = req_id
                    serial_write(result)
                else:
                    log(text[:300])
            elif text:
                log(text[:300])
        except Exception as exc:  # noqa: BLE001
            log(f"USB: {exc}")
            with _SERIAL_LOCK:
                if _SER is not None:
                    try:
                        _SER.close()
                    except Exception:
                        pass
                _SER = None
                _SER_PORT = ""
            time.sleep(2)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AlisBoard")
        self.geometry("720x560+40+40")
        self.minsize(640, 480)
        self.var_user = tk.StringVar(value=windows_user())
        self.var_sql = tk.StringVar(value="connecting…")
        self.var_esp = tk.StringVar(value="waiting for USB…")
        self.var_server = tk.StringVar(value=".\\WINCC")
        self.var_db = tk.StringVar(value="auto")
        self.var_ssid = tk.StringVar()
        self.var_pass = tk.StringVar()
        self.var_api = tk.StringVar(value="http://10.33.97.45/api/plc-records")
        self.var_token = tk.StringVar(value="lab-token")
        self._build()
        self.after(200, self._drain)
        self.after(400, self._connect_sql)
        self.after(1000, self._tick_esp)

    def _build(self) -> None:
        pad = ttk.Frame(self, padding=10)
        pad.pack(fill=tk.BOTH, expand=True)
        st = ttk.LabelFrame(pad, text=" Status ", padding=8)
        st.pack(fill=tk.X)
        ttk.Label(st, textvariable=self.var_user).pack(anchor=tk.W)
        ttk.Label(st, textvariable=self.var_sql).pack(anchor=tk.W)
        ttk.Label(st, textvariable=self.var_esp).pack(anchor=tk.W)

        sql = ttk.LabelFrame(pad, text=" SQL Server (Windows Authentication, no password) ", padding=8)
        sql.pack(fill=tk.X, pady=8)
        g = ttk.Frame(sql)
        g.pack(fill=tk.X)
        ttk.Label(g, text="Server").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(g, textvariable=self.var_server).grid(row=0, column=1, sticky=tk.EW, padx=6)
        ttk.Label(g, text="Database").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(g, textvariable=self.var_db).grid(row=1, column=1, sticky=tk.EW, padx=6)
        g.columnconfigure(1, weight=1)
        ttk.Button(sql, text="Test SQL", command=self._connect_sql).pack(anchor=tk.W, pady=4)

        wifi = ttk.LabelFrame(pad, text=" ESP32-S3 Wi-Fi (for API) ", padding=8)
        wifi.pack(fill=tk.X)
        g2 = ttk.Frame(wifi)
        g2.pack(fill=tk.X)
        ttk.Label(g2, text="SSID").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(g2, textvariable=self.var_ssid).grid(row=0, column=1, sticky=tk.EW, padx=6)
        ttk.Label(g2, text="Password").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(g2, textvariable=self.var_pass, show="*").grid(row=1, column=1, sticky=tk.EW, padx=6)
        ttk.Label(g2, text="API URL").grid(row=2, column=0, sticky=tk.W)
        ttk.Entry(g2, textvariable=self.var_api).grid(row=2, column=1, sticky=tk.EW, padx=6)
        ttk.Label(g2, text="Token").grid(row=3, column=0, sticky=tk.W)
        ttk.Entry(g2, textvariable=self.var_token, show="*").grid(row=3, column=1, sticky=tk.EW, padx=6)
        g2.columnconfigure(1, weight=1)
        ttk.Button(wifi, text="Send to ESP32-S3", command=self._send_esp).pack(anchor=tk.W, pady=4)

        logs = ttk.LabelFrame(pad, text=" Logs ", padding=8)
        logs.pack(fill=tk.BOTH, expand=True, pady=8)
        self.txt = scrolledtext.ScrolledText(logs, height=12, wrap=tk.WORD)
        self.txt.pack(fill=tk.BOTH, expand=True)

    def _drain(self) -> None:
        while True:
            try:
                msg = _LOG.get_nowait()
            except queue.Empty:
                break
            self.txt.insert(tk.END, msg + "\n")
            self.txt.see(tk.END)
        self.after(200, self._drain)

    def _connect_sql(self) -> None:
        def run() -> None:
            try:
                result = probe(self.var_server.get().strip(), self.var_db.get().strip())
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc), "windows_user": windows_user()}
            def apply() -> None:
                if result.get("ok"):
                    self.var_sql.set(
                        f"SQL OK — {result.get('database') or ''}  ({result.get('detail') or result.get('version') or ''})"
                    )
                    log("SQL connected as " + str(result.get("windows_user")))
                else:
                    self.var_sql.set("SQL FAIL — " + str(result.get("error")))
                    log("SQL fail: " + str(result.get("error")))
            self.after(0, apply)
        threading.Thread(target=run, daemon=True).start()

    def _tick_esp(self) -> None:
        self.var_esp.set(f"ESP USB {_SER_PORT}" if _SER_PORT else "ESP USB not found — plug the board")
        self.after(1500, self._tick_esp)

    def _send_esp(self) -> None:
        payload = {
            "command": "set_wifi",
            "ssid": self.var_ssid.get().strip(),
            "password": self.var_pass.get(),
            "api_url": self.var_api.get().strip(),
            "api_token": self.var_token.get().strip(),
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        pad = bytearray(b" " * 2048)
        pad[: min(len(raw), 2047)] = raw[:2047]
        try:
            (ROOT / "IN.JSON").write_bytes(bytes(pad))
            log("Wrote IN.JSON")
        except OSError as exc:
            log(f"IN.JSON: {exc}")
        try:
            serial_write(payload)
            log("Sent Wi-Fi / API to ESP32-S3")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("ESP32-S3", str(exc))


def main() -> None:
    log("AlisBoard 1.0.0 portable — nothing is installed on Windows")
    log("Windows user: " + windows_user())
    start_http()
    threading.Thread(target=serial_loop, daemon=True).start()
    App().mainloop()


if __name__ == "__main__":
    socket.gethostname()
    main()
