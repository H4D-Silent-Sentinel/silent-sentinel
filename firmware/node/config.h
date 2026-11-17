// Silent Sentinel node configuration.
// Detector constants MUST match cuas/detector.py (the reference implementation).
#pragma once

// ---------------------------------------------------------------- Pins ----
// ESP32-S3-DevKitC-1 N16R8. Avoid GPIO 0/3/45/46 (strapping), 19/20 (USB),
// 35/36/37 (octal PSRAM on the N16R8), 48 (on-board RGB LED).
//
// Two ICS-43434 per I2S bus: SEL→GND = left slot, SEL→3V3 = right slot.
//   Bus 0 (mics 0,1): BCLK 4,  WS 5,  SD 6
//   Bus 1 (mics 2,3): BCLK 7,  WS 15, SD 16
#define PIN_I2S0_BCLK 4
#define PIN_I2S0_WS   5
#define PIN_I2S0_DIN  6
#define PIN_I2S1_BCLK 7
#define PIN_I2S1_WS   15
#define PIN_I2S1_DIN  16

// RFM95W (Adafruit #3072): VIN→3V3, GND, SCK, MISO, MOSI, CS, RST, G0(DIO0)
#define PIN_LORA_SCK  12
#define PIN_LORA_MISO 13
#define PIN_LORA_MOSI 11
#define PIN_LORA_CS   10
#define PIN_LORA_RST  9
#define PIN_LORA_DIO0 8

// ---------------------------------------------------------------- LoRa ----
// 500 kHz bandwidth: ~15 ms airtime per 24-byte packet at SF7, so six nodes
// rarely collide. Intended to fit FCC 15.247 digital modulation; verify
// before fielding. Base receiver must use identical settings.
#define LORA_FREQ_HZ   915E6
#define LORA_SF        7
#define LORA_BW_HZ     500E3
#define LORA_CR4       5
#define LORA_SYNC      0x5E   // private network sync word (not LoRaWAN 0x34)
#define LORA_TX_DBM    17

// ----------------------------------------------------------- Reporting ----
#define REPORT_MS      2000   // while confirmed, one detection packet per ~2 s
#define REPORT_JITTER  500    // + random 0..500 ms so nodes don't sync up
#define HEARTBEAT_MS   30000
#define DEFAULT_NODE_ID 1     // overridden by `id <n>` on the serial console (stored in NVS)

// ------------------------------------------------------------ Detector ----
#define FS          32000
#define N_FFT       4096
#define HOP         2048
#define N_CH        4
#define DF          ((float)FS / N_FFT)
#define FRAME_RATE  ((float)FS / HOP)

#define HPF_HZ      60.0f
#define F0_MIN      70.0f
#define F0_MAX      400.0f
#define F0_STEP     0.5f
#define FMAX_HARM   3000.0f
#define H_MAX       12
#define MIN_HARM    3
#define HARM_DB     6.0f
#define SCORE_DB    6.0f
#define W_CLIP_LO   -10.0f
#define W_CLIP_HI   30.0f
#define MEDIAN_BINS 33
#define WARMUP_FRAMES 16

#define CONFIRM_WIN  8
#define CONFIRM_HITS 6
#define RELEASE_HITS 3
#define F0_TOL       0.10f

#define TONAL_ALPHA  0.001f
#define TONAL_MASK   0.9f

#define STEADY_WIN     64
#define STEADY_MIN     40
#define STEADY_REL_STD 0.0015f
#define SLOPE_WIN      16

#define SPL_OFFSET  120.0f   // ICS-43434: -26 dBFS @ 94 dB SPL

// ceil(3300 / 7.8125) + 2
#define K_MAX       425
#define N_CAND      661      // (400 - 70) / 0.5 + 1
