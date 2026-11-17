"""Rough position from loudness.

Nodes don't share precise clocks, so no time-difference triangulation. Instead
each node reports how loud the rotor comb is; sound falls ~6 dB per doubling
of distance, so

    L_i = S - 20 log10(d_i) - a d_i + g_i

with S the (unknown) source level at 1 m, d_i the 3-D distance node→drone,
a air absorption, g_i a per-node calibration. Unknowns (e, n, S) are solved by
weighted least squares with weak priors on S and on position (so one or two
nodes still give a usable, appropriately fuzzy fix). Altitude is assumed.

Outlier rejection: with 4+ nodes, a node whose residual is > 3σ (an echo, or
a node that's shadowed by a building) is dropped and the fit redone.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from .config import Site

POS_PRIOR_SIGMA_M = 150.0
OUTLIER_SIGMA = 3.0


@dataclass
class AcousticReport:
    node_id: int
    t: float
    level_db: float
    f0: float
    confidence: int = 0
    steady: bool = False


@dataclass
class Fix:
    t: float
    e: float
    n: float
    cov: np.ndarray  # 2x2, m²
    source_db: float
    f0: float
    node_ids: list[int]
    dropped: list[int] = field(default_factory=list)
    rms: float = 0.0  # normalised residual RMS

    @property
    def sigma_m(self) -> float:
        return float(np.sqrt(np.trace(self.cov) / 2))


def cluster_by_f0(reports: list[AcousticReport], tol: float = 0.15) -> list[list[AcousticReport]]:
    """Different drones usually have different blade-pass frequencies."""
    rs = sorted(reports, key=lambda r: r.f0)
    groups: list[list[AcousticReport]] = []
    for r in rs:
        if groups and abs(np.log(r.f0 / np.median([g.f0 for g in groups[-1]]))) < tol:
            groups[-1].append(r)
        else:
            groups.append([r])
    return groups


def _fit(reports, site: Site, x0):
    P = np.array([[site.nodes[r.node_id].e, site.nodes[r.node_id].n, site.nodes[r.node_id].height_m]
                  for r in reports])
    L = np.array([r.level_db - site.nodes[r.node_id].gain_db for r in reports])
    w = 10 ** (L / 20)
    ce, cn = (P[:, :2] * w[:, None]).sum(0) / w.sum()
    sl, a, alt = site.level_sigma_db, site.atten_db_per_m, site.drone_alt_m

    def resid(x):
        e, n, S = x
        d = np.sqrt((e - P[:, 0]) ** 2 + (n - P[:, 1]) ** 2 + (alt - P[:, 2]) ** 2)
        d = np.maximum(d, 1.0)
        model = S - 20 * np.log10(d) - a * d
        return np.concatenate([(L - model) / sl,
                               [(S - site.source_level_db) / site.source_level_sigma_db,
                                (e - ce) / POS_PRIOR_SIGMA_M, (n - cn) / POS_PRIOR_SIGMA_M]])

    return least_squares(resid, x0, method="lm"), len(reports)


def locate(reports: list[AcousticReport], site: Site) -> Fix | None:
    reports = [r for r in reports if r.node_id in site.nodes]
    if not reports:
        return None
    dropped: list[int] = []
    while True:
        best = None
        L = np.array([r.level_db for r in reports])
        loud = reports[int(np.argmax(L))]
        ln = site.nodes[loud.node_id]
        P = np.array([[site.nodes[r.node_id].e, site.nodes[r.node_id].n] for r in reports])
        w = 10 ** (L / 20)
        cen = (P * w[:, None]).sum(0) / w.sum()
        for start in (cen, np.array([ln.e, ln.n])):
            S0 = loud.level_db + 20 * np.log10(max(site.drone_alt_m - ln.height_m, 10.0))
            res, m = _fit(reports, site, np.array([start[0], start[1], S0]))
            if best is None or res.cost < best[0].cost:
                best = (res, m)
        res, m = best
        r_nodes = res.fun[:m]
        if len(reports) >= 4 and np.max(np.abs(r_nodes)) > OUTLIER_SIGMA:
            k = int(np.argmax(np.abs(r_nodes)))
            dropped.append(reports[k].node_id)
            reports = reports[:k] + reports[k + 1:]
            continue
        break
    J = res.jac
    try:
        cov = np.linalg.inv(J.T @ J)[:2, :2]
    except np.linalg.LinAlgError:
        cov = np.eye(2) * POS_PRIOR_SIGMA_M ** 2
    rms = float(np.sqrt(np.mean(r_nodes ** 2)))
    cov = cov * max(1.0, rms ** 2)  # inflate if the data disagree with the model
    e, n, S = res.x
    return Fix(t=max(r.t for r in reports), e=float(e), n=float(n), cov=cov, source_db=float(S),
               f0=float(np.median([r.f0 for r in reports])), node_ids=[r.node_id for r in reports],
               dropped=dropped, rms=rms)
