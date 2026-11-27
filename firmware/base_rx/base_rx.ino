// Silent Sentinel base receiver
// ESP32-S3-DevKitC-1 + RFM95W, plugged into the base laptop by USB.
// Same wiring as a node's LoRa module (no mics). Forwards every packet as:
//   PKT <rssi_dbm> <snr_db> <hex payload>
// which `python -m cuas run --serial <port>` reads.
// Downlink: the C2 writes `TX <hex payload>\n` on the same port; this transmits it
// (e.g. a HINT packet) and answers `TXOK <bytes>` or `TXERR <reason>`.
#include <Arduino.h>
#include <SPI.h>
#include <LoRa.h>
#include "../node/config.h"

static void out(const char *s) { Serial.print(s); Serial0.print(s); }

static void led(uint8_t r, uint8_t g, uint8_t b) {
#ifdef RGB_BUILTIN
  rgbLedWrite(RGB_BUILTIN, r, g, b);
#endif
}

void setup() {
  Serial.begin(115200);
  Serial0.begin(115200);
  Serial.setTxTimeoutMs(0);  // never stall the audio loop when no laptop is on the USB port
  delay(500);
  SPI.begin(PIN_LORA_SCK, PIN_LORA_MISO, PIN_LORA_MOSI, PIN_LORA_CS);
  LoRa.setSPI(SPI);
  LoRa.setPins(PIN_LORA_CS, PIN_LORA_RST, PIN_LORA_DIO0);
  while (!LoRa.begin(LORA_FREQ_HZ)) {
    out("FAULT: RFM95W not found (check SPI wiring)\n");
    led(40, 0, 40);
    delay(2000);
  }
  LoRa.setSpreadingFactor(LORA_SF);
  LoRa.setSignalBandwidth(LORA_BW_HZ);
  LoRa.setCodingRate4(LORA_CR4);
  LoRa.setSyncWord(LORA_SYNC);
  LoRa.enableCrc();
  out("HELLO silent-sentinel-base v1\n");
  led(0, 20, 0);
}

static int hexval(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static void downlink() {
  static char line[600];
  static int len = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c != '\n' && c != '\r') {
      if (len < (int)sizeof(line) - 1) line[len++] = c;
      continue;
    }
    line[len] = 0;
    int n = len;
    len = 0;
    if (n < 4 || strncmp(line, "TX ", 3) != 0) continue;
    uint8_t buf[255];
    int k = 0;
    const char *h = line + 3;
    bool ok = true;
    while (h[0] && h[1] && k < (int)sizeof(buf)) {
      int a = hexval(h[0]), b = hexval(h[1]);
      if (a < 0 || b < 0) { ok = false; break; }
      buf[k++] = (uint8_t)(a << 4 | b);
      h += 2;
    }
    if (!ok || k == 0) { out("TXERR bad hex\n"); continue; }
    LoRa.beginPacket();
    LoRa.write(buf, k);
    LoRa.endPacket();  // blocking ~15 ms; radio drops back to receive on the next parsePacket()
    char msg[24];
    snprintf(msg, sizeof(msg), "TXOK %d\n", k);
    out(msg);
    led(40, 20, 0);
  }
}

void loop() {
  downlink();
  int n = LoRa.parsePacket();
  if (n <= 0) return;
  static uint8_t buf[256];
  int len = 0;
  while (LoRa.available() && len < (int)sizeof(buf)) buf[len++] = LoRa.read();
  char line[16 + 2 * sizeof(buf)];
  int k = snprintf(line, sizeof(line), "PKT %d %.1f ", LoRa.packetRssi(), LoRa.packetSnr());
  for (int i = 0; i < len; i++) k += snprintf(line + k, sizeof(line) - k, "%02x", buf[i]);
  snprintf(line + k, sizeof(line) - k, "\n");
  out(line);
  led(0, 0, 40);
  delay(20);
  led(0, 20, 0);
}
