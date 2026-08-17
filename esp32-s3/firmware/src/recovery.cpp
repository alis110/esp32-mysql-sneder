#include <Arduino.h>

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("AlisBoard recovery — ready for upload. Flash env esp32-s3 next.");
}

void loop() {
  delay(1000);
  Serial.println("recovery ok");
}
