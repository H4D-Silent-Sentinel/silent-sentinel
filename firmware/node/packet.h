// Silent Sentinel LoRa packet. Byte-for-byte identical to cuas/packet.py.
#pragma once
#include <stdint.h>
#include <stddef.h>

#define PKT_MAGIC   0xC5
#define PKT_VERSION 1

enum PktType : uint8_t { PKT_DETECTION = 1, PKT_HEARTBEAT = 2, PKT_LOST = 3,
                         PKT_HINT = 4 };  // HINT: downlink base -> node, see cuas/packet.py make_hint()
#define HINT_ALL_NODES 0xFF

#define FLAG_CONFIRMED 0x01
#define FLAG_STEADY    0x02
#define FLAG_CLIPPING  0x04

#pragma pack(push, 1)
struct Packet {
  uint8_t  magic;
  uint8_t  ver_type;      // (version << 4) | type
  uint8_t  node_id;
  uint8_t  flags;
  uint16_t seq;
  uint32_t uptime_ms;
  uint16_t f0_dhz;        // 0.1 Hz
  int16_t  f0_rate_dhz_s; // 0.1 Hz/s
  int16_t  level_ddb;     // 0.1 dB SPL
  int16_t  score_ddb;     // 0.1 dB
  uint8_t  n_harm;
  uint8_t  confidence;    // 0..100
  int16_t  floor_ddb;     // 0.1 dB SPL
  uint16_t crc;           // CRC16-CCITT-FALSE over the 22 bytes above
};
#pragma pack(pop)
static_assert(sizeof(Packet) == 24, "Packet must be 24 bytes");

static inline uint16_t crc16_ccitt(const uint8_t *d, size_t n) {
  uint16_t crc = 0xFFFF;
  while (n--) {
    crc ^= (uint16_t)(*d++) << 8;
    for (int i = 0; i < 8; i++) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
  }
  return crc;
}

static inline void packet_seal(Packet &p) {
  p.magic = PKT_MAGIC;
  p.crc = crc16_ccitt((const uint8_t *)&p, sizeof(Packet) - 2);
}

static inline bool packet_valid(const Packet &p) {
  return p.magic == PKT_MAGIC && (p.ver_type >> 4) == PKT_VERSION &&
         p.crc == crc16_ccitt((const uint8_t *)&p, sizeof(Packet) - 2);
}
