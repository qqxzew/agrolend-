"""Crop and biomass monitoring for farm parcels with a boundary (the "crop_monitoring" section of a Lease Check).

Sources (open, no account or key):
  * Sentinel-2 L2A surface reflectance at 10 m (ESA Copernicus), read through the Microsoft Planetary Computer STAC and data API:
    bands B04 (red), B08 (near infrared) and SCL (scene classification, used as the cloud mask). One request per scene reads
    a small window around a group of neighbouring parcels; the statistics per parcel are computed here.
  * Daily global shortwave radiation at the farm centre (Open-Meteo, ERA5 archive).

Per parcel the section holds:
  * the cloud-screened NDVI series: mean of the clear pixels whose centre lies inside the boundary;
  * season indicators (peak, latest, baseline = the field's own lowest value) and a plain-language canopy status;
  * a season biomass ESTIMATE with Monteith's light-use-efficiency model (above-ground dry matter, t/ha):
        biomass = sum over days of  LUE(crop group) x fAPAR(NDVI) x 0.48 x global radiation,
        fAPAR   = 0.95 x clip((NDVI - soil) / (0.90 - soil), 0, 1),   soil = baseline + 0.10 (bare soil NDVI varies with moisture)
  * the same window one year earlier, for comparison;
  * observations worth a look (listed as farmed but no crop canopy; not listed but a crop canopy; lease area vs boundary).

Every derived number is recomputed by `verify` from the observations and radiation stored in the report. The observations
themselves can be re-read from the named Sentinel-2 items (a published L2A product does not change).
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
import numpy as np
import shapely
from pyproj import Geod, Transformer
from shapely.geometry import mapping, shape

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
DATA_URL = "https://planetarycomputer.microsoft.com/api/data/v1"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
COLLECTION = "sentinel-2-l2a"
USER_AGENT = "AgroLand/1.0 (crop monitoring; +https://github.com/)"
METHOD_VERSION = "agroland-cropwatch/1"

CLEAR = (4, 5, 6, 7)      # SCL: vegetation, not vegetated, water, unclassified
CLOUD = (3, 8, 9, 10)     # SCL: cloud shadow, cloud medium / high probability, thin cirrus
MAX_SCENE_CLOUD = 80      # % of the whole tile; scenes above this are not downloaded
MAX_FIELD_CLOUD = 0.10    # share of a parcel's pixels flagged as cloud or shadow; above this the scene is not used for it
MIN_CLEAR_SHARE = 0.60    # share of a parcel's pixels that must be clear
GROUP_MAX_M = 1500        # neighbouring parcels are read together in windows of at most 1.5 x 1.5 km
PIXEL_M = 10
PAR_SHARE = 0.48          # photosynthetically active share of global shortwave radiation
FAPAR_MAX = 0.95
NDVI_FULL = 0.90          # NDVI of a closed green canopy
BASELINE_RANGE = (0.12, 0.30)
SOIL_MARGIN = 0.10        # bare soil alone moves NDVI by about this much (moisture, residue); only canopy above it absorbs PAR
# Light-use efficiency, g above-ground dry matter per MJ absorbed PAR. Generic crop-group values of the size reported in the
# crop-physiology literature for crops without water or nutrient stress (e.g. Sinclair & Muchow 1999, Adv. Agron. 65), not calibrated
# for any field: hence the +-30 % range, and stressed rain-fed fields produce less.
LUE = {"c4": 3.0, "c3_cereal": 2.6, "other": 2.2, "unknown": 2.4}
LUE_UNCERTAINTY = 0.30
C4_WORDS = ("maize", "corn", "mais", "sorghum", "jowar", "millet", "bajra", "ragi", "sugarcane", "ganna")
C3_CEREAL_WORDS = ("wheat", "weizen", "gerste", "barley", "rice", "paddy", "rye", "roggen", "triticale", "oat", "hafer", "dinkel")
SEASON_START = {"IN": "06-01", "DE": "03-01"}  # India: kharif sowing with the monsoon; Germany: start of the main growing season
FLAG_PEAK_NO_CROP, FLAG_AMPLITUDE_NO_CROP = 0.40, 0.15
FLAG_PEAK_CROP, FLAG_AMPLITUDE_CROP = 0.50, 0.20
FLAG_BIOMASS_DROP = 0.70
GEOD = Geod(ellps="WGS84")
M2 = {"ha": 10_000.0, "acre": 4046.8564224}


class SourceError(RuntimeError):
    """A source did not answer; the section reports it as unavailable instead of guessing."""


# ----------------------------------------------------------------------------------------------------------------- pure helpers
def r4(x: float) -> float:
    return float(round(x, 4))


def r2(x: float) -> float:
    return float(round(x, 2))


def days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def year_back(d: str) -> str:
    x = date.fromisoformat(d)
    try:
        return x.replace(year=x.year - 1).isoformat()
    except ValueError:  # 29 February
        return x.replace(year=x.year - 1, day=28).isoformat()


def season_window(today: str, start_mmdd: str) -> dict:
    """The season so far: from the last start date that lies at least 30 days back, until today."""
    t = date.fromisoformat(today)
    m, d = (int(x) for x in start_mmdd.split("-"))
    s = date(t.year, m, d)
    if s > t - timedelta(days=30):
        s = date(t.year - 1, m, d)
    return {"start": s.isoformat(), "end": t.isoformat()}


def previous_window(w: dict) -> dict:
    return {"start": year_back(w["start"]), "end": year_back(w["end"])}


def crop_group(crop: Optional[str]) -> str:
    c = (crop or "").strip().lower()
    if not c:
        return "unknown"
    if any(w in c for w in C4_WORDS):
        return "c4"
    if any(w in c for w in C3_CEREAL_WORDS):
        return "c3_cereal"
    return "other"


def area_m2(geom) -> float:
    return abs(GEOD.geometry_area_perimeter(geom)[0])


def series_metrics(obs: list[dict], window: dict) -> dict:
    """Indicators of one window from its clear observations (sorted by date)."""
    if not obs:
        return {"clear_observations": 0}
    nd = [o["ndvi"] for o in obs]
    peak = max(obs, key=lambda o: (o["ndvi"], o["date"]))
    edges = [window["start"]] + [o["date"] for o in obs] + [window["end"]]
    return {"clear_observations": len(obs), "first_date": obs[0]["date"], "last_date": obs[-1]["date"],
            "peak_ndvi": peak["ndvi"], "peak_date": peak["date"], "latest_ndvi": obs[-1]["ndvi"], "latest_date": obs[-1]["date"],
            "baseline_ndvi": r4(min(max(min(nd), BASELINE_RANGE[0]), BASELINE_RANGE[1])),
            "max_gap_days": max(days_between(a, b) for a, b in zip(edges, edges[1:]))}


def fapar(ndvi: float, baseline: float) -> float:
    soil = baseline + SOIL_MARGIN
    return FAPAR_MAX * min(max((ndvi - soil) / (NDVI_FULL - soil), 0.0), 1.0)


def biomass(obs: list[dict], radiation: dict[str, Optional[float]], window: dict, lue: float, baseline: float) -> dict:
    """Light-use-efficiency estimate between the first and the last clear observation of the window (no extrapolation)."""
    if len(obs) < 2:
        return {"t_per_ha": None, "reason": "fewer than two clear observations"}
    s, e = max(window["start"], obs[0]["date"]), min(window["end"], obs[-1]["date"])
    pts = [(days_between(s, o["date"]), o["ndvi"]) for o in obs]
    grams, used, missing = 0.0, 0, 0
    for k in range(days_between(s, e) + 1):
        day = (date.fromisoformat(s) + timedelta(days=k)).isoformat()
        sw = radiation.get(day)
        if sw is None:
            missing += 1
            continue
        j = next(i for i in range(1, len(pts)) if pts[i][0] >= k) if k > 0 else 1
        (k0, v0), (k1, v1) = pts[j - 1], pts[j]
        ndvi = v0 if k1 == k0 else v0 + (v1 - v0) * (k - k0) / (k1 - k0)
        grams += lue * fapar(ndvi, baseline) * PAR_SHARE * sw
        used += 1
    t = grams / 100.0  # 1 g/m2 = 0.01 t/ha
    return {"t_per_ha": r2(t), "low": r2(t * (1 - LUE_UNCERTAINTY)), "high": r2(t * (1 + LUE_UNCERTAINTY)), "from": s, "to": e,
            "integrated_days": used, "window_days": days_between(window["start"], window["end"]) + 1, "missing_radiation_days": missing,
            "lue_g_per_mj": lue}


def canopy_status(m: dict, today: str) -> dict:
    if not m.get("clear_observations"):
        return {"code": "no_clear_view", "text": "No cloud-free view of this field in the season so far"}
    lat, peak, base, when = m["latest_ndvi"], m["peak_ndvi"], m["baseline_ndvi"], m["latest_date"]
    stale = days_between(when, today) > 30
    suffix = f" (last clear view {when}, {days_between(when, today)} days ago)" if stale else ""
    if lat >= 0.55:
        return {"code": "dense_canopy", "text": f"Dense green canopy: NDVI {lat:.2f} on {when}{suffix}"}
    if lat >= 0.35:
        return {"code": "green_canopy", "text": f"Green canopy: NDVI {lat:.2f} on {when}{suffix}"}
    if peak >= 0.45 and peak - base >= 0.2 and m["peak_date"] < when:
        return {"code": "after_peak", "text": f"Crop canopy earlier this season (peak NDVI {peak:.2f} on {m['peak_date']}); now low ({lat:.2f}): harvested or senescing{suffix}"}
    if peak < FLAG_PEAK_NO_CROP and peak - base < FLAG_AMPLITUDE_NO_CROP:
        return {"code": "no_crop_signal", "text": f"No crop canopy seen this season (peak NDVI {peak:.2f}){suffix}"}
    return {"code": "sparse", "text": f"Sparse vegetation: NDVI {lat:.2f} on {when}{suffix}"}


def parcel_flags(p: dict, ctx: dict) -> list[dict]:
    """Observations worth a look. They are not findings about money and they are not proof: a satellite sees canopy, not contracts."""
    out, m = [], p["metrics"]["season"]
    unit, s = ctx["area_unit"], ctx
    if m.get("clear_observations", 0) >= 3:
        amp = m["peak_ndvi"] - m["baseline_ndvi"]
        if p["farmed"] and m["peak_ndvi"] < FLAG_PEAK_NO_CROP and amp < FLAG_AMPLITUDE_NO_CROP:
            out.append({"type": "farmed_but_no_crop_signal", "numbers": {"peak_ndvi": m["peak_ndvi"], "baseline_ndvi": m["baseline_ndvi"], "clear_observations": m["clear_observations"]},
                        "text": f"Parcel {p['parcel_id']} is on your list of farmed fields ({p['crop'] or 'crop not stated'}), but no crop canopy was seen this season "
                                f"(peak NDVI {m['peak_ndvi']:.2f} in {m['clear_observations']} clear views)."})
        if not p["farmed"] and m["peak_ndvi"] >= FLAG_PEAK_CROP and amp >= FLAG_AMPLITUDE_CROP:
            out.append({"type": "crop_signal_not_listed", "numbers": {"peak_ndvi": m["peak_ndvi"], "peak_date": m["peak_date"], "baseline_ndvi": m["baseline_ndvi"]},
                        "text": f"Parcel {p['parcel_id']} is not on your list of farmed fields, but a crop canopy was seen (peak NDVI {m['peak_ndvi']:.2f} on {m['peak_date']}). "
                                f"Either the list is incomplete or someone else is using the land."})
    b, bp = p["biomass"]["season"], p["biomass"]["previous"]
    if b.get("t_per_ha") is not None and bp.get("t_per_ha") and bp["t_per_ha"] >= 1.0 \
            and b["integrated_days"] >= 0.5 * b["window_days"] and bp["integrated_days"] >= 0.5 * bp["window_days"] \
            and b["t_per_ha"] < FLAG_BIOMASS_DROP * bp["t_per_ha"]:
        out.append({"type": "biomass_below_last_year", "numbers": {"season_t_per_ha": b["t_per_ha"], "previous_t_per_ha": bp["t_per_ha"]},
                    "text": f"Season biomass estimate for {p['parcel_id']} is {b['t_per_ha']:.1f} t/ha against {bp['t_per_ha']:.1f} t/ha in the same weeks last year "
                            f"({round(100 * (b['t_per_ha'] / bp['t_per_ha'] - 1))} %)."})
    lease, bound = p.get("area_contract"), p["boundary"]["area"]
    if lease is not None and bound > 0:
        diff = r2(lease - bound)
        if abs(diff) > max(s["area_tolerance"], 0.1 * bound):
            src = "the 5am.earth on-chain registration" if p["boundary"]["source"] == "5am.earth" else "the boundary on file"
            out.append({"type": "lease_area_vs_boundary", "numbers": {"area_contract": lease, "boundary_area": bound, "diff": diff},
                        "text": f"Lease {p['contract_id']} bills {lease:g} {unit}; the field boundary from {src} measures {bound:g} {unit} ({diff:+g} {unit})."})
    return out


def derive(p: dict, radiation: dict, windows: dict, today: str, ctx: dict) -> dict:
    """Everything that follows from the stored observations; used both to build and to verify a report."""
    lue = LUE[crop_group(p["crop"])]
    out = {"metrics": {}, "biomass": {}}
    for k in ("season", "previous"):
        m = series_metrics(p["observations"][k], windows[k])
        out["metrics"][k] = m
        out["biomass"][k] = biomass(p["observations"][k], radiation, windows[k], lue, m["baseline_ndvi"]) if m.get("clear_observations") else \
            {"t_per_ha": None, "reason": "no clear observation"}
    b, bp = out["biomass"]["season"].get("t_per_ha"), out["biomass"]["previous"].get("t_per_ha")
    # a percentage against an almost bare field last year (+1000 %, -100 %) says nothing: compare only from 1 t/ha
    out["biomass"]["change_pct"] = round(100 * (b / bp - 1)) if b is not None and bp is not None and bp >= 1.0 else None
    out["biomass"]["field_t"] = r2(b * p["boundary"]["area_ha"]) if b is not None else None
    out["status"] = canopy_status(out["metrics"]["season"], today)
    out["flags"] = parcel_flags({**p, **out}, ctx)
    return out


# ----------------------------------------------------------------------------------------------------------------- pixels
def utm_epsg(lon: float, lat: float) -> int:
    return (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1


def project(geom, epsg: int):
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    return shapely.transform(geom, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))


def window_for(geoms_utm: list, pad: float = 20.0) -> tuple[float, float, float, float, int, int]:
    """Window aligned to the 20 m grid shared by every Sentinel-2 tile of a UTM zone (so 10 m and 20 m pixels are native)."""
    b = shapely.total_bounds(geoms_utm)
    minx, miny = 20 * math.floor((b[0] - pad) / 20), 20 * math.floor((b[1] - pad) / 20)
    maxx, maxy = 20 * math.ceil((b[2] + pad) / 20), 20 * math.ceil((b[3] + pad) / 20)
    return float(minx), float(miny), float(maxx), float(maxy), int((maxx - minx) // PIXEL_M), int((maxy - miny) // PIXEL_M)


def pixel_mask(geom_utm, win) -> tuple[np.ndarray, str]:
    minx, miny, maxx, maxy, w, h = win
    xs = minx + PIXEL_M / 2 + PIXEL_M * np.arange(w)
    ys = maxy - PIXEL_M / 2 - PIXEL_M * np.arange(h)
    gx, gy = np.meshgrid(xs, ys)
    m = shapely.contains_xy(geom_utm, gx, gy)
    if m.sum() >= 3:
        return m, "pixel centres inside the boundary"
    cells = shapely.box(gx - PIXEL_M / 2, gy - PIXEL_M / 2, gx + PIXEL_M / 2, gy + PIXEL_M / 2)
    return shapely.intersects(geom_utm, cells), "pixels touching the boundary (small field: edge pixels mix with the neighbours)"


def observe(arr: np.ndarray, mask: np.ndarray, offset: int) -> dict:
    """One parcel in one scene. arr = (B04, B08, SCL, valid) on the window grid."""
    px = int(mask.sum())
    scl, valid = arr[2], arr[3] > 0
    inside = mask & valid & (scl > 0)
    if px == 0 or inside.sum() < 0.95 * px:
        return {"use": False, "why": "no_data"}
    cloudy = int((mask & np.isin(scl, CLOUD)).sum())
    red = arr[0].astype(np.float64) - offset
    nir = arr[1].astype(np.float64) - offset
    # Reflectance at or below zero is an atmospheric-correction artefact (it would read as NDVI 1.0): such pixels are not clear.
    clear = inside & np.isin(scl, CLEAR) & (red > 0) & (nir > 0)
    if cloudy > MAX_FIELD_CLOUD * px or clear.sum() < MIN_CLEAR_SHARE * px:
        return {"use": False, "why": "cloudy"}
    nd = (nir[clear] - red[clear]) / (nir[clear] + red[clear])
    return {"use": True, "ndvi": r4(float(nd.mean())), "ndvi_p10": r4(float(np.percentile(nd, 10))), "ndvi_p90": r4(float(np.percentile(nd, 90))),
            "clear_px": int(clear.sum()), "px": px}


def boa_offset(baseline: Optional[str]) -> int:
    """Processing baseline 04.00 (January 2022) and later store reflectance x 10000 + 1000."""
    try:
        return 1000 if float(baseline or "0") >= 4.0 else 0
    except ValueError:
        return 1000


def groups(parcels: dict[str, Any], epsg: int) -> list[list[str]]:
    """Greedy grouping of parcels into windows of at most GROUP_MAX_M x GROUP_MAX_M metres."""
    utm = {k: project(g, epsg) for k, g in parcels.items()}
    out: list[tuple[list[str], list[float]]] = []
    for k in sorted(utm, key=lambda k: shapely.bounds(utm[k])[0]):
        b = list(shapely.bounds(utm[k]))
        for ids, gb in out:
            nb = [min(gb[0], b[0]), min(gb[1], b[1]), max(gb[2], b[2]), max(gb[3], b[3])]
            if nb[2] - nb[0] <= GROUP_MAX_M and nb[3] - nb[1] <= GROUP_MAX_M:
                ids.append(k)
                gb[:] = nb
                break
        else:
            out.append(([k], b))
    return [ids for ids, _ in out]


# ----------------------------------------------------------------------------------------------------------------- network
class Fetcher:
    """The only part that talks to the outside world. Tests give it an httpx MockTransport."""

    def __init__(self, cache_dir: Optional[Path] = None, transport: Optional[httpx.BaseTransport] = None, workers: int = 6, retries: int = 4,
                 stac_url: str = STAC_URL, data_url: str = DATA_URL, archive_url: str = ARCHIVE_URL, forecast_url: str = FORECAST_URL):
        self.http = httpx.Client(timeout=90.0, transport=transport, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        self.cache, self.workers, self.retries = cache_dir, workers, retries
        self.stac, self.data, self.archive, self.forecast = stac_url.rstrip("/"), data_url.rstrip("/"), archive_url, forecast_url
        if self.cache:
            (self.cache / "scenes").mkdir(parents=True, exist_ok=True)

    def _get(self, method: str, url: str, **kw) -> httpx.Response:
        last = ""
        for attempt in range(self.retries):
            try:
                r = self.http.request(method, url, **kw)
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            else:
                if r.status_code == 200:
                    return r
                last = f"HTTP {r.status_code}"
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
            if attempt + 1 < self.retries:
                time.sleep(min(8.0, 1.0 * 2 ** attempt))
        raise SourceError(f"{url.split('/')[2]}: {last}")

    def search(self, bbox: list[float], window: dict) -> list[dict]:
        body = {"collections": [COLLECTION], "bbox": bbox, "datetime": f"{window['start']}T00:00:00Z/{window['end']}T23:59:59Z", "limit": 250,
                "query": {"eo:cloud_cover": {"lt": MAX_SCENE_CLOUD}},
                "fields": {"include": ["id", "geometry", "properties.datetime", "properties.eo:cloud_cover", "properties.s2:processing_baseline",
                                       "properties.s2:mgrs_tile", "properties.proj:epsg", "properties.proj:code"], "exclude": ["assets", "links"]}}
        items, url = [], f"{self.stac}/search"
        for _ in range(20):
            j = self._get("POST", url, json=body).json()
            for f in j.get("features", []):
                p = f.get("properties", {})
                epsg = p.get("proj:epsg") or (int(str(p["proj:code"]).split(":")[1]) if p.get("proj:code") else None)
                if not epsg and p.get("s2:mgrs_tile"):
                    t = p["s2:mgrs_tile"]
                    epsg = (32600 if t[2].upper() >= "N" else 32700) + int(t[:2])
                items.append({"id": f["id"], "date": p["datetime"][:10], "cloud": r2(p.get("eo:cloud_cover", 100.0)), "baseline": p.get("s2:processing_baseline"),
                              "epsg": int(epsg), "footprint": f.get("geometry")})
            nxt = next((link for link in j.get("links", []) if link.get("rel") == "next"), None)
            if not nxt:
                break
            url, body = nxt["href"], nxt.get("body", body)
        return items

    def scene(self, item_id: str, epsg: int, win: tuple) -> np.ndarray:
        minx, miny, maxx, maxy, w, h = win
        key = hashlib.sha256(f"{item_id}|{epsg}|{minx}|{miny}|{maxx}|{maxy}".encode()).hexdigest()[:32]
        path = self.cache / "scenes" / f"{key}.npy" if self.cache else None
        if path and path.exists():
            return np.load(path, allow_pickle=False)
        params = [("collection", COLLECTION), ("item", item_id), ("assets", "B04"), ("assets", "B08"), ("assets", "SCL"),
                  ("coord_crs", f"EPSG:{epsg}"), ("dst_crs", f"EPSG:{epsg}"), ("resampling", "nearest")]
        r = self._get("GET", f"{self.data}/item/bbox/{minx},{miny},{maxx},{maxy}/{w}x{h}.npy", params=params)
        arr = np.load(io.BytesIO(r.content), allow_pickle=False)
        if arr.shape != (4, h, w):
            raise SourceError(f"unexpected scene array shape {arr.shape}")
        if path:
            tmp = path.with_suffix(".tmp")
            with open(tmp, "wb") as fh:
                np.save(fh, arr, allow_pickle=False)
            tmp.replace(path)
        return arr

    def radiation(self, lat: float, lon: float, start: str, end: str) -> dict[str, Optional[float]]:
        q = {"latitude": round(lat, 4), "longitude": round(lon, 4), "daily": "shortwave_radiation_sum", "timezone": "UTC"}
        j = self._get("GET", self.archive, params={**q, "start_date": start, "end_date": end}).json()["daily"]
        out = dict(zip(j["time"], j["shortwave_radiation_sum"]))
        gap = [d for d, v in out.items() if v is None and days_between(d, date.today().isoformat()) <= 90]
        if gap:  # the archive lags a few days behind; the forecast API serves the recent past
            k = self._get("GET", self.forecast, params={**q, "past_days": min(92, days_between(min(gap), date.today().isoformat()) + 1), "forecast_days": 1}).json()["daily"]
            out.update({d: v for d, v in zip(k["time"], k["shortwave_radiation_sum"]) if d in out and out[d] is None})
        return {d: (r2(v) if v is not None else None) for d, v in out.items()}


# ----------------------------------------------------------------------------------------------------------------- the section
def parcels_of(dataset: dict) -> list[dict]:
    """Parcels of the dataset that have a boundary, joined with the lease and field rows."""
    s = dataset["settings"]
    unit = s["area_unit"]
    out = []
    for f in (dataset.get("boundaries") or {}).get("features", []):
        pid = f["properties"]["parcel_id"]
        g = shape(f["geometry"])
        c = next((x for x in dataset["contracts"] if x["parcel_id"] == pid), None)
        fl = next((x for x in dataset["fields"] if x["parcel_id"] == pid), None)
        a = area_m2(g)
        reg = f["properties"].get("registry")
        out.append({"parcel_id": pid, "contract_id": c["contract_id"] if c else None, "owner": c["owner"] if c else None,
                    "area_contract": c["area_contract"] if c else None, "farmed": fl is not None, "field_id": fl["field_id"] if fl else None,
                    "crop": (fl["crop"] or None) if fl else None,
                    "boundary": {"area_m2": round(a), "area": r2(a / M2[unit]), "area_ha": r4(a / 1e4), "unit": unit,
                                 "source": "5am.earth" if reg else f["properties"].get("source", "uploaded")},
                    "registry_link": reg, "geometry": g})
    return out


def ctx_of(dataset: dict) -> dict:
    s = dataset["settings"]
    return {"area_unit": s["area_unit"], "area_tolerance": s["area_tolerance"]}


def windows_of(dataset: dict, today: str) -> dict:
    s = dataset["settings"]
    w = season_window(today, s.get("crop_season_start") or SEASON_START.get(s["country"], "03-01"))
    return {"season": w, "previous": previous_window(w)}


def analyze(dataset: dict, today: str, fetcher: Optional[Fetcher], registry: Optional[Callable[[str], dict]] = None) -> Optional[dict]:
    """The crop_monitoring section, or None when the dataset has no boundaries."""
    ps = parcels_of(dataset)
    if not ps:
        return None
    windows, ctx = windows_of(dataset, today), ctx_of(dataset)
    section: dict[str, Any] = {"status": "ok", "as_of": today, "season": windows["season"], "previous": windows["previous"], "method": method_text(),
                               "sources": [], "unavailable": [], "parcels": [], "radiation": None}
    reg = registry_part(ps, registry, section)
    if fetcher is None:
        section["status"] = "unavailable"
        section["unavailable"].append("Satellite monitoring is switched off on this server (AGROLAND_CROPWATCH=off).")
        section["parcels"] = [public_parcel(p, None, reg.get(p["parcel_id"])) for p in ps]
        section["summary"] = summary(section)
        return section
    allg = shapely.union_all([p["geometry"] for p in ps])
    c = allg.centroid
    obs: dict[str, dict[str, dict[str, dict]]] = {p["parcel_id"]: {"season": {}, "previous": {}} for p in ps}
    scenes = {k: {"considered": 0, "downloaded": 0} for k in windows}
    try:
        b = shapely.bounds(allg)
        bbox = [r4(b[0] - 0.001), r4(b[1] - 0.001), r4(b[2] + 0.001), r4(b[3] + 0.001)]
        jobs = []
        for k, w in windows.items():
            items = fetcher.search(bbox, w)
            scenes[k]["considered"] = len(items)
            for epsg in sorted({it["epsg"] for it in items}):
                geoms = {p["parcel_id"]: p["geometry"] for p in ps}
                for ids in groups(geoms, epsg):
                    gutm = [project(geoms[i], epsg) for i in ids]
                    win = window_for(gutm)
                    masks = {i: pixel_mask(g, win) for i, g in zip(ids, gutm)}
                    hull = shapely.union_all([geoms[i] for i in ids]).envelope
                    per_date: dict[str, list[dict]] = {}
                    for it in items:
                        if it["epsg"] == epsg and it["footprint"] and shape(it["footprint"]).intersects(hull):
                            per_date.setdefault(it["date"], []).append(it)
                    for day, its in per_date.items():
                        full = [it for it in its if shape(it["footprint"]).contains(hull)]
                        for it in (sorted(full, key=lambda x: x["cloud"])[:1] or its):
                            jobs.append((k, it, epsg, win, masks))
        with ThreadPoolExecutor(max_workers=fetcher.workers) as ex:
            arrays = list(ex.map(lambda j: fetcher.scene(j[1]["id"], j[2], j[3]), jobs))
        for (k, it, epsg, win, masks), arr in zip(jobs, arrays):
            scenes[k]["downloaded"] += 1
            for pid, (m, rule) in masks.items():
                o = observe(arr, m, boa_offset(it["baseline"]))
                o["pixel_rule"] = rule
                prev = obs[pid][k].get(it["date"])
                if o["use"] and (prev is None or not prev["use"] or o["clear_px"] > prev["clear_px"]):
                    obs[pid][k][it["date"]] = {**o, "item": it["id"]}
                elif prev is None:
                    obs[pid][k][it["date"]] = o
        rad = fetcher.radiation(c.y, c.x, windows["previous"]["start"], windows["previous"]["end"])
        rad.update(fetcher.radiation(c.y, c.x, windows["season"]["start"], windows["season"]["end"]))
    except (SourceError, ValueError, KeyError, OSError) as exc:  # unreachable source or a malformed answer: report it, do not fail the Lease Check
        section["status"] = "unavailable"
        section["unavailable"].append(f"Satellite or weather source did not answer usably ({type(exc).__name__}: {str(exc)[:160]}). Nothing is estimated without data.")
        section["parcels"] = [public_parcel(p, None, reg.get(p["parcel_id"])) for p in ps]
        section["summary"] = summary(section)
        return section
    section["radiation"] = {"source": "Open-Meteo archive (ERA5), daily global shortwave radiation, MJ/m2", "lat": r4(c.y), "lon": r4(c.x), "daily": rad}
    section["sources"] = [f"Sentinel-2 L2A ({COLLECTION}) via Microsoft Planetary Computer: {scenes['season']['considered']} scenes this season, "
                          f"{scenes['previous']['considered']} in the same weeks last year (tile cloud cover below {MAX_SCENE_CLOUD} %)",
                          "Open-Meteo ERA5 archive: daily global radiation at the farm centre",
                          "Copernicus Sentinel data (ESA), modified: contains processed Copernicus data"]
    section["scenes"] = scenes
    for p in ps:
        stored = {}
        for k in windows:
            stored[k] = [{"date": d, "item": o["item"], "ndvi": o["ndvi"], "ndvi_p10": o["ndvi_p10"], "ndvi_p90": o["ndvi_p90"], "clear_px": o["clear_px"], "px": o["px"]}
                         for d, o in sorted(obs[p["parcel_id"]][k].items()) if o["use"]]
        counts = {k: {"clear": len(stored[k]), "cloudy": sum(1 for o in obs[p["parcel_id"]][k].values() if not o["use"] and o["why"] == "cloudy"),
                      "no_data": sum(1 for o in obs[p["parcel_id"]][k].values() if not o["use"] and o["why"] == "no_data")} for k in windows}
        rules = {o.get("pixel_rule") for k in windows for o in obs[p["parcel_id"]][k].values() if o.get("pixel_rule")}
        section["parcels"].append(public_parcel(p, {"observations": stored, "dates": counts, "pixel_rule": sorted(rules)[0] if rules else None},
                                                reg.get(p["parcel_id"]), rad, windows, today, ctx))
    section["summary"] = summary(section)
    return section


def public_parcel(p: dict, sat: Optional[dict], reg: Optional[dict], rad: Optional[dict] = None, windows: Optional[dict] = None,
                  today: Optional[str] = None, ctx: Optional[dict] = None) -> dict:
    out = {k: p[k] for k in ("parcel_id", "contract_id", "owner", "area_contract", "farmed", "field_id", "crop", "boundary")}
    out["crop_group"] = crop_group(p["crop"])
    out["registry"] = reg
    if sat is None:
        out.update({"observations": None, "status": {"code": "unavailable", "text": "Satellite data unavailable"}, "flags": []})
        return out
    out["observations"] = sat["observations"]
    out["dates"] = sat["dates"]
    out["pixel_rule"] = sat["pixel_rule"]
    out.update(derive(out, rad, windows, today, ctx))
    return out


def summary(section: dict) -> dict:
    ps = section["parcels"]
    seen = [p for p in ps if p.get("observations") and p["observations"]["season"]]
    tot = [p["biomass"]["field_t"] for p in seen if p.get("biomass", {}).get("field_t") is not None]
    return {"parcels_with_boundary": len(ps), "parcels_observed": len(seen), "flags": sum(len(p["flags"]) for p in ps),
            "season_biomass_t_total": r2(sum(tot)) if tot else None,
            "status_counts": {c: sum(1 for p in ps if p["status"]["code"] == c) for c in sorted({p["status"]["code"] for p in ps})},
            "registry_verified": sum(1 for p in ps if (p.get("registry") or {}).get("verified")),
            "registry_linked": sum(1 for p in ps if p.get("registry"))}


def registry_part(ps: list[dict], registry: Optional[Callable[[str], dict]], section: dict) -> dict[str, dict]:
    """Check each parcel's 5am.earth registration on Cardano mainnet (read-only) and that its IPFS boundary is the one used here."""
    linked = [p for p in ps if p["registry_link"]]
    if not linked:
        return {}
    if registry is None:
        section["unavailable"].append("5am.earth registry lookup is not configured on this server.")
        return {p["parcel_id"]: {"tx_hash": p["registry_link"]["tx_hash"], "status": "not_checked"} for p in linked}

    def one(p):
        link = p["registry_link"]
        try:
            v = registry(link["tx_hash"])
        except Exception as exc:  # noqa: BLE001 - reported as a limitation, never as a pass
            return p["parcel_id"], {"tx_hash": link["tx_hash"], "status": "unavailable", "reason": f"{type(exc).__name__}: {str(exc)[:120]}"}
        return p["parcel_id"], registry_entry(p, link, v)

    with ThreadPoolExecutor(max_workers=4) as ex:
        out = dict(ex.map(one, linked))
    if any(v.get("status") == "unavailable" for v in out.values()):
        section["unavailable"].append("Some 5am.earth registry lookups did not answer (Koios or IPFS); those parcels show 'unavailable'.")
    return out


def registry_entry(p: dict, link: dict, v: dict) -> dict:
    rec = v.get("record") or {}
    doc = v.get("document") or {}
    farm = next((f for f in doc.get("farms", []) if str(f.get("farm_id")) == str(rec.get("ref_2"))), None)
    same = bool(farm) and shape(farm["geometry"]).equals_exact(p["geometry"], 1e-9)
    return {"registry": "5am.earth Project Swaminathan (Cardano mainnet)", "status": "checked", "tx_hash": v.get("tx_hash", link["tx_hash"]),
            "verified": bool(v.get("verified")), "checks": v.get("checks", {}), "block_time": v.get("block_time"),
            "farm_id": rec.get("ref_2"), "registration_ref": rec.get("ref_1"), "agent_code": rec.get("agent_code"),
            "registered_area_m2": rec.get("value_1"), "value_2": rec.get("value_2"),
            "value_2_note": "Integer between -20 and 100 in every registration seen; its meaning is not documented publicly, so it is shown, not interpreted.",
            "document_cid": rec.get("document_cid"), "document": {"status": doc.get("status", "not fetched"), "cid_verified": doc.get("cid_verified"), "gateway": doc.get("gateway")},
            "boundary_matches_registry": same,
            "explorer": f"https://cardanoscan.io/transaction/{v.get('tx_hash', link['tx_hash'])}",
            "limits": v.get("limits", [])}


def method_text() -> dict:
    return {"version": METHOD_VERSION,
            "ndvi": "NDVI = (B08 - B04) / (B08 + B04) from Sentinel-2 L2A surface reflectance (processing-baseline offset removed), mean of the clear 10 m pixels "
                    "whose centre lies inside the boundary; a scene is used for a parcel only if at most 10 % of its pixels are cloud or shadow and at least 60 % are clear (SCL).",
            "status": "Canopy status from the latest clear NDVI: >= 0.55 dense, >= 0.35 green; lower values are 'after peak' when the season peaked above 0.45, "
                      "'no crop canopy' when the season never rose above 0.40.",
            "biomass": "Monteith light-use efficiency: sum over days of LUE x fAPAR x 0.48 x global radiation; fAPAR = 0.95 x clip((NDVI - soil)/(0.90 - soil), 0, 1), "
                       "soil = the field's lowest clear NDVI in the window (0.12-0.30) + 0.10; NDVI interpolated linearly between clear views, never extrapolated. "
                       "LUE (g/MJ APAR): C4 crops 3.0, C3 cereals 2.6, other crops 2.2, crop not stated 2.4 - generic literature values for crops without water "
                       "or nutrient stress, shown with a +-30 % range.",
            "meaning": "Season biomass is above-ground dry matter PRODUCED in the window (an estimate), not standing biomass and not yield. Rain-fed fields under "
                       "drought or nutrient stress produce less than the LUE assumes, so read it as an upper-range figure; the comparison with last year and "
                       "between your fields is more robust than the absolute number. Field visits or crop cuts are the ground truth."}


# ----------------------------------------------------------------------------------------------------------------- verification
def verify(section: Optional[dict], dataset: dict, today: str) -> dict:
    """Recompute every derived number from the observations and radiation stored in the section."""
    if section is None:
        return {"status": "pass", "checked_parcels": 0, "reasons": []}
    made_with = (section.get("method") or {}).get("version")
    if made_with != METHOD_VERSION:  # an older report is not wrong, it just cannot be recomputed by this server's arithmetic
        return {"status": "not_recomputed", "checked_parcels": 0, "reasons": [f"report made with {made_with}; this server computes {METHOD_VERSION}"]}
    reasons: list[str] = []
    windows, ctx = windows_of(dataset, today), ctx_of(dataset)
    if section.get("season") != windows["season"] or section.get("previous") != windows["previous"]:
        reasons.append("season windows do not match the as-of date")
    truth = {p["parcel_id"]: p for p in parcels_of(dataset)}
    rad = (section.get("radiation") or {}).get("daily") or {}
    checked = 0
    for p in section.get("parcels", []):
        pid = p.get("parcel_id")
        t = truth.pop(pid, None)
        if t is None:
            reasons.append(f"{pid}: parcel has no boundary in the dataset")
            continue
        for k in ("contract_id", "farmed", "crop", "area_contract", "boundary"):
            if p.get(k) != t[k]:
                reasons.append(f"{pid}: {k} is {json.dumps(p.get(k))}, dataset says {json.dumps(t[k])}")
        if p.get("observations") is None:
            continue
        for k in ("season", "previous"):
            o = p["observations"][k]
            if [x["date"] for x in o] != sorted({x["date"] for x in o}):
                reasons.append(f"{pid}: {k} observations are not one per date in order")
            if any(not (-1.0 <= x["ndvi"] <= 1.0) for x in o) or any(not (windows[k]["start"] <= x["date"] <= windows[k]["end"]) for x in o):
                reasons.append(f"{pid}: {k} observation out of range")
        fresh = derive({**p, **{k: t[k] for k in ("parcel_id", "contract_id", "area_contract", "farmed", "crop", "boundary")}}, rad, windows, today, ctx)
        for k in ("metrics", "biomass", "status", "flags"):
            if json.dumps(p.get(k), sort_keys=True) != json.dumps(fresh[k], sort_keys=True):
                reasons.append(f"{pid}: {k} does not match the recomputation")
        checked += 1
    reasons += [f"{pid}: parcel with a boundary is missing from the section" for pid in truth]
    if json.dumps(section.get("summary"), sort_keys=True) != json.dumps(summary(section), sort_keys=True):
        reasons.append("summary does not match the parcels")
    return {"status": "fail" if reasons else "pass", "checked_parcels": checked, "reasons": reasons}


# ----------------------------------------------------------------------------------------------------------------- boundaries input
def validate_boundaries(fc: Any, dataset: dict, in_country: Callable[[float, float], bool]) -> dict:
    """Uploaded or demo boundaries: a FeatureCollection of Polygons with properties.parcel_id matching a lease or record row."""
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection" or not isinstance(fc.get("features"), list):
        raise ValueError("boundaries: must be a GeoJSON FeatureCollection")
    if len(fc["features"]) > 500:
        raise ValueError("boundaries: at most 500 features")
    known = {c["parcel_id"] for c in dataset["contracts"]} | {c["parcel_id"] for c in dataset["cadastre"]}
    out, seen = [], set()
    for i, f in enumerate(fc["features"], 1):
        props = (f or {}).get("properties") or {}
        pid = str(props.get("parcel_id", "")).strip()
        geom = (f or {}).get("geometry") or {}
        if pid not in known:
            raise ValueError(f"boundaries:{i}: parcel_id {pid!r} is not in the leases or the official record")
        if pid in seen:
            raise ValueError(f"boundaries:{i}: parcel_id {pid!r} appears twice")
        seen.add(pid)
        if geom.get("type") != "Polygon" or not geom.get("coordinates"):
            raise ValueError(f"boundaries:{i}: geometry must be a Polygon")
        ring = geom["coordinates"][0]
        if not 4 <= len(ring) <= 2000 or not all(isinstance(x, (list, tuple)) and len(x) >= 2 and in_country(float(x[1]), float(x[0])) for x in ring):
            raise ValueError(f"boundaries:{i}: the outline needs 3-2000 corners inside the farm's country")
        g = shape(geom)
        if not g.is_valid or g.is_empty or area_m2(g) > 5e7:
            raise ValueError(f"boundaries:{i}: invalid outline (self-intersecting, empty or larger than 5000 ha)")
        p = {"parcel_id": pid, "source": "uploaded"}
        reg = props.get("registry")
        if isinstance(reg, dict) and isinstance(reg.get("tx_hash"), str) and len(reg["tx_hash"]) == 64:
            p["registry"] = {"tx_hash": reg["tx_hash"].lower()}
        elif props.get("source") and str(props["source"])[:80]:
            p["source"] = str(props["source"])[:80]
        out.append({"type": "Feature", "properties": p, "geometry": mapping(g)})
    return {"type": "FeatureCollection", "features": out}


def markdown(section: Optional[dict], unit: str) -> list[str]:
    if not section:
        return []
    w = section["season"]
    lines = ["", f"## Crop and biomass (Sentinel-2), season {w['start']} to {w['end']}"]
    if section["status"] != "ok":
        return lines + [f"- {x}" for x in section["unavailable"]]
    lines += ["| Parcel | Crop (your list) | Canopy now | Peak NDVI | Season biomass (estimate) | vs. last year | 5am.earth on-chain |", "|---|---|---|---|---|---|---|"]
    for p in section["parcels"]:
        m, b, r = p["metrics"]["season"], p["biomass"]["season"], p.get("registry") or {}
        bio = f"{b['t_per_ha']:.1f} t/ha ({b['low']:.1f}-{b['high']:.1f})" if b.get("t_per_ha") is not None else "-"
        ch = f"{p['biomass']['change_pct']:+d} %" if p["biomass"].get("change_pct") is not None else "-"
        reg = ("verified" if r.get("verified") else r.get("status", "not verified")) if r else "-"
        peak = f"{m['peak_ndvi']:.2f}" if m.get("peak_ndvi") is not None else "-"
        lines.append(f"| {p['parcel_id']} | {p['crop'] or ('not farmed' if not p['farmed'] else '-')} | {p['status']['text']} | {peak} | {bio} | {ch} | {reg} |")
    flags = [f for p in section["parcels"] for f in p["flags"]]
    if flags:
        lines += ["", "Worth a look (satellite and registry observations; not findings about money):"] + [f"- {f['text']}" for f in flags]
    regs = [p for p in section["parcels"] if (p.get("registry") or {}).get("status") == "checked"]
    if regs:
        lines += ["", "5am.earth registrations (Cardano mainnet, read-only):"]
        for p in regs:
            r = p["registry"]
            lines.append(f"- {p['parcel_id']}: tx {r['tx_hash']} - {'verified' if r['verified'] else 'NOT verified'}; farm id {r['farm_id']}, "
                         f"registered area {r['registered_area_m2']} m2, boundary {'matches' if r['boundary_matches_registry'] else 'does NOT match'} the IPFS document "
                         f"{r['document_cid']} (content hash {'checked' if r['document'].get('cid_verified') else 'not checked'})")
    lines += ["", f"_Method: {section['method']['biomass']} {section['method']['meaning']}_"]
    if section["unavailable"]:
        lines += [f"- {x}" for x in section["unavailable"]]
    return lines
