"""LoRa packet format shared by node firmware and base software.

Must stay byte-for-byte identical to firmware/node/packet.h.
All fields little-endian, 24 bytes total, CRC16-CCITT-FALSE over bytes 0..21.

 off  size  field
   0   u8   magic         0xC5
   1   u8   ver_type      (version << 4) | type
   2   u8   node_id
   3   u8   flags         bit0 confirmed, bit1 steady tone, bit2 clipping
   4   u16  seq
   6   u32  uptime_ms
  10   u16  f0            comb spacing (blade-pass freq), 0.1 Hz units
  12   i16  f0_rate       0.1 Hz/s (how fast the comb is sliding)
  14   i16  level         harmonic band level, 0.1 dB SPL
  16   i16  score         comb contrast, 0.1 dB
  18   u8   n_harm        harmonics above threshold
  19   u8   confidence    0..100
  20   i16  floor         broadband background level, 0.1 dB SPL
  22   u16  crc
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum

MAGIC = 0xC5
VERSION = 1
_FMT = "<BBBBHIHhhhBBhH"
SIZE = struct.calcsize(_FMT)
assert SIZE == 24


class PktType(IntEnum):
    DETECTION = 1
    HEARTBEAT = 2
    LOST = 3
    HINT = 4  # downlink, base -> node: "the C2 still has this drone, look for it at f0"


HINT_ALL_NODES = 0xFF  # node_id for a broadcast hint


FLAG_CONFIRMED = 0x01
FLAG_STEADY = 0x02
FLAG_CLIPPING = 0x04


def crc16(data: bytes) -> int:
    """CRC16-CCITT-FALSE (poly 0x1021, init 0xFFFF)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def _clamp(v: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(v))))


@dataclass
class Packet:
    type: PktType
    node_id: int
    seq: int = 0
    uptime_ms: int = 0
    flags: int = 0
    f0_hz: float = 0.0
    f0_rate_hz_s: float = 0.0
    level_db: float = 0.0
    score_db: float = 0.0
    n_harm: int = 0
    confidence: int = 0
    floor_db: float = 0.0
    # Filled in by the base, not transmitted:
    rx_time: float = 0.0
    rssi: float | None = None
    snr: float | None = None
    meta: dict = field(default_factory=dict)

    @property
    def confirmed(self) -> bool:
        return bool(self.flags & FLAG_CONFIRMED)

    @property
    def steady(self) -> bool:
        return bool(self.flags & FLAG_STEADY)

    def encode(self) -> bytes:
        body = struct.pack(
            _FMT[:-1],
            MAGIC,
            (VERSION << 4) | int(self.type),
            self.node_id & 0xFF,
            self.flags & 0xFF,
            self.seq & 0xFFFF,
            self.uptime_ms & 0xFFFFFFFF,
            _clamp(self.f0_hz * 10, 0, 0xFFFF),
            _clamp(self.f0_rate_hz_s * 10, -32768, 32767),
            _clamp(self.level_db * 10, -32768, 32767),
            _clamp(self.score_db * 10, -32768, 32767),
            _clamp(self.n_harm, 0, 255),
            _clamp(self.confidence, 0, 100),
            _clamp(self.floor_db * 10, -32768, 32767),
        )
        return body + struct.pack("<H", crc16(body))

    @classmethod
    def decode(cls, data: bytes) -> "Packet":
        if len(data) != SIZE:
            raise ValueError(f"bad length {len(data)} (want {SIZE})")
        f = struct.unpack(_FMT, data)
        if f[0] != MAGIC:
            raise ValueError(f"bad magic 0x{f[0]:02x}")
        if crc16(data[:-2]) != f[-1]:
            raise ValueError("bad crc")
        ver, typ = f[1] >> 4, f[1] & 0x0F
        if ver != VERSION:
            raise ValueError(f"unsupported version {ver}")
        return cls(
            type=PktType(typ),
            node_id=f[2],
            flags=f[3],
            seq=f[4],
            uptime_ms=f[5],
            f0_hz=f[6] / 10,
            f0_rate_hz_s=f[7] / 10,
            level_db=f[8] / 10,
            score_db=f[9] / 10,
            n_harm=f[10],
            confidence=f[11],
            floor_db=f[12] / 10,
        )


def make_hint(node_id: int, f0_hz: float, hold_s: float, seq: int, confidence: int = 0) -> Packet:
    """Downlink re-acquire hint for one node (or HINT_ALL_NODES).

    Same 24-byte layout as an uplink packet; fields are reused:
      node_id     target node (0xFF = all)
      seq         C2 downlink sequence
      uptime_ms   how long the hint stays valid on the node, ms (0 cancels a hint)
      f0_hz       rotor comb spacing to look for
      confidence  C2 track confidence 0..100 (informational)
    """
    return Packet(PktType.HINT, node_id, seq=seq, uptime_ms=int(max(0.0, hold_s) * 1000),
                  f0_hz=f0_hz, confidence=confidence, flags=FLAG_CONFIRMED)
