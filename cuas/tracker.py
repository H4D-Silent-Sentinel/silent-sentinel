"""Multi-sensor Kalman tracker.

State per track: [east, north, v_east, v_north] in metres / m/s on the site's
local frame (altitude is carried separately as a simple estimate).

Measurement types, all fused into the same tracks:
  * position + covariance  - acoustic loudness fixes (fuzzy), or camera
                             detections that include a range estimate
  * bearing from a known point - camera detections without range (EKF update)

Each sensor is weighted by its own covariance, so precise sensors pull the
track hard and fuzzy ones pull gently. Gating (Mahalanobis distance) keeps
reports that land far from a track's prediction from being attached to it;
they start a new tentative track instead. Through gaps the filter keeps
predicting and its uncertainty grows until something hears or sees it again.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from .geo import wrap_pi

GATE_POS = 13.8  # chi² 2 dof, 99.9 %
GATE_BRG = 10.8  # chi² 1 dof, 99.9 %
SIGMA_ACCEL = 3.0  # m/s², manoeuvre noise
INIT_VEL_SIGMA = 15.0
CONFIRM_HITS = 3
CONFIRM_SENSORS = 2  # ...or this many different sensors on the same track, whichever comes first
MAX_COAST_S = 30.0
MAX_SIGMA_M = 400.0
F0_ASSOC_TOL = 0.2  # |ln(f0a/f0b)|


@dataclass
class Track:
    id: int
    x: np.ndarray
    P: np.ndarray
    t: float
    alt_m: float
    hits: int = 1
    last_update: float = 0.0
    f0: float | None = None
    sources: dict[str, float] = field(default_factory=dict)  # sensor kind -> last time
    label: str | None = None  # e.g. classification from the Jetson VLM
    history: list[tuple[float, float, float]] = field(default_factory=list)

    @property
    def confirmed(self) -> bool:
        return self.hits >= CONFIRM_HITS or len(self.sources) >= CONFIRM_SENSORS

    @property
    def sigma_m(self) -> float:
        return float(np.sqrt(np.trace(self.P[:2, :2]) / 2))

    @property
    def speed(self) -> float:
        return float(np.hypot(self.x[2], self.x[3]))

    @property
    def course_deg(self) -> float:
        return math.degrees(math.atan2(self.x[2], self.x[3])) % 360


def _F_Q(dt: float):
    F = np.eye(4)
    F[0, 2] = F[1, 3] = dt
    q = SIGMA_ACCEL ** 2
    Q1 = q * np.array([[dt ** 4 / 4, dt ** 3 / 2], [dt ** 3 / 2, dt ** 2]])
    Q = np.zeros((4, 4))
    Q[np.ix_([0, 2], [0, 2])] = Q1
    Q[np.ix_([1, 3], [1, 3])] = Q1
    return F, Q


class Tracker:
    def __init__(self):
        self.tracks: dict[int, Track] = {}
        self._ids = itertools.count(1)

    # -- prediction ----------------------------------------------------------
    def _predicted(self, tr: Track, t: float):
        dt = max(0.0, t - tr.t)
        F, Q = _F_Q(dt)
        return F @ tr.x, F @ tr.P @ F.T + Q

    def predict_to(self, tr: Track, t: float) -> None:
        tr.x, tr.P = self._predicted(tr, t)
        tr.t = max(tr.t, t)

    # -- position measurements ----------------------------------------------
    def update_position(self, z, R, t: float, *, source: str, f0: float | None = None,
                        alt_m: float | None = None, label: str | None = None,
                        can_init: bool = True) -> Track | None:
        z = np.asarray(z, float)
        R = np.asarray(R, float)
        H = np.zeros((2, 4)); H[0, 0] = H[1, 1] = 1
        best, best_d2 = None, GATE_POS
        for tr in self.tracks.values():
            if f0 and tr.f0 and abs(math.log(f0 / tr.f0)) > F0_ASSOC_TOL:
                continue
            x, P = self._predicted(tr, t)
            S = H @ P @ H.T + R
            y = z - H @ x
            d2 = float(y @ np.linalg.solve(S, y))
            if d2 < best_d2:
                best, best_d2 = tr, d2
        if best is None:
            if not can_init:
                return None
            P0 = np.zeros((4, 4))
            P0[:2, :2] = R
            P0[2, 2] = P0[3, 3] = INIT_VEL_SIGMA ** 2
            tr = Track(next(self._ids), np.array([z[0], z[1], 0.0, 0.0]), P0, t,
                       alt_m if alt_m is not None else 40.0, last_update=t, f0=f0)
            tr.sources[source] = t
            if label:
                tr.label = label
            tr.history.append((t, z[0], z[1]))
            self.tracks[tr.id] = tr
            return tr
        tr = best
        self.predict_to(tr, t)
        S = H @ tr.P @ H.T + R
        K = tr.P @ H.T @ np.linalg.inv(S)
        tr.x = tr.x + K @ (z - H @ tr.x)
        tr.P = (np.eye(4) - K @ H) @ tr.P
        self._after_update(tr, t, source, f0, alt_m, label)
        return tr

    # -- bearing measurements -------------------------------------------------
    def update_bearing(self, sensor_en, az_deg: float, sigma_deg: float, t: float, *,
                       source: str, label: str | None = None) -> Track | None:
        """Bearing-only report (camera without range). Updates the best-gated
        existing track; can't start a track on its own."""
        se, sn = sensor_en
        z = math.radians(az_deg)
        r2 = math.radians(sigma_deg) ** 2
        best, best_d2 = None, GATE_BRG
        for tr in self.tracks.values():
            x, P = self._predicted(tr, t)
            de, dn = x[0] - se, x[1] - sn
            rho2 = de * de + dn * dn
            if rho2 < 1.0:
                continue
            H = np.array([[dn / rho2, -de / rho2, 0, 0]])
            S = float((H @ P @ H.T)[0, 0]) + r2
            y = wrap_pi(z - math.atan2(de, dn))
            d2 = y * y / S
            if d2 < best_d2:
                best, best_d2 = tr, d2
        if best is None:
            return None
        tr = best
        self.predict_to(tr, t)
        de, dn = tr.x[0] - se, tr.x[1] - sn
        rho2 = de * de + dn * dn
        H = np.array([[dn / rho2, -de / rho2, 0, 0]])
        S = float((H @ tr.P @ H.T)[0, 0]) + r2
        K = (tr.P @ H.T / S).ravel()
        y = wrap_pi(z - math.atan2(de, dn))
        tr.x = tr.x + K * y
        tr.P = (np.eye(4) - np.outer(K, H)) @ tr.P
        self._after_update(tr, t, source, None, None, label)
        return tr

    def _after_update(self, tr, t, source, f0, alt_m, label):
        tr.hits += 1
        tr.last_update = t
        tr.sources[source] = t
        if f0:
            tr.f0 = f0 if tr.f0 is None else 0.7 * tr.f0 + 0.3 * f0
        if alt_m is not None:
            tr.alt_m = 0.7 * tr.alt_m + 0.3 * alt_m
        if label:
            tr.label = label
        tr.history.append((t, float(tr.x[0]), float(tr.x[1])))
        del tr.history[:-300]

    # -- housekeeping ----------------------------------------------------------
    def prune(self, t: float) -> list[Track]:
        gone = []
        for tid, tr in list(self.tracks.items()):
            _, P = self._predicted(tr, t)
            coast = t - tr.last_update
            sigma = float(np.sqrt(np.trace(P[:2, :2]) / 2))
            if coast > MAX_COAST_S or sigma > MAX_SIGMA_M or (not tr.confirmed and coast > 10):
                gone.append(self.tracks.pop(tid))
        return gone

    def snapshot(self, t: float) -> list[dict]:
        out = []
        for tr in self.tracks.values():
            x, P = self._predicted(tr, t)
            out.append(dict(id=tr.id, e=float(x[0]), n=float(x[1]), ve=float(x[2]), vn=float(x[3]),
                            cov=P[:2, :2].tolist(), sigma_m=float(np.sqrt(np.trace(P[:2, :2]) / 2)),
                            alt_m=tr.alt_m, confirmed=tr.confirmed, f0=tr.f0, label=tr.label,
                            coast_s=t - tr.last_update, sources=sorted(tr.sources),
                            history=[(e, n) for _, e, n in tr.history[-60:]]))
        return out
