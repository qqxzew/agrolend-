"""Two-party pool workflow against the REAL matcher, escrow and architect services (started as subprocesses).
Only the audit service is a stub (live geodata would make the test non-deterministic)."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import stack  # noqa: E402
from conftest import wait_state, workspace  # noqa: E402


def free_ports(n):
    socks = [socket.socket() for _ in range(n)]
    for s in socks:
        s.bind(("127.0.0.1", 0))
    ports = [s.getsockname()[1] for s in socks]
    for s in socks:
        s.close()
    return ports


@pytest.fixture(params=["DE", "IN"])
def geo_stack(request, tmp_path):
    ports = tuple(free_ports(4))
    k = stack.keys({})
    procs = stack.geo_processes(tmp_path, k, de_ports=ports, in_ports=ports, countries=(request.param,))
    audit = procs[0]
    audit["env"]["INTERNAL_API_KEY"] = k[f"GEO_{request.param}_INTERNAL_KEY"]
    request.node.country = request.param
    audit["args"] = [sys.executable, "-m", "uvicorn", "fake_audit:app", "--host", "127.0.0.1", "--port", str(ports[0]), "--log-level", "warning"]
    audit["cwd"] = str(Path(__file__).parent)
    running = []
    for p in procs:
        running.append(subprocess.Popen(p["args"], cwd=p["cwd"], env={**p["env"], "PYTHONPATH": str(Path(__file__).parent)}, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT))
    end = time.time() + 40
    for port in ports:
        while time.time() < end:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        else:
            raise RuntimeError(f"service on {port} did not start")
    yield ports, k, request.param
    for r in running:
        r.terminate()
    for r in running:
        r.wait(5)


def profile(name, rep, mail, country="DE"):
    if country == "IN":
        return {"company_name": name, "address": "Plot 4, Industrial Area, Bhuj", "state": "Gujarat", "pin_code": "370001", "representative": rep,
                "registration_no": "U00000GJ2020PTC000000", "gstin": "", "email": mail, "phone": "+91 98000 00000"}
    return {"company_name": name, "street": "Hauptstraße 1", "postal_code": "39104", "city": "Magdeburg", "representative": rep,
            "commercial_register": "AG Stendal, HRB 1", "email": mail, "phone": "+49 391 000000"}


def parcel_for(c, h, cty):
    from agroland import alkis
    if cty == "DE":
        return c.post("/api/parcels", headers=h, json={"source": "alkis-demo", "ref": alkis.demo_id()}).json()
    return c.post("/api/parcels", headers=h, json={"source": "in-demo", "ref": "IN-DEMO-1"}).json()


def test_two_party_deal_end_to_end(make_client, geo_stack):
    ports, k, cty = geo_stack
    env = stack.gateway_env(k, Path("/unused"), 0, de_ports=ports, in_ports=ports)
    env.pop("AGROLAND_STATE_DIR")
    c, app = make_client(**env)
    from agroland import alkis
    ha, a = workspace(c, "Windkraft Nord GmbH", "developer", cty)
    p = parcel_for(c, ha, cty)
    r = c.post("/api/pool/portfolio", headers=ha, json={"parcel_id": p["id"], "project_type": "wind"})
    assert r.status_code == 201 and r.json()["status"] == "registered", r.text
    assert c.post("/api/pool/portfolio", headers=ha, json={"parcel_id": p["id"], "project_type": "wind"}).status_code == 409
    # a second identity, created by the server next to my site; it must act for itself
    cp = c.post("/api/demo/counterpart", headers=ha, json={"pool_parcel_id": r.json()["id"]}).json()
    hb = {"Authorization": "Bearer " + cp["token"]}
    teasers = c.get("/api/pool/teasers", headers=ha).json()
    assert len(teasers) == 1 and "coordinates" not in str(teasers[0]).lower()
    mid = teasers[0]["match_id"]
    assert c.get(f"/api/pool/deals/{mid}", headers=hb).status_code == 200
    # outsiders cannot see the deal
    hc, _ = workspace(c, "Other Dev", "developer", cty)
    assert c.get(f"/api/pool/deals/{mid}", headers=hc).status_code in (403, 404)
    # consent needs a profile
    assert c.post(f"/api/pool/deals/{mid}/consent", headers=ha, json={"decision": "accept"}).status_code == 422
    assert c.put("/api/pool/profile", headers=ha, json=profile("Windkraft Nord GmbH", "Anna Müller, Geschäftsführerin", "anna@wn.example", cty)).status_code == 200
    d = c.post(f"/api/pool/deals/{mid}/consent", headers=ha, json={"decision": "accept"}).json()
    assert d["status"] == "pending_consent" and d["order"] is None, "no payment before both consented"
    d = c.post(f"/api/pool/deals/{mid}/consent", headers=hb, json={"decision": "accept"}).json()
    assert d["status"] == "awaiting_signatures" and d["order"]["state"] == "quoted" and d["order"]["price"]["display"] == "3.00 tUSDM"
    # NDA names both companies: locked until BOTH payments are locked
    assert c.get(f"/api/pool/deals/{mid}/nda.pdf", headers=ha).status_code == 402
    c.post(f"/api/orders/{d['order']['id']}/pay", headers=hb)
    da = c.get(f"/api/pool/deals/{mid}", headers=ha).json()
    assert da["own_paid"] is False and c.get(f"/api/pool/deals/{mid}/nda.pdf", headers=ha).status_code == 402
    c.post(f"/api/orders/{da['order']['id']}/pay", headers=ha)
    nda = c.get(f"/api/pool/deals/{mid}/nda.pdf", headers=ha)
    assert nda.status_code == 200 and nda.content.startswith(b"%PDF")
    import hashlib
    sha = hashlib.sha256(nda.content).hexdigest()
    sign = lambda h, name: c.post(f"/api/pool/deals/{mid}/sign", headers=h, json={"signer_name": name, "signer_role": "Geschäftsführer", "document_sha256": sha, "accept": True})
    assert sign(ha, "Anna Müller").status_code == 200
    # the order of party A must NOT deliver while B has not signed
    app.state.engine.tick(); time.sleep(0.5)
    assert c.get(f"/api/orders/{da['order']['id']}", headers=ha).json()["state"] == "waiting"
    assert c.get(f"/api/pool/deals/{mid}/documents/agreement.pdf", headers=ha).status_code == 409
    assert sign(hb, "Jörg Schäfer").status_code == 200
    oa = wait_state(c, ha, da["order"]["id"], {"delivered"}, 40)
    ob = wait_state(c, hb, d["order"]["id"], {"delivered"}, 40)
    res = c.get(f"/api/orders/{oa['id']}/result", headers=ha).json()["report"]
    assert res["disclosure"]["counterpart"]["company"]["company_name"].startswith(("Solarpark", "Surya"))
    assert res["joint_plan"]["plan"]["shares_bp"] and len(res["documents"]) == 2
    for kind in ("agreement", "grid_application"):
        pdf = c.get(f"/api/pool/deals/{mid}/documents/{kind}.pdf", headers=ha)
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert c.get(f"/api/pool/deals/{mid}/documents/agreement.pdf", headers=hc).status_code in (403, 404, 409)


def test_decline_ends_deal_without_delivery(make_client, geo_stack):
    ports, k, cty = geo_stack
    env = stack.gateway_env(k, Path("/unused"), 0, de_ports=ports, in_ports=ports)
    env.pop("AGROLAND_STATE_DIR")
    c, app = make_client(**env)
    ha, _ = workspace(c, "Dev A", "developer", cty)
    p = parcel_for(c, ha, cty)
    reg = c.post("/api/pool/portfolio", headers=ha, json={"parcel_id": p["id"], "project_type": "wind"}).json()
    cp = c.post("/api/demo/counterpart", headers=ha, json={"pool_parcel_id": reg["id"]}).json()
    hb = {"Authorization": "Bearer " + cp["token"]}
    mid = c.get("/api/pool/teasers", headers=ha).json()[0]["match_id"]
    c.put("/api/pool/profile", headers=ha, json=profile("Dev A GmbH", "A B, GF", "a@x.example", cty))
    c.post(f"/api/pool/deals/{mid}/consent", headers=ha, json={"decision": "accept"})
    d = c.post(f"/api/pool/deals/{mid}/consent", headers=hb, json={"decision": "decline"}).json()
    assert d["status"] == "declined" and d["order"] is None


def test_demo_neighbourhood_scenario(make_client, geo_stack):
    """One click builds: our site in the pool, another developer's site (teaser), and a Landowner agent's listed parcel that we can take on lease."""
    ports, k, cty = geo_stack
    env = stack.gateway_env(k, Path("/unused"), 0, de_ports=ports, in_ports=ports)
    env.pop("AGROLAND_STATE_DIR")
    c, app = make_client(**env)
    ha, _ = workspace(c, "Windkraft Nord GmbH", "developer", cty)
    assert c.post("/api/demo/neighbourhood", headers=ha).status_code == 202
    end = time.time() + 90
    while time.time() < end:
        job = c.get("/api/demo/neighbourhood", headers=ha).json()
        if job["status"] != "running":
            break
        time.sleep(1)
    assert job["status"] == "done", job
    assert [s["status"] for s in job["steps"]] == ["done", "done", "done"]
    # another developer's anonymous teaser exists
    assert len(c.get("/api/pool/teasers", headers=ha).json()) == 1
    # the Landowner agent's parcel is listed; taking it on lease is accepted by the demo owner and reveals the boundary
    m = c.get("/api/marketplace", headers=ha).json()
    assert len(m) == 1 and m[0]["agent_demo"] is True and m[0]["my_interest"]["status"] == "none"
    r = c.post(f"/api/marketplace/{m[0]['id']}/interest", headers=ha, json={"message": "Lease for our wind project"}).json()
    assert r["status"] == "accepted" and r["disclosed_boundary"]["type"] == "Polygon"
    # the seed order is labelled and carries no payment
    owner_order = [o for o in app.state.engine.list_for(job["result"]["counterpart"]["user"]["id"])]
    assert owner_order == []
    # a real (non-demo) owner is never auto-accepted
    ho, _ = workspace(c, "Real Owner", "owner", cty)
    p = parcel_for(c, ho, cty)
    c.post("/api/documents/sample", headers=ho, json={"label": p["label"]})
    o = c.post("/api/orders", headers=ho, json={"service": "land_audit", "input": {"parcel_id": p["id"], "project_type": "solar"}}).json()
    c.post(f"/api/orders/{o['id']}/pay", headers=ho)
    wait_state(c, ho, o["id"], {"delivered"}, 40)
    l = c.post("/api/listings", headers=ho, json={"parcel_id": p["id"], "deal_type": "lease", "price": 1000, "consent": True, "audit_order_id": o["id"]}).json()
    m2 = [x for x in c.get("/api/marketplace", headers=ha).json() if x["id"] == l["id"]][0]
    assert m2["agent_demo"] is False
    assert c.post(f"/api/marketplace/{l['id']}/interest", headers=ha, json={"message": "x"}).json()["status"] == "pending"
