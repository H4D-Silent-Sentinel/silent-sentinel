"""Local east/north/up frame around a site origin (equirectangular; fine for a few km)."""
from __future__ import annotations

import math

R_EARTH = 6371000.0


class LocalFrame:
    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self._k = math.cos(math.radians(lat0))

    def to_en(self, lat: float, lon: float) -> tuple[float, float]:
        e = math.radians(lon - self.lon0) * self._k * R_EARTH
        n = math.radians(lat - self.lat0) * R_EARTH
        return e, n

    def to_ll(self, e: float, n: float) -> tuple[float, float]:
        lat = self.lat0 + math.degrees(n / R_EARTH)
        lon = self.lon0 + math.degrees(e / (R_EARTH * self._k))
        return lat, lon


def bearing_deg(de: float, dn: float) -> float:
    """Azimuth clockwise from true north, 0..360."""
    return math.degrees(math.atan2(de, dn)) % 360.0


def wrap_pi(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi
