import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import serial

hits: list[dict] = []
ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {"raw": body.decode("utf-8", "replace")}
        hits.append(payload)
        print("API HIT", json.dumps(payload, ensure_ascii=True)[:240], flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *_args) -> None:
        return


def safe(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def main() -> None:
    probe = socket.socket()
    busy = probe.connect_ex(("127.0.0.1", 8089)) == 0
    probe.close()
    httpd = None
    if not busy:
        httpd = ThreadingHTTPServer(("0.0.0.0", 8089), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        print("mock api :8089", flush=True)
    else:
        print("mock already running", flush=True)

    ser = serial.Serial("COM7", 115200, timeout=1)
    time.sleep(3)
    deadline = time.time() + 25
    while time.time() < deadline:
        line = ser.readline()
        if not line:
            continue
        text = line.decode("utf-8", "replace").strip()
        print("BOOT", safe(text), flush=True)
        if '"event":"ready"' in text.replace(" ", ""):
            break

    env = {
        "type": "data",
        "id": 1,
        "idempotency_key": "plc-record-1",
        "payload": {"id": 1, "temperature": 73.4, "note": "sample-1"},
    }
    ser.write((json.dumps(env) + "\n").encode())
    ser.flush()
    print("SENT record 1", flush=True)

    result = None
    deadline = time.time() + 60
    while time.time() < deadline:
        line = ser.readline()
        if not line:
            continue
        text = line.decode("utf-8", "replace").strip()
        print("RX", safe(text), flush=True)
        try:
            reply = json.loads(text)
        except json.JSONDecodeError:
            continue
        if reply.get("type") in {"ack", "nack"} and str(reply.get("id")) == "1":
            result = reply
            break

    ser.close()
    print("RESULT", result, flush=True)
    print("API_HITS", len(hits), flush=True)
    if httpd is not None:
        httpd.shutdown()
    if not (result and result.get("type") == "ack"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
