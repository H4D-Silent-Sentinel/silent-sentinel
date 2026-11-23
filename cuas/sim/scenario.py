"""Network simulator: a drone flies through the site; nodes hear it (or not)
and send real encoded LoRa packets; a camera post sends Jetson-format visual
messages. Everything goes through the same Base code as the live system.

The acoustic model is deliberately simple (spherical spreading + absorption +
random multipath error, a fixed detection threshold); use it to exercise the
pipeline, not to predict real range. That comes from field tests.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..config import Site
from ..geo import bearing_deg
from ..packet import FLAG_CONFIRMED, Packet, PktType
from ..visual import make_visual, parse_visual


@dataclass
class DroneSim:
    waypoints: list[tuple[float, float]]
    speed: float = 8.0
    alt: float = 40.0
    source_db: float = 85.0
    f0: float = 200.0
    _seg: list = field(default_factory=list)

    def __post_init__(self):
        acc = 0.0
        for a, b in zip(self.waypoints, self.waypoints[1:]):
            L = math.dist(a, b)
            self._seg.append((acc, a, b, L))
            acc += L
        self.length = acc

    @property
    def duration(self) -> float:
        return self.length / self.speed

    def pos(self, t: float) -> tuple[float, float] | None:
        s = t * self.speed
        if s > self.length:
            return None
        for s0, a, b, L in self._seg:
            if s <= s0 + L:
                u = (s - s0) / L
                return a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1])
        return None


DEFAULT_PATH = [(-260, 60), (-60, 40), (0, 0), (40, -60), (160, -90), (280, -30)]


@dataclass
class NetworkSim:
    site: Site
    drones: list[DroneSim]
    floor_db: float = 35.0  # background band level at each node
    detect_margin_db: float = 8.0
    multipath_sigma_db: float = 3.0
    packet_loss: float = 0.05
    report_s: float = 2.0
    cam_range_m: float = 150.0
    cam_sigma_deg: float = 0.7
    seed: int = 0

    def events(self, dt: float = 0.1):
        """Yield (t, kind, payload, truth) in time order.
        kind 'lora' -> Packet (already encoded+decoded), 'visual' -> bytes."""
        rng = np.random.default_rng(self.seed)
        T = max(d.duration for d in self.drones) + 20
        next_rep = {i: rng.uniform(0, self.report_s) for i in self.site.nodes}
        next_hb = {i: rng.uniform(0, 5) for i in self.site.nodes}
        detecting = {i: False for i in self.site.nodes}
        seq = {i: 0 for i in self.site.nodes}
        next_cam = 0.0
        t = 0.0
        while t < T:
            truth = [d.pos(t) for d in self.drones]
            for nid, node in self.site.nodes.items():
                best = None
                for d, p in zip(self.drones, truth):
                    if p is None:
                        continue
                    r = math.sqrt((p[0] - node.e) ** 2 + (p[1] - node.n) ** 2 + (d.alt - node.height_m) ** 2)
                    L = d.source_db - 20 * math.log10(r) - self.site.atten_db_per_m * r
                    if best is None or L > best[0]:
                        best = (L, d)
                heard = best is not None and best[0] > self.floor_db + self.detect_margin_db
                pkt = None
                if heard and (t >= next_rep[nid] or not detecting[nid]):
                    L = best[0] + rng.normal(0, self.multipath_sigma_db)
                    pkt = Packet(PktType.DETECTION, nid, flags=FLAG_CONFIRMED, f0_hz=best[1].f0 + rng.normal(0, 1),
                                 level_db=L, score_db=12, n_harm=8, confidence=70, floor_db=self.floor_db)
                    next_rep[nid] = t + self.report_s + rng.uniform(0, 0.5)
                elif detecting[nid] and not heard:
                    pkt = Packet(PktType.LOST, nid, floor_db=self.floor_db)
                elif t >= next_hb[nid]:
                    pkt = Packet(PktType.HEARTBEAT, nid, floor_db=self.floor_db)
                    next_hb[nid] = t + 30
                detecting[nid] = heard
                if pkt is not None:
                    pkt.seq, pkt.uptime_ms = seq[nid], int(t * 1000)
                    seq[nid] += 1
                    if rng.random() >= self.packet_loss:
                        rx = Packet.decode(pkt.encode())
                        rx.rssi = -60 - 20 * rng.random()
                        yield t + 0.02, "lora", rx, truth
            if t >= next_cam:
                next_cam = t + 1.0
                for cid, cam in self.site.cameras.items():
                    if cam.lat is None:
                        continue
                    ce, cn = self.site.frame.to_en(cam.lat, cam.lon)
                    tracks = []
                    for k, (d, p) in enumerate(zip(self.drones, truth)):
                        if p is None or math.hypot(p[0] - ce, p[1] - cn) > self.cam_range_m:
                            continue
                        az = bearing_deg(p[0] - ce, p[1] - cn) + rng.normal(0, self.cam_sigma_deg)
                        rng_h = math.hypot(p[0] - ce, p[1] - cn)
                        el = math.degrees(math.atan2(d.alt - cam.height_m, rng_h))
                        tracks.append({"id": k + 1, "az_deg": round(az, 2), "el_deg": round(el, 2),
                                       "az_sigma_deg": 1.0, "conf": 0.8, "class": "drone",
                                       "label": "quadcopter"})
                    if tracks:
                        yield t + 0.05, "visual", make_visual(cid, t, {}, tracks), truth
            t = round(t + dt, 6)


def run(site: Site, base, sim: NetworkSim, on_tick=None, realtime: float = 0.0):
    """Drive base with the sim on a virtual clock. Returns per-second error log."""
    import time as _time
    clock = {"t": 0.0}
    base.clock = lambda: clock["t"]
    log = []
    next_step = 1.0
    for t, kind, payload, truth in sim.events():
        while t >= next_step:
            clock["t"] = next_step
            snap = base.step(next_step)
            log.append(_score(next_step, snap, sim, truth))
            if on_tick:
                on_tick(next_step, snap)
            if realtime:
                _time.sleep(1.0 / realtime)
            next_step += 1.0
        clock["t"] = t
        if kind == "lora":
            base.on_packet(payload, t)
        else:
            base.on_visual(parse_visual(payload, site.frame, site.cameras))
    return log


def _score(t, snap, sim, truth):
    errs = []
    for p in truth:
        if p is None:
            errs.append(None)
            continue
        conf = [tr for tr in snap if tr["confirmed"]]
        if not conf:
            errs.append(math.inf)
            continue
        errs.append(min(math.hypot(tr["e"] - p[0], tr["n"] - p[1]) for tr in conf))
    return {"t": t, "err": errs, "n_tracks": sum(tr["confirmed"] for tr in snap)}
