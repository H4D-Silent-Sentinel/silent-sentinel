import json
import math
from pathlib import Path

import numpy as np

from cuas.base import Base
from cuas.config import Site
from cuas.localize import AcousticReport, locate
from cuas.sim.scenario import DEFAULT_PATH, DroneSim, NetworkSim, run
from cuas.tracker import Tracker
from cuas.visual import make_cue, make_visual, parse_visual

SITE = Path(__file__).resolve().parents[1] / "sites/example_intersection.json"


def synth_reports(site, e, n, S=85.0, noise=0.0, rng=None):
    out = []
    for nid, nd in site.nodes.items():
        r = math.sqrt((e - nd.e) ** 2 + (n - nd.n) ** 2 + (site.drone_alt_m - nd.height_m) ** 2)
        L = S - 20 * math.log10(r) - site.atten_db_per_m * r + (rng.normal(0, noise) if rng else 0)
        out.append(AcousticReport(nid, 0.0, L, 200.0))
    return out


def test_locate_noiseless():
    site = Site.load(SITE)
    fix = locate(synth_reports(site, 20.0, -15.0), site)
    assert math.hypot(fix.e - 20, fix.n + 15) < 5
    assert abs(fix.source_db - 85) < 2


def test_locate_drops_echo_outlier():
    site = Site.load(SITE)
    reps = synth_reports(site, 10.0, 10.0)
    reps[2].level_db += 20  # node 3 hears a loud reflection
    fix = locate(reps, site)
    assert 3 in fix.dropped
    assert math.hypot(fix.e - 10, fix.n - 10) < 10


def test_tracker_follows_constant_velocity():
    tr = Tracker()
    rng = np.random.default_rng(0)
    R = np.eye(2) * 1.0
    for k in range(40):
        t = k * 1.0
        tr.update_position((5 * t + rng.normal(0, 1), -3 * t + rng.normal(0, 1)), R, t, source="acoustic")
    (track,) = tr.tracks.values()
    assert track.confirmed
    assert abs(track.x[2] - 5) < 2.5 and abs(track.x[3] + 3) < 2.5  # sigma_accel=3 keeps it agile, so v is noisy


def test_bearing_update_tightens_crossrange():
    tr = Tracker()
    tr.update_position((100.0, 0.0), np.eye(2) * 50 ** 2, 0.0, source="acoustic")
    (track,) = tr.tracks.values()
    before = track.P[1, 1]
    tr.update_bearing((0.0, 0.0), 90.0, 1.0, 0.1, source="visual:post-1")  # due east
    assert track.P[1, 1] < before / 10  # north (cross-range) uncertainty collapses


def test_visual_bbox_to_bearing():
    site = Site.load(SITE)
    msg = make_visual("chaser-1", 0.0, {"lat": site.origin[0], "lon": site.origin[1], "alt_m": 30,
                                        "yaw_deg": 90, "pitch_deg": 0, "hfov_deg": 60, "vfov_deg": 40},
                      [{"id": 1, "bbox": [0.70, 0.45, 0.10, 0.10], "conf": 0.9, "class": "drone"}])
    (o,) = parse_visual(msg, site.frame)
    # bbox centre u=+0.25 of width -> atan(0.5*tan30) ≈ 16.1° right of yaw
    assert abs(o.az_deg - (90 + math.degrees(math.atan(0.5 * math.tan(math.radians(30)))))) < 0.01
    assert abs(o.el_deg) < 0.01


def test_cue_message_shape():
    site = Site.load(SITE)
    cue = json.loads(make_cue(dict(id=4, e=10, n=20, alt_m=40, sigma_m=25, ve=1, vn=2, f0=200,
                                   confirmed=True, sources=["acoustic"]), site.frame, 1.0))
    assert cue["type"] == "cue" and cue["v"] == 1 and cue["track_id"] == 4


def _sim(cameras=True, seed=0):
    site = Site.load(SITE)
    if not cameras:
        site.cameras = {}
    base = Base(site)
    log = run(site, base, NetworkSim(site, [DroneSim(DEFAULT_PATH)], seed=seed))
    e = np.array([r["err"][0] for r in log if r["err"][0] is not None])
    return e


def test_sim_acoustic_only_tracks():
    e = _sim(cameras=False)
    fin = e[np.isfinite(e)]
    assert len(fin) > 0.6 * len(e)
    assert np.median(fin) < 70


def test_sim_camera_improves_track():
    a = _sim(cameras=False, seed=1)
    v = _sim(cameras=True, seed=1)
    assert np.median(v[np.isfinite(v)]) < np.median(a[np.isfinite(a)])
