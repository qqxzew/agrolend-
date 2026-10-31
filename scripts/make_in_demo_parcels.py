"""Generates data/in/parcels.geojson: ILLUSTRATIVE parcels for the India demo.

The first five boundaries are rectangles placed at real coordinates in wind/solar regions of Gujarat and Andhra Pradesh. They are NOT survey
boundaries and no registry was consulted; the survey numbers are invented. The file says so in every feature (`demo: true`).
"""
import json, math
from pathlib import Path

def rect(lat, lon, w_m, h_m):
    dlat = h_m / 110_900.0
    dlon = w_m / (111_320.0 * math.cos(math.radians(lat)))
    return [[[lon, lat], [lon + dlon, lat], [lon + dlon, lat + dlat], [lon, lat + dlat], [lon, lat]]]

P = [  # label, state, district, village, survey, lat, lon, width_m, height_m
    ("Kutch wind plot A", "Gujarat", "Kutch", "Samakhiali (demo)", "Survey 118/1", 23.3500, 70.5500, 400, 300),
    ("Kutch solar plot B", "Gujarat", "Kutch", "Samakhiali (demo)", "Survey 131", 23.3510, 70.5640, 360, 280),
    ("Kutch plot C", "Gujarat", "Kutch", "Samakhiali (demo)", "Survey 140/2", 23.3410, 70.5520, 300, 300),
    ("Anantapur wind plot D", "Andhra Pradesh", "Anantapur", "Peddavadugur (demo)", "Survey 56/3", 14.9700, 77.8200, 420, 320),
    ("Anantapur solar plot E", "Andhra Pradesh", "Anantapur", "Peddavadugur (demo)", "Survey 61", 14.9715, 77.8330, 380, 300),
]
feats = []
for i, (label, st, di, vi, sv, lat, lon, w, h) in enumerate(P):
    geom = {"type": "Polygon", "coordinates": rect(lat, lon, w, h)}
    feats.append({"type": "Feature", "geometry": geom, "properties": {
        "id": f"IN-DEMO-{i + 1}", "label": label, "state": st, "district": di, "village": vi, "survey_number": sv,
        "area_ha": round(w * h / 10_000, 2), "demo": True,
        "note": "Illustrative rectangle at real coordinates. Not a survey boundary. Survey number invented. Ownership not verified."}})

# ---- more fields so the map is a real working map: an illustrative mosaic around each demo region (seeded, reproducible)
import random
from shapely.geometry import shape

def field(lat0, lon0, tilt, cx, cy, w, h, rnd):
    """A slightly irregular quadrilateral, cx/cy/w/h in metres in a frame rotated by `tilt` degrees around (lat0, lon0)."""
    jit = lambda: rnd.uniform(-14, 14)
    pts = [(cx - w / 2 + jit(), cy - h / 2 + jit()), (cx + w / 2 + jit(), cy - h / 2 + jit()), (cx + w / 2 + jit(), cy + h / 2 + jit()), (cx - w / 2 + jit(), cy + h / 2 + jit())]
    t = math.radians(tilt)
    ring = []
    for x, y in pts + [pts[0]]:
        X, Y = x * math.cos(t) - y * math.sin(t), x * math.sin(t) + y * math.cos(t)
        ring.append([round(lon0 + X / (111_320.0 * math.cos(math.radians(lat0))), 6), round(lat0 + Y / 110_900.0, 6)])
    return ring

def area_ha(ring, lat0):
    a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        a += x1 * y2 - x2 * y1
    return abs(a) / 2 * (111_320.0 * math.cos(math.radians(lat0))) * 110_900.0 / 10_000

REGIONS = [  # state, district, village, centre lat, lon, tilt, seed, first survey no.
    ("Gujarat", "Kutch", "Samakhiali (demo)", 23.3480, 70.5600, 12, 11, 200),
    ("Andhra Pradesh", "Anantapur", "Peddavadugur (demo)", 14.9710, 77.8270, -18, 23, 300),
]
n = len(feats)
for st, di, vi, lat0, lon0, tilt, seed, sv0 in REGIONS:
    rnd = random.Random(seed)
    k = 0
    for gx in range(-4, 4):          # 8 columns x 6 rows of ~400 x 300 m cells, ~15 % left empty (roads, scrub, water)
        for gy in range(-3, 3):
            if rnd.random() < 0.15 or (abs(gx) <= 1 and abs(gy) <= 1 and (gx, gy) in ((0, 0), (1, 0), (0, 1))):
                continue
            w, h = rnd.choice((300, 340, 380, 420)), rnd.choice((230, 270, 310))
            ring = field(lat0, lon0, tilt, gx * 440 + 220, gy * 340 + 170, w, h, rnd)
            if any(shape(f["geometry"]).buffer(0.00005).intersects(shape({"type": "Polygon", "coordinates": [ring]})) for f in feats):
                continue  # never overlap an existing field
            k += 1; n += 1
            feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {
                "id": f"IN-DEMO-{n}", "label": f"{di} field {k}", "state": st, "district": di, "village": vi, "survey_number": f"Survey {sv0 + k}",
                "area_ha": round(area_ha(ring, lat0), 2), "demo": True,
                "note": "Illustrative field at real coordinates. Not a survey boundary. Survey number invented. Ownership not verified."}})

# ---- real: the six field outlines of the Nandur demo farm, registered on Cardano mainnet at 5am.earth
for f in json.loads((Path(__file__).resolve().parents[1] / "data" / "farm" / "in-mh" / "boundaries.geojson").read_text("utf-8"))["features"]:
    pid = f["properties"]["parcel_id"]
    ring = f["geometry"]["coordinates"][0]
    n += 1
    feats.append({"type": "Feature", "geometry": f["geometry"], "properties": {
        "id": f"IN-5AM-{pid}", "label": f"Registered field {pid}", "state": "Maharashtra", "district": "Beed", "village": "Nandur (demo farm)", "survey_number": pid.replace("Nandur-", "Gat "),
        "area_ha": round(area_ha(ring, ring[0][1]), 2), "demo": True, "registered": True, "registry_tx": f["properties"].get("registry", {}).get("tx_hash"),
        "note": "Field outline registered at 5am.earth (Project Swaminathan) on Cardano mainnet. Not a survey boundary; ownership not verified."}})
out = Path(__file__).resolve().parents[1] / "data" / "in" / "parcels.geojson"
out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, indent=1))
print("wrote", out, len(feats))
