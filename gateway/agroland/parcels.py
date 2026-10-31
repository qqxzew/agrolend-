"""Parcels a user works with. Geometry comes from the open ALKIS fragment (DE), the illustrative India demo set, or is drawn by the user.
Saving a parcel never asserts ownership: every record carries `ownership: not verified`."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from shapely.geometry import shape

from . import alkis
from .db import Database, jdump, new_id, now
from .geoclient import in_country

IN_PARCELS = Path(__file__).resolve().parents[2] / "data" / "in" / "parcels.geojson"


@lru_cache(maxsize=1)
def in_demo() -> dict:
    return {f["properties"]["id"]: f for f in json.loads(IN_PARCELS.read_text("utf-8"))["features"]}


def largest_polygon(g: dict) -> dict:
    if g["type"] == "Polygon":
        return g
    if g["type"] == "MultiPolygon":  # the auditor takes one polygon: a split parcel is audited by its largest part (stated in the report)
        return {"type": "Polygon", "coordinates": max(g["coordinates"], key=lambda p: shape({"type": "Polygon", "coordinates": p}).area)}
    raise HTTPException(422, "Parcel geometry must be a Polygon")


def area_ha(g: dict, country: str) -> float:
    s = shape(g)
    lat = s.centroid.y
    import math
    return round(s.area * (111_320.0 * math.cos(math.radians(lat))) * 110_900.0 / 10_000, 2)


def public(row) -> dict:
    d = dict(row)
    d["geometry"] = json.loads(d["geometry"])
    d["ownership"] = "not verified"
    d["demo"] = bool(d["demo"])
    return d


MAX_PER_USER = 200


def add(db: Database, user: dict, body: dict) -> dict:
    country, source = user["country"], body.get("source")
    with db.tx() as c:
        if c.execute("SELECT COUNT(*) FROM parcels WHERE user_id=?", (user["id"],)).fetchone()[0] >= MAX_PER_USER:
            raise HTTPException(409, f"A workspace can hold at most {MAX_PER_USER} parcels; remove some first")
    if source == "alkis-demo":
        if country != "DE":
            raise HTTPException(422, "ALKIS fragment parcels are German")
        ref = body.get("ref", "")
        f = alkis.BY_ID.get(ref)
        if not f:
            raise HTTPException(404, "That parcel is not in the loaded ALKIS fragment (Magdeburg, Sachsen-Anhalt)")
        label = f"Flurstück {f['properties']['parcel_number']} (Flur {f['properties']['flur']}), {f['properties']['address']}"
        geom, area, demo = f["geometry"], f["properties"]["area"], 0
    elif source == "in-demo":
        if country != "IN":
            raise HTTPException(422, "Demo parcels of this kind are Indian")
        f = in_demo().get(body.get("ref", ""))
        if not f:
            raise HTTPException(404, "Unknown demo parcel")
        p = f["properties"]
        label, geom, area, demo, ref = f"{p['label']} - {p['survey_number']}, {p['village']}, {p['state']}", f["geometry"], p["area_ha"], 1, p["id"]
    elif source == "drawn":
        g = body.get("geometry")
        if not isinstance(g, dict) or g.get("type") not in ("Polygon",):
            raise HTTPException(422, "Draw a polygon with at least three corners")
        ring = g["coordinates"][0]
        if len(ring) < 4 or len(ring) > 500:
            raise HTTPException(422, "A polygon needs 3 to 500 corners")
        if not all(in_country(country, y, x) for x, y in ring):
            raise HTTPException(422, f"All corners must be inside {'Germany' if country == 'DE' else 'India'}")
        sh = shape(g)
        if not sh.is_valid or sh.area == 0:
            raise HTTPException(422, "The outline crosses itself or is empty")
        label = (body.get("label") or "Drawn site").strip()[:120]
        geom, area, demo, ref = g, area_ha(g, country), 0, (body.get("ref") or "").strip()[:60]
    else:
        raise HTTPException(422, "source must be alkis-demo, in-demo or drawn")
    with db.tx() as c:
        dup = c.execute("SELECT id FROM parcels WHERE user_id=? AND source=? AND ref=?", (user["id"], source, ref)).fetchone() if ref else None
        if dup:
            return public(c.execute("SELECT * FROM parcels WHERE id=?", (dup["id"],)).fetchone())
        pid = new_id()
        c.execute("INSERT INTO parcels VALUES(?,?,?,?,?,?,?,?,?,?)", (pid, user["id"], country, label, jdump(geom), ref, area, source, demo, now()))
        return public(c.execute("SELECT * FROM parcels WHERE id=?", (pid,)).fetchone())


def get(db: Database, user_id: str, pid: str) -> dict:
    with db.tx() as c:
        r = c.execute("SELECT * FROM parcels WHERE id=? AND user_id=?", (pid, user_id)).fetchone()
    if not r:
        raise HTTPException(404, "Parcel not found")
    return public(r)


def list_for(db: Database, user_id: str) -> list[dict]:
    with db.tx() as c:
        return [public(r) for r in c.execute("SELECT * FROM parcels WHERE user_id=? ORDER BY created_at DESC", (user_id,))]


def remove(db: Database, user_id: str, pid: str) -> None:
    with db.tx() as c:
        if c.execute("SELECT 1 FROM listings WHERE parcel_id=? AND user_id=?", (pid, user_id)).fetchone():
            raise HTTPException(409, "Withdraw the listing before removing this parcel")
        if c.execute("SELECT 1 FROM land_sites WHERE parcel_id=? AND user_id=?", (pid, user_id)).fetchone():
            raise HTTPException(409, "This parcel is kept for the land database and cluster history. Withdraw its database entry to stop matching.")
        c.execute("DELETE FROM parcels WHERE id=? AND user_id=?", (pid, user_id))
