#define WIN32_LEAN_AND_MEAN
#define WINVER 0x0501
#define _WIN32_WINNT 0x0501
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <commctrl.h>
#include <sql.h>
#include <sqlext.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <setupapi.h>
#include <devguid.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <time.h>
#include <shellapi.h>

#pragma comment(lib, "odbc32.lib")
#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "setupapi.lib")
#pragma comment(lib, "shell32.lib")

#include "webui_win.h"

#define APP_NAME "AlisBoard"
#define APP_VER "1.0.4"
#define LISTEN_PORT 48123
#define BROWSER_URL "http://127.0.0.1:48123"
#define POLL_MS 4000
#define BACKFILL_MS 80
#define CURSOR_MAX 400
#define IN_SIZE 2048
#define OUT_SIZE 8192
#define QUEUE_SIZE 8192
#define JSON_MAX 12000
#define POST_MAX 48000
#define LOG_MAX 12000
#define SYNC_BATCH 8
#define WM_APP_LOG (WM_APP + 1)
#define WM_APP_SQL (WM_APP + 2)
#define WM_APP_CFG (WM_APP + 3)
#define WM_APP_ESP (WM_APP + 4)

#define IDC_USER 101
#define IDC_SQL 102
#define IDC_ESP 103
#define IDC_SERVER 104
#define IDC_DB 105
#define IDC_SSID 106
#define IDC_PASS 107
#define IDC_API 108
#define IDC_TOKEN 109
#define IDC_LOG 110
#define IDC_TEST 111
#define IDC_SEND 112
#define IDC_EXIT 113
#define IDC_BROWSER 114
#define IDC_COPY_LOG 115
#define IDC_HDR 116
#define IDC_CLEAR_LOG 117
#define IDC_ESP_LOG 118
#define IDC_CLEAR_ESP 119
#define IDC_COPY_ESP 120
#define IDC_API_USED 121

static const char *Q_TLG =
    "SELECT TOP (1) "
    "CAST(DATEDIFF(second, '19700101', u.TimeStamp) AS bigint) * 1000 + u.MS AS id, "
    "u.ValueID, RTRIM(a.ValueName) AS TagName, u.TimeStamp, u.MS, u.RealValue, u.Quality, u.Flags "
    "FROM TagUncompressed u LEFT JOIN Archive a ON a.ValueID = u.ValueID "
    "WHERE CAST(DATEDIFF(second, '19700101', u.TimeStamp) AS bigint) * 1000 + u.MS > %s "
    "ORDER BY u.TimeStamp ASC, u.MS ASC, u.ValueID ASC";

static HWND g_hwnd, g_log, g_esp_log;
static char g_dir[MAX_PATH];
static char g_user[128];
static char g_sql_status[256] = "SQL: connecting...";
static char g_esp_status[256] = "ESP: USB disk / COM...";
static char g_after_id[32] = "0";
static char g_server[128] = ".\\WINCC";
static char g_database[128] = "all";
static char g_ssid[64] = "Alis";
static char g_pass[64] = "Ali.s1380";
static char g_api[256] = "";
static char g_token[80] = "lab-token";
static char g_esp_api_url[256] = "";
static char g_log_ring[LOG_MAX];
static int g_log_ring_len = 0;
static HANDLE g_com = INVALID_HANDLE_VALUE;
static CRITICAL_SECTION g_lock;
static CRITICAL_SECTION g_sql;
static volatile int g_run = 1;
static volatile int g_http_ready = 0;
static long long g_last_id = 0;

static int write_padded(const char *name, const char *json, int size);
static int read_out_json(char *out, int n);
static const char *json_str(const char *js, const char *key, char *out, int n);
static int esp_queue_post(const char *json, char *err, int en);
static void serial_write_line(const char *json);
static void write_in_json_wifi(void);
static void append_esp_local_line(const char *line);
static void json_esc(char *dst, int n, const char *src);
static void sync_gui_to_globals(void);
static void json_esc(char *dst, int n, const char *src);

static void logf(const char *fmt, ...) {
    char buf[512];
    char line[560];
    SYSTEMTIME st;
    va_list ap;
    int linelen;
    GetLocalTime(&st);
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    snprintf(line, sizeof(line), "%02d:%02d:%02d %s", st.wHour, st.wMinute, st.wSecond, buf);
    linelen = (int)strlen(line);
    EnterCriticalSection(&g_lock);
    if (g_log_ring_len + linelen + 2 >= LOG_MAX) {
        int drop = LOG_MAX / 2;
        if (drop > g_log_ring_len) drop = g_log_ring_len;
        memmove(g_log_ring, g_log_ring + drop, (size_t)(g_log_ring_len - drop));
        g_log_ring_len -= drop;
    }
    if (g_log_ring_len + linelen + 2 < LOG_MAX) {
        if (g_log_ring_len) {
            g_log_ring[g_log_ring_len++] = '\n';
        }
        memcpy(g_log_ring + g_log_ring_len, line, linelen);
        g_log_ring_len += linelen;
        g_log_ring[g_log_ring_len] = 0;
    }
    LeaveCriticalSection(&g_lock);
    if (g_hwnd) {
        char *heap = (char *)HeapAlloc(GetProcessHeap(), 0, strlen(line) + 1);
        if (heap) {
            strcpy(heap, line);
            PostMessage(g_hwnd, WM_APP_LOG, 0, (LPARAM)heap);
        }
    }
}

static void sync_gui_to_globals(void) {
    if (!g_hwnd) return;
    GetDlgItemTextA(g_hwnd, IDC_SERVER, g_server, sizeof(g_server));
    GetDlgItemTextA(g_hwnd, IDC_DB, g_database, sizeof(g_database));
    GetDlgItemTextA(g_hwnd, IDC_SSID, g_ssid, sizeof(g_ssid));
    GetDlgItemTextA(g_hwnd, IDC_PASS, g_pass, sizeof(g_pass));
    GetDlgItemTextA(g_hwnd, IDC_API, g_api, sizeof(g_api));
    GetDlgItemTextA(g_hwnd, IDC_TOKEN, g_token, sizeof(g_token));
}

static void apply_globals_to_gui(void) {
    if (!g_hwnd) return;
    SetDlgItemTextA(g_hwnd, IDC_SERVER, g_server);
    SetDlgItemTextA(g_hwnd, IDC_DB, g_database);
    SetDlgItemTextA(g_hwnd, IDC_SSID, g_ssid);
    SetDlgItemTextA(g_hwnd, IDC_PASS, g_pass);
    SetDlgItemTextA(g_hwnd, IDC_API, g_api);
    SetDlgItemTextA(g_hwnd, IDC_TOKEN, g_token);
}

static void trim_cr(char *s) {
    int n = (int)strlen(s);
    while (n > 0 && (s[n - 1] == '\n' || s[n - 1] == '\r' || s[n - 1] == ' ' || s[n - 1] == '\t')) {
        s[--n] = 0;
    }
}

static void normalize_api_url(char *url, int n) {
    char tmp[256];
    const char *path;
    int len;
    if (!url || n < 24) return;
    trim_cr(url);
    while (url[0] == ' ' || url[0] == '\t') memmove(url, url + 1, strlen(url) + 1);
    if (!url[0]) return;
    if (_strnicmp(url, "https://", 8) == 0) {
        snprintf(tmp, sizeof(tmp), "http://%s", url + 8);
        snprintf(url, n, "%s", tmp);
    } else if (_strnicmp(url, "http://", 7) != 0) {
        snprintf(tmp, sizeof(tmp), "http://%s", url);
        snprintf(url, n, "%s", tmp);
    }
    path = strchr(url + 7, '/');
    if (!path) {
        len = (int)strlen(url);
        if (len + 18 < n) memcpy(url + len, "/api/plc-records", 17);
    } else if (path[1] == 0) {
        snprintf(tmp, sizeof(tmp), "%sapi/plc-records", url);
        snprintf(url, n, "%s", tmp);
    }
}

static void load_ini(void) {
    char path[MAX_PATH], line[384];
    FILE *f;
    snprintf(path, sizeof(path), "%s\\alisboard.ini", g_dir);
    f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof(line), f)) {
        trim_cr(line);
        if (!strncmp(line, "api=", 4))
            snprintf(g_api, sizeof(g_api), "%s", line + 4);
        else if (!strncmp(line, "ssid=", 5))
            snprintf(g_ssid, sizeof(g_ssid), "%s", line + 5);
        else if (!strncmp(line, "pass=", 5))
            snprintf(g_pass, sizeof(g_pass), "%s", line + 5);
        else if (!strncmp(line, "token=", 6))
            snprintf(g_token, sizeof(g_token), "%s", line + 6);
        else if (!strncmp(line, "server=", 7))
            snprintf(g_server, sizeof(g_server), "%s", line + 7);
        else if (!strncmp(line, "database=", 9))
            snprintf(g_database, sizeof(g_database), "%s", line + 9);
    }
    fclose(f);
    normalize_api_url(g_api, sizeof(g_api));
}

static void save_ini(void) {
    char path[MAX_PATH];
    FILE *f;
    sync_gui_to_globals();
    normalize_api_url(g_api, sizeof(g_api));
    snprintf(path, sizeof(path), "%s\\alisboard.ini", g_dir);
    f = fopen(path, "w");
    if (!f) return;
    fprintf(f, "server=%s\ndatabase=%s\napi=%s\nssid=%s\npass=%s\ntoken=%s\n",
            g_server, g_database, g_api, g_ssid, g_pass, g_token);
    fclose(f);
}

#define IDR_FAVICON 2

static void http_send(SOCKET c, int code, const char *ctype, const char *body) {
    char hdr[256];
    const char *msg = code == 204 ? "No Content" : "OK";
    if (code == 204) {
        const char *ok = "HTTP/1.1 204 No Content\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Headers: Content-Type\r\nContent-Length: 0\r\n\r\n";
        send(c, ok, (int)strlen(ok), 0);
        return;
    }
    snprintf(hdr, sizeof(hdr),
             "HTTP/1.1 %d %s\r\nContent-Type: %s\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Headers: Content-Type\r\nContent-Length: %d\r\n\r\n",
             code, msg, ctype, body ? (int)strlen(body) : 0);
    send(c, hdr, (int)strlen(hdr), 0);
    if (body && body[0]) send(c, body, (int)strlen(body), 0);
}

static void http_send_bin(SOCKET c, int code, const char *ctype, const void *body, int len) {
    char hdr[256];
    const char *msg = code == 204 ? "No Content" : "OK";
    snprintf(hdr, sizeof(hdr),
             "HTTP/1.1 %d %s\r\nContent-Type: %s\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Headers: Content-Type\r\nContent-Length: %d\r\n\r\n",
             code, msg, ctype, len);
    send(c, hdr, (int)strlen(hdr), 0);
    if (body && len > 0) send(c, (const char *)body, len, 0);
}

static int load_favicon(const void **out, DWORD *size) {
    HMODULE mod = GetModuleHandle(NULL);
    HRSRC res = FindResourceA(mod, MAKEINTRESOURCEA(IDR_FAVICON), RT_RCDATA);
    HGLOBAL mem;
    if (!res) return 0;
    mem = LoadResource(mod, res);
    if (!mem) return 0;
    *out = LockResource(mem);
    *size = SizeofResource(mod, res);
    return *out && *size;
}

static void windows_user(char *out, int n) {
    char domain[64] = "", name[64] = "";
    DWORD dn = sizeof(domain), nn = sizeof(name);
    GetEnvironmentVariableA("USERDOMAIN", domain, dn);
    GetEnvironmentVariableA("USERNAME", name, nn);
    if (domain[0] && name[0]) snprintf(out, n, "%s\\%s", domain, name);
    else snprintf(out, n, "%s", name[0] ? name : "unknown");
}

static void json_esc(char *dst, int n, const char *src) {
    int o = 0;
    if (!src) src = "";
    while (*src && o < n - 2) {
        unsigned char c = (unsigned char)*src++;
        if (c == '\\' || c == '"') {
            if (o + 2 >= n) break;
            dst[o++] = '\\';
            dst[o++] = (char)c;
        } else if (c == '\n') {
            if (o + 2 >= n) break;
            dst[o++] = '\\';
            dst[o++] = 'n';
        } else if (c == '\r') {
            continue;
        } else if (c < 32) {
            continue;
        } else {
            dst[o++] = (char)c;
        }
    }
    dst[o] = 0;
}

static int parse_http_url(const char *url, char *host, int hn, int *port, char *path, int pn) {
    const char *p = url;
    const char *slash;
    const char *colon;
    int hostlen;
    *port = 80;
    host[0] = 0;
    snprintf(path, pn, "/");
    if (!p || _strnicmp(p, "http://", 7) != 0) return 0;
    p += 7;
    slash = strchr(p, '/');
    colon = strchr(p, ':');
    if (colon && (!slash || colon < slash)) {
        hostlen = (int)(colon - p);
        *port = atoi(colon + 1);
        if (*port <= 0) *port = 80;
    } else {
        hostlen = slash ? (int)(slash - p) : (int)strlen(p);
    }
    if (hostlen <= 0 || hostlen >= hn) return 0;
    memcpy(host, p, hostlen);
    host[hostlen] = 0;
    if (slash) snprintf(path, pn, "%s", slash);
    return 1;
}

static void build_status_json(char *out, int n) {
    char logbuf[LOG_MAX];
    char elog[LOG_MAX * 2];
    char eserver[160], edb[160], ef[280], eapi[280], essid[80], esql[320], eesp[320], euser[160], eespapi[280];
    int sql_ok = strstr(g_sql_status, "SQL OK") != NULL;
    sync_gui_to_globals();
    EnterCriticalSection(&g_lock);
    snprintf(logbuf, sizeof(logbuf), "%s", g_log_ring);
    LeaveCriticalSection(&g_lock);
    sync_gui_to_globals();
    json_esc(eserver, sizeof(eserver), g_server);
    json_esc(edb, sizeof(edb), g_database);
    json_esc(ef, sizeof(ef), g_dir);
    json_esc(eapi, sizeof(eapi), g_api);
    json_esc(essid, sizeof(essid), g_ssid);
    json_esc(elog, sizeof(elog), logbuf);
    json_esc(esql, sizeof(esql), g_sql_status);
    json_esc(eesp, sizeof(eesp), g_esp_status);
    json_esc(euser, sizeof(euser), g_user);
    json_esc(eespapi, sizeof(eespapi), g_esp_api_url);
    snprintf(out, n,
             "{\"ok\":true,\"helper\":\"1.0.0\",\"browser_url\":\"" BROWSER_URL "\","
             "\"windows_user\":\"%s\",\"usb_folder\":\"%s\",\"sql_connected\":%s,"
             "\"sql_status\":\"%s\",\"esp_status\":\"%s\",\"server\":\"%s\",\"database\":\"%s\","
             "\"wifi_ssid\":\"%s\",\"api_url\":\"%s\",\"esp_api_url\":\"%s\",\"logs\":\"%s\"}",
             euser, ef, sql_ok ? "true" : "false", esql, eesp,
             eserver, edb, essid, eapi, eespapi, elog);
}

static const char *json_str(const char *js, const char *key, char *out, int n) {
    char pat[80];
    const char *p;
    int i = 0;
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    p = strstr(js, pat);
    if (!p) {
        out[0] = 0;
        return NULL;
    }
    p = strchr(p + strlen(pat), ':');
    if (!p) {
        out[0] = 0;
        return NULL;
    }
    p++;
    while (*p == ' ') p++;
    if (*p == '"') {
        p++;
        while (*p && *p != '"' && i < n - 1) {
            if (*p == '\\' && p[1]) p++;
            out[i++] = *p++;
        }
        out[i] = 0;
        return out;
    }
    while (*p && *p != ',' && *p != '}' && *p != ' ' && i < n - 1) out[i++] = *p++;
    out[i] = 0;
    return out;
}

static void exe_dir(char *out, int n) {
    char *slash;
    GetModuleFileNameA(NULL, out, n);
    slash = strrchr(out, '\\');
    if (slash) *slash = 0;
}

static int write_padded(const char *name, const char *json, int size) {
    char path[MAX_PATH];
    char *buf;
    HANDLE h;
    DWORD wr = 0;
    int len;
    snprintf(path, sizeof(path), "%s\\%s", g_dir, name);
    buf = (char *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, size);
    if (!buf) return 0;
    len = (int)strlen(json);
    if (len > size - 1) len = size - 1;
    memcpy(buf, json, len);
    memset(buf + len, ' ', size - len);
    h = CreateFileA(path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_ALWAYS,
                    FILE_ATTRIBUTE_NORMAL | FILE_FLAG_WRITE_THROUGH, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        HeapFree(GetProcessHeap(), 0, buf);
        return 0;
    }
    SetFilePointer(h, 0, NULL, FILE_BEGIN);
    WriteFile(h, buf, size, &wr, NULL);
    FlushFileBuffers(h);
    SetEndOfFile(h);
    CloseHandle(h);
    HeapFree(GetProcessHeap(), 0, buf);
    return wr == (DWORD)size;
}

static int read_out_json(char *out, int n) {
    char path[MAX_PATH];
    HANDLE h;
    DWORD rd = 0;
    snprintf(path, sizeof(path), "%s\\OUT.JSON", g_dir);
    h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING,
                    FILE_FLAG_NO_BUFFERING, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING,
                        FILE_ATTRIBUTE_NORMAL, NULL);
    }
    if (h == INVALID_HANDLE_VALUE) return 0;
    {
        DWORD want = (DWORD)(((n - 1) / 512) * 512);
        char *tmp = (char *)VirtualAlloc(NULL, want ? want : 512, MEM_COMMIT, PAGE_READWRITE);
        if (!tmp) {
            CloseHandle(h);
            return 0;
        }
        if (!want) want = 512;
        if (want > (DWORD)n - 1) want = (DWORD)(((n - 1) / 512) * 512);
        if (!ReadFile(h, tmp, want, &rd, NULL)) rd = 0;
        if (rd >= (DWORD)n) rd = (DWORD)n - 1;
        memcpy(out, tmp, rd);
        VirtualFree(tmp, 0, MEM_RELEASE);
    }
    CloseHandle(h);
    out[rd] = 0;
    return rd > 0;
}

static int esp_queue_post(const char *json, char *err, int en) {
    char out[OUT_SIZE + 512], base_log[1600], new_log[1600];
    int i;
    out[0] = base_log[0] = 0;
    read_out_json(out, sizeof(out));
    json_str(out, "esp_log", base_log, sizeof(base_log));
    if (!write_padded("QUEUE.JSON", json, QUEUE_SIZE)) {
        snprintf(err, en, "QUEUE.JSON write fail");
        return 0;
    }
    logf("SQL batch -> ESP queue (%d bytes), ESP posts via Wi-Fi", (int)strlen(json));
    for (i = 0; i < 60; i++) {
        char apio[16], detail[48], used[256];
        Sleep(500);
        if (!read_out_json(out, sizeof(out))) continue;
        json_str(out, "esp_log", new_log, sizeof(new_log));
        if (!strcmp(new_log, base_log)) continue;
        json_str(out, "api_ok", apio, sizeof(apio));
        json_str(out, "api_detail", detail, sizeof(detail));
        json_str(out, "api_url", used, sizeof(used));
        if (!used[0]) json_str(out, "api_post_url", used, sizeof(used));
        if (strstr(new_log, "sql_sync POST ok")) {
            snprintf(err, en, "HTTP %s via ESP URL %s", detail[0] ? detail : "ok", used[0] ? used : "?");
            return 1;
        }
        if (strstr(new_log, "API fail refused") || strstr(new_log, "API fail")) {
            snprintf(err, en, "ESP POST %s URL=%s", detail[0] ? detail : "fail", used[0] ? used : "?");
            return 0;
        }
    }
    snprintf(err, en, "ESP timeout - look at ESP API URL line (that is the real destination)");
    return 0;
}

static const char *pick_driver(void) {
    static const char *pref_new[] = {
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server Native Client RDA 11.0",
        "SQL Server",
        "ODBC Driver 18 for SQL Server",
        NULL};
    static const char *pref_old[] = {
        "SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server Native Client 10.0",
        "SQL Native Client",
        "ODBC Driver 13 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        NULL};
    OSVERSIONINFOA vi;
    const char **pref;
    SQLHENV env = NULL;
    SQLCHAR name[128], attr[128];
    SQLSMALLINT nlen, alen;
    int i, j;
    char installed[24][128];
    int ninst = 0;
    memset(&vi, 0, sizeof(vi));
    vi.dwOSVersionInfoSize = sizeof(vi);
    GetVersionExA(&vi);
    pref = (vi.dwMajorVersion < 10) ? pref_old : pref_new;
    SQLAllocHandle(SQL_HANDLE_ENV, SQL_NULL_HANDLE, &env);
    SQLSetEnvAttr(env, SQL_ATTR_ODBC_VERSION, (SQLPOINTER)SQL_OV_ODBC3, 0);
    if (SQLDriversA(env, SQL_FETCH_FIRST, name, sizeof(name), &nlen, attr, sizeof(attr), &alen) != SQL_NO_DATA) {
        do {
            if (ninst < 24) {
                snprintf(installed[ninst], sizeof(installed[0]), "%s", (char *)name);
                ninst++;
            }
        } while (SQLDriversA(env, SQL_FETCH_NEXT, name, sizeof(name), &nlen, attr, sizeof(attr), &alen) != SQL_NO_DATA);
    }
    SQLFreeHandle(SQL_HANDLE_ENV, env);
    for (i = 0; pref[i]; i++) {
        for (j = 0; j < ninst; j++) {
            if (!_stricmp(installed[j], pref[i])) return pref[i];
        }
    }
    return "SQL Server";
}

static void sql_err(SQLSMALLINT ht, SQLHANDLE h, char *out, int n) {
    SQLCHAR state[8], msg[256];
    SQLINTEGER native;
    SQLSMALLINT len;
    if (SQLGetDiagRecA(ht, h, 1, state, &native, msg, sizeof(msg), &len) == SQL_SUCCESS)
        snprintf(out, n, "%s %s", state, msg);
    else snprintf(out, n, "ODBC error");
}

static int add_server_cand(char names[][128], int *n, int maxn, const char *s) {
    int i;
    if (!s || !s[0] || *n >= maxn) return 0;
    for (i = 0; i < *n; i++) {
        if (!_stricmp(names[i], s)) return 0;
    }
    snprintf(names[*n], 128, "%s", s);
    (*n)++;
    return 1;
}

static int sql_connect_one(const char *server, const char *database, SQLHENV *env, SQLHDBC *dbc, char *resolved, int rn, char *err, int en) {
    char cs[512], db[128] = "";
    SQLCHAR outcs[512];
    SQLSMALLINT outn;
    const char *drv = pick_driver();
    *env = NULL;
    *dbc = NULL;
    resolved[0] = 0;
    SQLAllocHandle(SQL_HANDLE_ENV, SQL_NULL_HANDLE, env);
    SQLSetEnvAttr(*env, SQL_ATTR_ODBC_VERSION, (SQLPOINTER)SQL_OV_ODBC3, 0);
    SQLAllocHandle(SQL_HANDLE_DBC, *env, dbc);
    snprintf(cs, sizeof(cs),
             "DRIVER={%s};SERVER=%s;Trusted_Connection=yes;Connection Timeout=5;%s",
             drv, server,
             (strstr(drv, "ODBC Driver 1") == drv) ? "Encrypt=no;TrustServerCertificate=yes;" : "");
    {
        SQLRETURN rc = SQLDriverConnectA(*dbc, NULL, (SQLCHAR *)cs, SQL_NTS, outcs, sizeof(outcs), &outn, SQL_DRIVER_NOPROMPT);
        if (!SQL_SUCCEEDED(rc)) {
            sql_err(SQL_HANDLE_DBC, *dbc, err, en);
            SQLFreeHandle(SQL_HANDLE_DBC, *dbc);
            SQLFreeHandle(SQL_HANDLE_ENV, *env);
            *dbc = NULL;
            *env = NULL;
            return 0;
        }
    }
    if (!database[0] || !_stricmp(database, "auto") || !_stricmp(database, "all") || !strcmp(database, "*")) {
        snprintf(resolved, rn, "%s", (database[0] && _stricmp(database, "auto")) ? database : "all");
        err[0] = 0;
        return 1;
    }
    snprintf(db, sizeof(db), "[%s]", database);
    snprintf(resolved, rn, "%s", database);
    {
        char useq[160];
        SQLHSTMT st = NULL;
        snprintf(useq, sizeof(useq), "USE %s", db);
        SQLAllocHandle(SQL_HANDLE_STMT, *dbc, &st);
        if (!SQL_SUCCEEDED(SQLExecDirectA(st, (SQLCHAR *)useq, SQL_NTS))) {
            sql_err(SQL_HANDLE_STMT, st, err, en);
            SQLFreeHandle(SQL_HANDLE_STMT, st);
            SQLDisconnect(*dbc);
            SQLFreeHandle(SQL_HANDLE_DBC, *dbc);
            SQLFreeHandle(SQL_HANDLE_ENV, *env);
            *dbc = NULL;
            *env = NULL;
            return 0;
        }
        SQLFreeHandle(SQL_HANDLE_STMT, st);
    }
    err[0] = 0;
    return 1;
}

static int sql_connect(const char *server, const char *database, SQLHENV *env, SQLHDBC *dbc, char *resolved, int rn, char *err, int en) {
    char cands[8][128];
    char computer[64] = "";
    char named[128];
    DWORD cn = sizeof(computer);
    int n = 0, i, ok = 0;
    char last[256] = "";
    GetComputerNameA(computer, &cn);
    add_server_cand(cands, &n, 8, server);
    snprintf(named, sizeof(named), "%s\\WINCC", computer);
    add_server_cand(cands, &n, 8, named);
    add_server_cand(cands, &n, 8, ".\\WINCC");
    add_server_cand(cands, &n, 8, "(local)\\WINCC");
    add_server_cand(cands, &n, 8, "localhost\\WINCC");
    add_server_cand(cands, &n, 8, "CPUPC01\\WINCC");
    add_server_cand(cands, &n, 8, "CPUPC01-PC\\WINCC");
    for (i = 0; i < n; i++) {
        if (sql_connect_one(cands[i], database, env, dbc, resolved, rn, err, en)) {
            if (server && _stricmp(cands[i], server)) {
                snprintf(g_server, sizeof(g_server), "%s", cands[i]);
                if (g_hwnd) PostMessage(g_hwnd, WM_APP_CFG, 0, 0);
            }
            ok = 1;
            break;
        }
        snprintf(last, sizeof(last), "%s", err);
    }
    if (!ok) snprintf(err, en, "%s", last[0] ? last : "SQL connect failed");
    return ok;
}

static void sql_close(SQLHENV env, SQLHDBC dbc) {
    if (dbc) {
        SQLDisconnect(dbc);
        SQLFreeHandle(SQL_HANDLE_DBC, dbc);
    }
    if (env) SQLFreeHandle(SQL_HANDLE_ENV, env);
}

static int sql_scalar(SQLHDBC dbc, const char *q, char *out, int n) {
    SQLHSTMT st = NULL;
    SQLAllocHandle(SQL_HANDLE_STMT, dbc, &st);
    if (!SQL_SUCCEEDED(SQLExecDirectA(st, (SQLCHAR *)q, SQL_NTS))) {
        SQLFreeHandle(SQL_HANDLE_STMT, st);
        return 0;
    }
    if (SQLFetch(st) != SQL_SUCCESS) {
        SQLFreeHandle(SQL_HANDLE_STMT, st);
        return 0;
    }
    SQLGetData(st, 1, SQL_C_CHAR, out, n, NULL);
    SQLFreeHandle(SQL_HANDLE_STMT, st);
    return 1;
}

typedef struct {
    int ok;
    char err[256];
    char database[128];
    char version[180];
    char detail[180];
    char json[JSON_MAX];
    long long row_id;
} SqlResult;

static void probe_sql(const char *server, const char *database, SqlResult *r) {
    SQLHENV env;
    SQLHDBC dbc;
    char err[256];
    char resolved[128];
    char ver[180] = "", c1[32] = "", c2[32] = "";
    memset(r, 0, sizeof(*r));
    EnterCriticalSection(&g_sql);
    if (!sql_connect(server, database, &env, &dbc, resolved, sizeof(resolved), err, sizeof(err))) {
        LeaveCriticalSection(&g_sql);
        snprintf(r->err, sizeof(r->err), "%s", err);
        snprintf(r->json, sizeof(r->json),
                 "{\"ok\":false,\"error\":\"%s\",\"windows_user\":\"%s\",\"sql_connected\":false}",
                 err, g_user);
        return;
    }
    sql_scalar(dbc, "SELECT @@VERSION", ver, sizeof(ver));
    {
        char *nl = strchr(ver, '\n');
        if (nl) *nl = 0;
    }
    if (!_stricmp(resolved, "all") || !_stricmp(database, "all") || !_stricmp(database, "auto") || !strcmp(database, "*") || !database[0]) {
        char nbuf[16] = "0";
        sql_scalar(dbc, "SELECT COUNT(*) FROM sys.databases WHERE database_id > 4", nbuf, sizeof(nbuf));
        snprintf(c1, sizeof(c1), "%s", nbuf);
        snprintf(c2, sizeof(c2), "all");
        sql_close(env, dbc);
        LeaveCriticalSection(&g_sql);
        r->ok = 1;
        snprintf(r->database, sizeof(r->database), "all (%s user databases)", c1);
        snprintf(r->version, sizeof(r->version), "%s", ver);
        snprintf(r->detail, sizeof(r->detail), "check mill first (no duplicates), old archives then newest every 4s");
        snprintf(r->json, sizeof(r->json),
                 "{\"ok\":true,\"windows_user\":\"%s\",\"sql_connected\":true,\"server\":\"%s\","
                 "\"database\":\"all\",\"version\":\"%s\",\"detail\":\"%s\"}",
                 g_user, server, ver, r->detail);
        return;
    }
    sql_scalar(dbc, "SELECT COUNT(*) FROM TagUncompressed", c1, sizeof(c1));
    sql_scalar(dbc, "SELECT COUNT(*) FROM TagCompressed", c2, sizeof(c2));
    sql_close(env, dbc);
    LeaveCriticalSection(&g_sql);
    r->ok = 1;
    snprintf(r->database, sizeof(r->database), "%s", resolved);
    snprintf(r->version, sizeof(r->version), "%s", ver);
    snprintf(r->detail, sizeof(r->detail), "TagUncompressed=%s | TagCompressed=%s", c1, c2);
    snprintf(r->json, sizeof(r->json),
             "{\"ok\":true,\"windows_user\":\"%s\",\"sql_connected\":true,\"server\":\"%s\","
             "\"database\":\"%s\",\"version\":\"%s\",\"detail\":\"%s\"}",
             g_user, server, resolved, ver, r->detail);
}

static int query_row(const char *server, const char *database, const char *after_id, SqlResult *r) {
    SQLHENV env;
    SQLHDBC dbc;
    SQLHSTMT st = NULL;
    char err[256], resolved[128], q[1200];
    char id[32] = "", valueid[32] = "", tag[128] = "", ts[64] = "", ms[16] = "", realv[32] = "", qual[16] = "", flags[16] = "";
    char etag[160];
    memset(r, 0, sizeof(*r));
    EnterCriticalSection(&g_sql);
    if (!sql_connect(server, database, &env, &dbc, resolved, sizeof(resolved), err, sizeof(err))) {
        LeaveCriticalSection(&g_sql);
        snprintf(r->err, sizeof(r->err), "%s", err);
        snprintf(r->json, sizeof(r->json),
                 "{\"ok\":false,\"error\":\"%s\",\"windows_user\":\"%s\",\"sql_connected\":false}",
                 err, g_user);
        return 0;
    }
    snprintf(q, sizeof(q), Q_TLG, after_id && after_id[0] ? after_id : "0");
    SQLAllocHandle(SQL_HANDLE_STMT, dbc, &st);
    if (!SQL_SUCCEEDED(SQLExecDirectA(st, (SQLCHAR *)q, SQL_NTS))) {
        sql_err(SQL_HANDLE_STMT, st, err, sizeof(err));
        SQLFreeHandle(SQL_HANDLE_STMT, st);
        sql_close(env, dbc);
        LeaveCriticalSection(&g_sql);
        snprintf(r->err, sizeof(r->err), "%s", err);
        snprintf(r->json, sizeof(r->json),
                 "{\"ok\":false,\"error\":\"%s\",\"windows_user\":\"%s\"}", err, g_user);
        return 0;
    }
    if (SQLFetch(st) == SQL_SUCCESS) {
        SQLGetData(st, 1, SQL_C_CHAR, id, sizeof(id), NULL);
        SQLGetData(st, 2, SQL_C_CHAR, valueid, sizeof(valueid), NULL);
        SQLGetData(st, 3, SQL_C_CHAR, tag, sizeof(tag), NULL);
        SQLGetData(st, 4, SQL_C_CHAR, ts, sizeof(ts), NULL);
        SQLGetData(st, 5, SQL_C_CHAR, ms, sizeof(ms), NULL);
        SQLGetData(st, 6, SQL_C_CHAR, realv, sizeof(realv), NULL);
        SQLGetData(st, 7, SQL_C_CHAR, qual, sizeof(qual), NULL);
        SQLGetData(st, 8, SQL_C_CHAR, flags, sizeof(flags), NULL);
        r->row_id = _strtoi64(id, NULL, 10);
    }
    SQLFreeHandle(SQL_HANDLE_STMT, st);
    sql_close(env, dbc);
    LeaveCriticalSection(&g_sql);
    r->ok = 1;
    snprintf(r->database, sizeof(r->database), "%s", resolved);
    json_esc(etag, sizeof(etag), tag);
    if (id[0]) {
        snprintf(r->json, sizeof(r->json),
                 "{\"ok\":true,\"windows_user\":\"%s\",\"sql_connected\":true,\"server\":\"%s\","
                 "\"database\":\"%s\",\"query_id\":\"tlg_f\",\"rows\":[{\"id\":%s,\"ValueID\":%s,"
                 "\"TagName\":\"%s\",\"TimeStamp\":\"%s\",\"MS\":%s,\"RealValue\":%s,\"Quality\":%s,\"Flags\":%s}]}",
                 g_user, server, resolved, id, valueid[0] ? valueid : "null", etag, ts,
                 ms[0] ? ms : "0", realv[0] ? realv : "null", qual[0] ? qual : "null", flags[0] ? flags : "null");
    } else {
        snprintf(r->json, sizeof(r->json),
                 "{\"ok\":true,\"windows_user\":\"%s\",\"sql_connected\":true,\"server\":\"%s\","
                 "\"database\":\"%s\",\"query_id\":\"tlg_f\",\"rows\":[]}",
                 g_user, server, resolved);
    }
    return 1;
}

static void gui_get(int id, char *out, int n) {
    if (g_hwnd) {
        GetDlgItemTextA(g_hwnd, id, out, n);
        return;
    }
    switch (id) {
        case IDC_SERVER: snprintf(out, n, "%s", g_server); break;
        case IDC_DB: snprintf(out, n, "%s", g_database); break;
        case IDC_SSID: snprintf(out, n, "%s", g_ssid); break;
        case IDC_PASS: snprintf(out, n, "%s", g_pass); break;
        case IDC_API: snprintf(out, n, "%s", g_api); break;
        case IDC_TOKEN: snprintf(out, n, "%s", g_token); break;
        default: out[0] = 0; break;
    }
}

static int skip_sys_db(const char *n) {
    return !_stricmp(n, "master") || !_stricmp(n, "model") || !_stricmp(n, "msdb") ||
           !_stricmp(n, "tempdb") || !_stricmp(n, "ReportServer") || !_stricmp(n, "ReportServerTempDB");
}

static int skip_table_name(const char *n) {
    return !_strnicmp(n, "sys", 3) || !_stricmp(n, "dtproperties") || !_stricmp(n, "sysdiagrams");
}

static int all_db_mode(const char *database) {
    return !database[0] || !_stricmp(database, "auto") || !_stricmp(database, "all") || !strcmp(database, "*");
}

static int sql_use(SQLHDBC dbc, const char *database, char *err, int en) {
    char q[200];
    SQLHSTMT st = NULL;
    snprintf(q, sizeof(q), "USE [%s]", database);
    SQLAllocHandle(SQL_HANDLE_STMT, dbc, &st);
    if (!SQL_SUCCEEDED(SQLExecDirectA(st, (SQLCHAR *)q, SQL_NTS))) {
        sql_err(SQL_HANDLE_STMT, st, err, en);
        SQLFreeHandle(SQL_HANDLE_STMT, st);
        return 0;
    }
    SQLFreeHandle(SQL_HANDLE_STMT, st);
    return 1;
}

typedef struct {
    char name[128];
    unsigned long long t;
    int kind;
} DbEnt;

static DbEnt g_dbents[64];
static int g_ndbent;
static int g_db_added;

static int is_dig(char c) { return c >= '0' && c <= '9'; }

static unsigned long long ymd_key(int y, int mo, int d, int h, int mi, int s) {
    if (y < 100) y += (y >= 70) ? 1900 : 2000;
    if (y < 1990 || y > 2099 || mo < 1 || mo > 12 || d < 1 || d > 31) return 0;
    if (h > 23 || mi > 59 || s > 59) return 0;
    return (unsigned long long)y * 10000000000ULL + (unsigned long long)mo * 100000000ULL +
           (unsigned long long)d * 1000000ULL + (unsigned long long)h * 10000ULL + (unsigned long long)mi * 100ULL +
           (unsigned long long)s;
}

static int classify_db(const char *name) {
    char u[128];
    int i, n;
    for (i = 0; name[i] && i < 127; i++) {
        char c = name[i];
        u[i] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : c;
    }
    u[i] = 0;
    n = i;
    if (strstr(u, "TLG_F")) return 1;
    if (strstr(u, "TLG_S")) return 2;
    if (strstr(u, "_ALG_") || strstr(u, "#ALG")) return 3;
    if (!strncmp(u, "CC_", 3)) return (n > 0 && u[n - 1] == 'R') ? 5 : 4;
    return 0;
}

static unsigned long long db_name_time(const char *name) {
    unsigned long long first = 0;
    int i, n = (int)strlen(name);
    for (i = 0; i < n; ) {
        int j, len, y, mo, d, h, mi;
        char buf[16];
        if (!is_dig(name[i])) {
            i++;
            continue;
        }
        j = i;
        while (j < n && is_dig(name[j])) j++;
        len = j - i;
        if (len >= 12) {
            memcpy(buf, name + i, 12);
            buf[12] = 0;
            if (sscanf(buf, "%4d%2d%2d%2d%2d", &y, &mo, &d, &h, &mi) == 5) {
                unsigned long long k = ymd_key(y, mo, d, h, mi, 0);
                if (k && !first) first = k;
            }
        } else if (len == 8) {
            memcpy(buf, name + i, 8);
            buf[8] = 0;
            if (sscanf(buf, "%4d%2d%2d", &y, &mo, &d) == 3) {
                unsigned long long k = ymd_key(y, mo, d, 0, 0, 0);
                if (k && !first) first = k;
            }
        }
        i = j;
    }
    if (!first) {
        const char *p = name;
        while (*p) {
            int y, mo, d, h, mi, s;
            if (is_dig(p[0]) && is_dig(p[1]) && p[2] == '_' && is_dig(p[3]) && is_dig(p[4]) && p[5] == '_' &&
                is_dig(p[6]) && is_dig(p[7]) && p[8] == '_' && is_dig(p[9]) && is_dig(p[10]) && p[11] == '_' &&
                is_dig(p[12]) && is_dig(p[13]) && p[14] == '_' && is_dig(p[15]) && is_dig(p[16]) &&
                sscanf(p, "%2d_%2d_%2d_%2d_%2d_%2d", &y, &mo, &d, &h, &mi, &s) == 6) {
                unsigned long long k = ymd_key(y, mo, d, h, mi, s);
                if (k) return k;
            }
            p++;
        }
    }
    return first;
}

static int cmp_db_old_first(const void *a, const void *b) {
    const DbEnt *x = (const DbEnt *)a, *y = (const DbEnt *)b;
    if (x->t && y->t) {
        if (x->t < y->t) return -1;
        if (x->t > y->t) return 1;
        return _stricmp(x->name, y->name);
    }
    if (x->t) return -1;
    if (y->t) return 1;
    return _stricmp(x->name, y->name);
}

static void shuffle_range(DbEnt *a, int lo, int hi) {
    int i;
    for (i = hi - 1; i > lo; i--) {
        int j = lo + (rand() % (i - lo + 1));
        DbEnt tmp = a[i];
        a[i] = a[j];
        a[j] = tmp;
    }
}

static int find_dbent(const DbEnt *e, int n, const char *name) {
    int i;
    for (i = 0; i < n; i++)
        if (!_stricmp(e[i].name, name)) return i;
    return -1;
}

static void order_new_dbs(DbEnt *ents, int n) {
    int dated = 0, i;
    qsort(ents, (size_t)n, sizeof(DbEnt), cmp_db_old_first);
    for (i = 0; i < n; i++)
        if (ents[i].t) dated++;
    if (dated == 0) {
        shuffle_range(ents, 0, n);
        logf("no dates in DB names - random crawl until newest is found");
    } else {
        if (dated < n) shuffle_range(ents, dated, n);
        logf("crawl oldest-first (%d dated, %d unknown)", dated, n - dated);
    }
    if (n > 0) logf("first %s  last %s", ents[0].name, ents[n - 1].name);
}

static void sync_dbents(DbEnt *fresh, int nf) {
    DbEnt next[64];
    int nn = 0, i, added = 0;
    g_db_added = 0;
    if (nf < 1) {
        g_ndbent = 0;
        return;
    }
    if (g_ndbent == 0) {
        memcpy(g_dbents, fresh, (size_t)nf * sizeof(DbEnt));
        g_ndbent = nf;
        order_new_dbs(g_dbents, g_ndbent);
        g_db_added = 1;
        return;
    }
    for (i = 0; i < g_ndbent && nn < 64; i++) {
        if (find_dbent(fresh, nf, g_dbents[i].name) >= 0) next[nn++] = g_dbents[i];
    }
    for (i = 0; i < nf && nn < 64; i++) {
        int j;
        if (find_dbent(next, nn, fresh[i].name) >= 0) continue;
        if (fresh[i].t) {
            j = 0;
            while (j < nn && next[j].t && next[j].t <= fresh[i].t) j++;
            memmove(&next[j + 1], &next[j], (size_t)(nn - j) * sizeof(DbEnt));
            next[j] = fresh[i];
            nn++;
        } else {
            next[nn++] = fresh[i];
        }
        added = 1;
        logf("new database %s", fresh[i].name);
    }
    memcpy(g_dbents, next, (size_t)nn * sizeof(DbEnt));
    g_ndbent = nn;
    g_db_added = added;
}

static int list_user_db_ents(SQLHDBC dbc, DbEnt *ents, int maxn) {
    SQLHSTMT st = NULL;
    char name[128];
    int n = 0;
    SQLAllocHandle(SQL_HANDLE_STMT, dbc, &st);
    if (!SQL_SUCCEEDED(SQLExecDirectA(st, (SQLCHAR *)"SELECT name FROM sys.databases WHERE database_id > 4", SQL_NTS))) {
        SQLFreeHandle(SQL_HANDLE_STMT, st);
        return 0;
    }
    while (SQL_SUCCEEDED(SQLFetch(st)) && n < maxn) {
        name[0] = 0;
        SQLGetData(st, 1, SQL_C_CHAR, name, sizeof(name), NULL);
        if (name[0] && !skip_sys_db(name)) {
            snprintf(ents[n].name, 128, "%s", name);
            ents[n].t = db_name_time(name);
            ents[n].kind = classify_db(name);
            n++;
        }
    }
    SQLFreeHandle(SQL_HANDLE_STMT, st);
    return n;
}

static int fill_work_dbs(int live, char names[][128], int maxn) {
    int i, o = 0, ndated = 0, any_kind = 0;
    int seen[8];
    memset(seen, 0, sizeof(seen));
    if (!live) {
        for (i = 0; i < g_ndbent && o < maxn; i++) snprintf(names[o++], 128, "%s", g_dbents[i].name);
        return o;
    }
    for (i = 0; i < g_ndbent; i++) {
        if (g_dbents[i].t) ndated++;
        if (g_dbents[i].kind) any_kind = 1;
    }
    if (!any_kind) {
        for (i = 0; i < g_ndbent && o < maxn; i++) snprintf(names[o++], 128, "%s", g_dbents[i].name);
        return o;
    }
    for (i = ndated - 1; i >= 0 && o < maxn; i--) {
        int k = g_dbents[i].kind;
        if (k) {
            if (seen[k]) continue;
            seen[k] = 1;
        } else {
            if (seen[0]) continue;
            seen[0] = 1;
        }
        snprintf(names[o++], 128, "%s", g_dbents[i].name);
    }
    for (i = ndated; i < g_ndbent && o < maxn; i++) snprintf(names[o++], 128, "%s", g_dbents[i].name);
    return o;
}

static int list_user_tables(SQLHDBC dbc, const char *db, char names[][128], int maxn) {
    SQLHSTMT st = NULL;
    char name[128];
    int n = 0;
    SQLAllocHandle(SQL_HANDLE_STMT, dbc, &st);
    if (!SQL_SUCCEEDED(SQLTablesA(st, (SQLCHAR *)db, SQL_NTS, NULL, 0, NULL, 0, (SQLCHAR *)"TABLE", SQL_NTS))) {
        SQLFreeHandle(SQL_HANDLE_STMT, st);
        return 0;
    }
    while (SQL_SUCCEEDED(SQLFetch(st)) && n < maxn) {
        name[0] = 0;
        SQLGetData(st, 3, SQL_C_CHAR, name, sizeof(name), NULL);
        if (name[0] && !skip_table_name(name)) {
            snprintf(names[n], 128, "%s", name);
            n++;
        }
    }
    SQLFreeHandle(SQL_HANDLE_STMT, st);
    return n;
}

typedef struct {
    char name[64];
    char mysql[24];
} SyncCol;

static void map_mysql(SQLSMALLINT t, char *out, int n) {
    switch (t) {
        case SQL_TINYINT:
        case SQL_SMALLINT:
        case SQL_INTEGER:
            snprintf(out, n, "INT");
            break;
        case SQL_BIGINT:
            snprintf(out, n, "BIGINT");
            break;
        case SQL_REAL:
        case SQL_FLOAT:
        case SQL_DOUBLE:
        case SQL_DECIMAL:
        case SQL_NUMERIC:
            snprintf(out, n, "DOUBLE");
            break;
        case SQL_BIT:
            snprintf(out, n, "TINYINT");
            break;
        default:
            if (t == SQL_TYPE_TIMESTAMP || t == SQL_TIMESTAMP)
                snprintf(out, n, "DATETIME(3)");
            else
                snprintf(out, n, "TEXT");
            break;
    }
}

static int skip_col_type(SQLSMALLINT t) {
    return t == SQL_LONGVARBINARY || t == SQL_VARBINARY || t == SQL_BINARY || t == SQL_LONGVARCHAR ||
           t == SQL_WLONGVARCHAR;
}

static int list_cols(SQLHDBC dbc, const char *db, const char *table, SyncCol *cols, int maxn) {
    SQLHSTMT st = NULL;
    int n = 0;
    SQLAllocHandle(SQL_HANDLE_STMT, dbc, &st);
    if (!SQL_SUCCEEDED(SQLColumnsA(st, (SQLCHAR *)db, SQL_NTS, NULL, 0, (SQLCHAR *)table, SQL_NTS, NULL, 0))) {
        SQLFreeHandle(SQL_HANDLE_STMT, st);
        return 0;
    }
    while (SQL_SUCCEEDED(SQLFetch(st)) && n < maxn) {
        char name[64] = "";
        char dtbuf[16] = "";
        SQLSMALLINT dt = SQL_VARCHAR;
        SQLGetData(st, 4, SQL_C_CHAR, name, sizeof(name), NULL);
        SQLGetData(st, 5, SQL_C_CHAR, dtbuf, sizeof(dtbuf), NULL);
        dt = (SQLSMALLINT)atoi(dtbuf);
        if (!name[0] || skip_col_type(dt)) continue;
        snprintf(cols[n].name, sizeof(cols[n].name), "%s", name);
        map_mysql(dt, cols[n].mysql, sizeof(cols[n].mysql));
        n++;
    }
    SQLFreeHandle(SQL_HANDLE_STMT, st);
    return n;
}

static void sql_lit(char *dst, int n, const char *s) {
    int o = 0;
    if (o < n - 1) dst[o++] = '\'';
    while (s && *s && o < n - 3) {
        if (*s == '\'') {
            dst[o++] = '\'';
            dst[o++] = '\'';
        } else {
            dst[o++] = *s;
        }
        s++;
    }
    if (o < n - 1) dst[o++] = '\'';
    dst[o] = 0;
}

static char g_ckey[CURSOR_MAX][192];
static char g_cval[CURSOR_MAX][96];
static int g_cn;
static int g_idb, g_itab;
static long long g_sync_seq;
static int g_cursor_loaded;
static int g_resume_ok;

static void ident_name(const char *in, char *out, int n) {
    int i, o = 0;
    if (!in) in = "";
    for (i = 0; in[i] && o < n - 3; i++) {
        char c = in[i];
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_')
            out[o++] = c;
        else
            out[o++] = '_';
    }
    out[o] = 0;
    if (!out[0] || (out[0] >= '0' && out[0] <= '9')) {
        memmove(out + 2, out, (size_t)o + 1);
        out[0] = 'd';
        out[1] = '_';
        o += 2;
    }
    if (o > 64) out[64] = 0;
}

static void cursor_load(void) {
    char path[MAX_PATH], line[320];
    FILE *f;
    if (g_cursor_loaded) return;
    g_cursor_loaded = 1;
    snprintf(path, sizeof(path), "%s\\SYNC.POS", g_dir);
    f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof(line), f) && g_cn < CURSOR_MAX) {
        char *tab = strchr(line, '\t');
        char *nl;
        if (!tab) continue;
        *tab++ = 0;
        nl = strchr(tab, '\n');
        if (nl) *nl = 0;
        nl = strchr(tab, '\r');
        if (nl) *nl = 0;
        snprintf(g_ckey[g_cn], sizeof(g_ckey[0]), "%s", line);
        snprintf(g_cval[g_cn], sizeof(g_cval[0]), "%s", tab);
        g_cn++;
    }
    fclose(f);
}

static void cursor_save(void) {
    char path[MAX_PATH];
    FILE *f;
    int i;
    snprintf(path, sizeof(path), "%s\\SYNC.POS", g_dir);
    f = fopen(path, "w");
    if (!f) return;
    for (i = 0; i < g_cn; i++) fprintf(f, "%s\t%s\n", g_ckey[i], g_cval[i]);
    fclose(f);
}

static void cursor_get(const char *db, const char *table, char *after, int n) {
    char key[192], idb[128], itab[128], ikey[192];
    int i;
    snprintf(key, sizeof(key), "%s|%s", db, table);
    for (i = 0; i < g_cn; i++) {
        if (!strcmp(g_ckey[i], key)) {
            snprintf(after, n, "%s", g_cval[i]);
            return;
        }
    }
    ident_name(db, idb, sizeof(idb));
    ident_name(table, itab, sizeof(itab));
    snprintf(ikey, sizeof(ikey), "%s|%s", idb, itab);
    for (i = 0; i < g_cn; i++) {
        if (!strcmp(g_ckey[i], ikey)) {
            snprintf(after, n, "%s", g_cval[i]);
            return;
        }
    }
    for (i = 0; i < g_cn; i++) {
        char cdb[128], ctab[128], cidb[128], citab[128];
        char *bar = strchr(g_ckey[i], '|');
        if (!bar) continue;
        snprintf(cdb, sizeof(cdb), "%.*s", (int)(bar - g_ckey[i]), g_ckey[i]);
        snprintf(ctab, sizeof(ctab), "%s", bar + 1);
        ident_name(cdb, cidb, sizeof(cidb));
        ident_name(ctab, citab, sizeof(citab));
        if (!_stricmp(cidb, idb) && !_stricmp(citab, itab)) {
            snprintf(after, n, "%s", g_cval[i]);
            return;
        }
    }
    snprintf(after, n, "%s", "0");
}

static void cursor_set_mem(const char *db, const char *table, const char *after) {
    char key[192];
    int i;
    snprintf(key, sizeof(key), "%s|%s", db, table);
    for (i = 0; i < g_cn; i++) {
        if (!strcmp(g_ckey[i], key)) {
            snprintf(g_cval[i], sizeof(g_cval[0]), "%s", after);
            return;
        }
    }
    if (g_cn < CURSOR_MAX) {
        snprintf(g_ckey[g_cn], sizeof(g_ckey[0]), "%s", key);
        snprintf(g_cval[g_cn], sizeof(g_cval[0]), "%s", after);
        g_cn++;
    }
}

static void cursor_set(const char *db, const char *table, const char *after) {
    cursor_set_mem(db, table, after);
    cursor_save();
}

static int sync_build(SQLHDBC dbc, const char *db, const char *table, const char *after, char *env, int en,
                      char *new_after, int an, int *nrow, char *err, int enerr) {
    SyncCol cols[40];
    int nc, i, rows = 0, pos, first;
    SQLHSTMT st = NULL;
    char q[4000], lit[160], keycol[64], lastkey[128] = "";
    char cell[256], ecell[280], ename[80];
    nc = list_cols(dbc, db, table, cols, 40);
    if (nc < 1) {
        snprintf(err, enerr, "no readable columns");
        return 0;
    }
    snprintf(keycol, sizeof(keycol), "%s", cols[0].name);
    pos = snprintf(q, sizeof(q), "SELECT TOP (%d) ", SYNC_BATCH);
    for (i = 0; i < nc; i++) {
        pos += snprintf(q + pos, sizeof(q) - pos, "%s[%s]", i ? "," : "", cols[i].name);
        if (pos >= (int)sizeof(q) - 80) break;
    }
    pos += snprintf(q + pos, sizeof(q) - pos, " FROM [%s]", table);
    if (after && after[0] && strcmp(after, "0")) {
        sql_lit(lit, sizeof(lit), after);
        pos += snprintf(q + pos, sizeof(q) - pos, " WHERE [%s] > %s", keycol, lit);
    }
    snprintf(q + pos, sizeof(q) - pos, " ORDER BY [%s]", keycol);
    SQLAllocHandle(SQL_HANDLE_STMT, dbc, &st);
    if (!SQL_SUCCEEDED(SQLExecDirectA(st, (SQLCHAR *)q, SQL_NTS))) {
        sql_err(SQL_HANDLE_STMT, st, err, enerr);
        SQLFreeHandle(SQL_HANDLE_STMT, st);
        return 0;
    }
    pos = snprintf(env, en,
                   "{\"type\":\"sql_sync\",\"source\":\"alisboard\",\"database\":\"");
    json_esc(ecell, sizeof(ecell), db);
    pos += snprintf(env + pos, en - pos, "%s\",\"table\":\"", ecell);
    json_esc(ecell, sizeof(ecell), table);
    pos += snprintf(env + pos, en - pos, "%s\",\"columns\":[", ecell);
    for (i = 0; i < nc; i++) {
        json_esc(ename, sizeof(ename), cols[i].name);
        pos += snprintf(env + pos, en - pos, "%s{\"name\":\"%s\",\"mysql_type\":\"%s\"}", i ? "," : "", ename,
                        cols[i].mysql);
        if (pos >= en - 200) break;
    }
    pos += snprintf(env + pos, en - pos, "],\"rows\":[");
    first = 1;
    while (SQL_SUCCEEDED(SQLFetch(st))) {
        if (!first) pos += snprintf(env + pos, en - pos, ",");
        first = 0;
        pos += snprintf(env + pos, en - pos, "{");
        for (i = 0; i < nc; i++) {
            cell[0] = 0;
            SQLGetData(st, (SQLUSMALLINT)(i + 1), SQL_C_CHAR, cell, sizeof(cell), NULL);
            if (i == 0) snprintf(lastkey, sizeof(lastkey), "%s", cell);
            json_esc(ename, sizeof(ename), cols[i].name);
            json_esc(ecell, sizeof(ecell), cell);
            pos += snprintf(env + pos, en - pos, "%s\"%s\":\"%s\"", i ? "," : "", ename, ecell);
            if (pos >= en - 80) break;
        }
        pos += snprintf(env + pos, en - pos, "}");
        rows++;
        if (pos >= en - 80) break;
    }
    SQLFreeHandle(SQL_HANDLE_STMT, st);
    g_sync_seq++;
    {
        char ewm[160], ekey[200];
        json_esc(ewm, sizeof(ewm), lastkey[0] ? lastkey : (after ? after : "0"));
        snprintf(ekey, sizeof(ekey), "sql-%s-%s-%s", db, table, lastkey[0] ? lastkey : "0");
        pos += snprintf(env + pos, en - pos,
                        "],\"watermark\":\"%s\",\"mode\":\"crawl\",\"id\":%lld,\"idempotency_key\":\"%s\"}",
                        ewm, g_sync_seq, ekey);
    }
    if (pos >= en) {
        snprintf(err, enerr, "sync JSON too large");
        return 0;
    }
    *nrow = rows;
    snprintf(new_after, an, "%s", lastkey[0] ? lastkey : after);
    err[0] = 0;
    return 1;
}

static void handle_payload(const char *body, char *out, int n) {
    char cmd[32] = "", qid[32] = "", server[128] = "", database[128] = "", after[32] = "0";
    SqlResult r;
    json_str(body, "command", cmd, sizeof(cmd));
    json_str(body, "query_id", qid, sizeof(qid));
    json_str(body, "server", server, sizeof(server));
    json_str(body, "database", database, sizeof(database));
    json_str(body, "after_id", after, sizeof(after));
    if (!server[0]) gui_get(IDC_SERVER, server, sizeof(server));
    if (!database[0]) gui_get(IDC_DB, database, sizeof(database));
    if (!server[0]) snprintf(server, sizeof(server), ".\\WINCC");
    if (!database[0]) snprintf(database, sizeof(database), "auto");
    if (!cmd[0] || !_stricmp(cmd, "probe") || !_stricmp(cmd, "status") || !_stricmp(cmd, "test")) {
        probe_sql(server, database, &r);
        snprintf(out, n, "%s", r.json);
        return;
    }
    if (!_stricmp(cmd, "query") || !_stricmp(qid, "tlg_f") || !_stricmp(qid, "tlg_s")) {
        query_row(server, database, after, &r);
        snprintf(out, n, "%s", r.json);
        return;
    }
    snprintf(out, n, "{\"ok\":false,\"error\":\"unknown_command\"}");
}

static int serial_open(void) {
    HDEVINFO info;
    SP_DEVINFO_DATA dev;
    DWORD i;
    if (g_com != INVALID_HANDLE_VALUE) return 1;
    info = SetupDiGetClassDevsA(&GUID_DEVCLASS_PORTS, NULL, NULL, DIGCF_PRESENT);
    if (info == INVALID_HANDLE_VALUE) return 0;
    dev.cbSize = sizeof(dev);
    for (i = 0; SetupDiEnumDeviceInfo(info, i, &dev); i++) {
        char hwid[256] = "", port[64] = "";
        SetupDiGetDeviceRegistryPropertyA(info, &dev, SPDRP_HARDWAREID, NULL, (BYTE *)hwid, sizeof(hwid), NULL);
        if (!strstr(hwid, "VID_303A") && !strstr(hwid, "vid_303a")) continue;
        {
            HKEY key = SetupDiOpenDevRegKey(info, &dev, DICS_FLAG_GLOBAL, 0, DIREG_DEV, KEY_READ);
            DWORD type, n = sizeof(port);
            if (key != INVALID_HANDLE_VALUE) {
                RegQueryValueExA(key, "PortName", NULL, &type, (BYTE *)port, &n);
                RegCloseKey(key);
            }
        }
        if (port[0]) {
            char path[80];
            DCB dcb;
            COMMTIMEOUTS to;
            snprintf(path, sizeof(path), "\\\\.\\%s", port);
            g_com = CreateFileA(path, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
            if (g_com == INVALID_HANDLE_VALUE) continue;
            GetCommState(g_com, &dcb);
            dcb.BaudRate = CBR_115200;
            dcb.ByteSize = 8;
            dcb.Parity = NOPARITY;
            dcb.StopBits = ONESTOPBIT;
            dcb.fDtrControl = DTR_CONTROL_DISABLE;
            dcb.fRtsControl = RTS_CONTROL_DISABLE;
            SetCommState(g_com, &dcb);
            to.ReadIntervalTimeout = 30;
            to.ReadTotalTimeoutConstant = 80;
            to.ReadTotalTimeoutMultiplier = 0;
            to.WriteTotalTimeoutConstant = 200;
            to.WriteTotalTimeoutMultiplier = 0;
            SetCommTimeouts(g_com, &to);
            logf("ESP serial %s", port);
            snprintf(g_esp_status, sizeof(g_esp_status), "ESP: serial %s", port);
            SetupDiDestroyDeviceInfoList(info);
            return 1;
        }
    }
    SetupDiDestroyDeviceInfoList(info);
    return 0;
}

static void serial_write_line(const char *json) {
    char line[JSON_MAX + 4];
    DWORD wr;
    if (g_com == INVALID_HANDLE_VALUE) return;
    snprintf(line, sizeof(line), "%s\n", json);
    WriteFile(g_com, line, (DWORD)strlen(line), &wr, NULL);
}

static DWORD WINAPI serial_thread(LPVOID p) {
    char buf[JSON_MAX];
    int n = 0;
    (void)p;
    while (g_run) {
        DWORD rd = 0;
        char c;
        if (g_com == INVALID_HANDLE_VALUE) {
            serial_open();
            Sleep(1000);
            continue;
        }
        if (!ReadFile(g_com, &c, 1, &rd, NULL) || !rd) {
            DWORD err = GetLastError();
            if (err == ERROR_INVALID_HANDLE || err == ERROR_ACCESS_DENIED || err == ERROR_BAD_COMMAND) {
                CloseHandle(g_com);
                g_com = INVALID_HANDLE_VALUE;
            }
            continue;
        }
        if (c == '\n') {
            buf[n] = 0;
            n = 0;
            if (buf[0] == '{') {
                char cmd[32] = "", reply[JSON_MAX];
                json_str(buf, "command", cmd, sizeof(cmd));
                if (!_stricmp(cmd, "query") || !_stricmp(cmd, "probe") || !_stricmp(cmd, "status") || strstr(buf, "query_id")) {
                    handle_payload(buf, reply, sizeof(reply));
                    serial_write_line(reply);
                } else {
                    logf("%s", buf);
                }
            } else if (buf[0]) {
                logf("%s", buf);
            }
        } else if (c != '\r' && n < JSON_MAX - 1) {
            buf[n++] = c;
        }
    }
    return 0;
}

static DWORD WINAPI http_thread(LPVOID p) {
    SOCKET ls;
    struct sockaddr_in addr;
    WSADATA wsa;
    (void)p;
    WSAStartup(MAKEWORD(2, 2), &wsa);
    ls = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    {
        BOOL yes = 1;
        setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, (char *)&yes, sizeof(yes));
    }
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(LISTEN_PORT);
    if (bind(ls, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        logf("HTTP bind :%d failed", LISTEN_PORT);
        return 0;
    }
    listen(ls, 8);
    g_http_ready = 1;
    logf("HTTP ready at " BROWSER_URL " (only after Open browser)");
    while (g_run) {
        SOCKET c = accept(ls, NULL, NULL);
        char req[JSON_MAX], body[JSON_MAX], resp[JSON_MAX], hdr[256];
        int n, cl = 0;
        char *pbody;
        if (c == INVALID_SOCKET) continue;
        n = recv(c, req, sizeof(req) - 1, 0);
        if (n <= 0) {
            closesocket(c);
            continue;
        }
        req[n] = 0;
        pbody = strstr(req, "\r\n\r\n");
        {
            char *clh = strstr(req, "Content-Length:");
            if (!clh) clh = strstr(req, "content-length:");
            if (clh) cl = atoi(clh + 15);
        }
        body[0] = '{';
        body[1] = '}';
        body[2] = 0;
        if (pbody) {
            pbody += 4;
            if (cl > 0 && cl < JSON_MAX) {
                int have = (int)strlen(pbody);
                memcpy(body, pbody, have);
                while (have < cl) {
                    int m = recv(c, body + have, cl - have, 0);
                    if (m <= 0) break;
                    have += m;
                }
                body[cl] = 0;
            } else if (pbody[0] == '{') {
                snprintf(body, sizeof(body), "%s", pbody);
            }
        }
        if (strncmp(req, "OPTIONS", 7) == 0) {
            http_send(c, 204, "text/plain", NULL);
        } else if (strncmp(req, "GET / ", 6) == 0 || strncmp(req, "GET / HTTP", 10) == 0 ||
                   strncmp(req, "GET /index.html", 15) == 0) {
            http_send(c, 200, "text/html; charset=utf-8", WEBUI_WIN_HTML);
        } else if (strstr(req, "GET /favicon.ico") == req) {
            const void *ico = NULL;
            DWORD ico_len = 0;
            if (load_favicon(&ico, &ico_len))
                http_send_bin(c, 200, "image/x-icon", ico, (int)ico_len);
            else
                http_send(c, 404, "text/plain", "not found");
        } else if (strstr(req, "GET /api/status") == req) {
            build_status_json(resp, sizeof(resp));
            http_send(c, 200, "application/json", resp);
        } else if (strstr(req, "POST /api/sql") == req) {
            json_str(body, "server", g_server, sizeof(g_server));
            json_str(body, "database", g_database, sizeof(g_database));
            if (g_hwnd) PostMessage(g_hwnd, WM_APP_CFG, 0, 0);
            http_send(c, 200, "application/json", "{\"ok\":true}");
        } else if (strstr(req, "POST /api/test-sql") == req) {
            SqlResult r;
            probe_sql(g_server, g_database, &r);
            http_send(c, 200, "application/json", r.json);
        } else if (strstr(req, "POST /api/esp") == req) {
            json_str(body, "ssid", g_ssid, sizeof(g_ssid));
            json_str(body, "password", g_pass, sizeof(g_pass));
            json_str(body, "api_url", g_api, sizeof(g_api));
            json_str(body, "api_token", g_token, sizeof(g_token));
            if (g_hwnd) PostMessage(g_hwnd, WM_APP_CFG, 0, 0);
            write_in_json_wifi();
            http_send(c, 200, "application/json", "{\"ok\":true}");
        } else if (strstr(req, "GET /health") == req || strstr(req, "GET /v1/status") == req) {
            snprintf(resp, sizeof(resp),
                     "{\"ok\":true,\"helper\":\"1.0.0\",\"windows_user\":\"%s\"}", g_user);
            http_send(c, 200, "application/json", resp);
        } else if (strstr(req, "POST /v1/query") == req || (pbody && pbody[0] == '{')) {
            handle_payload(body, resp, sizeof(resp));
            http_send(c, 200, "application/json", resp);
        } else if (strncmp(req, "GET /", 5) == 0) {
            build_status_json(resp, sizeof(resp));
            http_send(c, 200, "application/json", resp);
        } else {
            handle_payload(body, resp, sizeof(resp));
            http_send(c, 200, "application/json", resp);
        }
        closesocket(c);
    }
    closesocket(ls);
    return 0;
}

static void send_wifi(void) {
    sync_gui_to_globals();
    normalize_api_url(g_api, sizeof(g_api));
    if (g_hwnd) SetDlgItemTextA(g_hwnd, IDC_API, g_api);
    logf("Box API URL (after normalize): %s", g_api[0] ? g_api : "(empty)");
    write_in_json_wifi();
}

static void write_in_json_wifi(void) {
    char js[IN_SIZE];
    char essid[80], epass[80], eapi[280], etok[100];
    sync_gui_to_globals();
    normalize_api_url(g_api, sizeof(g_api));
    if (g_hwnd) SetDlgItemTextA(g_hwnd, IDC_API, g_api);
    if (!g_ssid[0]) {
        logf("Fill Wi-Fi SSID and password, then Send to ESP32-S3");
        return;
    }
    if (!g_api[0]) {
        logf("Fill API URL (IP or full http://host/api/plc-records), then Send");
        return;
    }
    json_esc(essid, sizeof(essid), g_ssid);
    json_esc(epass, sizeof(epass), g_pass);
    json_esc(eapi, sizeof(eapi), g_api);
    json_esc(etok, sizeof(etok), g_token);
    snprintf(js, sizeof(js),
             "{\"command\":\"set_wifi\",\"ssid\":\"%s\",\"password\":\"%s\",\"api_url\":\"%s\",\"api_token\":\"%s\",\"nonce\":%lu}",
             essid, epass, eapi, etok, (unsigned long)GetTickCount());
    logf("Sending to ESP: SSID='%s'", g_ssid);
    logf("Sending to ESP: API URL='%s'", g_api);
    append_esp_local_line("Send clicked");
    append_esp_local_line(g_api);
    /* Fast path: if serial is connected, push command immediately. */
    serial_write_line(js);
    append_esp_local_line("Serial push sent");
    if (write_padded("IN.JSON", js, IN_SIZE)) {
        logf("Wrote IN.JSON with API URL above");
        append_esp_local_line("IN.JSON write OK");
        /* Write the same payload again to reduce Windows cache lag (no restart). */
        Sleep(260);
        write_padded("IN.JSON", js, IN_SIZE);
        append_esp_local_line("IN.JSON write repeat OK");
    } else {
        logf("IN.JSON not on this folder (plug ESP disk)");
        append_esp_local_line("IN.JSON write FAIL - plug ESP USB disk");
    }
}

static void do_probe(void) {
    SqlResult *r = (SqlResult *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(SqlResult));
    if (!r) return;
    sync_gui_to_globals();
    if (!g_server[0]) snprintf(g_server, sizeof(g_server), ".\\WINCC");
    if (!g_database[0]) snprintf(g_database, sizeof(g_database), "all");
    probe_sql(g_server, g_database, r);
    PostMessage(g_hwnd, WM_APP_SQL, 0, (LPARAM)r);
}

static DWORD WINAPI probe_thread(LPVOID p) {
    (void)p;
    do_probe();
    return 0;
}

static DWORD WINAPI poll_thread(LPVOID p) {
    char dbs[64][128];
    char tables[128][128];
    int ndb = 0, ntab = 0, live = 0, pass_posts = 0;
    (void)p;
    Sleep(1500);
    cursor_load();
    logf("SQL crawl -> ESP queue (ESP POSTs to API URL via Wi-Fi)");
    while (g_run) {
        char server[128], database[128], err[256], resolved[128];
        char after[96], new_after[96];
        char *env;
        SQLHENV henv;
        SQLHDBC hdbc;
        int nrow = 0, built, wait_ms;
        gui_get(IDC_SERVER, server, sizeof(server));
        gui_get(IDC_DB, database, sizeof(database));
        sync_gui_to_globals();
        if (!server[0]) snprintf(server, sizeof(server), ".\\WINCC");
        if (!database[0]) snprintf(database, sizeof(database), "all");
        env = (char *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, QUEUE_SIZE);
        if (!env) {
            Sleep(POLL_MS);
            continue;
        }
        EnterCriticalSection(&g_sql);
        if (!sql_connect(server, "all", &henv, &hdbc, resolved, sizeof(resolved), err, sizeof(err))) {
            LeaveCriticalSection(&g_sql);
            logf("SQL poll: %s", err);
            HeapFree(GetProcessHeap(), 0, env);
            Sleep(POLL_MS);
            continue;
        }
        if (all_db_mode(database)) {
            DbEnt fresh[64];
            int nf = list_user_db_ents(hdbc, fresh, 64);
            sync_dbents(fresh, nf);
            if (g_db_added) {
                live = 0;
                g_idb = 0;
                g_itab = 0;
            }
            ndb = fill_work_dbs(live, dbs, 64);
        } else {
            snprintf(dbs[0], 128, "%s", database);
            ndb = 1;
        }
        if (ndb < 1) {
            sql_close(henv, hdbc);
            LeaveCriticalSection(&g_sql);
            logf("SQL poll: no user databases");
            HeapFree(GetProcessHeap(), 0, env);
            Sleep(POLL_MS);
            continue;
        }
        if (g_idb >= ndb) {
            if (!live && pass_posts == 0) {
                live = 1;
                g_itab = 0;
                logf("crawl done - live newest DBs every 4s, first %s",
                     (fill_work_dbs(1, dbs, 64) > 0) ? dbs[0] : "?");
            }
            pass_posts = 0;
            g_idb = 0;
            if (live) {
                sql_close(henv, hdbc);
                LeaveCriticalSection(&g_sql);
                HeapFree(GetProcessHeap(), 0, env);
                Sleep(POLL_MS);
                continue;
            }
        }
        if (g_idb < 0) g_idb = 0;
        if (!sql_use(hdbc, dbs[g_idb], err, sizeof(err))) {
            logf("skip DB %s: %s", dbs[g_idb], err);
            g_idb++;
            g_itab = 0;
            sql_close(henv, hdbc);
            LeaveCriticalSection(&g_sql);
            HeapFree(GetProcessHeap(), 0, env);
            Sleep(BACKFILL_MS);
            continue;
        }
        ntab = list_user_tables(hdbc, dbs[g_idb], tables, 128);
        if (ntab < 1) {
            logf("DB %s: no tables", dbs[g_idb]);
            g_idb++;
            g_itab = 0;
            sql_close(henv, hdbc);
            LeaveCriticalSection(&g_sql);
            HeapFree(GetProcessHeap(), 0, env);
            continue;
        }
        if (g_itab >= ntab) {
            g_idb++;
            g_itab = 0;
            sql_close(henv, hdbc);
            LeaveCriticalSection(&g_sql);
            HeapFree(GetProcessHeap(), 0, env);
            continue;
        }
        cursor_get(dbs[g_idb], tables[g_itab], after, sizeof(after));
        built = sync_build(hdbc, dbs[g_idb], tables[g_itab], after, env, QUEUE_SIZE, new_after, sizeof(new_after), &nrow,
                           err, sizeof(err));
        sql_close(henv, hdbc);
        LeaveCriticalSection(&g_sql);
        if (!built) {
            logf("skip %s.%s: %s", dbs[g_idb], tables[g_itab], err);
            g_itab++;
            HeapFree(GetProcessHeap(), 0, env);
            Sleep(500);
            continue;
        }
        if (nrow < 1) {
            g_itab++;
            HeapFree(GetProcessHeap(), 0, env);
            continue;
        }
        if (esp_queue_post(env, err, sizeof(err))) {
            cursor_set(dbs[g_idb], tables[g_itab], new_after);
            pass_posts++;
            logf("%s %s.%s +%d after=%s %s", live ? "live" : "backfill", dbs[g_idb], tables[g_itab], nrow, new_after,
                 err);
            if (nrow < SYNC_BATCH) g_itab++;
            wait_ms = live ? POLL_MS : BACKFILL_MS;
        } else {
            logf("ESP POST fail: %s", err);
            logf("ESP used URL: %s", g_esp_api_url[0] ? g_esp_api_url : "(unknown)");
            logf("Box URL: %s", g_api[0] ? g_api : "(empty)");
            wait_ms = 5000;
        }
        HeapFree(GetProcessHeap(), 0, env);
        Sleep(wait_ms);
    }
    return 0;
}

static DWORD WINAPI out_watch(LPVOID p) {
    static char last_log[1600];
    (void)p;
    last_log[0] = 0;
    while (g_run) {
        char out[OUT_SIZE + 512];
        if (read_out_json(out, sizeof(out)) && out[0] == '{') {
            char ip[40] = "", ssid[64] = "", wifio[12] = "", apio[12] = "", detail[48] = "", esplog[1600] = "";
            char esp_api_url[256] = "", post_url[256] = "";
            static char last_mismatch[256];
            json_str(out, "wifi_ip", ip, sizeof(ip));
            json_str(out, "wifi_ssid", ssid, sizeof(ssid));
            json_str(out, "wifi_ok", wifio, sizeof(wifio));
            json_str(out, "api_ok", apio, sizeof(apio));
            json_str(out, "api_detail", detail, sizeof(detail));
            json_str(out, "api_url", esp_api_url, sizeof(esp_api_url));
            json_str(out, "api_post_url", post_url, sizeof(post_url));
            json_str(out, "esp_log", esplog, sizeof(esplog));
            if (post_url[0] && strcmp(post_url, "(empty)") != 0)
                snprintf(g_esp_api_url, sizeof(g_esp_api_url), "%s", post_url);
            else if (esp_api_url[0])
                snprintf(g_esp_api_url, sizeof(g_esp_api_url), "%s", esp_api_url);
            if (ip[0] && strcmp(ip, "0.0.0.0"))
                snprintf(g_esp_status, sizeof(g_esp_status), "ESP: Wi-Fi %s  %s  API %s", ip, ssid,
                         detail[0] ? detail : (apio[0] ? apio : "?"));
            else if (wifio[0])
                snprintf(g_esp_status, sizeof(g_esp_status), "ESP: Wi-Fi down  API %s", detail[0] ? detail : "-");
            if (g_api[0] && g_esp_api_url[0] && strcmp(g_api, g_esp_api_url) != 0 &&
                strcmp(last_mismatch, g_esp_api_url) != 0) {
                snprintf(last_mismatch, sizeof(last_mismatch), "%s", g_esp_api_url);
                logf("URL mismatch: box  = %s", g_api);
                logf("URL mismatch: ESP  = %s  (board POSTs to this one)", g_esp_api_url);
                logf("Click Send to ESP32-S3 to apply the box URL");
            }
            if (esplog[0] && strcmp(esplog, last_log) != 0) {
                char *heap = (char *)HeapAlloc(GetProcessHeap(), 0, strlen(esplog) + 1);
                snprintf(last_log, sizeof(last_log), "%s", esplog);
                if (heap && g_hwnd) {
                    strcpy(heap, esplog);
                    PostMessage(g_hwnd, WM_APP_ESP, 0, (LPARAM)heap);
                } else if (heap) {
                    HeapFree(GetProcessHeap(), 0, heap);
                }
            }
        }
        if (g_hwnd) PostMessage(g_hwnd, WM_APP_SQL, 1, 0);
        Sleep(1000);
    }
    return 0;
}

static HFONT g_font_ui, g_font_bold, g_font_log;
static HBRUSH g_brush_panel, g_brush_white, g_brush_log;

static HFONT make_font(int height, int weight, const char *face) {
    HFONT f = CreateFontA(height, 0, 0, 0, weight, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
                          OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                          DEFAULT_PITCH | FF_DONTCARE, face);
    return f ? f : (HFONT)GetStockObject(DEFAULT_GUI_FONT);
}

static void init_ui_resources(void) {
    g_font_ui = make_font(-15, FW_NORMAL, "Segoe UI");
    g_font_bold = make_font(-16, FW_BOLD, "Segoe UI");
    g_font_log = make_font(-14, FW_NORMAL, "Consolas");
    g_brush_panel = CreateSolidBrush(RGB(236, 242, 248));
    g_brush_white = CreateSolidBrush(RGB(255, 255, 255));
    g_brush_log = CreateSolidBrush(RGB(248, 250, 252));
}

static void free_ui_resources(void) {
    if (g_font_ui && g_font_ui != GetStockObject(DEFAULT_GUI_FONT)) DeleteObject(g_font_ui);
    if (g_font_bold && g_font_bold != GetStockObject(DEFAULT_GUI_FONT)) DeleteObject(g_font_bold);
    if (g_font_log && g_font_log != GetStockObject(DEFAULT_GUI_FONT) &&
        g_font_log != GetStockObject(ANSI_FIXED_FONT))
        DeleteObject(g_font_log);
    if (g_brush_panel) DeleteObject(g_brush_panel);
    if (g_brush_white) DeleteObject(g_brush_white);
    if (g_brush_log) DeleteObject(g_brush_log);
}

static HWND ui_ctrl(const char *cls, const char *text, DWORD style, int x, int y, int w, int h, int id, HFONT font) {
    HWND e = CreateWindowA(cls, text, WS_CHILD | WS_VISIBLE | style, x, y, w, h, g_hwnd,
                           (HMENU)(INT_PTR)id, GetModuleHandle(NULL), NULL);
    SendMessage(e, WM_SETFONT, (WPARAM)(font ? font : g_font_ui), TRUE);
    return e;
}

static HWND ui_group(const char *text, int x, int y, int w, int h) {
    return ui_ctrl("BUTTON", text, BS_GROUPBOX, x, y, w, h, 0, g_font_bold);
}

static void copy_edit(HWND edit, const char *okmsg) {
    int len;
    HGLOBAL hg;
    char *buf;
    if (!edit) return;
    len = GetWindowTextLengthA(edit);
    if (len <= 0) return;
    hg = GlobalAlloc(GMEM_MOVEABLE, (SIZE_T)len + 1);
    if (!hg) return;
    buf = (char *)GlobalLock(hg);
    if (!buf) {
        GlobalFree(hg);
        return;
    }
    GetWindowTextA(edit, buf, len + 1);
    GlobalUnlock(hg);
    if (OpenClipboard(g_hwnd)) {
        EmptyClipboard();
        SetClipboardData(CF_TEXT, hg);
        CloseClipboard();
        logf("%s", okmsg);
    } else {
        GlobalFree(hg);
    }
}

static void copy_logs(void) { copy_edit(g_log, "PC logs copied"); }

static int edit_is_near_bottom(HWND edit) {
    int first, lines, page;
    RECT rc;
    if (!edit) return 1;
    first = (int)SendMessageA(edit, EM_GETFIRSTVISIBLELINE, 0, 0);
    lines = (int)SendMessageA(edit, EM_GETLINECOUNT, 0, 0);
    GetClientRect(edit, &rc);
    page = (rc.bottom - rc.top) / 16;
    if (page < 1) page = 1;
    return first + page + 1 >= lines;
}

static void append_esp_local_line(const char *line) {
    int len, keep_bottom;
    if (!g_esp_log || !line || !line[0]) return;
    keep_bottom = edit_is_near_bottom(g_esp_log);
    len = GetWindowTextLengthA(g_esp_log);
    SendMessageA(g_esp_log, EM_SETSEL, len, len);
    SendMessageA(g_esp_log, EM_REPLACESEL, FALSE, (LPARAM)"[HOST] ");
    SendMessageA(g_esp_log, EM_REPLACESEL, FALSE, (LPARAM)line);
    SendMessageA(g_esp_log, EM_REPLACESEL, FALSE, (LPARAM)"\r\n");
    if (keep_bottom) {
        SendMessageA(g_esp_log, EM_SETSEL, (WPARAM)-1, (LPARAM)-1);
        SendMessageA(g_esp_log, EM_SCROLLCARET, 0, 0);
    }
}

static void set_esp_log_text(const char *joined) {
    char buf[1800];
    char clean[1800];
    int i, j = 0, keep_bottom, first_line;
    static char last_shown[1800];
    if (!g_esp_log || !joined) return;
    if (!strcmp(joined, last_shown)) return;
    snprintf(last_shown, sizeof(last_shown), "%s", joined);
    for (i = 0; joined[i] && j < (int)sizeof(clean) - 2; i++) {
        unsigned char c = (unsigned char)joined[i];
        if (c >= 32 && c < 127) clean[j++] = (char)c;
        else if (c == '\t') clean[j++] = ' ';
    }
    clean[j] = 0;
    joined = clean;
    j = 0;
    for (i = 0; joined[i] && j < (int)sizeof(buf) - 3; i++) {
        if (joined[i] == ' ' && joined[i + 1] == '|' && joined[i + 2] == ' ') {
            buf[j++] = '\r';
            buf[j++] = '\n';
            i += 2;
        } else {
            buf[j++] = joined[i];
        }
    }
    buf[j] = 0;
    keep_bottom = edit_is_near_bottom(g_esp_log);
    first_line = (int)SendMessageA(g_esp_log, EM_GETFIRSTVISIBLELINE, 0, 0);
    SendMessageA(g_esp_log, WM_SETREDRAW, FALSE, 0);
    SetWindowTextA(g_esp_log, buf);
    if (keep_bottom) {
        SendMessageA(g_esp_log, EM_SETSEL, (WPARAM)j, (LPARAM)j);
        SendMessageA(g_esp_log, EM_SCROLLCARET, 0, 0);
    } else {
        SendMessageA(g_esp_log, EM_LINESCROLL, 0, first_line);
    }
    SendMessageA(g_esp_log, WM_SETREDRAW, TRUE, 0);
    InvalidateRect(g_esp_log, NULL, TRUE);
    UpdateWindow(g_esp_log);
}

static void clear_logs(void) {
    EnterCriticalSection(&g_lock);
    g_log_ring[0] = 0;
    g_log_ring_len = 0;
    LeaveCriticalSection(&g_lock);
    if (g_log) SetWindowTextA(g_log, "");
}

static volatile int g_http_started;

static void open_browser(void) {
    if (!g_http_started) {
        g_http_started = 1;
        CreateThread(NULL, 0, http_thread, NULL, 0, NULL);
    }
    {
        int i;
        for (i = 0; i < 40 && !g_http_ready; i++) Sleep(50);
    }
    if (!g_http_ready) {
        logf("HTTP not ready - click Open browser again");
        return;
    }
    logf("Open browser clicked");
    ShellExecuteA(NULL, "open", BROWSER_URL, NULL, NULL, SW_SHOWNORMAL);
}

static void append_log_line(const char *line) {
    int len, keep_bottom;
    if (!g_log || !line) return;
    keep_bottom = edit_is_near_bottom(g_log);
    len = GetWindowTextLengthA(g_log);
    SendMessageA(g_log, EM_SETSEL, len, len);
    SendMessageA(g_log, EM_REPLACESEL, FALSE, (LPARAM)line);
    SendMessageA(g_log, EM_REPLACESEL, FALSE, (LPARAM)"\r\n");
    if (keep_bottom) {
        SendMessageA(g_log, EM_SETSEL, (WPARAM)-1, (LPARAM)-1);
        SendMessageA(g_log, EM_SCROLLCARET, 0, 0);
    }
}

static void layout(void) {
    const int m = 14;
    const int w = 748;
    int y;

    ui_group("Status", m, 8, w, 138);
    ui_ctrl("BUTTON", "Open browser", BS_PUSHBUTTON, m + w - 142, 24, 130, 28, IDC_BROWSER, g_font_ui);
    ui_ctrl("STATIC", "User:", 0, m + 12, 30, 44, 18, 0, g_font_ui);
    ui_ctrl("STATIC", g_user, 0, m + 58, 30, w - 210, 18, IDC_USER, g_font_ui);
    ui_ctrl("STATIC", "SQL:", 0, m + 12, 54, 44, 18, 0, g_font_ui);
    ui_ctrl("STATIC", g_sql_status, SS_LEFT | SS_NOPREFIX, m + 58, 52, w - 76, 36, IDC_SQL, g_font_ui);
    ui_ctrl("STATIC", "ESP:", 0, m + 12, 94, 44, 18, 0, g_font_ui);
    ui_ctrl("STATIC", g_esp_status, SS_LEFT | SS_NOPREFIX, m + 58, 94, w - 76, 18, IDC_ESP, g_font_ui);
    ui_ctrl("STATIC", "ESP API URL", 0, m + 12, 116, 88, 18, 0, g_font_ui);
    ui_ctrl("EDIT", "(waiting for ESP - this is the real POST URL)",
            WS_BORDER | ES_AUTOHSCROLL | ES_READONLY, m + 108, 114, w - 122, 22, IDC_API_USED, g_font_ui);

    y = 156;
    ui_group("SQL Server (Windows Authentication, no password)", m, y, w, 96);
    ui_ctrl("STATIC", "Server", 0, m + 16, y + 26, 56, 18, 0, g_font_ui);
    ui_ctrl("EDIT", ".\\WINCC", WS_BORDER | ES_AUTOHSCROLL, m + 76, y + 24, 220, 24, IDC_SERVER, g_font_ui);
    ui_ctrl("STATIC", "Database", 0, m + 310, y + 26, 64, 18, 0, g_font_ui);
    ui_ctrl("EDIT", "all", WS_BORDER | ES_AUTOHSCROLL, m + 378, y + 24, 160, 24, IDC_DB, g_font_ui);
    ui_ctrl("BUTTON", "Test SQL", BS_PUSHBUTTON, m + 556, y + 22, 100, 28, IDC_TEST, g_font_ui);
    ui_ctrl("STATIC", "PC reads SQL only. ESP POSTs batches to the API URL via Wi-Fi after Send.", 0,
            m + 16, y + 58, w - 32, 18, 0, g_font_ui);

    y = 262;
    ui_group("Mill API + Wi-Fi (ESP over Wi-Fi)", m, y, w, 178);
    ui_ctrl("STATIC", "API URL", 0, m + 16, y + 26, 88, 18, 0, g_font_ui);
    ui_ctrl("EDIT", "", WS_BORDER | ES_AUTOHSCROLL, m + 108, y + 24, 430, 24, IDC_API, g_font_ui);
    ui_ctrl("STATIC", "Token", 0, m + 16, y + 56, 88, 18, 0, g_font_ui);
    ui_ctrl("EDIT", "lab-token", WS_BORDER | ES_AUTOHSCROLL | ES_PASSWORD, m + 108, y + 54, 180, 24, IDC_TOKEN,
            g_font_ui);
    ui_ctrl("STATIC", "Wi-Fi SSID", 0, m + 16, y + 86, 88, 18, 0, g_font_ui);
    ui_ctrl("EDIT", "Alis", WS_BORDER | ES_AUTOHSCROLL, m + 108, y + 84, 180, 24, IDC_SSID, g_font_ui);
    ui_ctrl("STATIC", "Password", 0, m + 310, y + 86, 64, 18, 0, g_font_ui);
    ui_ctrl("EDIT", "Ali.s1380", WS_BORDER | ES_AUTOHSCROLL | ES_PASSWORD, m + 378, y + 84, 160, 24, IDC_PASS, g_font_ui);
    ui_ctrl("BUTTON", "Send to ESP32-S3", BS_PUSHBUTTON, m + 556, y + 80, 130, 28, IDC_SEND, g_font_ui);
    ui_ctrl("BUTTON", "Exit", BS_PUSHBUTTON, m + 692, y + 80, 52, 28, IDC_EXIT, g_font_ui);
    ui_ctrl("STATIC",
            "Type IP or full URL, then Send. ESP API URL above is what the board actually POSTs to.", 0,
            m + 16, y + 118, w - 32, 36, 0, g_font_ui);

    y = 450;
    ui_group("PC logs", m, y, 368, 228);
    ui_ctrl("BUTTON", "Clear", BS_PUSHBUTTON, m + 196, y + 18, 72, 24, IDC_CLEAR_LOG, g_font_ui);
    ui_ctrl("BUTTON", "Copy", BS_PUSHBUTTON, m + 276, y + 18, 72, 24, IDC_COPY_LOG, g_font_ui);
    g_log = ui_ctrl("EDIT", "", WS_BORDER | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY | WS_VSCROLL | WS_TABSTOP | ES_NOHIDESEL,
                    m + 12, y + 46, 344, 168, IDC_LOG, g_font_log);
    SendMessageA(g_log, EM_SETLIMITTEXT, LOG_MAX - 1, 0);

    ui_group("ESP32 logs (live)", m + 380, y, 368, 228);
    ui_ctrl("BUTTON", "Clear", BS_PUSHBUTTON, m + 576, y + 18, 72, 24, IDC_CLEAR_ESP, g_font_ui);
    ui_ctrl("BUTTON", "Copy", BS_PUSHBUTTON, m + 656, y + 18, 72, 24, IDC_COPY_ESP, g_font_ui);
    g_esp_log = ui_ctrl("EDIT", "Waiting for ESP OUT.JSON next to this exe...",
                        WS_BORDER | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY | WS_VSCROLL | WS_TABSTOP,
                        m + 392, y + 46, 344, 168, IDC_ESP_LOG, g_font_log);
    SendMessageA(g_esp_log, EM_SETLIMITTEXT, 4000, 0);
}

static LRESULT CALLBACK wnd(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_ERASEBKGND: {
        RECT rc;
        HDC dc = (HDC)w;
        GetClientRect(h, &rc);
        FillRect(dc, &rc, g_brush_panel ? g_brush_panel : (HBRUSH)(COLOR_BTNFACE + 1));
        return 1;
    }
    case WM_CREATE:
        g_hwnd = h;
        layout();
        apply_globals_to_gui();
        CreateThread(NULL, 0, probe_thread, NULL, 0, NULL);
        return 0;
    case WM_SIZE:
        InvalidateRect(h, NULL, TRUE);
        return 0;
    case WM_APP_LOG:
        if (l) {
            append_log_line((const char *)l);
            HeapFree(GetProcessHeap(), 0, (void *)l);
        }
        return 0;
    case WM_APP_SQL:
        if (w == 0 && l) {
            SqlResult *r = (SqlResult *)l;
            if (r->ok) {
                snprintf(g_sql_status, sizeof(g_sql_status), "SQL OK - %s  (%s)", r->database, r->detail[0] ? r->detail : r->version);
                logf("SQL connected as %s", g_user);
            } else {
                snprintf(g_sql_status, sizeof(g_sql_status), "SQL FAIL - %s", r->err);
                logf("SQL fail: %s", r->err);
            }
            SetDlgItemTextA(h, IDC_SQL, g_sql_status);
            HeapFree(GetProcessHeap(), 0, r);
        }
        SetDlgItemTextA(h, IDC_ESP, g_esp_status);
        SetDlgItemTextA(h, IDC_USER, g_user);
        SetDlgItemTextA(h, IDC_API_USED, g_esp_api_url[0] ? g_esp_api_url : "(waiting for ESP - this is the real POST URL)");
        return 0;
    case WM_APP_CFG:
        apply_globals_to_gui();
        return 0;
    case WM_APP_ESP:
        if (l) {
            set_esp_log_text((const char *)l);
            HeapFree(GetProcessHeap(), 0, (void *)l);
        }
        return 0;
    case WM_COMMAND:
        if (HIWORD(w) == BN_CLICKED && l && LOWORD(w) == IDC_BROWSER) open_browser();
        if (HIWORD(w) == BN_CLICKED && l && LOWORD(w) == IDC_TEST) CreateThread(NULL, 0, probe_thread, NULL, 0, NULL);
        if (HIWORD(w) == BN_CLICKED && l && LOWORD(w) == IDC_SEND) send_wifi();
        if (HIWORD(w) == BN_CLICKED && l && LOWORD(w) == IDC_COPY_LOG) copy_logs();
        if (HIWORD(w) == BN_CLICKED && l && LOWORD(w) == IDC_CLEAR_LOG) clear_logs();
        if (HIWORD(w) == BN_CLICKED && l && LOWORD(w) == IDC_COPY_ESP) copy_edit(g_esp_log, "ESP logs copied");
        if (HIWORD(w) == BN_CLICKED && l && LOWORD(w) == IDC_CLEAR_ESP) {
            if (g_esp_log) SetWindowTextA(g_esp_log, "");
        }
        if (HIWORD(w) == BN_CLICKED && l && LOWORD(w) == IDC_EXIT) DestroyWindow(h);
        return 0;
    case WM_CTLCOLORSTATIC: {
        HDC dc = (HDC)w;
        int id = GetDlgCtrlID((HWND)l);
        if ((HWND)l == g_log || (HWND)l == g_esp_log) {
            SetBkMode(dc, OPAQUE);
            SetBkColor(dc, RGB(248, 250, 252));
            SetTextColor(dc, RGB(35, 45, 60));
            return (INT_PTR)g_brush_log;
        }
        if (id == IDC_API_USED) {
            SetBkMode(dc, OPAQUE);
            SetBkColor(dc, RGB(255, 255, 255));
            SetTextColor(dc, RGB(55, 65, 85));
            return (INT_PTR)g_brush_white;
        }
        SetBkMode(dc, TRANSPARENT);
        if (id == IDC_SQL)
            SetTextColor(dc, strstr(g_sql_status, "SQL OK") ? RGB(0, 130, 70) : RGB(190, 45, 45));
        else if (id == IDC_ESP)
            SetTextColor(dc, RGB(0, 95, 150));
        else if (id == IDC_USER)
            SetTextColor(dc, RGB(55, 65, 85));
        else
            SetTextColor(dc, RGB(70, 80, 95));
        return (INT_PTR)g_brush_panel;
    }
    case WM_CTLCOLOREDIT:
        SetBkMode((HDC)w, OPAQUE);
        SetBkColor((HDC)w, RGB(255, 255, 255));
        SetTextColor((HDC)w, RGB(35, 45, 60));
        return (INT_PTR)g_brush_white;
    case WM_CTLCOLORBTN:
        SetBkColor((HDC)w, RGB(236, 242, 248));
        return (INT_PTR)g_brush_panel;
    case WM_CLOSE:
        ShowWindow(h, SW_HIDE);
        sync_gui_to_globals();
        save_ini();
        logf("Window hidden - use the taskbar or run OPEN.bat again. Exit to stop.");
        return 0;
    case WM_DESTROY:
        sync_gui_to_globals();
        save_ini();
        free_ui_resources();
        g_run = 0;
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(h, m, w, l);
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show) {
    WNDCLASSA wc;
    HWND h;
    MSG msg;
    (void)prev;
    (void)cmd;
    InitCommonControls();
    srand((unsigned)GetTickCount());
    InitializeCriticalSection(&g_lock);
    InitializeCriticalSection(&g_sql);
    windows_user(g_user, sizeof(g_user));
    exe_dir(g_dir, sizeof(g_dir));
    load_ini();
    init_ui_resources();
    memset(&wc, 0, sizeof(wc));
    wc.lpfnWndProc = wnd;
    wc.hInstance = inst;
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.hbrBackground = g_brush_panel;
    wc.lpszClassName = APP_NAME;
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hIcon = LoadIconA(inst, MAKEINTRESOURCEA(1));
    RegisterClassA(&wc);
    h = FindWindowA(APP_NAME, NULL);
    if (h) {
        ShowWindow(h, SW_RESTORE);
        SetForegroundWindow(h);
        return 0;
    }
    h = CreateWindowExA(WS_EX_COMPOSITED, APP_NAME, "AlisBoard " APP_VER,
                        WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN | WS_CLIPSIBLINGS,
                        40, 40, 796, 790, NULL, NULL, inst, NULL);
    ShowWindow(h, SW_SHOWNORMAL);
    SetForegroundWindow(h);
    UpdateWindow(h);
    logf("AlisBoard %s - nothing is installed on Windows", APP_VER);
    logf("Windows user: %s", g_user);
    logf("Folder: %s", g_dir);
    logf("API URL in this window: %s", g_api[0] ? g_api : "(empty - type IP or full URL then Send)");
    logf("ESP API URL line shows the address the board actually POSTs to.");
    CreateThread(NULL, 0, serial_thread, NULL, 0, NULL);
    CreateThread(NULL, 0, poll_thread, NULL, 0, NULL);
    CreateThread(NULL, 0, out_watch, NULL, 0, NULL);
    while (GetMessage(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }
    if (g_com != INVALID_HANDLE_VALUE) CloseHandle(g_com);
    DeleteCriticalSection(&g_lock);
    DeleteCriticalSection(&g_sql);
    return 0;
}
