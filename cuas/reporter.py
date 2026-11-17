"""Turns per-frame detector results into node packets, with the same cadence as
the firmware (firmware/node/node.ino): a detection report on confirmation and
then every ~2 s, a LOST packet when the drone goes away, a heartbeat every 30 s.
Used by the laptop-microphone node (`cuas listen`)."""
from __future__ import annotations

import random

from .detector import FrameResult
from .packet import FLAG_CLIPPING, FLAG_CONFIRMED, FLAG_STEADY, Packet, PktType

REPORT_MS, REPORT_JITTER, HEARTBEAT_MS = 2000, 500, 30000


class Reporter:
    def __init__(self, node_id: int):
        self.node_id = node_id
        self.seq = 0
        self.was = False
        self.next_report = 0
        self.next_hb = 2000

    def _pkt(self, typ: PktType, r: FrameResult, now_ms: int) -> Packet:
        flags = (FLAG_CONFIRMED if r.confirmed else 0) | (FLAG_STEADY if r.steady else 0) | \
                (FLAG_CLIPPING if r.clipping else 0)
        p = Packet(typ, self.node_id, seq=self.seq, uptime_ms=now_ms, flags=flags, floor_db=r.floor_db)
        if typ != PktType.HEARTBEAT:
            p.f0_hz, p.f0_rate_hz_s, p.level_db = r.f0, r.f0_rate, r.level_db
            p.score_db, p.n_harm, p.confidence = r.score, r.n_harm, r.confidence
        self.seq = (self.seq + 1) & 0xFFFF
        return Packet.decode(p.encode())  # exactly what would go over the air

    def update(self, r: FrameResult, now_ms: int) -> list[Packet]:
        out = []
        if r.confirmed and (not self.was or now_ms >= self.next_report):
            out.append(self._pkt(PktType.DETECTION, r, now_ms))
            self.next_report = now_ms + REPORT_MS + random.randrange(REPORT_JITTER)
        elif self.was and not r.confirmed:
            out.append(self._pkt(PktType.LOST, r, now_ms))
        self.was = r.confirmed
        if now_ms >= self.next_hb:
            out.append(self._pkt(PktType.HEARTBEAT, r, now_ms))
            self.next_hb = now_ms + HEARTBEAT_MS
        return out
