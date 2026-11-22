"""Rotor-comb detector: reference implementation.

This is the algorithm the ESP32 node runs (firmware/node/detector.cpp mirrors it
step for step, with the same constants from firmware/node/config.h). Keeping a
numpy version lets us tune it on recordings and simulations on a laptop first.

Per frame (4096 samples @ 32 kHz, hop 2048 → 15.6 frames/s, 7.8 Hz bins):
  1. High-pass each mic at 60 Hz (cuts wind rumble / handling noise).
  2. Hann window + FFT per mic, average the 4 power spectra.
     (Incoherent average: needs no clock sync between the two I2S buses, and
     wind, which is uncorrelated mic-to-mic, averages down.)
  3. Whiten: subtract a running median across frequency (33 bins ≈ ±125 Hz).
     Broadband noise (traffic, wind) becomes ~0 dB; tones stick out.
  4. Mask bins that have held a tone for minutes (AC units, transformers).
  5. Comb search: for every candidate spacing f0 in 70–400 Hz, compare the
     spectrum AT the harmonics h·f0 with the spectrum HALFWAY between them,
     (h+½)·f0. A rotor comb gives a big positive contrast; noise gives ~0;
     the wrong octave gives ~0 or negative.
  6. Confirm: comb in ≥6 of the last 8 frames with a consistent f0.
  7. Features: f0 slope (drones slide), f0 jitter (steady → likely machinery),
     harmonic band level (for range), confidence.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import lfilter

# ---- Constants: keep in sync with firmware/node/config.h -------------------
FS = 32000
N_FFT = 4096
HOP = 2048
N_CH = 4
DF = FS / N_FFT  # 7.8125 Hz per bin
FRAME_RATE = FS / HOP  # 15.625 frames/s

HPF_HZ = 60.0
F0_MIN, F0_MAX, F0_STEP = 70.0, 400.0, 0.5
FMAX_HARM = 3000.0
H_MAX = 12
MIN_HARM = 3
HARM_DB = 6.0  # a harmonic "counts" if this far above the local median
SCORE_DB = 6.0  # comb contrast needed for a frame-level hit
W_CLIP_LO, W_CLIP_HI = -10.0, 30.0
MEDIAN_BINS = 33
WARMUP_FRAMES = 16

CONFIRM_WIN, CONFIRM_HITS, RELEASE_HITS = 8, 6, 3
HINT_CONFIRM_HITS = 3  # while a C2 hint is active: hits near the hinted f0 needed to re-confirm
F0_TOL = 0.10  # relative f0 agreement within the confirm window

TONAL_ALPHA = 0.001  # ~2.5 min to learn a persistent tone
TONAL_MASK = 0.9

STEADY_WIN = 64  # frames (~4 s)
STEADY_MIN = 40
STEADY_REL_STD = 0.0015  # < 0.15 % f0 wander → "steady" (machinery-like)
SLOPE_WIN = 16  # frames (~1 s) for f0 slope

SPL_OFFSET = 120.0  # ICS-43434: -26 dBFS @ 94 dB SPL → SPL = dBFS + 120

K_MAX = int(np.ceil((FMAX_HARM * 1.1) / DF)) + 2  # only analyse bins we need


def hann(n: int) -> np.ndarray:
    return (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)).astype(np.float32)


def hpf_coeffs(fc: float, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """RBJ cookbook 2nd-order Butterworth high-pass (Q = 1/sqrt2)."""
    w0 = 2 * np.pi * fc / fs
    alpha = np.sin(w0) / (2 * (1 / np.sqrt(2)))
    c = np.cos(w0)
    b = np.array([(1 + c) / 2, -(1 + c), (1 + c) / 2])
    a = np.array([1 + alpha, -2 * c, 1 - alpha])
    return b / a[0], a / a[0]


def _build_comb_tables():
    f0s = np.arange(F0_MIN, F0_MAX + 1e-9, F0_STEP)
    h = np.arange(1, H_MAX + 1)
    n_h = np.minimum(H_MAX, np.floor(FMAX_HARM / f0s)).astype(int)
    on = np.rint(np.outer(f0s, h) / DF).astype(int)
    off = np.rint(np.outer(f0s, h + 0.5) / DF).astype(int)
    mask = h[None, :] <= n_h[:, None]
    on = np.clip(on, 1, K_MAX - 2)
    off = np.clip(off, 1, K_MAX - 2)
    return f0s, n_h, on, off, mask


F0S, N_H, ON_BINS, OFF_BINS, H_MASK = _build_comb_tables()


@dataclass
class FrameResult:
    frame: int
    hit: bool
    f0: float
    score: float
    n_harm: int
    level_db: float  # harmonic band level, dB SPL
    floor_db: float  # median per-bin background, dB SPL
    confirmed: bool
    steady: bool
    f0_rate: float  # Hz/s
    confidence: int
    clipping: bool


class CombDetector:
    def __init__(self, n_ch: int = N_CH):
        self.n_ch = n_ch
        self.b, self.a = hpf_coeffs(HPF_HZ, FS)
        self.zi = np.zeros((n_ch, 2))
        self.buf = np.zeros((n_ch, N_FFT), dtype=np.float32)
        self.win = hann(N_FFT)
        self.win_norm = 4.0 / (self.win.sum() ** 2)  # P[k] = A² for a sine of amplitude A
        self.tonal = np.zeros(K_MAX)
        self.frame = 0
        self.hist = deque(maxlen=max(CONFIRM_WIN, STEADY_WIN))  # (hit, f0)
        self.confirmed = False
        self.hint_f0 = 0.0  # C2 re-acquire hint (Hz); 0 = none
        self.hint_until = -1  # last frame the hint applies to

    # -- spectrum -----------------------------------------------------------
    def _spectrum_db(self, block: np.ndarray) -> np.ndarray:
        y, self.zi = lfilter(self.b, self.a, block, axis=1, zi=self.zi)
        self.buf = np.roll(self.buf, -HOP, axis=1)
        self.buf[:, -HOP:] = y
        X = np.fft.rfft(self.buf * self.win, axis=1)[:, :K_MAX]
        P = (np.abs(X) ** 2).mean(axis=0) * self.win_norm
        return 10 * np.log10(P + 1e-20)

    # -- one hop ------------------------------------------------------------
    def process(self, block: np.ndarray) -> FrameResult:
        """block: float array [n_ch, HOP] in full-scale units (±1.0)."""
        block = np.asarray(block, dtype=np.float64).reshape(self.n_ch, HOP)
        clipping = bool(np.max(np.abs(block)) > 0.99)
        P_db = self._spectrum_db(block)
        med = median_filter(P_db, size=MEDIAN_BINS, mode="nearest")
        W = P_db - med

        self.tonal += TONAL_ALPHA * ((W > HARM_DB).astype(float) - self.tonal)
        W = np.where(self.tonal > TONAL_MASK, 0.0, W)
        W = np.clip(W, W_CLIP_LO, W_CLIP_HI)

        # Comb contrast: max over ±1 bin at harmonic and at half-harmonic.
        Wmax3 = np.maximum(np.maximum(W[:-2], W[1:-1]), W[2:])
        Wmax3 = np.concatenate([[W[0]], Wmax3, [W[-1]]])
        on = np.where(H_MASK, Wmax3[ON_BINS], 0.0)
        off = np.where(H_MASK, Wmax3[OFF_BINS], 0.0)
        scores = (on.sum(1) - off.sum(1)) / N_H
        i = int(np.argmax(scores))
        f0, score = float(F0S[i]), float(scores[i])
        n_harm = int(((on[i] > HARM_DB) & H_MASK[i]).sum())
        f0 = self._refine_f0(P_db, f0, on[i])

        harm_bins = ON_BINS[i][H_MASK[i]]
        level_db = 10 * np.log10(np.sum(10 ** (P_db[harm_bins] / 10))) + SPL_OFFSET
        lo, hi = int(100 / DF), int(FMAX_HARM / DF)
        floor_db = float(np.median(P_db[lo:hi])) + SPL_OFFSET

        warm = self.frame >= WARMUP_FRAMES
        hit = warm and score >= SCORE_DB and n_harm >= MIN_HARM
        self.hist.append((hit, f0))
        self._update_confirm()
        steady, rate = self._features()
        conf = self._confidence(score, n_harm, steady) if self.confirmed else 0

        r = FrameResult(self.frame, hit, f0, score, n_harm, float(level_db), floor_db,
                        self.confirmed, steady, rate, conf, clipping)
        self.frame += 1
        return r

    @staticmethod
    def _refine_f0(P_db: np.ndarray, f0: float, on_row: np.ndarray) -> float:
        """Grid f0 is only good to ~±1 bin/h. Fit f0 through the interpolated
        peak frequency of every strong harmonic (least squares through origin)."""
        num = den = 0.0
        for h in range(1, H_MAX + 1):
            if h * f0 > FMAX_HARM or on_row[h - 1] <= HARM_DB:
                continue
            c = int(round(h * f0 / DF))
            k = c - 1 + int(np.argmax(P_db[c - 1:c + 2]))
            if k < 1 or k > K_MAX - 2:
                continue
            a, b, g = P_db[k - 1], P_db[k], P_db[k + 1]
            d = a - 2 * b + g
            delta = 0.5 * (a - g) / d if d < 0 else 0.0
            fh = (k + float(np.clip(delta, -0.5, 0.5))) * DF
            num += h * fh
            den += h * h
        return num / den if den > 0 else f0

    def set_hint(self, f0_hz: float, frames: int) -> None:
        """C2 says a drone with this comb spacing is still nearby: for the next `frames`
        frames, re-confirm on HINT_CONFIRM_HITS hits within F0_TOL of f0_hz."""
        self.hint_f0 = float(f0_hz) if frames > 0 else 0.0
        self.hint_until = self.frame + int(frames) if frames > 0 else -1

    def _update_confirm(self):
        recent = list(self.hist)[-CONFIRM_WIN:]
        f0s = [f for h, f in recent if h]
        hinted = self.hint_f0 > 0 and self.frame <= self.hint_until
        if not self.confirmed and hinted:
            near = sum(abs(f - self.hint_f0) <= F0_TOL * self.hint_f0 for f in f0s)
            self.confirmed = near >= HINT_CONFIRM_HITS
        elif not self.confirmed:
            if len(f0s) >= CONFIRM_HITS:
                m = float(np.median(f0s))
                agree = sum(abs(f - m) <= F0_TOL * m for f in f0s)
                self.confirmed = agree >= CONFIRM_HITS
        elif len(f0s) < RELEASE_HITS:
            self.confirmed = False

    def _features(self) -> tuple[bool, float]:
        h = list(self.hist)
        f_all = np.array([f for hit, f in h[-STEADY_WIN:] if hit])
        steady = False
        if len(f_all) >= STEADY_MIN:
            steady = bool(np.std(f_all) / np.mean(f_all) < STEADY_REL_STD)
        recent = h[-SLOPE_WIN:]
        t = np.array([k for k, (hit, _) in enumerate(recent) if hit], dtype=float)
        f = np.array([fv for hit, fv in recent if hit])
        rate = 0.0
        if len(t) >= 4:
            t = t / FRAME_RATE
            tc = t - t.mean()
            rate = float(np.sum(tc * (f - f.mean())) / np.sum(tc * tc))
        return steady, rate

    @staticmethod
    def _confidence(score: float, n_harm: int, steady: bool) -> int:
        c = 60 * np.clip((score - SCORE_DB) / 14, 0, 1)
        c += 30 * np.clip((n_harm - MIN_HARM) / 6, 0, 1)
        c += 0 if steady else 10
        return int(round(c))

    def run(self, x: np.ndarray) -> list[FrameResult]:
        """Process a whole [n_ch, n] signal; returns one result per hop."""
        x = np.atleast_2d(x)
        if x.shape[0] != self.n_ch:
            x = np.repeat(x[:1], self.n_ch, axis=0)
        return [self.process(x[:, s:s + HOP]) for s in range(0, x.shape[1] - HOP + 1, HOP)]
