#!/usr/bin/env python3
"""Relay Wi-Fi/LAN to localhost Docker ports.

Docker Desktop on Windows often accepts 127.0.0.1 and Hyper-V hairpin but
rejects real Wi-Fi clients (ESP). Bind Docker to 127.0.0.1 only and run this
relay on 0.0.0.0 for ports 80 and 18773.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
from pathlib import Path

PID_FILE = Path(__file__).with_name("lan_relay.pid")

RELAYS: list[tuple[str, int, str, int]] = [
    ("0.0.0.0", 18773, "127.0.0.1", 18773),
    ("0.0.0.0", 80, "127.0.0.1", 80),
]


def write_pid() -> None:
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")


def remove_pid() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            chunk = src.recv(65536)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        for sock in (src, dst):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


def handle(client: socket.socket, target_host: str, target_port: int) -> None:
    peer = client.getpeername()
    try:
        upstream = socket.create_connection((target_host, target_port), timeout=10)
    except OSError as exc:
        print(f"relay upstream fail {target_host}:{target_port} from {peer[0]}: {exc}", flush=True)
        client.close()
        return
    print(f"relay {peer[0]}:{peer[1]} -> {target_host}:{target_port}", flush=True)
    threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
    pipe(upstream, client)


def serve(bind_host: str, bind_port: int, target_host: str, target_port: int) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((bind_host, bind_port))
    srv.listen(128)
    print(f"relay listen {bind_host}:{bind_port} -> {target_host}:{target_port}", flush=True)
    while True:
        client, _addr = srv.accept()
        threading.Thread(
            target=handle,
            args=(client, target_host, target_port),
            daemon=True,
        ).start()


def main() -> int:
    write_pid()
    threads: list[threading.Thread] = []
    for bind_host, bind_port, target_host, target_port in RELAYS:
        thread = threading.Thread(
            target=serve,
            args=(bind_host, bind_port, target_host, target_port),
            daemon=True,
        )
        thread.start()
        threads.append(thread)
    print("relay ready (Ctrl+C to stop)", flush=True)
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        remove_pid()
    return 0


if __name__ == "__main__":
    sys.exit(main())
