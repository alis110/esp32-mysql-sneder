#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

void mscBegin();
void mscInit();
void mscLoop();
bool mscTakeInbox(JsonDocument &doc);
bool mscTakeQueue(String &json);
void mscWriteOut(const char *json);
bool mscHostMounted();
