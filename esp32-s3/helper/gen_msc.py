#!/usr/bin/env python3
"""Build a FAT12 image with AlisBoard.exe for ESP32-S3 USB MSC."""
from __future__ import annotations

import argparse
import datetime as dt
import struct
from pathlib import Path

IN_SIZE = 2048
OUT_SIZE = 8192
QUEUE_SIZE = 8192
SECTOR = 512

START_HERE = """AlisBoard 1.0.1

1. Double-click OPEN.bat (or AlisBoard.exe). Keep it running.
2. Do not wait for a browser. The window is the app.
3. Closing the window hides it. Use Exit to stop.
4. Nothing is installed on Windows. SQL uses Windows Authentication (no password).
5. Optional: set ESP32-S3 factory Wi-Fi for API upload.
"""


def dos_time(when: dt.datetime) -> tuple[int, int]:
    t = (when.hour << 11) | (when.minute << 5) | (when.second // 2)
    d = ((when.year - 1980) << 9) | (when.month << 5) | when.day
    return t, d


def lfn_checksum(name83: bytes) -> int:
    s = 0
    for c in name83:
        s = ((s & 1) << 7) + (s >> 1) + c
        s &= 0xFF
    return s


def lfn_entries(long_name: str, name83: bytes) -> list[bytes]:
    chk = lfn_checksum(name83)
    u = long_name.encode("utf-16le") + b"\x00\x00"
    while len(u) % 26:
        u += b"\xff\xff"
    chunks = [u[i : i + 26] for i in range(0, len(u), 26)]
    out = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        seq = i + 1
        if i == total - 1:
            seq |= 0x40
        name1 = chunk[0:10]
        name2 = chunk[10:22]
        name3 = chunk[22:26]
        out.append(bytes([seq]) + name1 + bytes([0x0F, 0x00, chk]) + name2 + b"\x00\x00" + name3)
    return list(reversed(out))


def dir_83(name83: bytes, attr: int, cluster: int, size: int, when: dt.datetime) -> bytes:
    if len(name83) != 11:
        raise ValueError(f"8.3 name must be 11 bytes, got {name83!r}")
    t, d = dos_time(when)
    return name83 + struct.pack("<BBBHHHHHHHL", attr, 0, 0, t, d, d, 0, t, d, cluster, size)


def fat12_table(clusters: list[int]) -> bytes:
    # clusters[0] unused; entries 0 and 1 are media
    entries = [0xFF8, 0xFFF] + clusters[2:]
    packed = bytearray()
    i = 0
    while i < len(entries):
        a = entries[i]
        b = entries[i + 1] if i + 1 < len(entries) else 0
        packed.append(a & 0xFF)
        packed.append(((a >> 8) & 0x0F) | ((b & 0x0F) << 4))
        packed.append((b >> 4) & 0xFF)
        i += 2
    return bytes(packed)


def add_file(files: list[dict], name83: str, lfn: str, data: bytes, attr: int = 0x20) -> None:
    n = name83.encode("ascii")
    if len(n) != 11:
        raise ValueError(name83)
    files.append({"name83": n, "lfn": lfn, "data": data, "attr": attr})


def mbr_sector(part_start: int, part_sectors: int) -> bytes:
    mbr = bytearray(SECTOR)
    mbr[510] = 0x55
    mbr[511] = 0xAA
    # partition 1 @ 0x1BE
    off = 0x1BE
    mbr[off] = 0x00  # not bootable
    mbr[off + 1 : off + 4] = bytes([0x00, 0x00, 0x00])  # CHS start
    mbr[off + 4] = 0x01  # FAT12
    mbr[off + 5 : off + 8] = bytes([0xFE, 0xFF, 0xFF])  # CHS end (placeholder)
    struct.pack_into("<I", mbr, off + 8, part_start)
    struct.pack_into("<I", mbr, off + 12, part_sectors)
    return bytes(mbr)


def build(exe: Path | None) -> tuple[bytes, dict]:
    now = dt.datetime.now()
    files: list[dict] = []
    add_file(files, "START   TXT", "START_HERE.txt", START_HERE.replace("\n", "\r\n").encode("ascii"))
    add_file(
        files,
        "OPEN    BAT",
        "OPEN.bat",
        b"@echo off\r\n"
        b"REM Do not cd - Win7 cmd cannot use UNC paths like \\\\host\\g\r\n"
        b"if not exist \"%~dp0AlisBoard.exe\" (\r\n"
        b"  echo AlisBoard.exe not found next to OPEN.bat\r\n"
        b"  pause\r\n"
        b"  exit /b 1\r\n"
        b")\r\n"
        b"start \"\" \"%~dp0AlisBoard.exe\"\r\n",
    )
    add_file(files, "IN      JSO", "IN.JSON", b"{}" + b" " * (IN_SIZE - 2))
    add_file(files, "OUT     JSO", "OUT.JSON", b'{"ok":true}' + b" " * (OUT_SIZE - 11))
    add_file(files, "QUEUE   JSO", "QUEUE.JSON", b"{}" + b" " * (QUEUE_SIZE - 2))
    if exe and exe.is_file():
        add_file(files, "ALISBO~1EXE", "AlisBoard.exe", exe.read_bytes())

    root_ents = 32
    reserved = 1
    fat_count = 1
    spc = 1

    data_sectors = sum(max(1, (len(f["data"]) + SECTOR - 1) // SECTOR) for f in files)
    fat_bytes_est = (data_sectors + 2) * 3 // 2 + 8
    fat_sectors = max(2, (fat_bytes_est + SECTOR - 1) // SECTOR)
    root_sectors = (root_ents * 32 + SECTOR - 1) // SECTOR
    total = reserved + fat_sectors * fat_count + root_sectors + data_sectors
    # ~320 KB USB disk: AlisBoard.exe (~132 KB) + JSON + free space for Windows
    if total < 640:
        total = 640
        data_sectors = total - reserved - fat_sectors * fat_count - root_sectors

    first_data = reserved + fat_sectors * fat_count + root_sectors
    cluster = 2
    meta = {}
    for f in files:
        f["cluster"] = cluster
        secs = max(1, (len(f["data"]) + SECTOR - 1) // SECTOR)
        f["sectors"] = secs
        lba = first_data + (cluster - 2) * spc
        meta[f["lfn"]] = {"lba": lba, "sectors": secs, "size": len(f["data"]), "cluster": cluster}
        cluster += secs

    used_clusters = cluster
    fat_entries = [0xFF8, 0xFFF] + [0] * max(0, used_clusters - 2)
    for f in files:
        start = f["cluster"]
        last = start + f["sectors"] - 1
        for c in range(start, last):
            fat_entries[c] = c + 1
        fat_entries[last] = 0xFFF

    fat = fat12_table(fat_entries)
    fat = fat.ljust(fat_sectors * SECTOR, b"\x00")

    oem = b"MSDOS5.0"
    vol = b"ALISBOARD  "
    boot = bytearray(SECTOR)
    boot[0:3] = b"\xEB\x3C\x90"
    boot[3:11] = oem
    struct.pack_into("<H", boot, 11, SECTOR)
    boot[13] = spc
    struct.pack_into("<H", boot, 14, reserved)
    boot[16] = fat_count
    struct.pack_into("<H", boot, 17, root_ents)
    struct.pack_into("<H", boot, 19, total if total < 65536 else 0)
    boot[21] = 0xF8
    struct.pack_into("<H", boot, 22, fat_sectors)
    struct.pack_into("<H", boot, 24, 1)
    struct.pack_into("<H", boot, 26, 1)
    boot[38] = 0x29
    struct.pack_into("<I", boot, 39, 0xA11B0A12)
    boot[43:54] = vol
    boot[54:62] = b"FAT12   "
    boot[510] = 0x55
    boot[511] = 0xAA

    root = bytearray(root_sectors * SECTOR)
    off = 0
    root[off : off + 32] = dir_83(vol, 0x08, 0, 0, now)
    off += 32
    for f in files:
        for ent in lfn_entries(f["lfn"], f["name83"]):
            if len(ent) != 32:
                raise ValueError(f"LFN size {len(ent)}")
            root[off : off + 32] = ent
            off += 32
        ent83 = dir_83(f["name83"], f["attr"], f["cluster"], len(f["data"]), now)
        if len(ent83) != 32:
            raise ValueError("dirent size")
        root[off : off + 32] = ent83
        off += 32

    image = bytearray(total * SECTOR)
    image[0:SECTOR] = boot
    image[SECTOR : SECTOR + len(fat)] = fat
    root_lba = reserved + fat_sectors * fat_count
    image[root_lba * SECTOR : root_lba * SECTOR + len(root)] = root
    for f in files:
        lba = first_data + (f["cluster"] - 2) * spc
        blob = f["data"].ljust(f["sectors"] * SECTOR, b"\x00")
        image[lba * SECTOR : lba * SECTOR + len(blob)] = blob

    meta["_sector_count"] = total + 1
    meta["_first_data"] = first_data
    meta["_part_start"] = 1
    fat_image = bytes(image)
    full = bytearray((total + 1) * SECTOR)
    full[0:SECTOR] = mbr_sector(1, total)
    full[SECTOR : SECTOR + len(fat_image)] = fat_image
    # LBAs in meta are relative to FAT volume; add partition offset for MSC firmware.
    for key, val in list(meta.items()):
        if key.startswith("_") or not isinstance(val, dict):
            continue
        val["lba"] = int(val["lba"]) + 1
    return bytes(full), meta


def c_array(data: bytes, name: str) -> str:
    lines = [f"static const uint8_t {name}[] = {{"]
    for i in range(0, len(data), 16):
        chunk = ", ".join(f"0x{b:02x}" for b in data[i : i + 16])
        lines.append(f"  {chunk},")
    lines.append("};")
    return "\n".join(lines)


def write_header(path: Path, image: bytes, meta: dict) -> None:
    def lba(name: str) -> tuple[int, int]:
        item = meta.get(name) or {"lba": 0, "sectors": 0}
        return int(item["lba"]), int(item["sectors"])

    in_lba, in_s = lba("IN.JSON")
    out_lba, out_s = lba("OUT.JSON")
    q_lba, q_s = lba("QUEUE.JSON")
    exe = meta.get("AlisBoard.exe")
    header = f"""#pragma once
#include <stdint.h>
#define MSC_SECTOR_COUNT {meta['_sector_count']}
#define MSC_SECTOR_SIZE 512
#define MSC_IN_LBA {in_lba}
#define MSC_IN_SECTORS {in_s}
#define MSC_OUT_LBA {out_lba}
#define MSC_OUT_SECTORS {out_s}
#define MSC_QUEUE_LBA {q_lba}
#define MSC_QUEUE_SECTORS {q_s}
#define MSC_HAS_EXE {1 if exe else 0}
{c_array(image, "MSC_IMAGE")}
"""
    path.write_text(header, encoding="ascii")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    image, meta = build(args.exe)
    write_header(args.out, image, meta)
    exe = meta.get("AlisBoard.exe")
    print(f"MSC {meta['_sector_count']} sectors ({len(image)} bytes) exe={bool(exe)}")


if __name__ == "__main__":
    main()
