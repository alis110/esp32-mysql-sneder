from __future__ import annotations

import argparse
import sys


_SERVICE_COMMANDS = {"install", "update", "remove", "start", "stop", "restart", "debug"}


def _run_as_service() -> bool:
    """True if hosted by Service Control Manager; False if double-clicked / console."""
    try:
        import servicemanager
        from app.service import PLCBridgeService

        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(PLCBridgeService)
        servicemanager.StartServiceCtrlDispatcher()
        return True
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "winerror", None)
        if code is None and getattr(exc, "args", None):
            code = exc.args[0]
        if code == 1063:
            return False
        raise


def _is_service_management_invocation(argv: list[str]) -> bool:
    tokens = {a.lower() for a in argv[1:]}
    if "--console" in tokens or "--config" in tokens:
        return False
    return bool(tokens.intersection(_SERVICE_COMMANDS))


def main() -> None:
    # Double-click frozen EXE with no args: try SCM, else console.
    if getattr(sys, "frozen", False) and len(sys.argv) == 1:
        if _run_as_service():
            return
        from app.main import run_console

        print("PLCBridge console mode (not running as Windows Service).")
        print("For auto-start after reboot, use Setup → Install auto-start Service.")
        run_console(None)
        return

    # install/remove/start/... must go to pywin32 with argv untouched.
    if _is_service_management_invocation(sys.argv):
        from app.service import PLCBridgeService
        import win32serviceutil

        win32serviceutil.HandleCommandLine(PLCBridgeService)
        return

    parser = argparse.ArgumentParser(description="PLC MySQL to ESP32 bridge")
    parser.add_argument("--config", help="Path to config.ini (console mode)")
    parser.add_argument("--console", action="store_true", help="Run interactively instead of as a service")
    args = parser.parse_args()
    from app.main import run_console

    run_console(args.config)


if __name__ == "__main__":
    main()
