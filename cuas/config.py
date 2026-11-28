"""Site configuration: where the nodes and cameras are, plus tuning knobs."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .geo import LocalFrame


@dataclass
class Node:
    id: int
    lat: float
    lon: float
    height_m: float = 2.0  # mic height above street level
    gain_db: float = 0.0  # per-node calibration added to reported level
    label: str = ""
    e: float = 0.0
    n: float = 0.0


@dataclass
class Camera:
    id: str
    lat: float | None = None  # fixed posts; a chaser reports its own pose per message
    lon: float | None = None
    height_m: float = 0.0
    label: str = ""


@dataclass
class Radar:
    id: int  # radar_id in its LoRa packets
    lat: float
    lon: float
    yaw_deg: float = 0.0  # boresight azimuth, degrees true (0 = north, 90 = east)
    height_m: float = 1.0
    flip_x: bool = False  # mirror left/right if targets move the wrong way
    max_range_m: float = 8.0
    label: str = ""


@dataclass
class Site:
    name: str
    origin: tuple[float, float]
    nodes: dict[int, Node]
    cameras: dict[str, Camera] = field(default_factory=dict)
    radars: dict[int, Radar] = field(default_factory=dict)
    drone_alt_m: float = 40.0  # assumed altitude for loudness localization
    source_level_db: float = 85.0  # prior on drone band level at 1 m (dB SPL)
    source_level_sigma_db: float = 10.0
    level_sigma_db: float = 4.0  # per-report loudness error (multipath, wind)
    atten_db_per_m: float = 0.005  # air absorption around 1 kHz
    report_window_s: float = 3.0
    frame: LocalFrame = None  # type: ignore[assignment]

    @classmethod
    def load(cls, path: str | Path) -> "Site":
        d = json.loads(Path(path).read_text())
        frame = LocalFrame(*d["origin"])
        nodes = {}
        for nd in d["nodes"]:
            node = Node(**nd)
            node.e, node.n = frame.to_en(node.lat, node.lon)
            nodes[node.id] = node
        cams = {c["id"]: Camera(**c) for c in d.get("cameras", [])}
        radars = {r["id"]: Radar(**r) for r in d.get("radars", [])}
        knobs = {k: d[k] for k in ("drone_alt_m", "source_level_db", "source_level_sigma_db",
                                   "level_sigma_db", "atten_db_per_m", "report_window_s") if k in d}
        return cls(name=d.get("name", Path(path).stem), origin=tuple(d["origin"]), nodes=nodes,
                   cameras=cams, radars=radars, frame=frame, **knobs)
