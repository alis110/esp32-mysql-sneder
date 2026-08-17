import subprocess
from pathlib import Path

Import("env")

root = Path(env["PROJECT_DIR"]).resolve().parent
header = Path(env["PROJECT_DIR"]) / "include" / "msc_image.h"
exe = root / "pack" / "AlisBoard.exe"
script = root / "helper" / "gen_msc.py"
py = env["PYTHONEXE"]

need = not header.exists()
if exe.exists() and header.exists() and exe.stat().st_mtime > header.stat().st_mtime:
    need = True
if need:
    cmd = [py, str(script), "--out", str(header)]
    if exe.exists():
        cmd += ["--exe", str(exe)]
    print("Generating MSC image:", " ".join(cmd))
    subprocess.check_call(cmd)
