# Lab / Setup UI

ابزار آزمایش و راه‌اندازی کنار پروژه اصلی. جزئیات معماری در [`README.md`](../README.md) ریشه است.

## اجرا

```powershell
# از ریشه پروژه
.\lab\run_lab.bat
# یا بعد از بیلد:
.\dist\PLCBridgeSetup.exe
```

## Docker MySQL (lab)

```powershell
cd lab
docker compose up -d
```

- Host: `127.0.0.1`
- Port: `3307`
- DB / user / pass: `plcbridge_lab` / `bridge` / `bridge`
- جدول نمونه: `lab_events` (از `init.sql`)

## Mock API

در Setup دکمه **Mock API** را بزنید (پورت `8089`). اگر پورت اشغال باشد خودش آزاد می‌شود و POSTهای ESP در Log همان پنجره دیده می‌شوند.

فایروال (اختیاری):

```powershell
.\lab\open_firewall_8089.ps1
```

شبکه ویندوز را **Private** کنید تا ESP به IP لپ‌تاپ برسد.

## ترتیب تست E2E

1. Docker MySQL بالا
2. Setup → Check MySQL
3. Scan Wi-Fi (2.4GHz) + Mock API
4. Setup ESP32
5. Install / Start Service
6. در Log باید hitهای API دیده شود

## فایل‌های کمکی

| فایل | کار |
|------|-----|
| `lab_app.py` | سورس Setup UI |
| `mock_api.py` | Mock API کنسولی جدا (اختیاری؛ ترجیح با دکمه داخل UI) |
| `build_setup.bat` | بیلد `PLCBridgeSetup.exe` |
| `finish_local_lab.bat` | اسکریپت جمع‌بندی تست lab |
| `diag_serial.py` | تشخیص سریال |
| `docker-compose.yml` + `init.sql` | MySQL lab |
