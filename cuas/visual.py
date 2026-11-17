"""Interface to the Jetson Orin Nano visual tracker (Visual-Tracker repo).

Transport: one JSON object per UDP datagram. Spec: docs/jetson-interface.md.

  Jetson -> base   "visual"  camera detections/tracks          (base port 47010)
  base   -> Jetson "cue"     where the acoustic network thinks
                             the drone is, so the camera/chaser
                             knows where to look               (Jetson port 47011)
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass

from .geo import LocalFrame

VISUAL_PORT = 47010
CUE_PORT = 47011
SCHEMA_VERSION = 1


@dataclass
class VisualObs:
    src: str
    t: float
    sensor_e: float
    sensor_n: float
    sensor_alt: float
    track_id: int | None
    az_deg: float
    el_deg: float | None
    az_sigma_deg: float
    range_m: float | None
    range_sigma_m: float | None
    conf: float
    cls: str
    label: str | None


def parse_visual(raw: bytes | str, frame: LocalFrame, fixed_cams: dict | None = None) -> list[VisualObs]:
    """Turn one Jetson datagram into bearing (and optional range) observations.

    If a track omits az_deg/el_deg, they're computed from the bbox centre and
    the camera pose (yaw/pitch/hfov/vfov), so the Jetson can send either."""
    m = json.loads(raw)
    if m.get("v") != SCHEMA_VERSION or m.get("type") != "visual":
        raise ValueError("not a v1 visual message")
    s = dict(m.get("sensor") or {})
    if (s.get("lat") is None) and fixed_cams and m["src"] in fixed_cams:
        cam = fixed_cams[m["src"]]  # fixed post: position comes from the site file
        s["lat"], s["lon"] = cam.lat, cam.lon
        s.setdefault("alt_m", cam.height_m)
    if s.get("lat") is None or s.get("lon") is None:
        raise ValueError(f"no position for sensor {m.get('src')}")
    se, sn = frame.to_en(s["lat"], s["lon"])
    out = []
    for tr in m.get("tracks", []):
        az, el = tr.get("az_deg"), tr.get("el_deg")
        if az is None:
            bx, by, bw, bh = tr["bbox"]  # normalised 0..1, x right, y down
            u, v = bx + bw / 2 - 0.5, by + bh / 2 - 0.5
            hf, vf = math.radians(s["hfov_deg"]), math.radians(s["vfov_deg"])
            az = s["yaw_deg"] + math.degrees(math.atan(2 * u * math.tan(hf / 2)))
            el = s.get("pitch_deg", 0.0) - math.degrees(math.atan(2 * v * math.tan(vf / 2)))
        out.append(VisualObs(
            src=m["src"], t=float(m.get("t", time.time())), sensor_e=se, sensor_n=sn,
            sensor_alt=float(s.get("alt_m", 0.0)), track_id=tr.get("id"), az_deg=float(az) % 360,
            el_deg=None if el is None else float(el), az_sigma_deg=float(tr.get("az_sigma_deg", 1.0)),
            range_m=tr.get("range_m"), range_sigma_m=tr.get("range_sigma_m"),
            conf=float(tr.get("conf", 0.5)), cls=tr.get("class", "unknown"), label=tr.get("label")))
    return out


def make_cue(track: dict, frame: LocalFrame, t: float | None = None) -> bytes:
    lat, lon = frame.to_ll(track["e"], track["n"])
    msg = {
        "v": SCHEMA_VERSION, "type": "cue", "t": t or time.time(), "track_id": track["id"],
        "lat": round(lat, 7), "lon": round(lon, 7), "alt_m": round(track["alt_m"], 1),
        "sigma_m": round(track["sigma_m"], 1), "vel_e": round(track["ve"], 2), "vel_n": round(track["vn"], 2),
        "f0_hz": None if track["f0"] is None else round(track["f0"], 1),
        "confirmed": track["confirmed"], "sources": track["sources"],
    }
    return json.dumps(msg, separators=(",", ":")).encode()


def make_visual(src: str, t: float, sensor: dict, tracks: list[dict]) -> bytes:
    """Reference encoder; the Jetson side should produce exactly this shape."""
    return json.dumps({"v": SCHEMA_VERSION, "type": "visual", "src": src, "t": t,
                       "sensor": sensor, "tracks": tracks}, separators=(",", ":")).encode()
