"""Input/output threads: base receiver serial port, Jetson UDP, cue sender."""
from __future__ import annotations

import socket
import threading
import time

from .packet import Packet
from .visual import CUE_PORT, VISUAL_PORT, make_cue, parse_visual


def parse_rx_line(line: str) -> Packet | None:
    """`PKT <rssi> <snr> <hex>` from firmware/base_rx."""
    parts = line.strip().split()
    if len(parts) != 4 or parts[0] != "PKT":
        return None
    pkt = Packet.decode(bytes.fromhex(parts[3]))
    pkt.rssi, pkt.snr = float(parts[1]), float(parts[2])
    return pkt


def serial_reader(port: str, base, log=print, baud: int = 115200) -> threading.Thread:
    import serial  # pyserial

    def run():
        while True:
            try:
                with serial.Serial(port, baud, timeout=1) as s:
                    log(f"serial: connected {port}")
                    while True:
                        raw = s.readline()
                        if not raw:
                            continue
                        line = raw.decode(errors="replace").strip()
                        try:
                            pkt = parse_rx_line(line)
                        except ValueError as e:
                            log(f"serial: bad packet ({e}): {line}")
                            continue
                        if pkt:
                            base.on_packet(pkt, time.time())
                        elif line:
                            log(f"base_rx: {line}")
            except Exception as e:  # unplugged etc.: keep retrying
                log(f"serial: {e}; retrying in 2 s")
                time.sleep(2)

    th = threading.Thread(target=run, daemon=True, name="serial")
    th.start()
    return th


def visual_listener(base, port: int = VISUAL_PORT, log=print) -> threading.Thread:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    peers: set = set()

    def run():
        log(f"visual: listening on udp/{port}")
        while True:
            data, addr = sock.recvfrom(65535)
            try:
                obs = parse_visual(data, base.site.frame, base.site.cameras)
            except (ValueError, KeyError) as e:
                log(f"visual: bad message from {addr[0]}: {e}")
                continue
            if addr[0] not in peers:
                peers.add(addr[0])
                log(f"visual: new Jetson at {addr[0]}")
            base.on_visual(obs)

    th = threading.Thread(target=run, daemon=True, name="visual")
    th.peers = peers  # type: ignore[attr-defined]
    th.start()
    return th


class CueSender:
    """Sends cues for confirmed tracks to every Jetson we've heard from (plus any fixed IPs)."""

    def __init__(self, base, peers: set, extra: list[str] | None = None, port: int = CUE_PORT,
                 min_interval_s: float = 1.0):
        self.base, self.peers, self.extra, self.port = base, peers, extra or [], port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.min_interval_s = min_interval_s
        self._last: dict[int, float] = {}

    def __call__(self, tr: dict) -> None:
        if not tr["confirmed"]:
            return
        now = time.time()
        if now - self._last.get(tr["id"], 0) < self.min_interval_s:
            return
        self._last[tr["id"]] = now
        msg = make_cue(tr, self.base.site.frame, now)
        for ip in set(self.peers) | set(self.extra):
            try:
                self.sock.sendto(msg, (ip, self.port))
            except OSError:
                pass
