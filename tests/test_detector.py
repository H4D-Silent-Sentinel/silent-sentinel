import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest

from cuas.detector import CombDetector
from cuas.sim.audio import drone, generator, pink, scene

ROOT = Path(__file__).resolve().parents[1]


def confirmed_frames(x):
    return sum(r.confirmed for r in CombDetector().run(x))


def test_quiet_noise_no_alarm():
    for seed in range(3):
        assert confirmed_frames(scene(8, rng=np.random.default_rng(seed))) == 0


def test_wind_no_alarm():
    assert confirmed_frames(scene(8, wind_spl=80, rng=np.random.default_rng(1))) == 0


def test_drone_detected_and_f0():
    rs = CombDetector().run(scene(6, drone_spl=55, drone_rpm=6000, rng=np.random.default_rng(2)))
    conf = [r for r in rs if r.confirmed]
    assert len(conf) > 40
    assert abs(np.median([r.f0 for r in conf]) - 200) < 5  # 2 blades x 6000 rpm / 60
    assert not conf[-1].steady


def test_generator_flagged_steady():
    rng = np.random.default_rng(3)
    n = 10 * 32000
    x = np.stack([generator(10, spl_db=55, rng=rng) + pink(n, 50, rng) for _ in range(4)])
    rs = CombDetector().run(x)
    assert rs[-1].confirmed and rs[-1].steady


def test_climbing_drone_reports_slope():
    rng = np.random.default_rng(4)
    n = 6 * 32000
    rpm = np.linspace(5000, 7000, 50)  # 167 -> 233 Hz over 6 s = +11 Hz/s
    x = np.stack([drone(6, rpm=rpm, spl_db=58, rng=np.random.default_rng(9)) + pink(n, 50, rng) for _ in range(4)])
    conf = [r for r in CombDetector().run(x) if r.confirmed]
    assert np.median([r.f0_rate for r in conf]) > 5


@pytest.mark.skipif(not shutil.which("clang++") and not shutil.which("g++"), reason="no C++ compiler")
def test_firmware_matches_reference():
    """Compile firmware/node/detector.cpp for the host and compare frame by frame."""
    cxx = shutil.which("clang++") or shutil.which("g++")
    with tempfile.TemporaryDirectory() as d:
        exe = os.path.join(d, "det")
        subprocess.run([cxx, "-std=c++17", "-O2", f"-I{ROOT/'tests/host'}", "-o", exe,
                        str(ROOT / "tests/host/run_detector.cpp"), str(ROOT / "firmware/node/detector.cpp")],
                       check=True)
        x = scene(6, drone_spl=50, noise_spl=50, rng=np.random.default_rng(5)).astype(np.float32)
        raw = os.path.join(d, "x.f32")
        x.tofile(raw)
        out = subprocess.run([exe, raw, str(x.shape[1])], capture_output=True, text=True, check=True).stdout
    fw = np.array([[float(v) for v in line.split(",")] for line in out.strip().splitlines()])
    ref = CombDetector().run(x.astype(np.float64))
    assert len(fw) == len(ref)
    py = np.array([[r.frame, r.hit, r.f0, r.score, r.n_harm, r.level_db, r.floor_db, r.confirmed]
                   for r in ref])
    agree_hit = np.mean(fw[:, 1] == py[:, 1])
    assert agree_hit > 0.95, agree_hit  # float32 vs float64 can flip a borderline frame
    assert np.mean(fw[:, 7] == py[:, 7]) > 0.95
    both = (fw[:, 1] == 1) & (py[:, 1] == 1)
    assert np.max(np.abs(fw[both, 2] - py[both, 2])) < 0.5  # f0 Hz
    assert np.max(np.abs(fw[:, 5] - py[:, 5])) < 0.5  # level dB
