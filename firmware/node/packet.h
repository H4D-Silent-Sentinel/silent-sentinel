// Silent Sentinel LoRa packet. Byte-for-byte identical to cuas/packet.py.
#pragma once
#include <stdint.h>
#include <stddef.h>

#define PKT_MAGIC   0xC5
#define PKT_VERSION 1

enum PktType : uint8_t { PKT_DETECTION = 1, PKT_HEARTBEAT = 2, PKT_LOST = 3,
                         PKT_HINT = 4,    // HINT: downlink base -> node, see cuas/packet.py make_hint()
                         PKT_RADAR = 5 }; // radar station plots, see RadarPacket below
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

// Radar station report (type PKT_RADAR): same magic, version, CRC and size as Packet.
// Up to 3 RD-03D targets, radar frame: x + right of boresight, y forward.
#define RADAR_MAX_TARGETS 3
#pragma pack(push, 1)
struct RadarTarget {
  int16_t x_cm;
  int16_t y_cm;
  int8_t  v_qms;          // radial speed, 0.25 m/s units, + = moving away
};
struct RadarPacket {
  uint8_t  magic;
  uint8_t  ver_type;      // (version << 4) | PKT_RADAR
  uint8_t  radar_id;
  uint8_t  n_targets;     // 0..3; 0 is the heartbeat
  uint16_t seq;
  RadarTarget t[RADAR_MAX_TARGETS];
  uint8_t  reserved;
  uint16_t crc;           // CRC16-CCITT-FALSE over the 22 bytes above
};
#pragma pack(pop)
static_assert(sizeof(RadarPacket) == 24, "RadarPacket must be 24 bytes");

static inline uint16_t crc16_ccitt(const uint8_t *d, size_t n) {
  uint16_t crc = 0xFFFF;
  while (n--) {
    crc ^= (uint16_t)(*d++) << 8;
    for (int i = 0; i < 8; i++) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
  }
  return crc;
}

static inline void radar_seal(RadarPacket &p) {
  p.magic = PKT_MAGIC;
  p.ver_type = (PKT_VERSION << 4) | PKT_RADAR;
  p.crc = crc16_ccitt((const uint8_t *)&p, sizeof(RadarPacket) - 2);
}

static inline void packet_seal(Packet &p) {
  p.magic = PKT_MAGIC;
  p.crc = crc16_ccitt((const uint8_t *)&p, sizeof(Packet) - 2);
}

static inline bool packet_valid(const Packet &p) {
  return p.magic == PKT_MAGIC && (p.ver_type >> 4) == PKT_VERSION &&
         p.crc == crc16_ccitt((const uint8_t *)&p, sizeof(Packet) - 2);
}
