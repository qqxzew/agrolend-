"""Order engine tests. Mocks here are TESTING MOCKS of the payment service: they prove our state machine, not a real payment."""
import json
import time

import httpx
import pytest

from agroland import masumi
from conftest import wait_state, workspace


def test_lease_check_unpaid_dev_flow_and_labels(make_client):
    c, app = make_client()
    h, u = workspace(c, "Hans Farm", "farm", "DE")
    o = c.post("/api/orders", headers=h, json={"service": "lease_check", "input": {"source": "demo"}, "idempotency_key": "k1"}).json()
    assert o["state"] == "quoted" and o["price"]["display"] == "2.00 tUSDM" and o["unpaid_dev_mode"] is True
    again = c.post("/api/orders", headers=h, json={"service": "lease_check", "input": {"source": "demo"}, "idempotency_key": "k1"}).json()
    assert again["id"] == o["id"], "same idempotency key must not create a second order"
    p = c.post(f"/api/orders/{o['id']}/pay", headers=h).json()
    assert p["state"] == "paid" and "UNPAID" in p["payment"]["label"]
    assert c.post(f"/api/orders/{o['id']}/pay", headers=h).json()["state"] in ("paid", "running", "delivered")  # refresh/double click is harmless
    d = wait_state(c, h, o["id"], {"delivered"})
    res = c.get(f"/api/orders/{o['id']}/result", headers=h).json()
    assert res["report"]["summary"]["identified_per_year"] == 1440 and res["unpaid_dev_mode"] is True
    v = c.get(f"/api/orders/{o['id']}/verify", headers=h).json()
    assert v["report_hash_matches"] and v["recomputation"]["status"] == "pass" and "UNPAID" in v["chain"]["note"]
    assert "BEGIN:VCALENDAR" in c.get(f"/api/orders/{o['id']}/reminders.ics", headers=h).text
    assert d["result_hash"] and len(d["result_hash"]) == 64


def test_access_is_per_user(make_client):
    c, _ = make_client()
    h1, _ = workspace(c, "Farm One", "farm", "DE")
    h2, _ = workspace(c, "Farm Two", "farm", "DE")
    o = c.post("/api/orders", headers=h1, json={"service": "lease_check", "input": {"source": "demo"}}).json()
    assert c.get(f"/api/orders/{o['id']}", headers=h2).status_code == 404
    assert c.post(f"/api/orders/{o['id']}/pay", headers=h2).status_code == 404
    assert c.get(f"/api/orders/{o['id']}/result", headers=h2).status_code == 404
    assert c.get("/api/orders", headers=h2).json() == []
    assert c.get("/api/orders").status_code == 401
    assert c.get("/api/orders", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_country_mismatch_and_unknown_inputs_rejected(make_client):
    c, _ = make_client()
    h, _ = workspace(c, "Farm IN", "farm", "IN")
    r = c.post("/api/orders", headers=h, json={"service": "lease_check", "input": {"source": "demo"}}).json()
    assert r["country"] == "IN" and r["price"]["display"] == "2.00 tUSDM"
    hd, _ = workspace(c, "Dev DE", "developer", "DE")
    assert c.post("/api/orders", headers=hd, json={"service": "land_audit", "input": {"lat": 28.6, "lon": 77.2}}).status_code == 422  # Delhi is not Germany
    assert c.post("/api/orders", headers=hd, json={"service": "land_audit", "input": {}}).status_code == 422
    assert c.post("/api/orders", headers=hd, json={"service": "land_audit", "input": {"lat": 52.0, "lon": 12.7, "project_type": "nuclear"}}).status_code == 422
    assert c.post("/api/orders", headers=hd, json={"service": "nope", "input": {}}).status_code == 422


def test_land_audit_with_stubbed_geo_keeps_three_concepts_separate(make_client, monkeypatch):
    from agroland import geoclient
    report = {"overall_verdict": "CONDITIONAL_GO", "score": 70, "assessed_technology": "solar", "warnings": ["w"],
              "technology_assessment": {"solar": {"verdict": "CONDITIONAL_GO", "score": 70, "score_breakdown": {}, "blockers": [], "conditions": ["c"]}},
              "data_quality": {"osm": "ok", "bfn": "unavailable: timeout"}, "location_info": {"area_hectares": 3.0}, "methodology": "t"}
    monkeypatch.setattr(geoclient.Geo, "audit", lambda self, body: report)
    c, _ = make_client()
    h, _ = workspace(c, "Maria", "owner", "DE")
    from agroland import alkis
    p = c.post("/api/parcels", headers=h, json={"source": "alkis-demo", "ref": alkis.demo_id()}).json()
    o = c.post("/api/orders", headers=h, json={"service": "land_audit", "input": {"parcel_id": p["id"], "project_type": "solar"}}).json()
    c.post(f"/api/orders/{o['id']}/pay", headers=h)
    wait_state(c, h, o["id"], {"delivered"})
    rep = c.get(f"/api/orders/{o['id']}/result", headers=h).json()["report"]
    assert rep["audit_conclusion"]["verdict"] == "CONDITIONAL_GO"
    assert rep["geometric_signal"]["geometry_signal"] in ("green", "yellow", "red")
    assert rep["data_quality"]["complete"] is False and rep["data_quality"]["unavailable_checks"] == ["bfn"]
    assert any("not legal advice" in x.lower() for x in rep["limitations"])


def test_execution_failure_is_not_delivered(make_client, monkeypatch):
    from agroland import geoclient
    def boom(self, body):
        raise geoclient.GeoUnavailable("down")
    monkeypatch.setattr(geoclient.Geo, "audit", boom)
    c, app = make_client()
    h, _ = workspace(c, "Dev", "developer", "DE")
    o = c.post("/api/orders", headers=h, json={"service": "land_audit", "input": {"lat": 52.07, "lon": 12.73}}).json()
    c.post(f"/api/orders/{o['id']}/pay", headers=h)
    end = time.time() + 30
    while time.time() < end:
        app.state.engine.tick()
        st = c.get(f"/api/orders/{o['id']}", headers=h).json()
        if st["state"] == "failed":
            break
        time.sleep(0.3)
    assert st["state"] == "failed" and not st["has_result"] and st["payment"]["attempts"] == 3


class FakeMps:
    """Testing double for the Masumi payment service."""
    def __init__(self):
        self.calls, self.state, self.hash = [], None, None

    def __call__(self, request: httpx.Request):
        body = json.loads(request.content)
        path = request.url.path
        self.calls.append((path, body))
        now = int(time.time() * 1000)
        if path.endswith("/payment") and request.method == "POST":
            return httpx.Response(200, json={"data": {"blockchainIdentifier": "bc-1", "agentIdentifier": body["agentIdentifier"], "payByTime": str(now + 900_000),
                                                      "submitResultTime": str(now + 1_800_000), "unlockTime": str(now + 3_600_000), "externalDisputeUnlockTime": str(now + 5_400_000),
                                                      "sellerReturnAddress": None, "PaymentSource": {"smartContractAddress": "addr_test1sc", "policyId": "pol"},
                                                      "RequestedFunds": body["RequestedFunds"], "SmartContractWallet": {"walletVkey": "vk"}}})
        if path.endswith("resolve-blockchain-identifier"):
            data = {"onChainState": self.state, "resultHash": self.hash, "CurrentTransaction": None, "TransactionHistory": []}
            if self.state:
                data["TransactionHistory"] = [{"status": "Confirmed", "newOnChainState": st, "txHash": f"tx-{st}"} for st in self._chain()]
            return httpx.Response(200, json={"data": data})
        if path.endswith("submit-result"):
            self.hash, self.state = body["submitResultHash"], "ResultSubmitted"
            return httpx.Response(200, json={"data": {}})
        return httpx.Response(404, json={})

    def _chain(self):
        order = ["FundsLocked", "ResultSubmitted", "Withdrawn"]
        return order[: order.index(self.state) + 1] if self.state in order else []


def test_masumi_path_with_fake_payment_service(make_client, monkeypatch):
    fake = FakeMps()
    real_init = masumi.Mps.__init__
    def init(self, base, token, network="Preprod", timeout=30.0):
        real_init(self, base, token, network, timeout)
        self.http = httpx.Client(transport=httpx.MockTransport(fake))
    monkeypatch.setattr(masumi.Mps, "__init__", init)
    c, app = make_client(mode="masumi", MPS_URL="http://mps", MPS_RUNTIME_TOKEN="t", AGENT_IDENTIFIER_LEASE_CHECK="agent-lease")
    eng = app.state.engine
    h, _ = workspace(c, "Hans", "farm", "DE")
    o = c.post("/api/orders", headers=h, json={"service": "lease_check", "input": {"source": "demo"}}).json()
    assert o["state"] == "quoted" and not o["unpaid_dev_mode"]
    p = c.post(f"/api/orders/{o['id']}/pay", headers=h).json()
    assert p["state"] == "awaiting_payment" and p["payment"]["blockchain_identifier"] == "bc-1"
    created = [b for path, b in fake.calls if path.endswith("/payment")]
    assert len(created) == 1 and created[0]["RequestedFunds"][0]["amount"] == "2000000" and created[0]["inputHash"] == o["input_hash"]
    c.post(f"/api/orders/{o['id']}/pay", headers=h)  # refresh / double click
    assert len([1 for path, _ in fake.calls if path.endswith("/payment")]) == 1, "no duplicate payment request"
    eng.tick(); time.sleep(0.2)
    assert c.get(f"/api/orders/{o['id']}", headers=h).json()["state"] == "awaiting_payment", "nothing runs before funds are locked"
    fake.state = "FundsLocked"
    eng.tick()
    st = wait_state(c, h, o["id"], {"delivered"})
    assert st["payment"]["funds_locked"] is True and st["payment"]["funds_locked_tx"] == "tx-FundsLocked"
    eng.tick()  # submit result hash
    assert fake.hash == st["result_hash"]
    st = c.get(f"/api/orders/{o['id']}", headers=h).json()
    assert st["payment"]["stage"] in ("awaiting-result-confirmation", "awaiting-withdrawal")
    eng.tick()
    st = c.get(f"/api/orders/{o['id']}", headers=h).json()
    assert st["payment"]["result_hash_confirmed"] is True and st["payment"]["seller_paid_out"] is False  # report ready != tx confirmed != seller paid
    fake.state = "Withdrawn"
    eng.tick()
    st = c.get(f"/api/orders/{o['id']}", headers=h).json()
    assert st["payment"]["seller_paid_out"] is True and st["payment"]["stage"] == "settled"


def test_unregistered_agent_blocks_payment_and_uncertain_create_freezes(make_client, monkeypatch):
    c, _ = make_client(mode="masumi", MPS_URL="http://mps", MPS_RUNTIME_TOKEN="t")
    h, _ = workspace(c, "Hans", "farm", "DE")
    o = c.post("/api/orders", headers=h, json={"service": "lease_check", "input": {"source": "demo"}}).json()
    r = c.post(f"/api/orders/{o['id']}/pay", headers=h)
    assert r.status_code == 503 and "not registered" in r.json()["detail"]
    c2, _ = make_client(mode="masumi", MPS_URL="http://mps", MPS_RUNTIME_TOKEN="t", AGENT_IDENTIFIER_LEASE_CHECK="a")
    real = masumi.Mps.__init__
    def init(self, *a, **k):
        real(self, *a, **k)
        self.http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")))
    monkeypatch.setattr(masumi.Mps, "__init__", init)
    h2, _ = workspace(c2, "H2", "farm", "DE")
    o2 = c2.post("/api/orders", headers=h2, json={"service": "lease_check", "input": {"source": "demo"}}).json()
    assert c2.post(f"/api/orders/{o2['id']}/pay", headers=h2).status_code == 502
    st = c2.get(f"/api/orders/{o2['id']}", headers=h2).json()
    assert st["state"] == "failed" and st["payment"]["stage"] == "terms-uncertain"
    assert c2.post(f"/api/orders/{o2['id']}/pay", headers=h2).json()["state"] == "failed", "no blind replay of an uncertain write"


def test_internal_routes_need_key_and_sokosumi_channel_uses_markdown_hash(make_client):
    c, _ = make_client()
    assert c.post("/internal/orders", json={}).status_code == 401
    k = {"X-Internal-Key": "internal-test-key"}
    r = c.post("/internal/orders", headers=k, json={"service": "pool_access", "country": "DE", "external_ref": "t1"})
    assert r.status_code == 422 and "website" in r.json()["detail"]
    o = c.post("/internal/orders", headers=k, json={"service": "lease_check", "country": "IN", "external_ref": "task-1", "input": {"source": "demo"}}).json()
    assert o["channel"] == "sokosumi"
    assert c.post("/internal/orders", headers=k, json={"service": "lease_check", "country": "IN", "external_ref": "task-1", "input": {"source": "demo"}}).json()["id"] == o["id"]
    c.post(f"/internal/orders/{o['id']}/pay", headers=k)
    end = time.time() + 20
    while time.time() < end:
        d = c.get(f"/internal/orders/{o['id']}", headers=k).json()
        if d["state"] == "delivered":
            break
        time.sleep(0.2)
    assert d["state"] == "delivered" and "# Lease Check" in d["markdown"] and d["hashed_text_is_markdown"] is True
    from agroland.hashing import result_hash_raw
    assert d["result_hash"] == result_hash_raw(d["markdown"], d["nonce"])
