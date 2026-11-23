"""Ai-Thinker RD-03D 24 GHz mmWave radar (bench-scale stand-in for a real air-search radar).

The radar streams one 30-byte frame ~10 times a second at 256000 baud:

    AA FF 03 00 | target 1 (8 B) | target 2 | target 3 | 55 CC

Each target is four little-endian uint16: x (mm, lateral), y (mm, forward),
speed (cm/s), distance resolution (mm). x/y/speed use sign-magnitude with the
top bit meaning *positive*. An empty slot is all zeros. The radar only reports
things that move.

It reaches the laptop either through firmware/radar_bridge (an ESP32-S3 that
passes bytes straight through to USB) or a plain USB-serial adapter; the same
parser handles both.
"""
from __future__ import annotations

import math
import struct
import threading
import time
from dataclasses import dataclass

HEADER = b"\xAA\xFF\x03\x00"
TAIL = b"\x55\xCC"
FRAME_LEN = 30
BAUD = 256000
MULTI_TARGET_CMD = bytes.fromhex("FDFCFBFA0200900004030201")  # default is single-target mode


@dataclass
class RadarTarget:
    x_m: float  # + = right of boresight (looking out from the radar)
    y_m: float  # forward along boresight
    speed_mps: float
    res_m: float = 0.0

    @property
    def range_m(self) -> float:
        return math.hypot(self.x_m, self.y_m)

    @property
    def angle_deg(self) -> float:
        """Angle off boresight, + = right."""
        return math.degrees(math.atan2(self.x_m, self.y_m))


def _dec(raw: int) -> int:
    v = raw & 0x7FFF
    return v if raw & 0x8000 else -v


def _enc(v: float) -> int:
    v = int(round(v))
    return (min(abs(v), 0x7FFF) | 0x8000) if v >= 0 else min(-v, 0x7FFF)


def decode_frame(frame: bytes) -> list[RadarTarget]:
    if len(frame) != FRAME_LEN or frame[:4] != HEADER or frame[-2:] != TAIL:
        raise ValueError("not an RD-03D frame")
    out = []
    for k in range(3):
        x, y, v, res = struct.unpack_from("<HHHH", frame, 4 + 8 * k)
        if x == 0 and y == 0 and v == 0 and res == 0:
            continue
        out.append(RadarTarget(_dec(x) / 1000, _dec(y) / 1000, _dec(v) / 100, res / 1000))
    return out


def encode_frame(targets: list[RadarTarget]) -> bytes:
    """Reference encoder (simulator and tests)."""
    body = b""
    for tg in targets[:3]:
        body += struct.pack("<HHHH", _enc(tg.x_m * 1000), _enc(tg.y_m * 1000),
                            _enc(tg.speed_mps * 100), int(tg.res_m * 1000))
    body += b"\0" * (24 - len(body))
    return HEADER + body + TAIL


class FrameParser:
    """Byte stream -> frames. Skips command ACKs, console text and partial frames."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes) -> list[list[RadarTarget]]:
        self.buf += data
        frames = []
        while True:
            i = self.buf.find(HEADER)
            if i < 0:
                del self.buf[:-3]
                return frames
            if len(self.buf) - i < FRAME_LEN:
                del self.buf[:i]
                return frames
            chunk = bytes(self.buf[i:i + FRAME_LEN])
            if chunk[-2:] == TAIL:
                frames.append(decode_frame(chunk))
                del self.buf[:i + FRAME_LEN]
            else:
                del self.buf[:i + 1]


def radar_reader(port: str, radar_id: str, base, log=print, rate_hz: float = 5.0) -> threading.Thread:
    """Feeds base.on_radar() from a serial port (bridge or USB-serial adapter)."""
    import serial  # pyserial

    def run():
        while True:
            try:
                s = serial.Serial()
                s.port, s.baudrate, s.timeout = port, BAUD, 0.2
                s.dtr = s.rts = False
                s.open()
                with s:
                    s.write(MULTI_TARGET_CMD)
                    log(f"radar {radar_id}: connected {port}")
                    p, last = FrameParser(), 0.0
                    while True:
                        frames = p.feed(s.read(512))
                        now = time.time()
                        if frames and now - last >= 1.0 / rate_hz:
                            last = now
                            base.on_radar(radar_id, frames[-1], now)
            except Exception as e:  # unplugged etc.: keep retrying
                log(f"radar {radar_id}: {e}; retrying in 2 s")
                time.sleep(2)

    th = threading.Thread(target=run, daemon=True, name=f"radar-{radar_id}")
    th.start()
    return th
