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
    id: str
    lat: float
    lon: float
    yaw_deg: float = 0.0  # where the radar's face points, degrees clockwise from north
    height_m: float = 1.0
    fov_deg: float = 120.0
    max_range_m: float = 8.0  # RD-03D; raise it in a site file to simulate a real radar
    range_sigma_m: float = 0.3
    az_sigma_deg: float = 4.0
    flip_x: bool = False  # set if targets move the wrong way left/right on the map
    label: str = ""
    e: float = 0.0
    n: float = 0.0


@dataclass
class Site:
    name: str
    origin: tuple[float, float]
    nodes: dict[int, Node]
    cameras: dict[str, Camera] = field(default_factory=dict)
    radars: dict[str, Radar] = field(default_factory=dict)
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
        radars = {}
        for rd in d.get("radars", []):
            radar = Radar(**rd)
            radar.e, radar.n = frame.to_en(radar.lat, radar.lon)
            radars[radar.id] = radar
        knobs = {k: d[k] for k in ("drone_alt_m", "source_level_db", "source_level_sigma_db",
                                   "level_sigma_db", "atten_db_per_m", "report_window_s") if k in d}
        return cls(name=d.get("name", Path(path).stem), origin=tuple(d["origin"]), nodes=nodes,
                   cameras=cams, radars=radars, frame=frame, **knobs)
