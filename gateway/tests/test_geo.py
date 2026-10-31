from shapely.geometry import shape

from agroland.geoclient import in_country


def test_india_map_has_a_working_set_of_fields(make_client):
    c, _ = make_client()
    fc = c.get("/api/geo/in/demo-parcels").json()
    fs = fc["features"]
    ids = [f["properties"]["id"] for f in fs]
    assert len(fs) >= 60 and len(set(ids)) == len(ids)
    assert {f["properties"]["district"] for f in fs} >= {"Kutch", "Anantapur", "Beed"}
    assert all(f["properties"]["demo"] and shape(f["geometry"]).is_valid for f in fs)
    assert all(in_country("IN", f["geometry"]["coordinates"][0][0][1], f["geometry"]["coordinates"][0][0][0]) for f in fs)
    reg = [f for f in fs if f["properties"].get("registered")]
    assert len(reg) == 6 and all(len(f["properties"]["registry_tx"]) == 64 for f in reg)
    # the first five keep their ids: docs and the demo neighbourhood refer to them
    assert ids[:5] == [f"IN-DEMO-{i}" for i in range(1, 6)]


def test_any_india_field_can_be_saved_as_a_parcel(make_client):
    c, _ = make_client()
    u = c.post("/api/session", json={"name": "IN owner", "role": "owner", "country": "IN"}).json()
    h = {"Authorization": "Bearer " + u["token"]}
    fs = c.get("/api/geo/in/demo-parcels").json()["features"]
    for f in (fs[10], next(x for x in fs if x["properties"].get("registered"))):
        r = c.post("/api/parcels", headers=h, json={"source": "in-demo", "ref": f["properties"]["id"]})
        assert r.status_code == 201 and r.json()["area_ha"] == f["properties"]["area_ha"]
