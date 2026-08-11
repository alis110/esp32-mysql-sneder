from __future__ import annotations

import threading

import servicemanager
import win32event
import win32service
import win32serviceutil

from .config import default_config_path, load_config
from .main import BridgeApplication


class PLCBridgeService(win32serviceutil.ServiceFramework):
    _svc_name_ = "PLCBridge"
    _svc_display_name_ = "PLC MySQL to ESP32 Bridge"
    _svc_description_ = "Reliably forwards new local MySQL records through an ESP32 to a remote API."

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = threading.Event()
        self.scm_stop_event = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()
        win32event.SetEvent(self.scm_stop_event)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("PLCBridge service starting")
        try:
            BridgeApplication(load_config(default_config_path()), self.stop_event).run()
        except Exception as exc:
            servicemanager.LogErrorMsg(f"PLCBridge service failed: {type(exc).__name__}: {exc}")
            raise
