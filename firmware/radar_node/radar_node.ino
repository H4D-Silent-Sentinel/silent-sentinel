// Silent Sentinel radar station
// ESP32-S3-DevKitC-1 + Ai-Thinker RD-03D (24 GHz) + RFM95W 915 MHz, on a USB power bank.
// Reads RD-03D frames on UART and sends up to 3 targets per LoRa packet (type PKT_RADAR,
// see ../node/packet.h) to the base receiver on the node channel.
//
// Wiring: RFM95W as on a listening node (../node/config.h).
//   RD-03D 5V -> J1-21 5V   GND -> J1-22 GND   TX -> GPIO17   RX <- GPIO18
//
// Serial console 115200 baud:
//   id <n>     set radar id (1..254), stored in flash; must match "radars" in the site file
//   debug 0|1  print every radar frame
//   info       show settings
//
// LED: blue = no radar frames in the last second, green = radar running,
//      magenta = RFM95W not found (check serial output).
#include <Arduino.h>
#include <stdarg.h>
#include <SPI.h>
#include <LoRa.h>
#include <Preferences.h>

#include "../node/config.h"
#include "../node/packet.h"

#define PIN_RADAR_RX 17
#define PIN_RADAR_TX 18
#define RADAR_BAUD   256000
#define RADAR_REPORT_MS    200   // 5 packets/s while targets are present
#define RADAR_HEARTBEAT_MS 1000  // 1 packet/s with none
#define RADAR_JITTER_MS    40    // + random 0..40 ms so the radar does not lock step with a node
#define RADAR_STALE_MS     300   // targets older than this are not reported
#define DEFAULT_RADAR_ID   1

static const uint8_t FRAME_HDR[4] = {0xAA, 0xFF, 0x03, 0x00};
static const uint8_t MULTI_TARGET_CMD[] = {0xFD, 0xFC, 0xFB, 0xFA, 0x02, 0x00, 0x90, 0x00,
                                           0x04, 0x03, 0x02, 0x01};

static Preferences prefs;
static uint8_t radar_id = DEFAULT_RADAR_ID;
static uint16_t seq = 0;
static bool lora_ok = false, debug_on = false;
static RadarTarget latest[RADAR_MAX_TARGETS];
static uint8_t n_latest = 0;
static uint32_t latest_ms = 0, frames = 0, next_tx = 0, last_frame_ms = 0;

static void logf(const char *fmt, ...) {
  char buf[200];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  Serial.print(buf);
  Serial0.print(buf);
}

static void led(uint8_t r, uint8_t g, uint8_t b) {
#ifdef RGB_BUILTIN
  rgbLedWrite(RGB_BUILTIN, r, g, b);
#endif
}

// RD-03D sign-magnitude: top bit set = positive.
static int32_t sm(uint16_t raw) { int32_t v = raw & 0x7FFF; return (raw & 0x8000) ? v : -v; }

static void on_frame(const uint8_t *f) {  // 30 bytes: header, 3 x 8-byte target, 55 CC
  n_latest = 0;
  for (int k = 0; k < RADAR_MAX_TARGETS; k++) {
    const uint8_t *t = f + 4 + 8 * k;
    uint16_t x = t[0] | t[1] << 8, y = t[2] | t[3] << 8, v = t[4] | t[5] << 8, res = t[6] | t[7] << 8;
    if (!x && !y && !v && !res) continue;
    RadarTarget &o = latest[n_latest++];
    o.x_cm = (int16_t)constrain(sm(x) / 10, -32768, 32767);  // mm -> cm
    o.y_cm = (int16_t)constrain(sm(y) / 10, -32768, 32767);
    o.v_qms = (int8_t)constrain(lroundf(sm(v) / 25.0f), -128, 127);  // cm/s -> 0.25 m/s
    if (debug_on) logf("T%d x=%d y=%d v=%d cm/s\n", k, sm(x), sm(y), sm(v));
  }
  latest_ms = last_frame_ms = millis();
  frames++;
}

static void read_radar() {
  static uint8_t f[30];
  static int len = 0;
  while (Serial1.available()) {
    uint8_t b = Serial1.read();
    if (len < 4) {  // resync on the header
      if (b == FRAME_HDR[len]) f[len++] = b;
      else len = (b == FRAME_HDR[0]) ? 1 : 0;
      if (len == 1) f[0] = b;
      continue;
    }
    f[len++] = b;
    if (len == 30) {
      if (f[28] == 0x55 && f[29] == 0xCC) on_frame(f);
      len = 0;
    }
  }
}

static void send() {
  RadarPacket p{};
  p.radar_id = radar_id;
  p.seq = seq++;
  bool fresh = millis() - latest_ms < RADAR_STALE_MS;
  p.n_targets = fresh ? n_latest : 0;
  for (int k = 0; k < p.n_targets; k++) p.t[k] = latest[k];
  radar_seal(p);
  if (lora_ok) {
    LoRa.beginPacket();
    LoRa.write((const uint8_t *)&p, sizeof(p));
    LoRa.endPacket();  // blocking, ~15 ms at SF7/500 kHz
  }
  // Same line format as firmware/base_rx, so ROAREE can read this board directly over USB.
  char hex[2 * sizeof(RadarPacket) + 1];
  for (size_t i = 0; i < sizeof(RadarPacket); i++) sprintf(hex + 2 * i, "%02x", ((const uint8_t *)&p)[i]);
  logf("PKT 0 0 %s\n", hex);
}

static void console() {
  static String line;
  while (Serial.available() || Serial0.available()) {
    char c = Serial.available() ? Serial.read() : Serial0.read();
    if (c != '\n' && c != '\r') { line += c; continue; }
    line.trim();
    if (line.startsWith("id ")) {
      int v = line.substring(3).toInt();
      if (v >= 1 && v <= 254) { radar_id = v; prefs.putUChar("radar_id", radar_id); }
      logf("radar id = %d\n", radar_id);
    } else if (line.startsWith("debug ")) {
      debug_on = line.substring(6).toInt() != 0;
    } else if (line == "info") {
      logf("Silent Sentinel radar id=%d lora=%s frames=%u last=%u ms ago sf=%d bw=%.0fk\n", radar_id,
           lora_ok ? "ok" : "FAIL", frames, millis() - last_frame_ms, LORA_SF, LORA_BW_HZ / 1e3);
    }
    line = "";
  }
}

void setup() {
  Serial.begin(115200);
  Serial0.begin(115200);
  Serial.setTxTimeoutMs(0);  // never block when no laptop is on the USB port
  delay(500);
  led(0, 0, 20);
  prefs.begin("sentinel", false);
  radar_id = prefs.getUChar("radar_id", DEFAULT_RADAR_ID);
  logf("\nSilent Sentinel radar %d booting\n", radar_id);

  Serial1.setRxBufferSize(4096);
  Serial1.begin(RADAR_BAUD, SERIAL_8N1, PIN_RADAR_RX, PIN_RADAR_TX);
  delay(200);
  Serial1.write(MULTI_TARGET_CMD, sizeof(MULTI_TARGET_CMD));  // default is single-target mode

  SPI.begin(PIN_LORA_SCK, PIN_LORA_MISO, PIN_LORA_MOSI, PIN_LORA_CS);
  LoRa.setSPI(SPI);
  LoRa.setPins(PIN_LORA_CS, PIN_LORA_RST, PIN_LORA_DIO0);
  lora_ok = LoRa.begin(LORA_FREQ_HZ);
  if (lora_ok) {
    LoRa.setSpreadingFactor(LORA_SF);
    LoRa.setSignalBandwidth(LORA_BW_HZ);
    LoRa.setCodingRate4(LORA_CR4);
    LoRa.setSyncWord(LORA_SYNC);
    LoRa.setTxPower(LORA_TX_DBM);
    LoRa.enableCrc();
  } else {
    logf("FAULT: RFM95W not found (check SPI wiring); USB output only\n");
    led(40, 0, 40);
  }
  randomSeed(esp_random());
  next_tx = millis() + 1000;
}

void loop() {
  read_radar();
  console();
  uint32_t now = millis();
  if ((int32_t)(now - next_tx) >= 0) {
    bool targets = now - latest_ms < RADAR_STALE_MS && n_latest > 0;
    send();
    next_tx = now + (targets ? RADAR_REPORT_MS : RADAR_HEARTBEAT_MS) + random(RADAR_JITTER_MS + 1);
    if (lora_ok) {
      bool running = now - last_frame_ms < 1000;
      led(0, running ? 20 : 0, running ? 0 : 20);
    }
  }
}
