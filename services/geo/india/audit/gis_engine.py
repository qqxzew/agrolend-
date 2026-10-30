"""Real open-data queries for an Indian site (Andhra Pradesh and Gujarat first), executed concurrently.

Nothing in here is mocked: every check calls a live public endpoint. A check that fails is reported in
``GisResult.errors`` (and later in the report's ``data_quality`` / ``warnings``) — it never silently falls back to
made-up values.

What is *not* here (and why): there is no open state land-record API and no authoritative open protected-area layer
for India (WDPA withholds a large share of Indian polygons), so land records are user-supplied references and the
protected-area screen is OpenStreetMap-based. The report says so.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
import weakref
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from ..common.geo import Projector, polygon_from_geojson
from .config import AuditSettings
from .models import LandCheckInput

# Overpass search radii (m) around the site — also the "not found" cut-offs reported to the user.
R_SUBSTATION, R_POWERLINE, R_HABITATION, R_ROAD, R_TURBINE = 20_000, 10_000, 1_500, 1_000, 3_000
ESZ_BUFFER_M = 1_000  # screening distance for a possible eco-sensitive zone around a protected area
CLUSTER_MIN_BUILDINGS, CLUSTER_RADIUS_M = 15, 100  # MNRE 2024: a "cluster of dwellings" is >= 15 buildings

# One lock per event loop and name: Nominatim allows one request per second, and the public Overpass servers
# rate-limit concurrent queries per IP, so a worker sends its Overpass queries one at a time.
_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = weakref.WeakKeyDictionary()
_nominatim_last = 0.0


def _lock(name: str) -> asyncio.Lock:
    return _LOCKS.setdefault(asyncio.get_running_loop(), {}).setdefault(name, asyncio.Lock())


# --------------------------------------------------------------------------- site


@dataclass
class Site:
    poly_wgs: Polygon  # lon/lat
    poly_m: Polygon  # local UTM, metres
    proj: Projector
    lat: float  # representative point (always inside the polygon)
    lon: float
    area_ha: float
    reach_m: float  # max distance from the representative point to the polygon boundary


def build_site(inp: LandCheckInput, settings: AuditSettings) -> Site:
    """Build the analysis polygon from lat/lon(+radius) or a GeoJSON polygon."""
    if inp.polygon_geojson is not None:
        poly_wgs = polygon_from_geojson(inp.polygon_geojson)
        c = poly_wgs.representative_point()
        proj = Projector.at(c.x, c.y)
        poly_m = proj.to_m(poly_wgs)
    else:
        proj = Projector.at(inp.lon, inp.lat)
        x, y = proj.xy(inp.lon, inp.lat)
        poly_m = Point(x, y).buffer(inp.radius_m, quad_segs=16)
        poly_wgs = proj.to_wgs(poly_m)

    area_ha = poly_m.area / 10_000.0
    if area_ha <= 0:
        raise ValueError("polygon has zero area")
    if area_ha > settings.max_area_ha:
        raise ValueError(f"area {area_ha:.0f} ha exceeds the limit of {settings.max_area_ha:.0f} ha")

    rp = poly_m.representative_point()
    lon, lat = proj.lonlat(rp.x, rp.y)
    reach = max(math.dist((rp.x, rp.y), c) for c in poly_m.exterior.coords)
    return Site(poly_wgs, poly_m, proj, lat, lon, area_ha, reach)


# --------------------------------------------------------------------------- http


async def _request(client: httpx.AsyncClient, method: str, url: str, *, retries: int, **kw: Any) -> httpx.Response:
    last: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            r = await client.request(method, url, **kw)
            if r.status_code in (429, 502, 503, 504) and attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last = e
            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last or RuntimeError("request failed")  # pragma: no cover


def _explain(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code} from {e.request.url.host}"
    if isinstance(e, httpx.TimeoutException):
        return "timeout"
    return f"{type(e).__name__}: {e}"[:200]


# --------------------------------------------------------------------------- 1. administrative area (Nominatim)

_STATE_CODES = {"andhra pradesh": "IN-AP", "gujarat": "IN-GJ", "telangana": "IN-TG", "maharashtra": "IN-MH",
                "karnataka": "IN-KA", "tamil nadu": "IN-TN", "rajasthan": "IN-RJ", "madhya pradesh": "IN-MP"}


async def query_admin(client: httpx.AsyncClient, site: Site, settings: AuditSettings, retries: int) -> dict[str, Any]:
    """State / district / taluka-or-mandal / village via OSM Nominatim reverse geocoding (best effort)."""
    global _nominatim_last
    params = {"format": "jsonv2", "lat": round(site.lat, 6), "lon": round(site.lon, 6), "zoom": 14,
              "addressdetails": 1, "accept-language": "en"}
    async with _lock("nominatim"):
        wait = 1.1 - (time.monotonic() - _nominatim_last)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            r = await _request(client, "GET", settings.nominatim_url, retries=retries, params=params)
        finally:
            _nominatim_last = time.monotonic()
    body = r.json()
    if "error" in body:
        raise LookupError(f"no address found ({body['error']})")
    a = body.get("address", {})
    if a.get("country_code") not in (None, "in"):
        raise LookupError(f"location is in country '{a.get('country_code')}', not India")
    state = a.get("state")
    code = a.get("ISO3166-2-lvl4") or _STATE_CODES.get((state or "").lower())
    return {
        "state": state, "state_code": code,
        "district": a.get("state_district") or a.get("district"),
        "sub_district": a.get("county") or a.get("subdistrict"),
        "village": a.get("village") or a.get("hamlet") or a.get("town") or a.get("city") or a.get("suburb"),
    }


# --------------------------------------------------------------------------- 2. OSM Overpass


async def _overpass_fetch(client: httpx.AsyncClient, query: str, endpoints: list[str]) -> dict[str, Any]:
    """Hedged request over the Overpass mirrors: staggered starts (0 s, 6 s, 12 s, ...), first valid answer wins.
    Queries of one worker are serialised (see `_lock`)."""
    async with _lock("overpass"):
        return await _overpass_hedged(client, query, endpoints)


async def _overpass_hedged(client: httpx.AsyncClient, query: str, endpoints: list[str]) -> dict[str, Any]:
    errs: list[str] = []

    async def one(url: str, delay: float) -> dict[str, Any]:
        await asyncio.sleep(delay)
        r = await _request(client, "POST", url, retries=0, data={"data": query},
                           timeout=httpx.Timeout(45.0, connect=8.0))
        body = r.json()
        if "elements" not in body:
            raise ValueError("no 'elements' in Overpass response")
        if "runtime error" in str(body.get("remark", "")).lower():
            raise ValueError(str(body["remark"])[:120])
        return body

    tasks = {asyncio.create_task(one(u, 6.0 * i)): u for i, u in enumerate(endpoints)}
    pending = set(tasks)
    try:
        async with asyncio.timeout(80):
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    if t.exception() is None:
                        return t.result()
                    errs.append(f"{tasks[t].split('/')[2]}: {_explain(t.exception())}")
    except TimeoutError:
        errs.append("overall 80 s deadline")
    finally:
        for t in tasks:
            t.cancel()
    raise ConnectionError("all Overpass mirrors failed (" + "; ".join(errs) + ")")


def _el_geom(el: dict[str, Any]):
    """Shapely geometry (lon/lat) of an Overpass element returned with `out geom` / `out center`."""
    if el["type"] == "node":
        return Point(el["lon"], el["lat"])
    if "geometry" not in el:
        c = el.get("center")
        return Point(c["lon"], c["lat"]) if c else None
    coords = [(g["lon"], g["lat"]) for g in el["geometry"] if g]
    if len(coords) < 2:
        return None
    tags = el.get("tags", {})
    closed = len(coords) >= 4 and coords[0] == coords[-1]
    if closed and (tags.get("landuse") or tags.get("natural") or tags.get("building")):
        return Polygon(coords)
    return LineString(coords)


def _kv(tags: dict[str, str]) -> Optional[float]:
    """Highest voltage of an OSM `voltage` tag ("220000;132000") in kV."""
    best: Optional[float] = None
    for part in re.split(r"[;,]", tags.get("voltage", "")):
        try:
            v = float(part.strip()) / 1000.0
        except ValueError:
            continue
        best = v if best is None else max(best, v)
    return best


def _around(site: Site, r: int) -> str:
    return f"around:{r + math.ceil(site.reach_m)},{site.lat:.6f},{site.lon:.6f}"


def _infra_query(site: Site) -> str:
    return f"""[out:json][timeout:30];
(
  node["power"="substation"]({_around(site, R_SUBSTATION)});
  way["power"="substation"]({_around(site, R_SUBSTATION)});
  way["power"="line"]({_around(site, R_POWERLINE)});
  way["highway"~"^(trunk|primary|secondary|tertiary|unclassified|residential|track)$"]({_around(site, R_ROAD)});
  node["power"="generator"]["generator:source"="wind"]({_around(site, R_TURBINE)});
);
out geom;"""


async def query_infra(client: httpx.AsyncClient, site: Site, settings: AuditSettings) -> dict[str, Any]:
    data = await _overpass_fetch(client, _infra_query(site), settings.overpass_endpoints)
    best_sub: Optional[dict[str, Any]] = None
    best_line: Optional[tuple[float, Optional[float]]] = None
    road = False
    turbines: set[int] = set()
    for el in data["elements"]:
        tags = el.get("tags", {})
        g = _el_geom(el)
        if g is None:
            continue
        d = site.poly_m.distance(site.proj.to_m(g))
        if tags.get("power") == "substation":
            label = tags.get("name") or tags.get("operator") or "unnamed substation"
            kv = _kv(tags)
            if kv:
                label += f" ({kv:g} kV)"
            if best_sub is None or d < best_sub["d"]:
                best_sub = {"d": d, "name": label, "operator": tags.get("operator"), "kv": kv}
        elif tags.get("power") == "line":
            if best_line is None or d < best_line[0]:
                best_line = (d, _kv(tags))
        elif tags.get("highway"):
            road = road or d <= R_ROAD
        elif tags.get("power") == "generator":
            if d <= R_TURBINE:
                turbines.add(el["id"])
    if best_sub is not None and best_sub["d"] > R_SUBSTATION:
        best_sub = None
    if best_line is not None and best_line[0] > R_POWERLINE:
        best_line = None
    return {
        "substation_m": round(best_sub["d"], 1) if best_sub else None,
        "substation_name": best_sub["name"] if best_sub else None,
        "substation_operator": best_sub["operator"] if best_sub else None,
        "substation_kv": best_sub["kv"] if best_sub else None,
        "powerline_m": round(best_line[0], 1) if best_line else None,
        "powerline_kv": best_line[1] if best_line else None,
        "road_access": road,
        "wind_turbines_3km": len(turbines),
    }


def _habitation_query(site: Site) -> str:
    return f"""[out:json][timeout:30];
(
  node["place"~"^(village|hamlet|town|city|suburb|isolated_dwelling)$"]({_around(site, R_HABITATION)});
  way["landuse"="residential"]({_around(site, R_HABITATION)});
);
out geom;
way["building"]({_around(site, R_HABITATION)});
out center 600;"""


def _cluster_distance(site: Site, centres: list[Point]) -> Optional[float]:
    """Distance from the site to the nearest building that belongs to a 'cluster of dwellings' (>= 15 buildings
    within 100 m of each other — MNRE's 2024 definition, unless a state norm differs)."""
    pts = [site.proj.to_m(c) for c in centres]
    best: Optional[float] = None
    for p in pts:
        near = sum(1 for q in pts if p.distance(q) <= CLUSTER_RADIUS_M)  # includes p itself
        if near >= CLUSTER_MIN_BUILDINGS:
            d = site.poly_m.distance(p)
            best = d if best is None else min(best, d)
    return best


async def query_habitation(client: httpx.AsyncClient, site: Site, settings: AuditSettings) -> dict[str, Any]:
    data = await _overpass_fetch(client, _habitation_query(site), settings.overpass_endpoints)
    res_poly: Optional[float] = None
    place: Optional[tuple[float, str]] = None
    buildings: list[Point] = []
    for el in data["elements"]:
        tags = el.get("tags", {})
        g = _el_geom(el)
        if g is None:
            continue
        if tags.get("building"):
            buildings.append(g if isinstance(g, Point) else g.representative_point())
            continue
        d = site.poly_m.distance(site.proj.to_m(g))
        if tags.get("landuse") == "residential":
            res_poly = d if res_poly is None else min(res_poly, d)
        elif tags.get("place"):
            if place is None or d < place[0]:
                place = (d, tags.get("name") or tags["place"])
    cluster = _cluster_distance(site, buildings) if buildings else None
    candidates = [(d, basis) for d, basis in (
        (cluster, "nearest dwelling cluster (>= 15 buildings, OSM buildings)"),
        (res_poly, "nearest residential landuse polygon (OSM)"),
        (place[0] if place else None,
         f"centre of mapped settlement '{place[1] if place else ''}' (OSM place node; houses may be closer)"),
    ) if d is not None and d <= R_HABITATION]
    if not candidates:
        return {"habitation_m": None, "basis": None, "buildings_seen": len(buildings)}
    d, basis = min(candidates, key=lambda t: t[0])
    return {"habitation_m": round(d, 1), "basis": basis, "buildings_seen": len(buildings)}


# --------------------------------------------------------------------------- 3. protected areas + land cover (OSM)


@dataclass
class Zone:
    category: str
    name: str
    within_site: bool = True  # False: only found within the eco-sensitive buffer

    @property
    def veto(self) -> bool:
        return self.within_site and self.category in VETO_CATEGORIES

    def label(self) -> str:
        return f"{CATEGORY_LABELS[self.category]}: {self.name}"


# Hard stop (screening): the project cannot proceed without a central/state clearance this tool does not model.
VETO_CATEGORIES = {"NP", "WLS", "TR", "RF"}
CATEGORY_LABELS = {
    "NP": "National Park", "WLS": "Wildlife / bird sanctuary", "TR": "Tiger reserve", "RF": "Reserved Forest",
    "PF": "Protected Forest", "CR": "Conservation / community reserve", "BR": "Biosphere reserve",
    "RAMSAR": "Ramsar wetland", "OTHER": "Protected area",
}
_COVER_TAGS = (("natural", {"wood", "wetland", "water"}), ("landuse", {"forest", "reservoir"}))


def classify_protected(tags: dict[str, str]) -> Optional[str]:
    """Map OSM tags of a protected-area feature to an Indian category (None = not a protected area)."""
    if not (tags.get("boundary") in ("protected_area", "national_park") or tags.get("leisure") == "nature_reserve"
            or tags.get("protection_title")):
        return None
    text = " ".join(tags.get(k, "") for k in ("name", "name:en", "designation", "protection_title", "official_name")).lower()
    pclass = tags.get("protect_class", "")
    if tags.get("boundary") == "national_park" or "national park" in text or pclass == "2":
        return "NP"
    if "tiger reserve" in text:
        return "TR"
    if "sanctuary" in text or "sanctuary" in tags.get("designation", "").lower() or pclass in ("1a", "1b", "4"):
        return "WLS"
    if re.search(r"reserved? forest", text):
        return "RF"
    if "protected forest" in text:
        return "PF"
    if "conservation reserve" in text or "community reserve" in text:
        return "CR"
    if "biosphere" in text:
        return "BR"
    if "ramsar" in text:
        return "RAMSAR"
    if tags.get("boundary") == "protected_area" or tags.get("leisure") == "nature_reserve" or pclass:
        return "OTHER"
    return None


def _sample_points(site: Site) -> list[tuple[float, float]]:
    """(lat, lon) of the representative point and the four extreme vertices pulled 10 % towards it."""
    pts = [(site.lat, site.lon)]
    coords = list(site.poly_wgs.exterior.coords)
    for key in (lambda c: c[1], lambda c: -c[1], lambda c: c[0], lambda c: -c[0]):
        x, y = min(coords, key=key)
        p = (round(y + (site.lat - y) * 0.1, 6), round(x + (site.lon - x) * 0.1, 6))
        if p not in pts:
            pts.append(p)
    return pts


def _environment_query(site: Site) -> str:
    pts = _sample_points(site)
    is_in = "\n".join(f"is_in({lat},{lon})->.p{i};" for i, (lat, lon) in enumerate(pts))
    union = ";".join(f".p{i}" for i in range(len(pts)))
    pa = '["boundary"~"^(protected_area|national_park)$"]'
    near = _around(site, ESZ_BUFFER_M)
    cover = f'{_around(site, 0)}'
    return f"""[out:json][timeout:40];
{is_in}
({union};)->.pts;
(
  area.pts{pa};
  area.pts["leisure"="nature_reserve"];
  area.pts["protection_title"];
  area.pts["landuse"~"^(forest|reservoir)$"];
  area.pts["natural"~"^(wood|wetland|water)$"];
);
out tags;
(
  way{pa}({near});
  relation{pa}({near});
  way["leisure"="nature_reserve"]({near});
  relation["leisure"="nature_reserve"]({near});
);
out tags;
(
  way["landuse"~"^(forest|reservoir)$"]({cover});
  way["natural"~"^(wood|wetland|water)$"]({cover});
);
out geom;"""


def _is_cover(tags: dict[str, str]) -> bool:
    return any(tags.get(k) in vals for k, vals in _COVER_TAGS)


async def query_environment(client: httpx.AsyncClient, site: Site, settings: AuditSettings) -> dict[str, Any]:
    data = await _overpass_fetch(client, _environment_query(site), settings.overpass_endpoints)
    zones: dict[str, Zone] = {}
    contained_ids: set[int] = set()
    centre_in_cover = False
    cover_polys: list[Polygon] = []
    for el in data["elements"]:
        tags = el.get("tags", {})
        et = el["type"]
        cat = classify_protected(tags)
        if et == "area":
            contained_ids.add(el["id"])
            if cat:
                zones[f"a{el['id']}"] = Zone(cat, tags.get("name") or "unnamed", within_site=True)
            elif _is_cover(tags):
                centre_in_cover = True  # one of the sample points lies inside a mapped forest / water area
        elif cat:
            area_id = (3_600_000_000 if et == "relation" else 2_400_000_000) + el["id"]
            if area_id not in contained_ids and f"a{area_id}" not in zones:
                zones.setdefault(f"n{area_id}", Zone(cat, tags.get("name") or "unnamed", within_site=False))
        elif et == "way" and _is_cover(tags):
            g = _el_geom(el)
            if isinstance(g, Polygon) and g.is_valid:
                cover_polys.append(site.proj.to_m(g))
    # a zone found in the buffer search AND as containing area is the same zone: keep the containing one
    for k in [k for k, z in zones.items() if k.startswith("n") and f"a{k[1:]}" in zones]:
        zones.pop(k)
    overlap = 0.0
    if cover_polys:
        overlap = site.poly_m.intersection(unary_union(cover_polys)).area / site.poly_m.area * 100.0
    if centre_in_cover:
        overlap = 100.0 if overlap == 0 else max(overlap, 50.0)
    return {"zones": list(zones.values()), "cover_overlap_pct": round(min(overlap, 100.0), 1)}


# --------------------------------------------------------------------------- 4. solar / wind / slope


async def query_solar(client: httpx.AsyncClient, site: Site, settings: AuditSettings, retries: int) -> dict[str, Any]:
    params = {
        "lat": round(site.lat, 5), "lon": round(site.lon, 5), "peakpower": 1, "loss": 14,
        "optimalangles": 1,  # without this PVGIS assumes a flat (0 deg) array and under-reports yield
        "outputformat": "json",
    }
    r = await _request(client, "GET", settings.pvgis_url, retries=retries, params=params)
    body = r.json()
    fixed = body["outputs"]["totals"]["fixed"]
    mount = body["inputs"].get("mounting_system", {}).get("fixed", {})
    meteo = body["inputs"].get("meteo_data", {})
    return {
        "e_y": float(fixed["E_y"]),
        "elevation": body["inputs"]["location"].get("elevation"),
        "opt_slope": mount.get("slope", {}).get("value"),
        "opt_azimuth": mount.get("azimuth", {}).get("value"),
        "database": meteo.get("radiation_db") or "unknown",
    }


async def query_wind(client: httpx.AsyncClient, site: Site, settings: AuditSettings, retries: int) -> dict[str, Any]:
    """Mean ERA5 hourly 100 m wind speed over a fixed multi-year reference period (reproducible, annual)."""
    params: dict[str, Any] = {
        "latitude": round(site.lat, 5), "longitude": round(site.lon, 5), "hourly": "wind_speed_100m",
        "start_date": settings.wind_start_date, "end_date": settings.wind_end_date,
        "wind_speed_unit": "ms",  # API default is km/h
        "models": "era5",
    }
    if settings.open_meteo_api_key:
        params["apikey"] = settings.open_meteo_api_key
    r = await _request(client, "GET", settings.open_meteo_archive_url, retries=retries, params=params,
                       timeout=httpx.Timeout(90.0, connect=10.0))
    body = r.json()
    vals = [v for v in body["hourly"].get("wind_speed_100m", []) if v is not None]
    if len(vals) < 24 * 300:
        raise LookupError("Open-Meteo returned too little wind data for this location")
    return {
        "v100": sum(vals) / len(vals), "elevation": body.get("elevation"), "n": len(vals),
        "method": f"ERA5 hourly 100 m mean {settings.wind_start_date}..{settings.wind_end_date} "
                  f"(~25 km grid: smooths hills and coasts)",
    }


async def query_slope(client: httpx.AsyncClient, site: Site, settings: AuditSettings, retries: int) -> dict[str, Any]:
    """Horn slope from a 3x3 Copernicus-DEM (90 m) grid sampled via Open-Meteo."""
    d = min(max(site.reach_m / 2, 100.0), 300.0)
    x0, y0 = site.proj.xy(site.lon, site.lat)
    pts = []
    for j in (1, 0, -1):  # rows north -> south
        for i in (-1, 0, 1):
            lon, lat = site.proj.lonlat(x0 + i * d, y0 + j * d)
            pts.append((lat, lon))
    params: dict[str, Any] = {
        "latitude": ",".join(f"{p[0]:.6f}" for p in pts),
        "longitude": ",".join(f"{p[1]:.6f}" for p in pts),
    }
    if settings.open_meteo_api_key:
        params["apikey"] = settings.open_meteo_api_key
    r = await _request(client, "GET", settings.open_meteo_elevation_url, retries=retries, params=params)
    z = r.json()["elevation"]
    if len(z) != 9 or any(v is None for v in z):
        raise LookupError("incomplete elevation grid")
    a, b, c, dd, e, f, g, h, i = z
    dzdx = ((c + 2 * f + i) - (a + 2 * dd + g)) / (8 * d)
    dzdy = ((a + 2 * b + c) - (g + 2 * h + i)) / (8 * d)
    return {"slope_deg": math.degrees(math.atan(math.hypot(dzdx, dzdy))), "elevation": e, "spacing_m": d}


# --------------------------------------------------------------------------- orchestration


@dataclass
class GisResult:
    admin: Optional[dict] = None
    infra: Optional[dict] = None
    habitation: Optional[dict] = None
    environment: Optional[dict] = None
    solar: Optional[dict] = None
    wind: Optional[dict] = None
    slope: Optional[dict] = None
    errors: dict[str, str] = field(default_factory=dict)


class GisEngine:
    def __init__(self, client: httpx.AsyncClient, settings: AuditSettings):
        self.client = client
        self.s = settings

    async def run(self, site: Site) -> GisResult:
        res = GisResult()
        retries = self.s.http_retries
        jobs = {
            "admin": query_admin(self.client, site, self.s, retries),
            "infra": query_infra(self.client, site, self.s),
            "habitation": query_habitation(self.client, site, self.s),
            "environment": query_environment(self.client, site, self.s),
            "solar": query_solar(self.client, site, self.s, retries),
            "wind": query_wind(self.client, site, self.s, retries),
            "slope": query_slope(self.client, site, self.s, retries),
        }
        outcomes = await asyncio.gather(*jobs.values(), return_exceptions=True)
        for key, out in zip(jobs, outcomes):
            if isinstance(out, BaseException):
                res.errors[key] = _explain(out) if isinstance(out, Exception) else repr(out)
            else:
                setattr(res, key, out)
        return res
