"""Wait for ESP32-S3 download port and flash without 1200bps reset."""
import subprocess
import sys
import time
from pathlib import Path

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM11"
ROOT = Path(__file__).resolve().parent
BUILD = ROOT / ".pio" / "build" / "esp32-s3"
ESPTOOL = Path.home() / ".platformio" / "packages" / "tool-esptoolpy" / "esptool.py"

FILES = [
    ("0x0", BUILD / "bootloader.bin"),
    ("0x8000", BUILD / "partitions.bin"),
    ("0x10000", BUILD / "firmware.bin"),
]

for _, path in FILES:
    if not path.is_file():
        print(f"Missing {path}. Run: pio run -e esp32-s3")
        sys.exit(1)

cmd = [
    sys.executable,
    str(ESPTOOL),
    "--chip",
    "esp32s3",
    "--port",
    PORT,
    "--baud",
    "115200",
    "--before",
    "no_reset",
    "--after",
    "hard_reset",
    "write_flash",
    "-z",
]
for addr, path in FILES:
    cmd.extend([addr, str(path)])

print(f"Hold BOOT, tap RESET, keep BOOT until done (~60s). Trying {PORT}...")
deadline = time.time() + 180
attempt = 0
while time.time() < deadline:
    attempt += 1
    print(f"Attempt {attempt}...", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        print(out)
        print("Done. Unplug USB, wait 5 sec, replug. Drive G: should have AlisBoard.exe.")
        sys.exit(0)
    if (
        "Could not open" in out
        or "Failed to connect" in out
        or "serial exception" in out.lower()
        or "PermissionError" in out
        or "does not recognize the command" in out
    ):
        print(out.splitlines()[-1] if out.strip() else "USB dropped, retrying...")
        time.sleep(1.0)
        continue
    print(out)
    sys.exit(proc.returncode)

print("Timed out. Hold BOOT, tap RESET, keep BOOT held, run flash-wait.bat again.")
sys.exit(1)
