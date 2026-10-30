"""Generates data/in/parcels.geojson: ILLUSTRATIVE parcels for the India demo.

The boundaries are rectangles placed at real coordinates in wind/solar regions of Gujarat and Andhra Pradesh. They are NOT survey
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
out = Path(__file__).resolve().parents[1] / "data" / "in" / "parcels.geojson"
out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, indent=1))
print("wrote", out, len(feats))
