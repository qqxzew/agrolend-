"""Crop-and-biomass section of the Lease Check (cropwatch.py) and the Maharashtra demo farm with 5am.earth boundaries.

Offline. One fixture is a real section recorded on 2026-10-31 for the six registered fields of the demo farm (Nandur, Beed district):
Sentinel-2 observations, Open-Meteo radiation and the 5am.earth registry checks exactly as the live sources answered. The other tests
replace the sources with an httpx MockTransport whose arrays are synthetic (they test the arithmetic, not the world).
"""
import io
import json
import re
from pathlib import Path

import httpx
import numpy as np
import pytest

from agroland import cropwatch as cw, farm

FIX = Path(__file__).parent / "data" / "crop_section_in-mh_2026-10-31.json"
TODAY = "2026-10-31"


def section():
    return json.loads(FIX.read_text("utf-8"))


def test_demo_farm_uses_real_registry_boundaries():
    ds = farm.load_demo("IN", "in-mh")
    feats = ds["boundaries"]["features"]
    assert len(feats) == 6 and all(len(f["properties"]["registry"]["tx_hash"]) == 64 for f in feats)
    assert {f["properties"]["parcel_id"] for f in feats} == {c["parcel_id"] for c in ds["contracts"]}
    assert [d["id"] for d in farm.demo_list("IN")] == ["in", "in-mh"] and farm.demo_list("DE")[0]["boundaries"] == 22  # fictional outlines (scripts/make_de_farm_boundaries.py), no registry links
    with pytest.raises(farm.DataError):
        farm.load_demo("IN", "../de")
    # the lease check itself is unchanged by boundaries
    r = farm.full_report(ds, TODAY)
    assert r["verification"]["status"] == "pass"
    assert sorted((f["type"], f["contract_id"]) for f in r["findings"]) == sorted([
        ("paid_not_farmed", "NK-05"), ("area_mismatch", "NK-02"), ("above_market_rent", "NK-06"), ("expiring_soon", "NK-03")])


def test_recorded_section_recomputes_and_tells_the_story():
    sec, ds = section(), farm.load_demo("IN", "in-mh")
    v = cw.verify(sec, ds, TODAY)
    assert v["status"] == "pass" and v["checked_parcels"] == 6, v
    flags = {(f["type"], p["parcel_id"]) for p in sec["parcels"] for f in p["flags"]}
    assert ("farmed_but_no_crop_signal", "Nandur-118") in flags          # listed as bajra, bare all season
    assert ("crop_signal_not_listed", "Nandur-121/3") in flags           # paid, not on the list, yet a canopy was seen
    assert ("lease_area_vs_boundary", "Nandur-112/1") in flags           # documents agree, the on-chain boundary does not
    by = {p["parcel_id"]: p for p in sec["parcels"]}
    assert by["Nandur-118"]["biomass"]["season"]["t_per_ha"] == 0.0     # no canopy, no biomass (soil margin)
    assert all(p["registry"]["verified"] and p["registry"]["boundary_matches_registry"] and p["registry"]["document"]["cid_verified"] for p in sec["parcels"])
    assert all(o["item"].startswith("S2") for p in sec["parcels"] for o in p["observations"]["season"])


@pytest.mark.parametrize("forge", [
    lambda s: s["parcels"][0]["biomass"]["season"].__setitem__("t_per_ha", 99.0),
    lambda s: s["parcels"][3]["observations"]["season"][5].__setitem__("ndvi", 0.81),   # a greener observation changes every derived number
    lambda s: s["parcels"][3]["flags"].clear(),
    lambda s: s["parcels"][4].__setitem__("farmed", True),
    lambda s: s["parcels"].pop(),
    lambda s: s["summary"].__setitem__("flags", 0),
    lambda s: s["radiation"]["daily"].__setitem__("2026-08-01", 40.0),
    lambda s: s.__setitem__("season", {"start": "2026-07-01", "end": TODAY}),
])
def test_forged_section_fails(forge):
    sec = section()
    forge(sec)
    assert cw.verify(sec, farm.load_demo("IN", "in-mh"), TODAY)["status"] == "fail"


def test_other_method_version_is_not_called_forged():
    sec = section()
    sec["method"]["version"] = "agroland-cropwatch/0"
    assert cw.verify(sec, farm.load_demo("IN", "in-mh"), TODAY)["status"] == "not_recomputed"


def test_pure_arithmetic():
    assert cw.season_window("2026-10-31", "06-01") == {"start": "2026-06-01", "end": "2026-10-31"}
    assert cw.season_window("2026-06-15", "06-01")["start"] == "2025-06-01"      # less than 30 days in: the season before
    assert cw.previous_window({"start": "2024-02-29", "end": "2024-03-10"}) == {"start": "2023-02-28", "end": "2023-03-10"}
    assert [cw.crop_group(c) for c in ("Bajra (pearl millet)", "Winterweizen", "Soybean", "", None, "Mais")] == ["c4", "c3_cereal", "other", "unknown", "unknown", "c4"]
    assert cw.fapar(0.22, 0.12) == 0.0 and cw.fapar(0.95, 0.12) == cw.FAPAR_MAX
    assert cw.boa_offset("05.13") == 1000 and cw.boa_offset("03.01") == 0
    obs = [{"date": "2026-07-01", "ndvi": 0.2}, {"date": "2026-07-03", "ndvi": 0.9}]
    rad = {"2026-07-01": 20.0, "2026-07-02": 20.0, "2026-07-03": 20.0}
    b = cw.biomass(obs, rad, {"start": "2026-06-01", "end": "2026-10-31"}, 2.0, 0.2)
    # day 1: NDVI 0.2 -> 0; day 2: NDVI 0.55 -> 0.95*(0.25/0.6); day 3: NDVI 0.9 -> 0.95; each x 2.0 g/MJ x 0.48 x 20 MJ
    expect = 2.0 * 0.48 * 20 * (0.95 * 0.25 / 0.6 + 0.95) / 100
    assert b["t_per_ha"] == round(expect, 2) and b["integrated_days"] == 3 and b["from"] == "2026-07-01"
    assert cw.biomass(obs[:1], rad, {"start": "2026-06-01", "end": "2026-10-31"}, 2.0, 0.2)["t_per_ha"] is None
    m = cw.series_metrics([{"date": "2026-06-10", "ndvi": 0.15}, {"date": "2026-08-20", "ndvi": 0.85}, {"date": "2026-10-20", "ndvi": 0.25}],
                          {"start": "2026-06-01", "end": "2026-10-31"})
    assert m["peak_ndvi"] == 0.85 and m["baseline_ndvi"] == 0.15 and m["max_gap_days"] == 71
    assert cw.canopy_status(m, "2026-10-31")["code"] == "after_peak"
    assert cw.canopy_status({**m, "latest_ndvi": 0.6}, "2026-10-31")["code"] == "dense_canopy"
    assert cw.canopy_status({"clear_observations": 0}, "2026-10-31")["code"] == "no_clear_view"


def scene(red, nir, scl, h=6, w=6):
    return np.stack([np.full((h, w), red, np.uint16), np.full((h, w), nir, np.uint16), np.full((h, w), scl, np.uint16), np.full((h, w), 255, np.uint16)])


def test_observe_offset_clouds_and_artefacts():
    mask = np.zeros((6, 6), bool)
    mask[1:5, 1:5] = True  # 16 pixels
    o = cw.observe(scene(1300, 4000, 4), mask, 1000)
    assert o["use"] and o["ndvi"] == round((3000 - 300) / 3300, 4) and o["clear_px"] == 16
    assert cw.observe(scene(1300, 4000, 4), mask, 0)["ndvi"] == round(2700 / 5300, 4)  # an old baseline has no offset
    a = scene(1300, 4000, 4)
    a[2, 1, 1:4] = 9  # 3 of 16 pixels cloud > 10 %
    assert cw.observe(a, mask, 1000) == {"use": False, "why": "cloudy"}
    a = scene(1300, 4000, 4)
    a[0, 1, 1] = 990  # one pixel with negative red reflectance would read NDVI 1.0: dropped, not used
    o = cw.observe(a, mask, 1000)
    assert o["use"] and o["clear_px"] == 15 and o["ndvi"] == round(2700 / 3300, 4)
    a = scene(1300, 4000, 4)
    a[3, :, :3] = 0  # half the parcel outside the scene footprint
    assert cw.observe(a, mask, 1000)["why"] == "no_data"


def fake_sources(fail=False):
    """STAC + data API + Open-Meteo stand-ins. NDVI of every parcel follows a crop curve that peaks in late August."""
    def ndvi_on(day):
        doy = (np.datetime64(day) - np.datetime64(day[:4] + "-01-01")).astype(int)
        return float(0.15 + 0.7 * np.exp(-((doy - 235) / 30.0) ** 2))

    def handler(req: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(503)
        u = str(req.url)
        if u.endswith("/search"):
            body = json.loads(req.content)
            start, end = body["datetime"].split("/")
            days = np.arange(np.datetime64(start[:10]), np.datetime64(end[:10]) + np.timedelta64(1, "D"), np.timedelta64(10, "D"))
            feats = [{"id": f"S2X_MSIL2A_{str(d).replace('-', '')}_T43QDB", "geometry": {"type": "Polygon", "coordinates": [[[74, 18], [76, 18], [76, 20], [74, 20], [74, 18]]]},
                      "properties": {"datetime": f"{d}T05:30:00Z", "eo:cloud_cover": 5.0, "s2:processing_baseline": "05.13", "proj:epsg": 32643}} for d in days]
            return httpx.Response(200, json={"features": feats, "links": []})
        m = re.search(r"/bbox/[^/]+/(\d+)x(\d+)\.npy", u)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            day = re.search(r"MSIL2A_(\d{8})", u).group(1)
            nd = ndvi_on(f"{day[:4]}-{day[4:6]}-{day[6:]}")
            red = 1000 + 400
            nir = int(round(1000 + 400 * (1 + nd) / (1 - nd)))  # (nir-1000 - 400)/(nir-1000 + 400) = nd
            buf = io.BytesIO()
            np.save(buf, scene(red, nir, 4, h, w))
            return httpx.Response(200, content=buf.getvalue())
        if "open-meteo" in u:
            q = dict(req.url.params)
            days = np.arange(np.datetime64(q["start_date"]), np.datetime64(q["end_date"]) + np.timedelta64(1, "D"), np.timedelta64(1, "D"))
            return httpx.Response(200, json={"daily": {"time": [str(d) for d in days], "shortwave_radiation_sum": [20.0] * len(days)}})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def registry_stub(ds):
    geoms = {f["properties"]["registry"]["tx_hash"]: f for f in ds["boundaries"]["features"]}

    def lookup(tx):
        f = geoms[tx]
        rid = f["properties"]["registry"]["farm_id"]
        return {"tx_hash": tx, "verified": True, "checks": {"spent_from_registry_address": True, "pays_farm_token": True}, "block_time": 1793411522,
                "record": {"ref_1": "1", "ref_2": rid, "agent_code": "SYNG000000", "value_1": 1000, "value_2": 7, "document_cid": f["properties"]["registry"]["document_cid"]},
                "document": {"status": "ok", "cid_verified": True, "farms": [{"farm_id": int(rid), "geometry": f["geometry"]}]}}
    return lookup


def test_analyze_with_mock_sources_round_trips():
    ds = farm.load_demo("IN", "in-mh")
    sec = cw.analyze(ds, TODAY, cw.Fetcher(transport=fake_sources(), workers=2), registry_stub(ds))
    assert sec["status"] == "ok" and sec["summary"]["parcels_observed"] == 6 and sec["summary"]["registry_verified"] == 6
    p = sec["parcels"][0]
    assert p["observations"]["season"] and abs(p["metrics"]["season"]["peak_ndvi"] - 0.85) < 0.03
    assert p["biomass"]["season"]["t_per_ha"] > 0 and p["registry"]["boundary_matches_registry"]
    assert cw.verify(json.loads(json.dumps(sec)), ds, TODAY)["status"] == "pass"
    md = "\n".join(cw.markdown(sec, "acre"))
    assert "Crop and biomass" in md and "5am.earth registrations" in md


def test_sources_down_or_registry_down_are_reported_not_guessed():
    ds = farm.load_demo("IN", "in-mh")

    def broken(tx):
        raise RuntimeError("Koios unreachable")
    sec = cw.analyze(ds, TODAY, cw.Fetcher(transport=fake_sources(fail=True), workers=2, retries=1), broken)
    assert sec["status"] == "unavailable" and all(p["status"]["code"] == "unavailable" for p in sec["parcels"])
    assert all(p["registry"]["status"] == "unavailable" for p in sec["parcels"]) and len(sec["unavailable"]) == 2
    assert cw.verify(json.loads(json.dumps(sec)), ds, TODAY)["status"] == "pass"
    off = cw.analyze(ds, TODAY, None, None)
    assert off["status"] == "unavailable" and "switched off" in off["unavailable"][-1]
    assert cw.analyze(farm.load_demo("IN"), TODAY, None, None) is None  # no boundaries, no section


def test_uploaded_boundaries_are_validated():
    ds = farm.load_demo("IN", "in-mh")
    good = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"parcel_id": f["properties"]["parcel_id"]}, "geometry": f["geometry"]}
                                                       for f in ds["boundaries"]["features"]]}
    india = lambda la, lo: 6 <= la <= 37.5 and 68 <= lo <= 97.5  # noqa: E731
    out = cw.validate_boundaries(good, ds, india)
    assert len(out["features"]) == 6 and out["features"][0]["properties"]["source"] == "uploaded"
    bad_id = json.loads(json.dumps(good)); bad_id["features"][0]["properties"]["parcel_id"] = "Elsewhere-1"
    dup = json.loads(json.dumps(good)); dup["features"][1]["properties"]["parcel_id"] = dup["features"][0]["properties"]["parcel_id"]
    away = json.loads(json.dumps(good)); away["features"][0]["geometry"]["coordinates"] = [[[11.5, 52.0], [11.6, 52.0], [11.6, 52.1], [11.5, 52.0]]]
    line = json.loads(json.dumps(good)); line["features"][0]["geometry"] = {"type": "LineString", "coordinates": [[74.9, 18.9], [75.0, 19.0]]}
    for fc in (bad_id, dup, away, line, {"type": "Feature"}):
        with pytest.raises(ValueError):
            cw.validate_boundaries(fc, ds, india)


def test_lease_check_order_carries_the_section(make_client):
    from conftest import wait_state, workspace
    c, _ = make_client()
    h, _ = workspace(c, "Nandur tenant", "farm", "IN")
    assert [d["id"] for d in c.get("/api/farm/demos", headers=h).json()] == ["in", "in-mh"]
    demo = c.get("/api/farm/demo?demo=in-mh", headers=h).json()
    assert len(demo["boundaries"]["features"]) == 6 and demo["demo_id"] == "in-mh"
    assert c.get("/api/farm/demo?demo=nope", headers=h).status_code == 404
    o = c.post("/api/orders", headers=h, json={"service": "lease_check", "input": {"source": "demo", "demo": "in-mh"}}).json()
    c.post(f"/api/orders/{o['id']}/pay", headers=h)
    wait_state(c, h, o["id"], {"delivered"})
    res = c.get(f"/api/orders/{o['id']}/result", headers=h).json()
    sec = res["report"]["crop_monitoring"]
    assert sec["status"] == "unavailable" and len(sec["parcels"]) == 6  # the test server runs with AGROLAND_CROPWATCH=off
    assert "Crop and biomass" in res["markdown"]
    v = c.get(f"/api/orders/{o['id']}/verify", headers=h).json()
    assert v["recomputation"]["status"] == "pass" and v["crop_recomputation"]["status"] == "pass"
    # uploads may carry boundaries; a boundary for an unknown parcel is refused
    files = {k: (Path(farm.DATA, "in-mh") / f"{k[:-4]}.csv").read_text("utf-8") for k in ("contracts_csv", "cadastre_csv", "fields_csv")}
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"parcel_id": f["properties"]["parcel_id"]}, "geometry": f["geometry"]}
                                                     for f in demo["boundaries"]["features"]]}
    assert c.put("/api/farm/dataset", headers=h, json={**files, "boundaries_geojson": json.dumps(fc)}).status_code == 200
    saved = c.get("/api/farm/dataset", headers=h).json()["dataset"]
    assert len(saved["boundaries"]["features"]) == 6
    fc["features"][0]["properties"]["parcel_id"] = "X-1"
    r = c.put("/api/farm/dataset", headers=h, json={**files, "boundaries_geojson": json.dumps(fc)})
    assert r.status_code == 422 and "boundaries" in r.json()["detail"]
