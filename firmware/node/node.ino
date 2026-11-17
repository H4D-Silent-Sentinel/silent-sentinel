// Silent Sentinel listening node
// ESP32-S3-DevKitC-1 N16R8 + 4x ICS-43434 (2 per I2S bus) + RFM95W 915 MHz
//
// Board: "ESP32S3 Dev Module", PSRAM: "OPI PSRAM", Flash: 16MB
// Serial console 115200 baud:
//   id <n>     set node id (1..254), stored in flash
//   debug 0|1  print one line per audio frame (for bench / range tests)
//   info       show settings
//   tx         send a test heartbeat now
//
// LED: blue = listening, green flash = packet sent, red = drone confirmed,
//      magenta = hardware fault (check serial output).
#include <Arduino.h>
#include <SPI.h>
#include <LoRa.h>
#include <Preferences.h>
#include "driver/i2s_std.h"

#include "config.h"
#include "detector.h"
#include "packet.h"

static i2s_chan_handle_t rx0, rx1;
static CombDetector det;
static Preferences prefs;
static int32_t *raw0, *raw1;           // interleaved stereo 32-bit slots
static float *mic[N_CH];
static uint8_t node_id = DEFAULT_NODE_ID;
static uint16_t seq = 0;
static bool debug_on = false, lora_ok = false;
static uint32_t next_report = 0, next_heartbeat = 0;
static bool was_confirmed = false;
static FrameResult last{};

static void led(uint8_t r, uint8_t g, uint8_t b) {
#ifdef RGB_BUILTIN
  rgbLedWrite(RGB_BUILTIN, r, g, b);
#endif
}

static bool i2s_open(i2s_port_t port, int bclk, int ws, int din, i2s_chan_handle_t *h) {
  i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(port, I2S_ROLE_MASTER);
  cc.dma_desc_num = 8;
  cc.dma_frame_num = 512;  // 8 x 512 frames = 128 ms of slack
  if (i2s_new_channel(&cc, NULL, h) != ESP_OK) return false;
  i2s_std_config_t sc = {
      .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(FS),
      .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
      .gpio_cfg = {.mclk = I2S_GPIO_UNUSED, .bclk = (gpio_num_t)bclk, .ws = (gpio_num_t)ws,
                   .dout = I2S_GPIO_UNUSED, .din = (gpio_num_t)din,
                   .invert_flags = {.mclk_inv = false, .bclk_inv = false, .ws_inv = false}},
  };
  if (i2s_channel_init_std_mode(*h, &sc) != ESP_OK) return false;
  // Two mics share SD and tri-state on the other's half-frame; the
  // ICS-43434 datasheet asks for a pull-down to drain the line between them.
  gpio_pulldown_en((gpio_num_t)din);
  return i2s_channel_enable(*h) == ESP_OK;
}

static bool read_hop(i2s_chan_handle_t h, int32_t *dst) {
  size_t want = HOP * 2 * sizeof(int32_t), got = 0;
  uint8_t *p = (uint8_t *)dst;
  while (got < want) {
    size_t n = 0;
    if (i2s_channel_read(h, p + got, want - got, &n, 1000) != ESP_OK) return false;
    got += n;
  }
  return true;
}

// ICS-43434: 24-bit two's complement, MSB-aligned in a 32-bit slot.
static void deinterleave(const int32_t *src, float *left, float *right) {
  const float k = 1.0f / 8388608.0f;
  for (int n = 0; n < HOP; n++) {
    left[n] = (src[2 * n] >> 8) * k;
    right[n] = (src[2 * n + 1] >> 8) * k;
  }
}

static void send(PktType type, const FrameResult &r) {
  if (!lora_ok) return;
  Packet p{};
  p.ver_type = (PKT_VERSION << 4) | type;
  p.node_id = node_id;
  p.flags = (r.confirmed ? FLAG_CONFIRMED : 0) | (r.steady ? FLAG_STEADY : 0) | (r.clipping ? FLAG_CLIPPING : 0);
  p.seq = seq++;
  p.uptime_ms = millis();
  if (type != PKT_HEARTBEAT) {
    p.f0_dhz = (uint16_t)lroundf(r.f0 * 10);
    p.f0_rate_dhz_s = (int16_t)constrain(lroundf(r.f0_rate * 10), -32768, 32767);
    p.level_ddb = (int16_t)lroundf(r.level_db * 10);
    p.score_ddb = (int16_t)lroundf(r.score * 10);
    p.n_harm = r.n_harm;
    p.confidence = r.confidence;
  }
  p.floor_ddb = (int16_t)lroundf(r.floor_db * 10);
  packet_seal(p);
  LoRa.beginPacket();
  LoRa.write((const uint8_t *)&p, sizeof(p));
  LoRa.endPacket();  // blocking, ~15 ms at SF7/500 kHz
  Serial.printf("TX type=%d seq=%u f0=%.1f lvl=%.1f conf=%d\n", type, p.seq, r.f0, r.level_db, r.confidence);
}

static void console() {
  static String line;
  while (Serial.available()) {
    char c = Serial.read();
    if (c != '\n' && c != '\r') { line += c; continue; }
    line.trim();
    if (line.startsWith("id ")) {
      int v = line.substring(3).toInt();
      if (v >= 1 && v <= 254) { node_id = v; prefs.putUChar("id", node_id); }
      Serial.printf("node id = %d\n", node_id);
    } else if (line.startsWith("debug ")) {
      debug_on = line.substring(6).toInt() != 0;
    } else if (line == "info") {
      Serial.printf("Silent Sentinel node id=%d lora=%s fs=%d nfft=%d sf=%d bw=%.0fk\n", node_id,
                    lora_ok ? "ok" : "FAIL", FS, N_FFT, LORA_SF, LORA_BW_HZ / 1e3);
    } else if (line == "tx") {
      send(PKT_HEARTBEAT, last);
    }
    line = "";
  }
}

static void fault(const char *msg) {
  while (true) {
    Serial.printf("FAULT: %s\n", msg);
    led(40, 0, 40);
    delay(2000);
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);
  led(0, 0, 20);
  prefs.begin("sentinel", false);
  node_id = prefs.getUChar("id", DEFAULT_NODE_ID);
  Serial.printf("\nSilent Sentinel node %d booting\n", node_id);

  raw0 = (int32_t *)heap_caps_malloc(HOP * 2 * sizeof(int32_t), MALLOC_CAP_INTERNAL);
  raw1 = (int32_t *)heap_caps_malloc(HOP * 2 * sizeof(int32_t), MALLOC_CAP_INTERNAL);
  for (int c = 0; c < N_CH; c++) mic[c] = (float *)heap_caps_malloc(HOP * sizeof(float), MALLOC_CAP_INTERNAL);
  if (!raw0 || !raw1 || !mic[0] || !mic[1] || !mic[2] || !mic[3]) fault("out of memory");
  if (!det.begin()) fault("detector init");
  if (!i2s_open(I2S_NUM_0, PIN_I2S0_BCLK, PIN_I2S0_WS, PIN_I2S0_DIN, &rx0)) fault("I2S bus 0");
  if (!i2s_open(I2S_NUM_1, PIN_I2S1_BCLK, PIN_I2S1_WS, PIN_I2S1_DIN, &rx1)) fault("I2S bus 1");

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
    Serial.println("WARN: RFM95W not found; running detector only (check SPI wiring)");
  }
  randomSeed(esp_random());
  next_heartbeat = millis() + 2000;
  Serial.println("listening");
}

void loop() {
  if (!read_hop(rx0, raw0) || !read_hop(rx1, raw1)) {
    Serial.println("WARN: I2S read timeout");
    return;
  }
  deinterleave(raw0, mic[0], mic[1]);
  deinterleave(raw1, mic[2], mic[3]);
  FrameResult r = det.process(mic);
  last = r;

  if (debug_on)
    Serial.printf("DBG %lu hit=%d f0=%.1f score=%.1f nh=%d lvl=%.1f floor=%.1f conf=%d steady=%d rate=%.1f clip=%d\n",
                  (unsigned long)r.frame, r.hit, r.f0, r.score, r.n_harm, r.level_db, r.floor_db,
                  r.confidence, r.steady, r.f0_rate, r.clipping);

  uint32_t now = millis();
  if (r.confirmed) {
    led(40, 0, 0);
    if (!was_confirmed || (int32_t)(now - next_report) >= 0) {
      send(PKT_DETECTION, r);
      next_report = now + REPORT_MS + random(REPORT_JITTER);
    }
  } else {
    led(0, 0, 20);
    if (was_confirmed) send(PKT_LOST, r);
  }
  was_confirmed = r.confirmed;

  if ((int32_t)(now - next_heartbeat) >= 0) {
    send(PKT_HEARTBEAT, r);
    next_heartbeat = now + HEARTBEAT_MS + random(REPORT_JITTER);
  }
  console();
}
