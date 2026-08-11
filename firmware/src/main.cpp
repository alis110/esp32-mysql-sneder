#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <esp_task_wdt.h>

#include "secrets.h"

namespace {
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr size_t MAX_LINE_BYTES = 16384;
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 15000;
constexpr uint32_t HTTP_TIMEOUT_MS = 8000;
constexpr uint8_t HTTP_ATTEMPTS = 2;
constexpr uint32_t RETRY_DELAY_MS = 1000;
constexpr uint32_t WATCHDOG_SECONDS = 60;

String inputLine;

void sendReply(const char *type, JsonVariantConst id, const char *detailKey, const char *detail) {
  JsonDocument reply;
  reply["type"] = type;
  reply["id"].set(id);
  reply[detailKey] = detail;
  serializeJson(reply, Serial);
  Serial.println();
}

void sendNack(JsonVariantConst id, const char *error) {
  sendReply("nack", id, "error", error);
}

void sendEvent(const char *event, const char *detail = "") {
  JsonDocument reply;
  reply["type"] = "event";
  reply["event"] = event;
  if (detail && detail[0]) reply["detail"] = detail;
  serializeJson(reply, Serial);
  Serial.println();
}

bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.disconnect();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  const uint32_t started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < WIFI_CONNECT_TIMEOUT_MS) {
    esp_task_wdt_reset();
    delay(250);
  }
  return WiFi.status() == WL_CONNECTED;
}

int postJson(const String &body, const String &idempotencyKey, String &error) {
  // Diagnose TCP reachability to the API host before HTTPClient.
  {
    String url = API_URL;
    int scheme = url.indexOf("://");
    String rest = scheme >= 0 ? url.substring(scheme + 3) : url;
    int slash = rest.indexOf('/');
    String hostPort = slash >= 0 ? rest.substring(0, slash) : rest;
    int colon = hostPort.indexOf(':');
    String host = colon >= 0 ? hostPort.substring(0, colon) : hostPort;
    uint16_t port = 80;
    if (colon >= 0) port = static_cast<uint16_t>(hostPort.substring(colon + 1).toInt());
    if (url.startsWith("https://") && colon < 0) port = 443;

    WiFiClient probe;
    sendEvent("tcp_try", (host + ":" + String(port)).c_str());
    if (!probe.connect(host.c_str(), port)) {
      error = "tcp_connect_failed";
      sendEvent("tcp_fail", host.c_str());
      return -1;
    }
    probe.stop();
    sendEvent("tcp_ok");
  }

  HTTPClient http;
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  bool begun = false;
  WiFiClient plainClient;
  WiFiClientSecure secureClient;

  if (String(API_URL).startsWith("https://")) {
#if ALLOW_INSECURE_TLS
    secureClient.setInsecure();
#else
    secureClient.setCACert(ROOT_CA);
#endif
    begun = http.begin(secureClient, API_URL);
  } else {
    begun = http.begin(plainClient, API_URL);
  }
  if (!begun) {
    error = "http_begin_failed";
    return -1;
  }
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + API_TOKEN);
  http.addHeader("Idempotency-Key", idempotencyKey);
  int status = http.POST(body);
  if (status < 0) {
    error = http.errorToString(status).c_str();
    if (error.length() == 0) error = "http_transport_error";
  }
  http.end();
  return status;
}

void handleLine(const String &line) {
  JsonDocument incoming;
  DeserializationError parseError = deserializeJson(incoming, line);
  if (parseError) {
    JsonDocument nullId;
    nullId["id"] = nullptr;
    sendNack(nullId["id"], "invalid_json");
    return;
  }
  JsonVariantConst id = incoming["id"];
  if (incoming["type"] != "data" || id.isNull() || incoming["payload"].isNull()) {
    sendNack(id, "invalid_envelope");
    return;
  }
  String idempotencyKey = incoming["idempotency_key"] | "";
  if (idempotencyKey.length() == 0) {
    sendNack(id, "missing_idempotency_key");
    return;
  }

  sendEvent("wifi_check");
  if (!ensureWiFi()) {
    sendNack(id, "wifi_unavailable");
    return;
  }
  sendEvent("wifi_ok", WiFi.localIP().toString().c_str());

  String body;
  serializeJson(incoming, body);
  String error = "http_failed";
  int status = -1;
  for (uint8_t attempt = 0; attempt < HTTP_ATTEMPTS; ++attempt) {
    esp_task_wdt_reset();
    if (!ensureWiFi()) {
      error = "wifi_unavailable";
    } else {
      sendEvent("http_post");
      status = postJson(body, idempotencyKey, error);
      if (status >= 200 && status < 300) {
        sendReply("ack", id, "status", "success");
        return;
      }
      if (status >= 400 && status < 500 && status != 408 && status != 429) {
        error = "http_non_retryable";
        break;
      }
      char detail[48];
      snprintf(detail, sizeof(detail), "status=%d", status);
      sendEvent("http_retry", detail);
      error = status > 0 ? "http_status_error" : error;
    }
    delay(RETRY_DELAY_MS);
  }
  sendNack(id, error.c_str());
}
}  // namespace

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);
  inputLine.reserve(MAX_LINE_BYTES);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  esp_task_wdt_init(WATCHDOG_SECONDS, true);
  esp_task_wdt_add(nullptr);
  sendEvent("boot");
  if (ensureWiFi()) {
    sendEvent("ready", WiFi.localIP().toString().c_str());
  } else {
    sendEvent("ready", "wifi_pending");
  }
}

void loop() {
  esp_task_wdt_reset();
  while (Serial.available()) {
    char c = static_cast<char>(Serial.read());
    if (c == '\n') {
      inputLine.trim();
      if (!inputLine.isEmpty()) handleLine(inputLine);
      inputLine = "";
    } else if (c != '\r') {
      if (inputLine.length() >= MAX_LINE_BYTES) {
        inputLine = "";
        JsonDocument nullId;
        nullId["id"] = nullptr;
        sendNack(nullId["id"], "line_too_long");
      } else {
        inputLine += c;
      }
    }
  }
  if (WiFi.status() != WL_CONNECTED) WiFi.reconnect();
  delay(5);
}
