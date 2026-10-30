import pytest
from agroland import geoclient
from conftest import wait_state, workspace

REPORT = {"overall_verdict": "GO", "score": 80, "assessed_technology": "solar", "warnings": [], "technology_assessment": {"solar": {"verdict": "GO", "score": 80, "score_breakdown": {}, "blockers": [], "conditions": []}},
          "data_quality": {"osm": "ok"}, "location_info": {"area_hectares": 3.0}, "methodology": "t"}


@pytest.mark.parametrize("country", ["DE", "IN"])
def test_listing_is_controlled_by_owner(make_client, monkeypatch, country):
    monkeypatch.setattr(geoclient.Geo, "audit", lambda self, body: REPORT)
    c, _ = make_client()
    ho, owner = workspace(c, "Maria", "owner", country)
    hd, _ = workspace(c, "Dev", "developer", country)
    from agroland import alkis
    p = (c.post("/api/parcels", headers=ho, json={"source": "alkis-demo", "ref": alkis.demo_id()}) if country == "DE" else c.post("/api/parcels", headers=ho, json={"source": "in-demo", "ref": "IN-DEMO-3"})).json()
    assert p["ownership"] == "not verified"
    doc = c.post("/api/documents/sample", headers=ho, json={"label": p["label"]}).json()
    assert doc["sample"] and "Not verified" in doc["note"]
    l = c.post("/api/listings", headers=ho, json={"parcel_id": p["id"], "deal_type": "lease", "price": 1800, "consent": True, "document_id": doc["id"]}).json()
    assert l["status"] == "needs_audit" and not l["visible_to_developers"], "consent alone does not publish: an audit is attached first"
    assert c.get("/api/marketplace", headers=hd).json() == []
    o = c.post("/api/orders", headers=ho, json={"service": "land_audit", "input": {"parcel_id": p["id"], "project_type": "solar"}}).json()
    c.post(f"/api/orders/{o['id']}/pay", headers=ho)
    wait_state(c, ho, o["id"], {"delivered"})
    l = c.patch(f"/api/listings/{l['id']}", headers=ho, json={"audit_order_id": o["id"]}).json()
    assert l["status"] == "published" and l["ownership"] == "not verified"
    m = c.get("/api/marketplace", headers=hd).json()
    assert len(m) == 1 and not ({"owner", "owner_name", "document_id", "geometry", "parcel_id"} & set(m[0])), "allow-listed fields only"
    assert m[0]["audit"]["verdict"] == "GO" and m[0]["my_interest"]["status"] == "none"
    # publishing transfers nothing: the exact boundary is disclosed only to a developer the owner accepts
    c.post(f"/api/marketplace/{l['id']}/interest", headers=hd, json={"message": "Interested"})
    st = c.get("/api/marketplace", headers=hd).json()[0]["my_interest"]
    assert st["status"] == "pending" and "disclosed_boundary" not in st
    iid = c.get("/api/listings", headers=ho).json()[0]["interests"][0]["id"]
    c.post(f"/api/listings/{l['id']}/interests/{iid}", headers=ho, json={"decision": "accepted"})
    assert c.get("/api/marketplace", headers=hd).json()[0]["my_interest"]["disclosed_boundary"]["type"] == "Polygon"
    # revoking consent removes it immediately
    c.patch(f"/api/listings/{l['id']}", headers=ho, json={"consent": False})
    assert c.get("/api/marketplace", headers=hd).json() == []
    # document is owner-only
    assert c.get(f"/api/documents/{doc['id']}", headers=hd).status_code == 404
    assert c.get(f"/api/documents/{doc['id']}", headers=ho).headers["content-type"] == "application/pdf"
    # farm role cannot list; developers cannot see owner endpoints
    hf, _ = workspace(c, "Farm F", "farm", country)
    assert c.post("/api/listings", headers=hf, json={}).status_code == 403
    assert c.get("/api/marketplace", headers=hf).status_code == 403


def test_pdf_upload_validation(make_client):
    c, _ = make_client()
    h, _ = workspace(c, "Maria", "owner", "DE")
    assert c.post("/api/documents", headers=h, files={"file": ("x.pdf", b"not a pdf", "application/pdf")}).status_code == 422
    ok = c.post("/api/documents", headers=h, files={"file": ("x.pdf", b"%PDF-1.4\n...\n%%EOF", "application/pdf")})
    assert ok.status_code == 201 and ok.json()["sample"] is False


def test_farm_upload_and_outcomes(make_client):
    from agroland import farm
    from pathlib import Path
    c, _ = make_client()
    h, _ = workspace(c, "Hans", "farm", "DE")
    d = Path(farm.DATA, "de")
    body = {"contracts_csv": (d / "contracts.csv").read_text(), "cadastre_csv": (d / "cadastre.csv").read_text(), "fields_csv": (d / "fields.csv").read_text()}
    assert c.put("/api/farm/dataset", headers=h, json={**body, "contracts_csv": "garbage"}).status_code == 422
    assert c.put("/api/farm/dataset", headers=h, json=body).json()["contracts"] == 22
    o = c.post("/api/orders", headers=h, json={"service": "lease_check", "input": {"source": "saved"}}).json()
    c.post(f"/api/orders/{o['id']}/pay", headers=h)
    wait_state(c, h, o["id"], {"delivered"})
    rep = c.get(f"/api/orders/{o['id']}/result", headers=h).json()["report"]
    assert rep["summary"]["achieved_per_year"] == 0
    out = c.post("/api/farm/outcomes", headers=h, json={"order_id": o["id"], "finding_key": "above_market_rent:HF-03", "amount_per_year": 500, "note": "owner agreed"}).json()
    assert out["achieved_per_year"] == 500
    assert c.post("/api/farm/outcomes", headers=h, json={"order_id": o["id"], "finding_key": "nope:XX", "amount_per_year": 1}).status_code == 404
