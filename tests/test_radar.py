import math
from pathlib import Path

from cuas.base import Base
from cuas.config import Site
from cuas.radar import FrameParser, MULTI_TARGET_CMD, RadarTarget, decode_frame, encode_frame
from cuas.sim.scenario import DEFAULT_PATH, DroneSim, NetworkSim, run

SITES = Path(__file__).resolve().parents[1] / "sites"


def test_frame_sign_magnitude():
    # bytes are little-endian; the top bit set means positive
    raw = bytes.fromhex("AAFF0300" "0E03" "B185" "1000" "6801" + "00" * 16 + "55CC")
    (tg,) = decode_frame(raw)
    assert tg.x_m == -0x030E / 1000          # top bit clear -> negative
    assert tg.y_m == (0x85B1 - 0x8000) / 1000  # top bit set -> positive
    assert tg.speed_mps == -0x10 / 100
    assert tg.res_m == 0x168 / 1000


def test_round_trip_and_empty_slots():
    tgs = [RadarTarget(-1.25, 3.5, 0.4), RadarTarget(2.0, 6.0, -1.1)]
    out = decode_frame(encode_frame(tgs))
    assert len(out) == 2
    for a, b in zip(tgs, out):
        assert abs(a.x_m - b.x_m) < 1e-3 and abs(a.y_m - b.y_m) < 1e-3 and abs(a.speed_mps - b.speed_mps) < 1e-2
    assert decode_frame(encode_frame([])) == []


def test_parser_handles_garbage_and_split_frames():
    f1, f2 = encode_frame([RadarTarget(0.5, 2.0, 0.3)]), encode_frame([RadarTarget(-0.5, 4.0, 0.3)])
    stream = b"ESP-ROM boot junk\r\n" + MULTI_TARGET_CMD + f1 + b"\xAA\xFF" + f2
    p = FrameParser()
    got = []
    for k in range(0, len(stream), 7):
        got += p.feed(stream[k:k + 7])
    assert [round(g[0].y_m, 3) for g in got] == [2.0, 4.0]


def test_radar_hit_lands_where_the_radar_points():
    site = Site.load(SITES / "demo_bench_radar.json")
    rd = site.radars["r1"]
    rd.yaw_deg = 90  # facing east
    base = Base(site)
    for k in range(4):  # target 3 m out, 30° right of boresight -> bearing 120°
        a = math.radians(30)
        base.on_radar("r1", [RadarTarget(3 * math.sin(a), 3 * math.cos(a), 0.5)], t=k * 0.2)
    (tr,) = base.tracker.snapshot(0.6)
    assert tr["confirmed"] and tr["sources"] == ["radar:r1"]
    assert math.hypot(tr["e"] - (rd.e + 3 * math.sin(math.radians(120))),
                      tr["n"] - (rd.n + 3 * math.cos(math.radians(120)))) < 0.3
    st = base.state(0.6)
    assert st["radars"][0]["online"] and len(st["radars"][0]["hits"]) == 1


def test_handoff_radar_to_acoustic_keeps_one_track():
    site = Site.load(SITES / "radar_handoff.json")
    base = Base(site)
    snaps = []
    run(site, base, NetworkSim(site, [DroneSim(DEFAULT_PATH)], seed=1),
        on_tick=lambda t, s: snaps.append((t, [x for x in s if x["confirmed"]])))
    radar_only = [s for t, s in snaps if s and s[0]["live_sources"] == ["radar:r1"]]
    assert radar_only, "radar should see the drone first, before the acoustic nodes"
    first_id = radar_only[0][0]["id"]
    later = [s for t, s in snaps if t > 45 and s]
    assert later and all("radar:r1" not in s[0]["live_sources"] for s in later)  # radar has lost it
    assert any(tr["id"] == first_id and "acoustic" in tr["live_sources"] for s in later for tr in s)
