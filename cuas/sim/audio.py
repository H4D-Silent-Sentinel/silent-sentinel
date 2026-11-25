"""Synthetic audio for exercising the detector before we have field recordings.

Levels are in dB SPL; output is in full-scale units as the ICS-43434 would
report them (dBFS = dB SPL - 120).
"""
from __future__ import annotations

import numpy as np

from ..detector import FS, N_CH, SPL_OFFSET


def _fs_amp(spl_db: float) -> float:
    """RMS in full-scale units for a given SPL."""
    return 10 ** ((spl_db - SPL_OFFSET) / 20) / np.sqrt(2)


def _random_walk(n: int, rng, rel_std: float, corr_s: float = 0.5) -> np.ndarray:
    """Smooth multiplicative wander around 1.0 (motor RPM hunting)."""
    k = max(1, int(corr_s * FS))
    step = max(1, k // 8)
    coarse = rng.standard_normal(n // step + 2)
    a = np.exp(-1 / 8)
    for i in range(1, len(coarse)):
        coarse[i] = a * coarse[i - 1] + np.sqrt(1 - a * a) * coarse[i]
    walk = np.interp(np.arange(n), np.arange(len(coarse)) * step, coarse)
    return 1 + rel_std * walk


def drone(duration: float, rpm=6000.0, blades=2, motors=4, spl_db=60.0,
          rpm_wander=0.015, harmonics=14, rng=None) -> np.ndarray:
    """Multirotor tone comb. `rpm` may be scalar or array over time (per-sample)."""
    rng = rng or np.random.default_rng()
    n = int(duration * FS)
    base = np.broadcast_to(np.asarray(rpm, dtype=float), (n,)) if np.ndim(rpm) == 0 \
        else np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(rpm)), rpm)
    out = np.zeros(n)
    for _ in range(motors):
        r = base * (1 + 0.004 * rng.standard_normal()) * _random_walk(n, rng, rpm_wander)
        bpf = blades * r / 60.0
        phase = 2 * np.pi * np.cumsum(bpf) / FS
        for h in range(1, harmonics + 1):
            if h * blades * base.max() / 60.0 * 1.05 >= FS / 2:
                break  # nothing above Nyquist
            amp = h ** -0.8 * 10 ** (rng.normal(0, 2) / 20)
            out += amp * np.sin(h * phase + rng.uniform(0, 2 * np.pi))
    out *= _fs_amp(spl_db) / (np.std(out) + 1e-12)
    return out


def pink(n: int, spl_db: float, rng) -> np.ndarray:
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / FS)
    X /= np.sqrt(np.maximum(f, 20.0))
    x = np.fft.irfft(X, n)
    return x * _fs_amp(spl_db) / np.std(x)


def wind(n: int, spl_db: float, rng) -> np.ndarray:
    """Gusty low-frequency rumble (mostly < 100 Hz)."""
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / FS)
    X /= np.maximum(f, 2.0) ** 1.5
    x = np.fft.irfft(X, n)
    gust = 0.5 + _random_walk(n, rng, 0.5, corr_s=2.0).clip(0.1)
    x *= gust
    return x * _fs_amp(spl_db) / np.std(x)


def generator(duration: float, f0=120.0, spl_db=55.0, rng=None) -> np.ndarray:
    """Steady machinery hum: same comb shape as a rotor but it never moves."""
    return drone(duration, rpm=f0 * 30, blades=2, motors=1, spl_db=spl_db,
                 rpm_wander=0.0, rng=rng)


def scene(duration: float, *, drone_spl=None, drone_rpm=6000.0, drone_blades=2, noise_spl=50.0,
          wind_spl=None, gen_spl=None, n_ch=N_CH, rng=None) -> np.ndarray:
    """4-mic recording: shared sources + independent per-mic noise/wind."""
    rng = rng or np.random.default_rng()
    n = int(duration * FS)
    common = np.zeros(n)
    if drone_spl is not None:
        common += drone(duration, rpm=drone_rpm, blades=drone_blades, spl_db=drone_spl, rng=rng)
    if gen_spl is not None:
        common += generator(duration, spl_db=gen_spl, rng=rng)
    x = np.empty((n_ch, n))
    for c in range(n_ch):
        x[c] = common + pink(n, noise_spl, rng)
        if wind_spl is not None:
            x[c] += wind(n, wind_spl, rng)
    return x
