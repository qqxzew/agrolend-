"""Generates data/farm/de/boundaries.geojson: FICTIONAL field outlines for the German demo farm (Hans Farm).
Rectangles of the cadastre area, laid out in four village clusters in the Magdeburger Boerde. Not survey boundaries; the villages are invented."""
import csv, json, math
from pathlib import Path
root = Path(__file__).resolve().parents[1] / "data" / "farm" / "de"
rows = list(csv.DictReader((root / "cadastre.csv").read_text("utf-8").splitlines()))
centres = {"Altenbrueck": (52.050, 11.480), "Kleinrode": (52.025, 11.560), "Wendelsdorf": (52.078, 11.620), "Rosenfelde": (52.000, 11.640)}
feats, cursor = [], {k: [0.0, 0.0, 0.0] for k in centres}   # x offset, y offset, row height (m)
for r in rows:
    v = r["parcel_id"].split("-")[0]
    lat0, lon0 = centres[v]
    area_m2 = float(r["area_cadastre"]) * 10_000
    h = math.sqrt(area_m2 / 2); w = 2 * h
    c = cursor[v]
    if c[0] + w > 900:
        c[0], c[1], c[2] = 0.0, c[1] + c[2] + 25, 0.0
    x, y = c[0], c[1]
    c[0] += w + 25; c[2] = max(c[2], h)
    dlat = lambda m: m / 110_900.0
    dlon = lambda m: m / (111_320.0 * math.cos(math.radians(lat0)))
    ring = [[lon0 + dlon(x), lat0 + dlat(y)], [lon0 + dlon(x + w), lat0 + dlat(y)], [lon0 + dlon(x + w), lat0 + dlat(y + h)], [lon0 + dlon(x), lat0 + dlat(y + h)]]
    ring.append(ring[0])
    feats.append({"type": "Feature", "properties": {"parcel_id": r["parcel_id"]}, "geometry": {"type": "Polygon", "coordinates": [[[round(a, 6), round(b, 6)] for a, b in ring]]}})
(root / "boundaries.geojson").write_text(json.dumps({"type": "FeatureCollection", "note": "FICTIONAL outlines for the demo farm: rectangles of the cadastre area in invented villages. Not survey boundaries.", "features": feats}, indent=1))
print("wrote", len(feats), "outlines")
