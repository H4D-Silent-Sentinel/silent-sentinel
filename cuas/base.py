"""The base station: everything that runs on the base laptop.

  LoRa packets (acoustic nodes) ─┐
  UDP JSON (Jetson visual) ──────┼─> Base ─> Tracker ─> map / CoT (TAK) / cues to Jetson
  RD-03D frames (radar) ─────────┘

Thread-safe: inputs may arrive from serial / UDP threads; call step() ~1 Hz.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from .config import Site
from .localize import AcousticReport, Fix, cluster_by_f0, locate
from .packet import Packet, PktType
from .radar import RadarTarget
from .tracker import Tracker
from .visual import VisualObs

NODE_STALE_S = 75.0  # two missed heartbeats → node shown as offline
RADAR_STALE_S = 3.0


def polar_cov(az_deg: float, range_m: float, range_sigma_m: float, az_sigma_deg: float) -> np.ndarray:
    """2x2 east/north covariance of a range + bearing measurement."""
    a = math.radians(az_deg)
    u_r = np.array([math.sin(a), math.cos(a)])
    u_t = np.array([math.cos(a), -math.sin(a)])
    ts = range_m * math.radians(az_sigma_deg)
    return range_sigma_m ** 2 * np.outer(u_r, u_r) + ts ** 2 * np.outer(u_t, u_t)


@dataclass
class RadarHit:
    radar: str
    t: float
    e: float
    n: float
    range_m: float
    speed_mps: float


@dataclass
class NodeStatus:
    id: int
    last_seen: float = 0.0
    floor_db: float | None = None
    rssi: float | None = None
    detecting: bool = False
    last_det: AcousticReport | None = None
    packets: int = 0
    seq_gaps: int = 0
    _last_seq: int | None = None


@dataclass
class Base:
    site: Site
    tracker: Tracker = field(default_factory=Tracker)
    clock: callable = time.time
    on_track: list = field(default_factory=list)  # callbacks(track_dict)
    on_node: list = field(default_factory=list)  # callbacks(node, status_str)

    def __post_init__(self):
        self.lock = threading.RLock()
        self.nodes = {i: NodeStatus(i) for i in self.site.nodes}
        self.fixes: list[Fix] = []
        self.visual: list[VisualObs] = []
        self.radar_hits: list[RadarHit] = []
        self.radar_seen: dict[str, float] = {}
        self._new_acoustic = False

    # -- inputs ----------------------------------------------------------------
    def on_packet(self, pkt: Packet, rx_time: float | None = None) -> None:
        t = rx_time if rx_time is not None else self.clock()
        with self.lock:
            ns = self.nodes.setdefault(pkt.node_id, NodeStatus(pkt.node_id))
            if ns._last_seq is not None:
                ns.seq_gaps += max(0, ((pkt.seq - ns._last_seq) & 0xFFFF) - 1)
            ns._last_seq = pkt.seq
            ns.last_seen, ns.packets, ns.rssi = t, ns.packets + 1, pkt.rssi
            ns.floor_db = pkt.floor_db
            if pkt.type == PktType.DETECTION and pkt.confirmed:
                ns.detecting = True
                ns.last_det = AcousticReport(pkt.node_id, t, pkt.level_db, pkt.f0_hz,
                                             pkt.confidence, pkt.steady)
                self._new_acoustic = True
            elif pkt.type == PktType.LOST:
                ns.detecting = False
            for cb in self.on_node:
                cb(self.site.nodes.get(pkt.node_id), self._node_str(ns))

    def on_visual(self, obs: list[VisualObs]) -> None:
        with self.lock:
            for o in obs:
                self.visual.append(o)
                del self.visual[:-200]
                if o.range_m:
                    e = o.sensor_e + o.range_m * math.sin(math.radians(o.az_deg))
                    n = o.sensor_n + o.range_m * math.cos(math.radians(o.az_deg))
                    R = polar_cov(o.az_deg, o.range_m, o.range_sigma_m or 0.2 * o.range_m, o.az_sigma_deg)
                    alt = None
                    if o.el_deg is not None:
                        alt = o.sensor_alt + o.range_m * math.tan(math.radians(o.el_deg))
                    self.tracker.update_position((e, n), R, o.t, source=f"visual:{o.src}",
                                                 alt_m=alt, label=o.label, can_init=o.conf >= 0.6)
                else:
                    self.tracker.update_bearing((o.sensor_e, o.sensor_n), o.az_deg, o.az_sigma_deg,
                                                o.t, source=f"visual:{o.src}", label=o.label)

    def on_radar(self, radar_id: str, targets: list[RadarTarget], t: float | None = None) -> None:
        """One radar frame (0-3 moving targets in the radar's own x/y)."""
        t = t if t is not None else self.clock()
        rd = self.site.radars.get(radar_id)
        if rd is None:
            return
        with self.lock:
            self.radar_seen[radar_id] = t
            for tg in targets:
                rng = tg.range_m
                if tg.y_m <= 0 or rng < 0.1 or rng > rd.max_range_m * 1.2:
                    continue
                az = (rd.yaw_deg + (-tg.angle_deg if rd.flip_x else tg.angle_deg)) % 360
                e = rd.e + rng * math.sin(math.radians(az))
                n = rd.n + rng * math.cos(math.radians(az))
                self.radar_hits.append(RadarHit(radar_id, t, e, n, rng, tg.speed_mps))
                del self.radar_hits[:-100]
                R = polar_cov(az, rng, rd.range_sigma_m, rd.az_sigma_deg)
                self.tracker.update_position((e, n), R, t, source=f"radar:{radar_id}")

    # -- periodic --------------------------------------------------------------
    def step(self, now: float | None = None) -> list[dict]:
        now = now if now is not None else self.clock()
        with self.lock:
            if self._new_acoustic:
                self._new_acoustic = False
                win = self.site.report_window_s
                reports = [ns.last_det for ns in self.nodes.values()
                           if ns.detecting and ns.last_det and now - ns.last_det.t <= win
                           and not ns.last_det.steady]
                for group in cluster_by_f0(reports):
                    fix = locate(group, self.site)
                    if fix is None:
                        continue
                    self.fixes.append(fix)
                    del self.fixes[:-100]
                    self.tracker.update_position((fix.e, fix.n), fix.cov, fix.t, source="acoustic",
                                                 f0=fix.f0, alt_m=self.site.drone_alt_m)
            self.tracker.prune(now)
            snap = self.tracker.snapshot(now)
            for tr in snap:
                for cb in self.on_track:
                    cb(tr)
            return snap

    # -- view ------------------------------------------------------------------
    def _node_str(self, ns: NodeStatus) -> str:
        s = "DETECTING" if ns.detecting else "listening"
        if ns.floor_db is not None:
            s += f", background {ns.floor_db:.0f} dB"
        return s

    def state(self, now: float | None = None) -> dict:
        now = now if now is not None else self.clock()
        f = self.site.frame
        with self.lock:
            nodes = []
            for nid, node in self.site.nodes.items():
                ns = self.nodes[nid]
                online = ns.last_seen > 0 and now - ns.last_seen < NODE_STALE_S
                det = ns.last_det if ns.detecting else None
                nodes.append(dict(id=nid, label=node.label, lat=node.lat, lon=node.lon, online=online,
                                  detecting=bool(det), level_db=det.level_db if det else None,
                                  f0=det.f0 if det else None, floor_db=ns.floor_db, rssi=ns.rssi,
                                  packets=ns.packets, lost=ns.seq_gaps))
            tracks = []
            for tr in self.tracker.snapshot(now):
                lat, lon = f.to_ll(tr["e"], tr["n"])
                tr.update(lat=lat, lon=lon, history=[f.to_ll(e, n) for e, n in tr["history"]])
                tracks.append(tr)
            fixes = []
            for fx in self.fixes[-20:]:
                if now - fx.t < 15:
                    lat, lon = f.to_ll(fx.e, fx.n)
                    fixes.append(dict(lat=lat, lon=lon, sigma_m=fx.sigma_m, age=now - fx.t, nodes=fx.node_ids))
            vis = []
            for o in self.visual[-30:]:
                if now - o.t < 5:
                    lat, lon = f.to_ll(o.sensor_e, o.sensor_n)
                    vis.append(dict(src=o.src, lat=lat, lon=lon, az=o.az_deg, label=o.label, cls=o.cls))
            radars = []
            for rid, rd in self.site.radars.items():
                lat, lon = f.to_ll(rd.e, rd.n)
                hits = []
                seen = self.radar_seen.get(rid, 0.0)
                for h in self.radar_hits:  # targets from the latest frame only
                    if h.radar == rid and h.t == seen and now - h.t < 2:
                        hlat, hlon = f.to_ll(h.e, h.n)
                        hits.append(dict(lat=hlat, lon=hlon, range_m=h.range_m, speed=h.speed_mps))
                radars.append(dict(id=rid, label=rd.label, lat=lat, lon=lon, yaw=rd.yaw_deg, fov=rd.fov_deg,
                                   range_m=rd.max_range_m, online=seen > 0 and now - seen < RADAR_STALE_S,
                                   hits=hits))
            return dict(t=now, site=self.site.name, origin=self.site.origin, nodes=nodes,
                        tracks=tracks, fixes=fixes, visual=vis, radars=radars)
