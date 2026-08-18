#include "msc_disk.h"

#include "USB.h"
#include "USBMSC.h"

#include "msc_image.h"

namespace {

USBMSC MSC;
uint8_t inBuf[MSC_IN_SECTORS * 512];
uint8_t outBuf[MSC_OUT_SECTORS * 512];
uint8_t queueBuf[MSC_QUEUE_SECTORS * 512];

constexpr int kDirtyMax = 48;
uint32_t dirtyLba[kDirtyMax];
uint8_t dirtyData[kDirtyMax][512];
int dirtyCount = 0;

volatile bool inDirty = false;
volatile bool queueDirty = false;
volatile bool hostMounted = false;
uint32_t inMs = 0;
uint32_t queueMs = 0;

int dirtyFind(uint32_t lba) {
  for (int i = 0; i < dirtyCount; i++) {
    if (dirtyLba[i] == lba) return i;
  }
  return -1;
}

uint8_t *writablePtr(uint32_t lba, uint32_t *maxLen) {
  if (lba >= MSC_IN_LBA && lba < MSC_IN_LBA + MSC_IN_SECTORS) {
    uint32_t off = (lba - MSC_IN_LBA) * 512;
    *maxLen = sizeof(inBuf) - off;
    return inBuf + off;
  }
  if (lba >= MSC_OUT_LBA && lba < MSC_OUT_LBA + MSC_OUT_SECTORS) {
    uint32_t off = (lba - MSC_OUT_LBA) * 512;
    *maxLen = sizeof(outBuf) - off;
    return outBuf + off;
  }
  if (lba >= MSC_QUEUE_LBA && lba < MSC_QUEUE_LBA + MSC_QUEUE_SECTORS) {
    uint32_t off = (lba - MSC_QUEUE_LBA) * 512;
    *maxLen = sizeof(queueBuf) - off;
    return queueBuf + off;
  }
  return nullptr;
}

int32_t onRead(uint32_t lba, uint32_t offset, void *buffer, uint32_t bufsize) {
  if (lba >= MSC_SECTOR_COUNT) return -1;
  int di = dirtyFind(lba);
  if (di >= 0) {
    memcpy(buffer, dirtyData[di] + offset, bufsize);
    return bufsize;
  }
  uint32_t room = 0;
  uint8_t *src = writablePtr(lba, &room);
  if (src && offset + bufsize <= room) {
    memcpy(buffer, src + offset, bufsize);
    return bufsize;
  }
  const uint8_t *flash = MSC_IMAGE + lba * 512 + offset;
  memcpy(buffer, flash, bufsize);
  return bufsize;
}

int32_t onWrite(uint32_t lba, uint32_t offset, uint8_t *buffer, uint32_t bufsize) {
  if (lba >= MSC_SECTOR_COUNT) return -1;
  uint32_t room = 0;
  uint8_t *dst = writablePtr(lba, &room);
  if (dst && offset + bufsize <= room) {
    memcpy(dst + offset, buffer, bufsize);
    if (lba >= MSC_IN_LBA && lba < MSC_IN_LBA + MSC_IN_SECTORS) {
      inDirty = true;
      inMs = millis();
    }
    if (lba >= MSC_QUEUE_LBA && lba < MSC_QUEUE_LBA + MSC_QUEUE_SECTORS) {
      queueDirty = true;
      queueMs = millis();
    }
    return bufsize;
  }
  int di = dirtyFind(lba);
  if (di < 0) {
    if (dirtyCount >= kDirtyMax) di = 0;
    else di = dirtyCount++;
    dirtyLba[di] = lba;
    memcpy(dirtyData[di], MSC_IMAGE + lba * 512, 512);
  }
  memcpy(dirtyData[di] + offset, buffer, bufsize);
  return bufsize;
}

bool onStartStop(uint8_t, bool start, bool) {
  hostMounted = start;
  return true;
}

void copyRegion(uint8_t *dst, uint32_t lba, uint32_t sectors) {
  memcpy(dst, MSC_IMAGE + lba * 512, sectors * 512);
}

String trimJson(uint8_t *buf, uint32_t len) {
  int start = -1, end = -1;
  for (uint32_t i = 0; i < len; i++) {
    if (buf[i] == '{') {
      start = static_cast<int>(i);
      break;
    }
  }
  if (start < 0) return String();
  for (int i = static_cast<int>(len) - 1; i >= start; i--) {
    if (buf[i] == '}') {
      end = i;
      break;
    }
  }
  if (end < start) return String();
  String s;
  s.reserve(end - start + 2);
  for (int i = start; i <= end; i++) s += static_cast<char>(buf[i]);
  return s;
}

}  // namespace

void mscInit() {
  copyRegion(inBuf, MSC_IN_LBA, MSC_IN_SECTORS);
  copyRegion(outBuf, MSC_OUT_LBA, MSC_OUT_SECTORS);
  copyRegion(queueBuf, MSC_QUEUE_LBA, MSC_QUEUE_SECTORS);

  MSC.vendorID("Alis");
  MSC.productID("AlisBoard");
  MSC.productRevision("1.0");
  MSC.onStartStop(onStartStop);
  MSC.onRead(onRead);
  MSC.onWrite(onWrite);
  MSC.mediaPresent(true);
  MSC.begin(MSC_SECTOR_COUNT, 512);
}

void mscBegin() {
  mscInit();
  USB.begin();
}

void mscLoop() {}

bool mscTakeInbox(JsonDocument &doc) {
  static String lastIn;
  static uint32_t lastPollMs = 0;

  /* Process dirty write (USB cable write-through) */
  if (inDirty && millis() - inMs >= 400) {
    inDirty = false;
    String js = trimJson(inBuf, sizeof(inBuf));
    if (js.length() >= 12 && js.indexOf("\"command\"") >= 0 && js != lastIn) {
      if (!deserializeJson(doc, js)) {
        lastIn = js;
        memset(inBuf, ' ', sizeof(inBuf));
        memcpy(inBuf, "{}", 2);
        return true;
      }
    }
    memset(inBuf, ' ', sizeof(inBuf));
    memcpy(inBuf, "{}", 2);
    return false;
  }

  /* Poll every 500ms in case Windows cached the write and inDirty was never set */
  if (millis() - lastPollMs < 500) return false;
  lastPollMs = millis();

  String js = trimJson(inBuf, sizeof(inBuf));
  if (js.length() < 12 || js.indexOf("\"command\"") < 0) return false;
  if (js == lastIn) return false;
  if (deserializeJson(doc, js)) return false;
  lastIn = js;
  /* Clear so it doesn't fire again next poll */
  memset(inBuf, ' ', sizeof(inBuf));
  memcpy(inBuf, "{}", 2);
  return true;
}

bool mscTakeQueue(String &json) {
  if (queueDirty && millis() - queueMs >= 400) {
    queueDirty = false;
    json = trimJson(queueBuf, sizeof(queueBuf));
    memset(queueBuf, ' ', sizeof(queueBuf));
    memcpy(queueBuf, "{}", 2);
    return json.length() > 2;
  }
  json = trimJson(queueBuf, sizeof(queueBuf));
  if (json.length() <= 2 || json == "{}") return false;
  if (json.indexOf("sql_sync") < 0 && json.indexOf("\"type\"") < 0) return false;
  static String lastQueue;
  if (json == lastQueue) return false;
  lastQueue = json;
  memset(queueBuf, ' ', sizeof(queueBuf));
  memcpy(queueBuf, "{}", 2);
  return true;
}

bool mscHostMounted() { return hostMounted; }

void mscWriteOut(const char *json) {
  memset(outBuf, ' ', sizeof(outBuf));
  size_t n = strlen(json);
  if (n > sizeof(outBuf) - 1) n = sizeof(outBuf) - 1;
  memcpy(outBuf, json, n);
}
