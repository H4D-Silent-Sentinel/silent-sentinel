"""Cursor-on-Target output so tracks appear on ATAK / WinTAK / iTAK maps.

Default: UDP multicast 239.2.3.1:6969 (TAK "SA" mesh). Point at a TAK server
or a single device with --cot udp://<ip>:<port>.
"""
from __future__ import annotations

import socket
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from xml.sax.saxutils import quoteattr

UNKNOWN_UAV = "a-u-A-M-F-Q"  # unknown affiliation, air, military, fixed... Q = UAV
SENSOR_NODE = "a-f-G-E-S"  # friendly ground equipment, sensor


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def event(uid: str, cot_type: str, lat: float, lon: float, hae: float, ce: float, le: float,
          callsign: str, remarks: str = "", stale_s: float = 30.0, course: float | None = None,
          speed: float | None = None) -> bytes:
    now = datetime.now(timezone.utc)
    track = "" if course is None else f'<track course="{course:.1f}" speed="{speed or 0:.1f}"/>'
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
           f'<event version="2.0" uid={quoteattr(uid)} type="{cot_type}" how="m-f" '
           f'time="{_iso(now)}" start="{_iso(now)}" stale="{_iso(now + timedelta(seconds=stale_s))}">'
           f'<point lat="{lat:.7f}" lon="{lon:.7f}" hae="{hae:.1f}" ce="{ce:.1f}" le="{le:.1f}"/>'
           f'<detail><contact callsign={quoteattr(callsign)}/>{track}'
           f'<remarks>{remarks}</remarks></detail></event>')
    return xml.encode()


class CotSender:
    def __init__(self, url: str = "udp://239.2.3.1:6969", prefix: str = "silent-sentinel"):
        u = urlparse(url)
        self.addr = (u.hostname, u.port or 6969)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        self.prefix = prefix
        self.run_id = uuid.uuid4().hex[:6]
        self.min_interval_s = 0.2  # per track; the fusion loop can run up to ~10 Hz
        self._last_sent: dict[int, float] = {}

    def send(self, data: bytes) -> None:
        try:
            self.sock.sendto(data, self.addr)
        except OSError:
            pass

    def track(self, tr: dict, frame) -> None:
        import time
        now = time.monotonic()
        if now - self._last_sent.get(tr["id"], float("-inf")) < self.min_interval_s:
            return
        self._last_sent[tr["id"]] = now
        lat, lon = frame.to_ll(tr["e"], tr["n"])
        name = f"SS-{tr['id']}" + (f" {tr['label']}" if tr.get("label") else "")
        rem = f"sources: {', '.join(tr['sources'])}; f0 {tr['f0']:.0f} Hz" if tr.get("f0") else \
            f"sources: {', '.join(tr['sources'])}"
        import math
        course = math.degrees(math.atan2(tr["ve"], tr["vn"])) % 360
        speed = math.hypot(tr["ve"], tr["vn"])
        self.send(event(f"{self.prefix}-{self.run_id}-trk{tr['id']}", UNKNOWN_UAV, lat, lon, tr["alt_m"],
                        ce=2 * tr["sigma_m"], le=30.0, callsign=name, remarks=rem,
                        course=course, speed=speed))

    def node(self, node, status: str) -> None:
        self.send(event(f"{self.prefix}-node{node.id}", SENSOR_NODE, node.lat, node.lon, node.height_m,
                        ce=5, le=5, callsign=f"SS node {node.id}", remarks=status, stale_s=120))
