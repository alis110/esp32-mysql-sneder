# Factory PC tools (Windows)

Install helpers for the industrial Windows PC:

| Tool | Why |
|------|-----|
| **CP2102 (Silicon Labs VCP)** | USB serial driver so Windows sees ESP32 as `COMx` (`10C4:EA60`) |
| **PlatformIO Core (`pio`)** | Required for **Setup ESP32** (compile + flash firmware) |

## One-click helper

From repo root or `dist/`:

```powershell
# Prefer: right-click → Run with PowerShell  (or from Admin PowerShell)
Set-ExecutionPolicy -Scope Process Bypass
.\tools\Install-CP2102-and-PlatformIO.ps1
```

Or double-click:

```text
dist\Install-CP2102-and-PlatformIO.bat
```

The script:

1. Detects if a CP2102 port is already present
2. Opens the official Silicon Labs CP210x driver page (and tries `winget` if available)
3. Installs / upgrades PlatformIO Core (`pio`) via Python pip when Python exists, otherwise opens PlatformIO install docs
4. Prints `pio --version` and PATH tips

## Manual install (if the script cannot finish offline)

### A) CP2102 driver

1. Open: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers  
2. Download **CP210x Universal Windows Driver** (ZIP).  
3. Extract → right-click `silabser.inf` (or run the vendor installer in the package) → **Install**.  
4. Plug ESP32 with a **data** USB cable.  
5. Check Device Manager → **Ports (COM & LPT)** → should show something like `Silicon Labs CP210x USB to UART Bridge (COMx)`.  
6. If you see a yellow warning under **Other devices**, the driver is missing — install again / reboot.

VID/PID expected by this project: **`10C4:EA60`**.

### B) PlatformIO (`pio`)

**Option 1 — with Python already on the PC (simplest):**

```powershell
py -3 -m pip install -U platformio
pio --version
```

If `pio` is not found, add this to User PATH (typical):

```text
%USERPROFILE%\.platformio\penv\Scripts
```

Then open a **new** PowerShell window and run `pio --version` again.

**Option 2 — without caring about Python UI:**

1. Install Python 3.11+ from https://www.python.org/downloads/windows/  
   - Enable **“Add python.exe to PATH”**  
2. Then run Option 1.

**Option 3 — VS Code / PlatformIO IDE:**

1. Install VS Code  
2. Install the **PlatformIO IDE** extension  
3. Ensure `pio` is on PATH (PlatformIO Core CLI)

First flash downloads Espressif toolchains (needs internet once).

## Do I need Python to run the Bridge?

**No.** `PLCBridge.exe` / `PLCBridgeSetup.exe` do not need Python.

You need **PlatformIO** only to **flash** the ESP32 on that PC.  
If you flash the board on another machine first, the factory PC only needs the **CP2102 driver** + the EXEs.
