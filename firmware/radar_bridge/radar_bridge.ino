// Silent Sentinel radar bridge: Ai-Thinker RD-03D <-> USB, bytes passed straight through.
// The base laptop (cuas/radar.py) does all the parsing and sends the multi-target command.
//
// Wiring (ESP32-S3-DevKitC-1; same pins are free on a listening node):
//   RD-03D 5V  -> 5V (VBUS)   (it does not run reliably on 3.3 V)
//   RD-03D GND -> GND
//   RD-03D TX  -> GPIO17 (ESP RX)
//   RD-03D RX  -> GPIO18 (ESP TX)    UART logic is 3.3 V, no level shifter needed
#include <Arduino.h>

#define PIN_RADAR_RX 17
#define PIN_RADAR_TX 18
#define RADAR_BAUD 256000

static uint8_t buf[512];

void setup() {
  Serial.begin(115200);       // USB CDC: baud is ignored
  Serial.setTxTimeoutMs(0);   // never block when no laptop is listening
  Serial1.setRxBufferSize(4096);
  Serial1.begin(RADAR_BAUD, SERIAL_8N1, PIN_RADAR_RX, PIN_RADAR_TX);
}

void loop() {
  int n = Serial1.available();
  if (n > 0) Serial.write(buf, Serial1.readBytes(buf, min(n, (int)sizeof buf)));
  n = Serial.available();
  if (n > 0) Serial1.write(buf, Serial.readBytes(buf, min(n, (int)sizeof buf)));
}
