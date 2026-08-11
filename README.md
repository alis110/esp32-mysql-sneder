# ESP32 MySQL Sender (PLCBridge)

ارسال امن و سبک رکوردهای MySQL از کامپیوتر صنعتی ویندوز به REST API، از مسیر:

```text
MySQL  →  Python Bridge (Windows Service)  →  USB Serial  →  ESP32  →  Wi-Fi  →  HTTPS/HTTP API
```

ریپوی گیت‌هاب: [alis110/esp32-mysql-sneder](https://github.com/alis110/esp32-mysql-sneder)

این پروژه **schema را حدس نمی‌زند**. باید خودتان Query واقعی را در config بگذارید. تا وقتی `enabled=true` و Query درست نباشد، داده‌ای خوانده/فرستاده نمی‌شود.

---

## فهرست

1. [چی ساخته شده؟](#چی-ساخته-شده)
2. [پیش‌نیازها](#پیشنیازها)
3. [شروع سریع با EXE آماده](#شروع-سریع-با-exe-آماده)
4. [پنل Setup (PLCBridgeSetup)](#پنل-setup-plcbridgesetup)
5. [آزمایشگاه محلی (Docker MySQL + Mock API)](#آزمایشگاه-محلی-docker-mysql--mock-api)
6. [تنظیم Query سبک و بی‌فشار](#تنظیم-query-سبک-و-بیفشار)
7. [Firmware ESP32](#firmware-esp32)
8. [پروتکل Serial](#پروتکل-serial)
9. [اجرای کنسول از سورس Python](#اجرای-کنسول-از-سورس-python)
10. [بیلد EXE از سورس](#بیلد-exe-از-سورس)
11. [Windows Service](#windows-service)
12. [تضمین تحویل و Idempotency](#تضمین-تحویل-و-idempotency)
13. [ساختار پروژه](#ساختار-پروژه)
14. [عیب‌یابی](#عیبیابی)
15. [امنیت](#امنیت)

---

## چی ساخته شده؟

| قطعه | نقش |
|------|-----|
| **PLCBridge.exe** | Bridge: MySQL می‌خواند، به ESP روی USB می‌فرستد، بعد از ACK وضعیت را در SQLite نگه می‌دارد |
| **PLCBridgeSetup.exe** | UI راه‌اندازی: Wi-Fi، MySQL، Mock API، فلش ESP، نصب Service |
| **firmware/** | کد ESP32 (PlatformIO): از Serial می‌گیرد، با Wi-Fi به API پست می‌کند، ACK/NACK برمی‌گرداند |
| **service/** | نصب/حذف سرویس ویندوز با auto-start و restart بعد از crash |
| **lab/** | Docker MySQL، Mock API، اسکریپت‌های تست |

طراحی برای PC کارخانه: **کم‌مصرف** — batch کوچک، poll با فاصله، فقط ردیف‌های جدید با `id > last_id`.

---

## پیش‌نیازها

### سخت‌افزار
- ویندوز ۱۰/۱۱ روی PC صنعتی
- ESP32-DevKitC (یا معادل) + کابل USB **data** (نه فقط شارژ)
- مبدل CP2102 معمولاً با VID/PID `10C4:EA60` دیده می‌شود
- Wi-Fi **2.4GHz** (ESP32 معمولی 5GHz ندارد)

### نرم‌افزار
- برای EXE آماده: فقط ویندوز + درایور CP2102
- برای توسعه/فلش دستی:
  - Python 3.11+
  - [PlatformIO](https://platformio.org/) (`pio` در PATH)
  - (اختیاری lab) Docker Desktop برای MySQL آزمایشی

---

## شروع سریع با EXE آماده

در پوشه `dist/` این‌ها آماده است:

- `PLCBridgeSetup.exe` — پنل راه‌اندازی
- `PLCBridge.exe` — Bridge
- `Install-Service.bat` / `Uninstall-Service.bat`
- `Open-Setup-UI.bat` / `run-console.bat`

### ترتیب پیشنهادی (کارخانه)

1. `PLCBridgeSetup.exe` را اجرا کنید.
2. تنظیمات MySQL را پر کنید → **Check MySQL**.
3. Wi-Fi 2.4GHz را **Scan** کنید، رمز را تأیید کنید، **API URL** و Token را بگذارید.
4. ESP را به USB وصل کنید → **Setup ESP32** (secrets + فلش).
5. **Install Service** (UAC / Administrator) — یک‌بار کافی است.
6. سرویس از boot بالا می‌آید حتی بدون login کاربر.

مسیرهای runtime بعد از نصب Service:

| چیز | مسیر |
|-----|------|
| EXE | `C:\Program Files\PLCBridge\PLCBridge.exe` |
| Config | `C:\ProgramData\PLCBridge\config\config.ini` |
| State | `C:\ProgramData\PLCBridge\data\state.sqlite3` |
| Log | `C:\ProgramData\PLCBridge\logs\plcbridge.log` |

---

## پنل Setup (PLCBridgeSetup)

```powershell
.\dist\PLCBridgeSetup.exe
# یا از سورس:
.\lab\run_lab.bat
```

| دکمه | کار |
|------|-----|
| **Refresh / Check MySQL** | وضعیت ESP، Wi-Fi، MySQL، Mock API، Service |
| **Scan Wi-Fi** | لیست SSID + پر کردن رمز ذخیره‌شده ویندوز (در صورت وجود) |
| **Mock API** | API آزمایشی روی پورت `8089` داخل همین پنجره؛ اگر پورت اشغال باشد خودش آزاد می‌کند |
| **Setup ESP32** | نوشتن `secrets.h` + فلش با PlatformIO |
| **Install / Uninstall Service** | نصب سرویس auto-start (نیاز به Admin) |
| **Start / Stop** | کنترل سرویس |
| **UI at login** | شورتکات Startup برای باز شدن Setup بعد از login |
| **Copy / Clear** | مدیریت Log داخل UI |

**نکته شبکه:** پروفایل Wi-Fi ویندوز را **Private** کنید و فایروال پورت API (مثلاً `8089` برای lab) را باز بگذارید تا ESP بتواند به PC برسد.

جزئیات بیشتر: [`lab/README.md`](lab/README.md)

---

## آزمایشگاه محلی (Docker MySQL + Mock API)

برای تست بدون دیتابیس کارخانه:

```powershell
cd lab
docker compose up -d
# در Setup: MySQL host=127.0.0.1 port=3307 db=plcbridge_lab user/pass=bridge
# دکمه Mock API → سپس Setup ESP32 با API:
#   http://<LAN-IP-PC>:8089/api/plc-records
```

فایل نمونه lab: [`config/config.lab.ini`](config/config.lab.ini)

جریان E2E موفق یعنی:
1. Bridge رکوردهای `lab_events` را می‌خواند
2. روی COM به ESP می‌فرستد
3. ESP با Wi-Fi به Mock API پست می‌کند
4. ACK برمی‌گردد و `last_success_id` جلو می‌رود
5. JSON در Log پنل Setup دیده می‌شود

---

## تنظیم Query سبک و بی‌فشار

هرگز `SELECT *` روی جدول بزرگ نزنید. فقط ستون‌های لازم + فقط IDهای جدید + LIMIT کوچک.

نمونه (lab):

```sql
SELECT id, temperature, note, created_at
FROM lab_events
WHERE id > %(last_id)s
ORDER BY id ASC
LIMIT %(batch_size)s
```

قرارداد اجباری:

- ستون `id_column` (پیش‌فرض `id`) عددی، یکتا، **همواره افزایشی** باشد
- شرط `> %(last_id)s` و `ORDER BY ... ASC`
- ترجیحاً ایندکس روی همان ستون ID
- `%(batch_size)s` را استفاده کنید

پیش‌فرض‌های سبک این پروژه:

| پارامتر | مقدار پیشنهادی | معنی |
|---------|----------------|------|
| `batch_size` | `5` | حداکثر ۵ رکورد در هر دور |
| `poll_interval_seconds` | `10` | هر ۱۰ ثانیه یکبار نگاه به MySQL |
| `retry_delay_seconds` | `15` | تأخیر بعد از خطا |
| `connect_timeout_seconds` | `5` | تایم‌اوت اتصال |

فایل نمونه: [`config/config.example.ini`](config/config.example.ini)  
کپی کنید به `config/config.ini` (این فایل واقعی در git نیست).

قبل از تولید، schema را ببینید:

```sql
SHOW TABLES;
DESCRIBE your_table;
SHOW INDEX FROM your_table;
```

کاربر MySQL فقط با دسترسی **SELECT** روی همان جدول بسازید.

---

## Firmware ESP32

1. PlatformIO نصب باشد.
2. `firmware/include/secrets.example.h` را به `secrets.h` کپی کنید و پر کنید:

```cpp
#define WIFI_SSID "Your-2.4GHz-SSID"
#define WIFI_PASSWORD "..."
#define API_URL "https://your.api/endpoint"
#define API_TOKEN "..."
#define ALLOW_INSECURE_TLS false   // lab: true فقط برای HTTP/تست
```

3. فلش:

```powershell
cd firmware
pio run -t upload
pio device monitor -b 115200
```

یا از Setup: دکمه **Setup ESP32**.

رفتار firmware:
- خط JSON تا ۱۶ KiB
- reconnect Wi-Fi
- HTTP timeout / retry
- watchdog ~۶۰s
- فقط HTTP 2xx → ACK
- 4xx (به‌جز 408/429) معمولاً retry داخلی ندارد؛ Bridge بعداً دوباره می‌فرستد

TLS: در lab با `ALLOW_INSECURE_TLS true` (یا HTTP) کار می‌کند. برای production، CA را در `ROOT_CA` بگذارید و insecure را خاموش کنید.

---

## پروتکل Serial

هر پیام یک خط JSON UTF-8 + `\n`:

```json
{"type":"data","id":15230,"idempotency_key":"plc-record-15230","payload":{"temperature":73.4}}
{"type":"ack","id":15230,"status":"success"}
{"type":"nack","id":15230,"error":"wifi_unavailable"}
```

Bridge فقط بعد از `ack` هم‌ID، مقدار `last_success_id` را در SQLite با تراکنش durable ذخیره می‌کند. اگر MySQL/COM/ESP/Wi-Fi/API قطع شود، **همان ID** دوباره تلاش می‌شود؛ رکورد بعدی جلو نمی‌افتد.

---

## اجرای کنسول از سورس Python

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config\config.example.ini config\config.ini
# config.ini را ویرایش کنید: enabled=true + query واقعی
python plcbridge.py --config config\config.ini
```

پورت سریال:

```ini
[serial]
port = auto
vid_pid = 10C4:EA60
```

یا صریح: `port = COM7`

لیست پورت‌ها:

```powershell
Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Name, PNPDeviceID
```

تست واحد:

```powershell
python -m unittest discover -s tests -v
```

---

## بیلد EXE از سورس

```powershell
.\build.bat
```

خروجی در `dist/`:
- `PLCBridge.exe`
- کپی اسکریپت‌های service و فایل‌های کمکی

بیلد جداگانه Setup UI:

```powershell
.\lab\build_setup.bat
```

فایل‌های PyInstaller: `PLCBridge.spec` و `PLCBridgeSetup.spec` (داخل ریپو هستند).

---

## Windows Service

از Setup (دکمه Install) یا:

```powershell
# Administrator
Set-ExecutionPolicy -Scope Process Bypass
.\dist\Install-Service.bat
# یا:
.\service\install-service.ps1
```

سرویس:
- نام: `PLCBridge`
- Startup: Automatic (delayed)
- Recovery: restart بعد از crash
- حساب پیش‌فرض: `LocalSystem`

حذف:

```powershell
.\dist\Uninstall-Service.bat
```

Config / state / log عمداً در `ProgramData` می‌مانند تا داده نقطه ادامه پاک نشود.

کنسول روی EXE نصب‌شده:

```powershell
& "C:\Program Files\PLCBridge\PLCBridge.exe" --console --config "C:\ProgramData\PLCBridge\config\config.ini"
```

---

## تضمین تحویل و Idempotency

مدل: **at-least-once**.

اگر API رکورد را قبول کند ولی ACK به Bridge نرسد، همان پیام دوباره می‌رود. برای جلوگیری از duplicate، API باید هدر:

```http
Idempotency-Key: plc-record-15230
```

را unique نگه دارد و درخواست تکراری را با 2xx بدون ساخت رکورد جدید جواب دهد.

بدون همکاری API، هم‌زمان «هیچ رکوردی گم نشود» و «هرگز duplicate نشود» در سیستم توزیع‌شده تضمین قطعی ندارد.

---

## ساختار پروژه

```text
esp32-mysql-sneder/
├── app/                      # Bridge Python (MySQL, serial, state, service)
├── config/
│   ├── config.example.ini    # قالب تولید
│   └── config.lab.ini        # قالب lab (Docker)
├── firmware/                 # PlatformIO ESP32
│   ├── platformio.ini
│   ├── src/main.cpp
│   └── include/secrets.example.h
├── lab/                      # Setup UI + Docker + Mock API
│   ├── lab_app.py
│   ├── mock_api.py
│   ├── docker-compose.yml
│   └── README.md
├── service/                  # نصب/حذف Windows Service
├── tests/
├── dist/                     # EXEهای آماده + batها
├── plcbridge.py              # Entry point
├── build.bat
├── PLCBridge.spec
├── PLCBridgeSetup.spec
├── requirements.txt
└── README.md
```

### چیزهایی که عمداً در Git نیستند

| فایل | دلیل |
|------|------|
| `config/config.ini` | رمز MySQL واقعی |
| `firmware/include/secrets.h` | Wi-Fi / Token واقعی |
| `.venv/` | محیط مجازی محلی |
| `build/` ، `firmware/.pio/` | خروجی بیلد |
| `data/*.sqlite3` ، `logs/` | state و لاگ runtime |

برای استفاده: از `*.example*` / `config.lab.ini` کپی بگیرید.

---

## عیب‌یابی

| مشکل | کار |
|------|-----|
| ESP پیدا نمی‌شود | کابل data، درایور CP2102، Device Manager؛ گاهی unplug/replug |
| `wifi_unavailable` / ACK timeout | SSID باید 2.4GHz باشد نه 5G |
| `tcp_connect_failed` به API روی PC | شبکه Private + فایروال پورت API |
| Mock API «port in use» | در Setup دوباره **Mock API** بزنید (پورت را آزاد می‌کند) |
| Service error 1063 با دبل‌کلیک EXE | عادی است؛ سرویس از SCM استارت می‌شود یا `--console` بزنید |
| MySQL fail | host/port/user و `enabled=true` را چک کنید؛ lab معمولاً پورت `3307` است |
| داده نمی‌رود | Query باید `%(last_id)s` داشته باشد؛ Log سرویس را ببینید |

---

## امنیت

- رمزها را در Git نگذارید (`secrets.h` و `config.ini` ignore شده‌اند).
- کاربر MySQL فقط `SELECT`.
- در production: HTTPS + CA واقعی، `ALLOW_INSECURE_TLS=false`.
- Token API را در log عمومی چاپ نکنید.
- Token / payload را روی سرویس‌های request-bin عمومی واقعی نگذارید.

---

## لایسنس / استفاده

برای استقرار کارخانه و آزمایشگاه محلی آماده شده است. قبل از اتصال به MySQL تولید، Query و ایندکس را روی کپی/کاربر read-only تست کنید.
