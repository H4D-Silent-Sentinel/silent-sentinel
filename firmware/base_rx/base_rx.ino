// Silent Sentinel base receiver
// ESP32-S3-DevKitC-1 + RFM95W, plugged into the base laptop by USB.
// Same wiring as a node's LoRa module (no mics). Forwards every packet as:
//   PKT <rssi_dbm> <snr_db> <hex payload>
// which `python -m cuas run --serial <port>` reads.
#include <Arduino.h>
#include <SPI.h>
#include <LoRa.h>
#include "../node/config.h"

static void led(uint8_t r, uint8_t g, uint8_t b) {
#ifdef RGB_BUILTIN
  rgbLedWrite(RGB_BUILTIN, r, g, b);
#endif
}

void setup() {
  Serial.begin(115200);
  delay(500);
  SPI.begin(PIN_LORA_SCK, PIN_LORA_MISO, PIN_LORA_MOSI, PIN_LORA_CS);
  LoRa.setSPI(SPI);
  LoRa.setPins(PIN_LORA_CS, PIN_LORA_RST, PIN_LORA_DIO0);
  while (!LoRa.begin(LORA_FREQ_HZ)) {
    Serial.println("FAULT: RFM95W not found (check SPI wiring)");
    led(40, 0, 40);
    delay(2000);
  }
  LoRa.setSpreadingFactor(LORA_SF);
  LoRa.setSignalBandwidth(LORA_BW_HZ);
  LoRa.setCodingRate4(LORA_CR4);
  LoRa.setSyncWord(LORA_SYNC);
  LoRa.enableCrc();
  Serial.println("HELLO silent-sentinel-base v1");
  led(0, 20, 0);
}

void loop() {
  int n = LoRa.parsePacket();
  if (n <= 0) return;
  static uint8_t buf[256];
  int len = 0;
  while (LoRa.available() && len < (int)sizeof(buf)) buf[len++] = LoRa.read();
  Serial.printf("PKT %d %.1f ", LoRa.packetRssi(), LoRa.packetSnr());
  for (int i = 0; i < len; i++) Serial.printf("%02x", buf[i]);
  Serial.println();
  led(0, 0, 40);
  delay(20);
  led(0, 20, 0);
}
