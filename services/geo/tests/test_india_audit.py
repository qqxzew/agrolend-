"""Offline test of India Agent 1 (land audit): geometry, scoring/verdict rules and the MIP-003 flow with a stubbed GIS engine.

No network: the public data sources (Overpass, Nominatim, PVGIS, Open-Meteo) are covered by ../test_worker_india.py.

    python tests/test_india_audit.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import httpx
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from india.audit.config import AuditSettings  # noqa: E402
from india.audit.gis_engine import GisResult, Zone, build_site, classify_protected  # noqa: E402
from india.audit.main import create_app  # noqa: E402
from india.audit.models import LandCheckInput  # noqa: E402
from india.audit.scoring import build_report, connection_route, grid_score  # noqa: E402
from india.common.geo import Projector, polygon_from_geojson, utm_epsg  # noqa: E402

S = AuditSettings(_env_file=None)


def site_of(lat, lon, r=300, **kw):
    inp = LandCheckInput(lat=lat, lon=lon, radius_m=r, **kw)
    return inp, build_site(inp, S)


def gis(**over):
    """A healthy Gujarat solar+wind site; override single parts to probe the rules."""
    base = dict(
        admin={"state": "Gujarat", "state_code": "IN-GJ", "district": "Kachchh", "sub_district": "Bhuj", "village": "Testvillage"},
        infra={"substation_m": 1500.0, "substation_name": "Test 220 kV", "substation_operator": "GETCO", "substation_kv": 220.0,
               "powerline_m": 300.0, "powerline_kv": 66.0, "road_access": True, "wind_turbines_3km": 3},
        habitation={"habitation_m": 900.0, "basis": "dwelling cluster", "buildings_seen": 40},
        environment={"zones": [], "cover_overlap_pct": 0.0},
        solar={"e_y": 1700.0, "database": "PVGIS-ERA5", "elevation": 40.0},
        wind={"v100": 6.6, "method": "ERA5 100 m, 2022-2024", "elevation": 40.0},
        slope={"slope_deg": 1.5, "elevation": 40.0},
    )
    base.update(over)
    return GisResult(**base)


def test_geo_and_input():
    assert utm_epsg(69.5, 23.3) == 32642 and utm_epsg(77.6, 14.68) == 32643 and utm_epsg(88.0, 27.0) == 32645
    p = Projector.at(69.5, 23.3)
    lon, lat = p.lonlat(*p.xy(69.5, 23.3))
    assert abs(lon - 69.5) < 1e-9 and abs(lat - 23.3) < 1e-9
    _, site = site_of(23.3, 69.5, 300)
    assert abs(site.area_ha - 28.27) < 0.3, site.area_ha  # local UTM keeps the area within ~0.5 %
    assert polygon_from_geojson({"type": "Polygon", "coordinates": [[[77.6, 14.68], [77.605, 14.68], [77.605, 14.684], [77.6, 14.684], [77.6, 14.68]]]})
    for bad in ({"lat": 52.0, "lon": 13.0}, {"lat": 23.3}, {}, {"lat": 23.3, "lon": 69.5, "ulpin": "short"}):
        try:
            LandCheckInput(**bad)
        except ValidationError:
            continue
        raise AssertionError(f"input must be rejected: {bad}")
    assert LandCheckInput(lat=23.3, lon=69.5, ulpin="gj123456789012").ulpin == "GJ123456789012"
    try:
        build_site(LandCheckInput(lat=23.3, lon=69.5, radius_m=5000), AuditSettings(_env_file=None, max_area_ha=100))
    except ValueError as e:
        assert "exceeds" in str(e)
    else:
        raise AssertionError("area limit not enforced")
    print("geo + input OK")


def test_protected_areas():
    assert classify_protected({"boundary": "national_park", "name": "Gir"}) == "NP"
    assert classify_protected({"boundary": "protected_area", "name": "Gir Wildlife Sanctuary"}) == "WLS"
    assert classify_protected({"boundary": "protected_area", "name": "Nagarjunasagar-Srisailam Tiger Reserve"}) == "TR"
    assert classify_protected({"boundary": "protected_area", "name": "Test Reserved Forest"}) == "RF"
    assert classify_protected({"highway": "residential"}) is None
    assert Zone("NP", "x").veto and not Zone("NP", "x", within_site=False).veto and not Zone("PF", "x").veto
    print("protected areas OK")


def test_scoring():
    assert grid_score(1500, 300) == 100 and grid_score(25_000, 12_000) == 0 and grid_score(None, None) == 0
    assert connection_route("IN-GJ", "GETCO", 220).startswith("state") and "GETCO" in connection_route("IN-GJ", "GETCO", 220)
    assert connection_route("IN-AP", "APTRANSCO", 132).startswith("state") and "APTRANSCO" in connection_route("IN-AP", None, None)
    assert connection_route("IN-GJ", "Power Grid Corporation of India", 400).startswith("central")
    assert connection_route("IN-GJ", None, 765).startswith("central")

    inp, site = site_of(23.3, 69.5, 300, survey_number="112/1", ulpin="GJ123456789012")
    r = build_report(inp, site, gis())
    assert r.overall_verdict == "GO" and r.score >= 65 and r.assessed_technology in ("solar", "wind"), r
    assert r.location_info.state_supported and r.location_info.land_record.reference_supplied
    assert not r.location_info.land_record.title_verified and "AnyROR" in r.location_info.land_record.record_portal
    assert r.grid_access.connection_route_hint.startswith("state") and r.grid_access.grid_score == 100
    assert any("title is NOT verified" in w for w in r.warnings)
    assert build_report(inp, site, gis()).model_dump() == r.model_dump(), "report must be deterministic"

    # no land-record reference -> never an unconditional GO
    inp2, _ = site_of(23.3, 69.5, 300)
    r2 = build_report(inp2, site, gis())
    assert r2.overall_verdict == "CONDITIONAL_GO" and any("no survey number" in w for w in r2.warnings), r2.warnings

    # unsupported state -> conditional, no state knowledge applied
    r3 = build_report(inp, site, gis(admin={"state": "Rajasthan", "state_code": "IN-RJ"}))
    assert r3.overall_verdict == "CONDITIONAL_GO" and not r3.location_info.state_supported

    # hard veto categories: NP/WLS/TR/RF inside the site -> NO_GO with the score capped
    r4 = build_report(inp, site, gis(environment={"zones": [Zone("WLS", "Test Sanctuary")], "cover_overlap_pct": 0.0}))
    assert r4.overall_verdict == "NO_GO" and r4.score <= 10 and r4.environmental_veto.has_veto, r4
    # soft zone: penalty and no unconditional GO, no veto
    r5 = build_report(inp, site, gis(environment={"zones": [Zone("PF", "Test Protected Forest")], "cover_overlap_pct": 0.0}))
    assert not r5.environmental_veto.has_veto and r5.overall_verdict == "CONDITIONAL_GO" and r5.score <= r.score - 15
    # protected area only nearby (possible eco-sensitive zone) -> condition, no veto
    r6 = build_report(inp, site, gis(environment={"zones": [Zone("NP", "Gir", within_site=False)], "cover_overlap_pct": 0.0}))
    assert not r6.environmental_veto.has_veto and r6.environmental_veto.protected_zones_within_buffer
    assert r6.overall_verdict == "CONDITIONAL_GO" and any("eco-sensitive" in w for w in r6.warnings)

    # wind rules: setback, speed floor
    winp, _ = site_of(23.3, 69.5, 300, project_type="wind", survey_number="1")
    near = build_report(winp, site, gis(habitation={"habitation_m": 120.0, "basis": "dwelling cluster", "buildings_seen": 30}))
    assert near.overall_verdict == "NO_GO" and any("habitation only 120 m" in w for w in near.warnings)
    calm = build_report(winp, site, gis(wind={"v100": 4.0, "method": "x", "elevation": 1.0}))
    assert calm.overall_verdict == "NO_GO" and any("m/s at 100 m" in w for w in calm.warnings)
    mid = build_report(winp, site, gis(wind={"v100": 5.0, "method": "x", "elevation": 1.0}))
    assert mid.overall_verdict != "GO" and any("on-site / NIWE" in w for w in mid.warnings)
    # solar: yield and terrain
    sinp, _ = site_of(23.3, 69.5, 300, project_type="solar", survey_number="1")
    steep = build_report(sinp, site, gis(slope={"slope_deg": 24.0, "elevation": 1.0}))
    assert steep.overall_verdict == "NO_GO" and any("too steep for PV" in w for w in steep.warnings)

    # honest degradation: failed sources are reported, never invented, and block a clean GO
    dead = GisResult(errors={k: "boom" for k in ("admin", "infra", "habitation", "environment", "solar", "wind", "slope")})
    rd = build_report(inp, site, dead)
    assert rd.overall_verdict != "GO" and rd.resource_potential.solar_kwh_per_kwp_year is None
    assert all(v.startswith("unavailable") for k, v in rd.data_quality.items() if k not in ("land_record",)), rd.data_quality
    assert rd.grid_access.nearest_substation_m is None and rd.location_info.state is None

    # Andhra Pradesh: the blockchain-pilot note names a pilot mandal when OSM names match
    ap = build_report(inp, site, gis(admin={"state": "Andhra Pradesh", "state_code": "IN-AP", "district": "Guntur",
                                            "sub_district": "Repalle", "village": "Testpalli"}))
    assert "pilot mandal Repalle" in ap.location_info.land_record.blockchain_pilot and "Mee Bhoomi" in ap.location_info.land_record.record_portal
    ap2 = build_report(inp, site, gis(admin={"state": "Andhra Pradesh", "state_code": "IN-AP", "sub_district": "Elsewhere"}))
    assert "does not match a pilot mandal" in ap2.location_info.land_record.blockchain_pilot
    print("scoring OK")


async def test_habitation_parsing():
    """query_habitation on canned Overpass answers: no place node, a place node, a building cluster."""
    import india.audit.gis_engine as ge

    _, site = site_of(23.3, 69.5, 300)
    answers = {}

    async def fake_fetch(client, query, endpoints):
        return answers["data"]

    orig, ge._overpass_fetch = ge._overpass_fetch, fake_fetch
    try:
        answers["data"] = {"elements": []}
        r = await ge.query_habitation(None, site, S)
        assert r["habitation_m"] is None and r["buildings_seen"] == 0, r  # regression: used to raise TypeError
        answers["data"] = {"elements": [{"type": "node", "lat": site.lat + 0.004, "lon": site.lon, "tags": {"place": "village", "name": "Testpur"}}]}
        r = await ge.query_habitation(None, site, S)
        assert r["habitation_m"] is not None and "Testpur" in r["basis"], r
        blds = [{"type": "way", "center": {"lat": site.lat + 0.005 + i * 0.0001, "lon": site.lon}, "tags": {"building": "yes"}} for i in range(20)]
        answers["data"] = {"elements": blds}
        r = await ge.query_habitation(None, site, S)
        assert r["buildings_seen"] == 20 and "dwelling cluster" in r["basis"], r
    finally:
        ge._overpass_fetch = orig
    print("habitation parsing OK")


class StubEngine:
    def __init__(self):
        self.calls = 0

    async def run(self, site):
        self.calls += 1
        return gis()


async def test_api():
    s = AuditSettings(_env_file=None, bypass_payment=True, internal_api_key="ikey", database_path=f"{tempfile.mkdtemp()}/jobs.sqlite3")
    app = create_app(s)
    async with app.router.lifespan_context(app):
        app.state.jobs.engine = StubEngine()
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        av = (await c.get("/availability")).json()
        assert av["status"] == "available" and "India" in av["message"]
        sch = (await c.get("/input_schema")).json()
        assert {f["id"] for f in sch["input_data"]} >= {"lat", "lon", "project_type", "survey_number", "ulpin"}

        r = await c.post("/start_job", json={"input_data": {"lat": 23.3, "lon": 69.5, "survey_number": "112/1"}})
        assert r.status_code == 200, r.text
        job = r.json()
        assert job["status"] == "completed" and job["report"]["overall_verdict"] == "GO" and len(job["result_hash"]) == 64, job
        assert json.loads(job["result"]) == job["report"]
        st = (await c.get("/status", params={"job_id": job["job_id"]})).json()
        assert st["status"] == "completed" and st["result_hash"] == job["result_hash"]
        assert (await c.get("/status", params={"job_id": "nope"})).status_code == 404

        # flat body works; invalid inputs fail fast with 422
        assert (await c.post("/start_job", json={"lat": 14.68, "lon": 77.6})).status_code == 200
        assert (await c.post("/start_job", json={"lat": 52.1, "lon": 13.1})).status_code == 422  # Germany
        assert (await c.post("/start_job", json={"lat": 23.3, "lon": 69.5, "ulpin": "x"})).status_code == 422

        # internal audit: keyed, unpaid, same report
        geo = {"lat": 23.3, "lon": 69.5, "survey_number": "112/1"}
        r = await c.post("/internal/audit", json=geo, headers={"X-API-Key": "ikey"})
        assert r.status_code == 200 and r.json()["report"] == job["report"], r.text
        assert (await c.post("/internal/audit", json=geo, headers={"X-API-Key": "bad"})).status_code == 401
        print("api OK")


test_geo_and_input()
test_protected_areas()
test_scoring()
asyncio.run(test_habitation_parsing())
asyncio.run(test_api())
print("audit OK")
