"""Offline test of India Agent 2 (Matcher) with a stubbed validator (India Agent 1).

The validator is stubbed only to keep this deterministic and fast; geometry (local UTM), distances, bands,
anonymity and the SQLite store are the real code.

    python tests/test_india_matcher.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import httpx
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from india.matcher.config import MatcherSettings  # noqa: E402
from india.matcher.main import create_app  # noqa: E402

TO_UTM = Transformer.from_crs(4326, 32642, always_xy=True)  # Kutch, Gujarat: UTM zone 42N
TO_WGS = Transformer.from_crs(32642, 4326, always_xy=True)
x0, y0 = TO_UTM.transform(69.5, 23.3)
R = 300.0


def at(dx_m: float, dy_m: float = 0.0):
    lon, lat = TO_WGS.transform(x0 + dx_m, y0 + dy_m)
    return {"lat": round(lat, 6), "lon": round(lon, 6), "radius_m": R}


state = {"verdict": "CONDITIONAL_GO", "tech": "solar"}


def fake_validator(request: httpx.Request) -> httpx.Response:
    assert request.url.path in ("/start_job", "/internal/audit")
    if request.url.path == "/internal/audit":
        assert request.headers.get("X-API-Key") == "ikey", "internal audit needs the validator key"
    report = {
        "overall_verdict": state["verdict"], "score": 77 if state["verdict"] != "NO_GO" else 10,
        "assessed_technology": state["tech"], "warnings": ["title is NOT verified"] if state["verdict"] == "NO_GO" else [],
        "location_info": {"state": "Gujarat", "state_code": "IN-GJ", "district": "Kachchh", "village": "Testvillage",
                          "land_record": {"survey_number": "112/1", "ulpin": "GJ123456789012"}},
        "environmental_veto": {"has_veto": state["verdict"] == "NO_GO",
                               "intersecting_protected_zones": ["Wildlife Sanctuary: Test"] if state["verdict"] == "NO_GO" else []},
        "technology_assessment": {state["tech"]: {"blockers": ["x"] if state["verdict"] == "NO_GO" else []}},
    }
    return httpx.Response(200, json={"job_id": "j1", "status": "completed", "report": report})


async def main():
    s = MatcherSettings(_env_file=None, matcher_database_path=f"{tempfile.mkdtemp()}/m.sqlite3", max_parcels_per_developer=3,
                        matcher_api_key="")
    app = create_app(s)
    async with app.router.lifespan_context(app):
        app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(fake_validator))
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://m")

        async def reg(dev, tech, **geo):
            state["tech"] = tech
            return await c.post("/register_parcel", json={"developer_id": dev, **geo})

        # A (dev1, solar)
        r = await reg("dev1", "solar", **at(0)); a = r.json()
        assert r.status_code == 200 and a["status"] == "registered" and a["new_matches"] == 0, r.text

        # B (dev2, wind): 800 m gap to A -> match
        r = await reg("dev2", "wind", **at(2 * R + 800)); b = r.json()
        assert b["new_matches"] == 1, b
        t = b["teasers"][0]
        assert t["distance_band"] == "500-1000 m" and t["neighbour"]["technology"] == "solar", t
        assert t["neighbour"]["state"] == "Gujarat" and "complementary" in t["synergy"], t
        dev1 = (await c.get("/teasers", params={"developer_id": "dev1"})).json()
        assert dev1["count"] == 1 and dev1["teasers"][0]["neighbour"]["technology"] == "wind", dev1

        # anonymity: nothing identifying in either teaser (state is the only location hint)
        blob = json.dumps([t, dev1["teasers"]])
        for forbidden in ("Testvillage", "Kachchh", "dev1", "dev2", "112/1", "GJ1234", "69.5", "23.3",
                          str(a["parcel_id"]), str(b["parcel_id"])):
            assert forbidden not in blob.replace(t["your_parcel_id"], "").replace(dev1["teasers"][0]["your_parcel_id"], ""), forbidden
        again = (await c.get("/teasers", params={"developer_id": "dev1", "unread_only": True})).json()
        assert again["count"] == 0, "teaser should be marked read"

        # C (dev1) near A on the far side: same developer as A -> never matched with A; too far from B
        r = await reg("dev1", "solar", **at(-(2 * R + 700))); assert r.json()["new_matches"] == 0, r.text
        # D (dev3) far away
        r = await reg("dev3", "wind", **at(25_000)); assert r.json()["new_matches"] == 0, r.text
        # between 1 and 1.5 km is still a match in India (1.5 km radius), beyond is not
        r = await reg("dev7", "wind", **at(-(2 * R + 700) - 2 * R - 1300)); assert r.json()["new_matches"] == 1, r.text
        # duplicate by the same developer
        r = await reg("dev2", "wind", **at(2 * R + 800)); assert r.status_code == 409, r.text
        # NO_GO is rejected and not stored
        state["verdict"] = "NO_GO"
        r = await reg("dev4", "wind", **at(0, 8000)); assert r.json()["status"] == "rejected" and r.json()["reasons"], r.text
        assert (await c.get("/parcels", params={"developer_id": "dev4"})).json()["parcels"] == []
        state["verdict"] = "CONDITIONAL_GO"
        # quota (limit 3 for dev1: A, C + one more, then 429)
        assert (await reg("dev1", "solar", **at(0, 30_000))).status_code == 200
        assert (await reg("dev1", "solar", **at(0, 40_000))).status_code == 429
        # polygon input works (Andhra Pradesh, UTM zone 43N)
        poly = {"type": "Polygon", "coordinates": [[[77.6, 14.68], [77.605, 14.68], [77.605, 14.684], [77.6, 14.684], [77.6, 14.68]]]}
        r = await reg("dev5", "solar", polygon_geojson=poly); assert r.json()["status"] == "registered", r.text
        # outside India -> 422
        r = await reg("dev5", "solar", lat=52.5, lon=13.0, radius_m=300); assert r.status_code == 422, r.text
        # a 0.8 ha parcel is below the 1 ha minimum
        r = await reg("dev6", "solar", lat=23.5, lon=69.6, radius_m=50); assert r.json()["status"] == "rejected", r.text

        # withdraw closes the match
        assert (await c.delete(f"/parcels/{b['parcel_id']}", params={"developer_id": "dev1"})).status_code == 404
        assert (await c.delete(f"/parcels/{b['parcel_id']}", params={"developer_id": "dev2"})).status_code == 200
        left = (await c.get("/teasers", params={"developer_id": "dev1"})).json()  # only the dev7 match (to parcel C) remains
        assert left["count"] == 1 and left["teasers"][0]["match_id"] != t["match_id"], left
        print("matcher OK")

    # auth + internal match endpoint
    s2 = MatcherSettings(_env_file=None, matcher_database_path=f"{tempfile.mkdtemp()}/m2.sqlite3", matcher_api_key="secret")
    app2 = create_app(s2)
    async with app2.router.lifespan_context(app2):
        app2.state.client = httpx.AsyncClient(transport=httpx.MockTransport(fake_validator))
        c2 = httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://m")
        h = {"X-API-Key": "secret"}
        assert (await c2.get("/teasers", params={"developer_id": "x"})).status_code == 401
        assert (await c2.get("/teasers", params={"developer_id": "x"}, headers=h)).status_code == 200
        state.update(verdict="CONDITIONAL_GO", tech="solar")
        for dev, dx in (("devA", 0), ("devB", 1200)):
            r = await c2.post("/register_parcel", json={"developer_id": dev, **at(dx)}, headers=h)
            assert r.status_code == 200, r.text
        mid = (await c2.get("/teasers", params={"developer_id": "devA"}, headers=h)).json()["teasers"][0]["match_id"]
        rec = (await c2.get(f"/internal/matches/{mid}", headers=h)).json()
        assert {p["developer_id"] for p in rec["parcels"]} == {"devA", "devB"}
        p0 = rec["parcels"][0]
        assert p0["village"] == "Testvillage" and p0["survey_number"] == "112/1" and p0["ulpin"] == "GJ123456789012"
        assert p0["geometry"]["type"] == "Polygon" and p0["report"]["overall_verdict"] == "CONDITIONAL_GO"
        assert (await c2.get("/internal/matches/nope", headers=h)).status_code == 404
        print("auth + internal match OK")

    # paid Agent 1: the matcher must use the keyed /internal/audit, not the public /start_job
    s3 = MatcherSettings(_env_file=None, matcher_database_path=f"{tempfile.mkdtemp()}/m3.sqlite3", matcher_api_key="",
                         validator_api_key="ikey")
    app3 = create_app(s3)
    async with app3.router.lifespan_context(app3):
        seen: list[str] = []
        app3.state.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: (seen.append(req.url.path), fake_validator(req))[1]))
        c3 = httpx.AsyncClient(transport=httpx.ASGITransport(app=app3), base_url="http://m")
        state.update(verdict="CONDITIONAL_GO", tech="solar")
        r = await c3.post("/register_parcel", json={"developer_id": "dev9", **at(0)})
        assert r.status_code == 200 and r.json()["status"] == "registered", r.text
        assert seen == ["/internal/audit"], seen
        print("internal validator OK")


asyncio.run(main())
