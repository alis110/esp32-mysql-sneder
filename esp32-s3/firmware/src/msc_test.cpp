#if ARDUINO_USB_MODE
#error msc test needs ARDUINO_USB_MODE=0
#endif
#include <Arduino.h>
#include "USB.h"
#include "USBMSC.h"

USBMSC MSC;

#define FAT_U8(v) ((v) & 0xFF)
#define FAT_U16(v) FAT_U8(v), FAT_U8((v) >> 8)

static const uint32_t DISK_SECTOR_COUNT = 16;
static const uint16_t DISK_SECTOR_SIZE = 512;
static uint8_t msc_disk[DISK_SECTOR_COUNT][DISK_SECTOR_SIZE];

static int32_t onWrite(uint32_t lba, uint32_t offset, uint8_t *buffer, uint32_t bufsize) {
  if (lba >= DISK_SECTOR_COUNT) return -1;
  memcpy(msc_disk[lba] + offset, buffer, bufsize);
  return bufsize;
}

static int32_t onRead(uint32_t lba, uint32_t offset, void *buffer, uint32_t bufsize) {
  if (lba >= DISK_SECTOR_COUNT) return -1;
  memcpy(buffer, msc_disk[lba] + offset, bufsize);
  return bufsize;
}

void setup() {
  memset(msc_disk, 0, sizeof(msc_disk));
  msc_disk[0][510] = 0x55;
  msc_disk[0][511] = 0xAA;
  memcpy(msc_disk[0] + 3, "MSDOS5.0", 8);
  msc_disk[0][11] = 0x00;
  msc_disk[0][12] = 0x02;
  MSC.vendorID("Alis");
  MSC.productID("Board");
  MSC.onRead(onRead);
  MSC.onWrite(onWrite);
  MSC.mediaPresent(true);
  MSC.begin(DISK_SECTOR_COUNT, DISK_SECTOR_SIZE);
  USB.begin();
}

void loop() { delay(1000); }
