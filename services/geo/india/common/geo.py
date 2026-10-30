"""Geometry helpers for India.

India spans UTM zones 42-47, so there is no single metric CRS that is accurate everywhere: EPSG:7755 (India NSF
LCC) was measured at ~2 % scale error in Gujarat and ESRI:102028 (Albers) at ~10 %. Every metric computation
therefore happens in the UTM zone of the geometry's own centre (`Projector`). Geometries are stored and exchanged
as WGS84 GeoJSON.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

from pyproj import Transformer
from shapely.geometry import Polygon, shape
from shapely.ops import transform as shp_transform
from shapely.validation import make_valid

# Bounding box of the Indian mainland + islands, used for input validation only.
LAT_MIN, LAT_MAX = 6.0, 37.5
LON_MIN, LON_MAX = 68.0, 97.5


def utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180.0) // 6.0) + 1
    return (32600 if lat >= 0 else 32700) + zone


@lru_cache(maxsize=64)
def _transformer(src: int, dst: int) -> Transformer:
    return Transformer.from_crs(src, dst, always_xy=True)


@dataclass(frozen=True)
class Projector:
    """WGS84 <-> local UTM (metres) around a reference point."""

    epsg: int

    @classmethod
    def at(cls, lon: float, lat: float) -> "Projector":
        return cls(utm_epsg(lon, lat))

    @property
    def fwd(self) -> Transformer:
        return _transformer(4326, self.epsg)

    @property
    def inv(self) -> Transformer:
        return _transformer(self.epsg, 4326)

    def to_m(self, geom):
        return shp_transform(self.fwd.transform, geom)

    def to_wgs(self, geom):
        return shp_transform(self.inv.transform, geom)

    def xy(self, lon: float, lat: float) -> tuple[float, float]:
        return self.fwd.transform(lon, lat)

    def lonlat(self, x: float, y: float) -> tuple[float, float]:
        return self.inv.transform(x, y)


def polygon_from_geojson(gj: dict[str, Any]) -> Polygon:
    """GeoJSON Polygon (or Feature wrapping one) -> valid shapely Polygon, lon/lat order."""
    if gj.get("type") == "Feature":
        gj = gj.get("geometry") or {}
    if gj.get("type") != "Polygon":
        raise ValueError("polygon_geojson must be a GeoJSON Polygon in EPSG:4326")
    poly = shape(gj)
    if not poly.is_valid:
        poly = make_valid(poly)
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        if poly.geom_type != "Polygon":
            raise ValueError("polygon_geojson is not a valid polygon")
    minx, miny, maxx, maxy = poly.bounds
    if not (LON_MIN <= minx and maxx <= LON_MAX and LAT_MIN <= miny and maxy <= LAT_MAX):
        raise ValueError("polygon must lie within India's bounding box (coordinates are lon,lat)")
    return poly


def degrees_for_metres(lat: float, metres: float) -> tuple[float, float]:
    """(dlat, dlon) in degrees that cover `metres` around `lat` — for SQL bounding-box prefilters."""
    dlat = metres / 111_000.0
    dlon = metres / (111_320.0 * max(math.cos(math.radians(lat)), 0.2))
    return dlat, dlon


def project_pair(a_wgs, b_wgs) -> tuple[Any, Any, Projector]:
    """Both geometries in the UTM zone of `a`'s centre (accurate for the few-km distances used here)."""
    c = a_wgs.representative_point()
    p = Projector.at(c.x, c.y)
    return p.to_m(a_wgs), p.to_m(b_wgs), p


ToMetres = Callable[[Any], Any]
