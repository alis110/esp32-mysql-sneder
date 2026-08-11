#!/usr/bin/env python3
"""Tiny local HTTP API for ESP32 lab tests. Accepts POST JSON and returns 2xx."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    server_version = "PLCBridgeMockAPI/1.0"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":false,"error":"invalid_json"}')
            return

        idem = self.headers.get("Idempotency-Key", "")
        auth = self.headers.get("Authorization", "")
        print("=" * 60, flush=True)
        print(f"POST {self.path}", flush=True)
        print(f"Idempotency-Key: {idem}", flush=True)
        print(f"Authorization: {auth[:24]}..." if len(auth) > 24 else f"Authorization: {auth}", flush=True)
        print("Body:", flush=True)
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
        print("=" * 60, flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        reply = {"ok": True, "id": payload.get("id"), "idempotency_key": idem}
        self.wfile.write(json.dumps(reply).encode("utf-8"))

    def log_message(self, fmt: str, *args) -> None:
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="PLCBridge mock REST API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8089)
    args = parser.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock API listening on http://{args.host}:{args.port}/api/plc-records", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
