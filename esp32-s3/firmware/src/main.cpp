#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <esp_system.h>

#include "USB.h"

#include "config.h"
#include "favicon.h"
#include "msc_disk.h"
#include "webui.h"

namespace {

Preferences prefs;
WebServer server(80);
String logs[80];
uint8_t logHead = 0;
uint8_t logCount = 0;
uint32_t lastPollMs = 0;
uint32_t lastOutMs = 0;
uint32_t lastDrainMs = 0;
uint32_t bootMs = 0;
bool wifiStarted = false;
bool httpStarted = false;
bool wifiLoggedUp = false;
String lastOutBody;
int64_t lastId = 0;
bool lastHelperOk = false;
bool lastSqlOk = false;
bool lastApiOk = false;
String lastApiDetail = "never";
String helperUser;
String helperDb;
String helperError;
uint32_t helperReq = 1;
JsonDocument inboxDoc;

String getPref(const char *key, const char *fallback) {
  String v = prefs.getString(key, fallback);
  v.trim();
  return v.length() ? v : String(fallback);
}

void addLog(const String &line) {
  String stamped = String(millis() / 1000) + "s " + line;
  logs[logHead] = stamped;
  logHead = (logHead + 1) % 80;
  if (logCount < 80) logCount++;
}

void collectLogs(JsonArray arr) {
  uint8_t n = logCount;
  uint8_t start = (logHead + 80 - n) % 80;
  for (uint8_t i = 0; i < n; i++) arr.add(logs[(start + i) % 80]);
}

void connectWifi() {
  String ssid = getPref("wifi_ssid", "");
  String pass = getPref("wifi_pass", "");
  if (!ssid.length()) {
    addLog("Wi-Fi: no SSID saved");
    return;
  }
  addLog("Wi-Fi scan for " + ssid);
  int n = WiFi.scanNetworks(false, true);
  bool found = false;
  int32_t rssi = 0;
  for (int i = 0; i < n; i++) {
    if (ssid == WiFi.SSID(i)) {
      found = true;
      rssi = WiFi.RSSI(i);
      break;
    }
  }
  if (found) addLog("found " + ssid + " rssi=" + String(rssi));
  else addLog("SSID not in scan (" + String(n) + " APs) - still trying");
  WiFi.scanDelete();
  WiFi.disconnect(true);
  delay(50);
  WiFi.begin(ssid.c_str(), pass.c_str());
  addLog("Wi-Fi joining " + ssid);
}

void sendStatus();
void handleRoot();
void handleFavicon();
void handleSql();
void handleWifi();
void handleApi();
void handleTestSql();
void handleTestApi();

void startHttpServer() {
  if (httpStarted) return;
  httpStarted = true;
  server.on("/", handleRoot);
  server.on("/favicon.ico", handleFavicon);
  server.on("/api/status", HTTP_GET, sendStatus);
  server.on("/api/sql", HTTP_POST, handleSql);
  server.on("/api/wifi", HTTP_POST, handleWifi);
  server.on("/api/api", HTTP_POST, handleApi);
  server.on("/api/test-sql", HTTP_POST, handleTestSql);
  server.on("/api/test-api", HTTP_POST, handleTestApi);
  server.on("/api/logs/clear", HTTP_POST, []() {
    logCount = 0;
    logHead = 0;
    server.send(200, "application/json", "{\"ok\":true}");
  });
  server.on("/api/restart", HTTP_POST, []() {
    server.send(200, "application/json", "{\"ok\":true}");
    delay(200);
    ESP.restart();
  });
  server.begin();
  addLog("HTTP http://192.168.4.1");
}

void ensureWifiRadio() {
  if (wifiStarted) return;
  wifiStarted = true;
  WiFi.mode(WIFI_AP_STA);
  WiFi.setTxPower(WIFI_POWER_8_5dBm);
  WiFi.softAP(AP_SSID, AP_PASS);
  startHttpServer();
  addLog("Wi-Fi AP " + String(AP_SSID));
}

void applyHost(JsonDocument &doc) {
  const char *cmd = doc["command"] | "";
  if (!strcmp(cmd, "set_wifi")) {
    if (doc["ssid"].is<const char *>()) prefs.putString("wifi_ssid", doc["ssid"].as<String>());
    if (doc["password"].is<const char *>()) prefs.putString("wifi_pass", doc["password"].as<String>());
    if (doc["api_url"].is<const char *>()) prefs.putString("api_url", doc["api_url"].as<String>());
    if (doc["api_token"].is<const char *>()) prefs.putString("api_token", doc["api_token"].as<String>());
    ensureWifiRadio();
    connectWifi();
    addLog("Wi-Fi/API from AlisBoard.exe");
  } else if (!strcmp(cmd, "start_ap")) {
    ensureWifiRadio();
    addLog("Wi-Fi AP started (manual)");
  } else if (!strcmp(cmd, "set_api")) {
    if (doc["url"].is<const char *>()) prefs.putString("api_url", doc["url"].as<String>());
    if (doc["token"].is<const char *>()) prefs.putString("api_token", doc["token"].as<String>());
    addLog("API from AlisBoard.exe");
  }
}

int httpPost(const String &url, const String &body, const String &auth, String &response) {
  HTTPClient http;
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  WiFiClient client;
  if (!http.begin(client, url)) return -1;
  http.addHeader("Content-Type", "application/json");
  if (auth.length()) http.addHeader("Authorization", auth);
  int code = http.POST(body);
  response = http.getString();
  http.end();
  return code;
}

bool callHelper(const char *command, const char *queryId, int64_t afterId, JsonDocument &out) {
  JsonDocument req;
  req["v"] = 1;
  req["id"] = helperReq++;
  req["command"] = command;
  req["query_id"] = queryId;
  req["after_id"] = afterId;
  req["batch_size"] = 1;
  req["server"] = getPref("sql_server", SQL_DEFAULT_SERVER);
  req["database"] = getPref("sql_db", SQL_DEFAULT_DATABASE);

  String url = getPref("helper_url", HELPER_DEFAULT_URL);
  if (!url.endsWith("/v1/query")) {
    if (url.endsWith("/")) url.remove(url.length() - 1);
    url += "/v1/query";
  }
  String body;
  serializeJson(req, body);
  String resp;
  int code = httpPost(url, body, "", resp);
  if (code < 0) {
    out["ok"] = false;
    out["error"] = "helper_http_fail";
    return false;
  }
  if (deserializeJson(out, resp)) {
    out.clear();
    out["ok"] = false;
    out["error"] = "helper_bad_json";
    return false;
  }
  bool ok = out["ok"] == true;
  lastHelperOk = out["windows_user"].is<const char *>() || ok;
  helperUser = out["windows_user"] | "";
  helperDb = out["database"] | "";
  helperError = out["error"] | "";
  if (ok) lastSqlOk = true;
  return ok;
}

void postBody(const String &body, int64_t id) {
  String url = getPref("api_url", API_DEFAULT_URL);
  String token = getPref("api_token", API_DEFAULT_TOKEN);
  String auth = token.length() ? ("Bearer " + token) : "";
  String resp;
  int code = httpPost(url, body, auth, resp);
  lastApiOk = code >= 200 && code < 300;
  lastApiDetail = String(code);
  if (lastApiOk) {
    if (id > 0) {
      lastId = id;
      prefs.putLong64("last_id", lastId);
    }
    addLog(String("sent id=") + id);
  } else {
    addLog("API fail " + lastApiDetail);
  }
}

void postRow(JsonObjectConst row) {
  int64_t id = row["id"] | 0;
  if (id <= 0) return;
  char idbuf[24];
  snprintf(idbuf, sizeof(idbuf), "%lld", static_cast<long long>(id));
  JsonDocument env;
  env["type"] = "data";
  env["id"] = id;
  env["idempotency_key"] = String("plc-record-") + idbuf;
  JsonObject payload = env["payload"].to<JsonObject>();
  for (JsonPairConst kv : row) payload[kv.key()] = kv.value();
  String body;
  serializeJson(env, body);
  postBody(body, id);
}

void writeStatusFile() {
  if (mscHostMounted()) return;
  JsonDocument doc;
  doc["ok"] = true;
  doc["wifi_ok"] = WiFi.status() == WL_CONNECTED;
  doc["wifi_ip"] = WiFi.localIP().toString();
  doc["wifi_ssid"] = getPref("wifi_ssid", "");
  doc["api_ok"] = lastApiOk;
  doc["api_detail"] = lastApiDetail;
  doc["sql_connected"] = lastSqlOk;
  String body;
  serializeJson(doc, body);
  if (body == lastOutBody) return;
  lastOutBody = body;
  mscWriteOut(body.c_str());
}

void drainQueue() {
  if (millis() - lastDrainMs < 20000) return;
  String queued;
  if (!mscTakeQueue(queued)) return;
  if (queued.length() > 1500) {
    addLog("ESP skip large queue (PC does backfill)");
    lastDrainMs = millis();
    return;
  }
  if (queued.indexOf("\"sql_sync\"") >= 0) {
    addLog("ESP skip sql_sync (PC crawl)");
    lastDrainMs = millis();
    return;
  }
  lastDrainMs = millis();
  postBody(queued, 0);
  lastHelperOk = true;
  lastSqlOk = true;
}

void pollOnce() {
  JsonDocument helper;
  if (!callHelper("query", "tlg_f", lastId, helper)) {
    addLog(String("Helper: ") + helperError);
    return;
  }
  JsonArrayConst rows = helper["rows"].as<JsonArrayConst>();
  if (rows.isNull() || rows.size() == 0) {
    addLog("SQL 0 rows (TagUncompressed empty?)");
    return;
  }
  for (JsonVariantConst row : rows) {
    if (row.is<JsonObjectConst>()) postRow(row.as<JsonObjectConst>());
  }
}

void sendStatus() {
  JsonDocument doc;
  doc["firmware"] = ALISBOARD_VERSION;
  doc["wifi_ok"] = WiFi.status() == WL_CONNECTED;
  doc["wifi_ip"] = WiFi.localIP().toString();
  doc["wifi_ssid"] = getPref("wifi_ssid", "");
  doc["ap_ip"] = WiFi.softAPIP().toString();
  doc["api_ok"] = lastApiOk;
  doc["api_detail"] = lastApiDetail;
  doc["api_url"] = getPref("api_url", API_DEFAULT_URL);
  doc["helper_url"] = getPref("helper_url", HELPER_DEFAULT_URL);
  doc["sql_server"] = getPref("sql_server", SQL_DEFAULT_SERVER);
  doc["sql_database"] = getPref("sql_db", SQL_DEFAULT_DATABASE);
  doc["last_id"] = lastId;
  JsonObject h = doc["helper"].to<JsonObject>();
  h["ok"] = lastHelperOk;
  h["sql_connected"] = lastSqlOk;
  h["windows_user"] = helperUser;
  h["database"] = helperDb;
  h["error"] = helperError;
  collectLogs(doc["logs"].to<JsonArray>());
  String body;
  serializeJson(doc, body);
  server.send(200, "application/json", body);
}

String jsonBody() { return server.arg("plain"); }

void handleRoot() { server.send_P(200, "text/html", WEBUI_HTML); }

void handleFavicon() {
  server.setContentLength(FAVICON_ICO_LEN);
  server.send(200, "image/x-icon", "");
  WiFiClient client = server.client();
  for (size_t i = 0; i < FAVICON_ICO_LEN; i++) client.write(pgm_read_byte(FAVICON_ICO + i));
}

void handleSql() {
  JsonDocument doc;
  deserializeJson(doc, jsonBody());
  if (doc["server"].is<const char *>()) prefs.putString("sql_server", doc["server"].as<String>());
  if (doc["database"].is<const char *>()) prefs.putString("sql_db", doc["database"].as<String>());
  addLog("SQL settings saved");
  server.send(200, "application/json", "{\"ok\":true}");
}

void handleWifi() {
  JsonDocument doc;
  deserializeJson(doc, jsonBody());
  prefs.putString("wifi_ssid", doc["ssid"] | "");
  prefs.putString("wifi_pass", doc["password"] | "");
  ensureWifiRadio();
  connectWifi();
  server.send(200, "application/json", "{\"ok\":true}");
}

void handleApi() {
  JsonDocument doc;
  deserializeJson(doc, jsonBody());
  if (doc["url"].is<const char *>()) prefs.putString("api_url", doc["url"].as<String>());
  if (doc["token"].is<const char *>()) prefs.putString("api_token", doc["token"].as<String>());
  if (doc["helper_url"].is<const char *>()) prefs.putString("helper_url", doc["helper_url"].as<String>());
  addLog("API settings saved");
  server.send(200, "application/json", "{\"ok\":true}");
}

void handleTestSql() {
  JsonDocument out;
  callHelper("probe", "tlg_f", 0, out);
  String body;
  serializeJson(out, body);
  server.send(200, "application/json", body);
}

void handleTestApi() {
  String url = getPref("api_url", API_DEFAULT_URL);
  int scheme = url.indexOf("://");
  String rest = scheme >= 0 ? url.substring(scheme + 3) : url;
  int slash = rest.indexOf('/');
  String hostPort = slash >= 0 ? rest.substring(0, slash) : rest;
  int colon = hostPort.indexOf(':');
  String host = colon >= 0 ? hostPort.substring(0, colon) : hostPort;
  uint16_t port = 80;
  if (colon >= 0) port = static_cast<uint16_t>(hostPort.substring(colon + 1).toInt());
  WiFiClient c;
  bool ok = c.connect(host.c_str(), port);
  c.stop();
  lastApiOk = ok;
  lastApiDetail = ok ? "tcp_ok" : "tcp_fail";
  addLog("API probe " + lastApiDetail + " " + host);
  server.send(200, "application/json", ok ? "{\"ok\":true}" : "{\"ok\":false}");
}

}  // namespace

void setup() {
  bootMs = millis();
  mscInit();
  USB.begin();

  prefs.begin("alisboard", false);
  lastId = prefs.getLong64("last_id", 0);

  addLog("AlisBoard " + String(ALISBOARD_VERSION));
  addLog("USB MSC only — run AlisBoard.exe on drive G:");
}

void loop() {
  if (wifiStarted) {
    server.handleClient();
    drainQueue();
    if (WiFi.status() == WL_CONNECTED) {
      if (!wifiLoggedUp) {
        wifiLoggedUp = true;
        addLog("Wi-Fi up " + WiFi.SSID() + " " + WiFi.localIP().toString());
      }
    } else if (wifiLoggedUp) {
      wifiLoggedUp = false;
      addLog("Wi-Fi lost - scanning again");
      connectWifi();
    }
    if (millis() - lastOutMs >= OUT_UPDATE_INTERVAL_MS) {
      lastOutMs = millis();
      writeStatusFile();
    }
  }

  inboxDoc.clear();
  if (mscTakeInbox(inboxDoc)) applyHost(inboxDoc);

  delay(10);
}
