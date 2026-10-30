"""MIP-003 surface used by Masumi buyers / the Sokosumi marketplace. The payment service is a TESTING mock."""
import time

import httpx

from agroland import masumi
from agroland.hashing import input_hash, result_hash_mip004
from test_orders import FakeMps


def setup(make_client, monkeypatch, **env):
    fake = FakeMps()
    real = masumi.Mps.__init__
    def init(self, base, token, network="Preprod", timeout=30.0):
        real(self, base, token, network, timeout)
        self.http = httpx.Client(transport=httpx.MockTransport(fake))
    monkeypatch.setattr(masumi.Mps, "__init__", init)
    c, app = make_client(mode="masumi", MPS_URL="http://mps", MPS_RUNTIME_TOKEN="t", AGENT_IDENTIFIER_LEASE_CHECK="agent-lease", **env)
    return c, app, fake


def test_schema_availability_and_pool_access_boundary(make_client, monkeypatch):
    c, app, fake = setup(make_client, monkeypatch)
    assert c.get("/masumi/lease_check/availability").json() == {"status": "available", "type": "masumi-agent", "message": None}
    assert c.get("/masumi/land_audit/availability").json()["status"] == "unavailable"  # not registered here
    ids = [f["id"] for f in c.get("/masumi/land_audit/input_schema").json()["input_data"]]
    assert len(ids) == len(set(ids)) and "project_type" in ids
    assert c.get("/masumi/lease_check/demo").json()["input"]["country"] == "IN"
    r = c.post("/masumi/pool_access/start_job", json={"identifier_from_purchaser": "ab" * 10, "input_data": {}})
    assert r.status_code == 400 and "website" in r.json()["detail"]
    assert c.get("/masumi/nope/availability").status_code == 404


def test_start_job_pay_deliver_and_hash_rules(make_client, monkeypatch):
    c, app, fake = setup(make_client, monkeypatch)
    nonce = "0123456789abcdef0123"
    data = {"country": "IN", "source": "demo"}
    assert c.post("/masumi/lease_check/start_job", json={"identifier_from_purchaser": "xyz", "input_data": data}).status_code == 400
    r = c.post("/masumi/lease_check/start_job", json={"identifier_from_purchaser": nonce, "input_data": data})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["blockchainIdentifier"] == "bc-1" and j["agentIdentifier"] == "agent-lease" and j["identifierFromPurchaser"] == nonce
    assert j["input_hash"] == input_hash(data, nonce), "MIP-004: hash over the buyer's RAW input and identifier"
    assert c.post("/masumi/lease_check/start_job", json={"identifier_from_purchaser": nonce, "input_data": data}).json()["id"] == j["id"], "idempotent"
    assert c.get("/masumi/lease_check/status", params={"job_id": j["id"]}).json()["status"] == "awaiting_payment"
    fake.state = "FundsLocked"
    end = time.time() + 20
    while time.time() < end:
        app.state.engine.tick()
        s = c.get("/masumi/lease_check/status", params={"job_id": j["id"]}).json()
        if s["status"] == "completed":
            break
        time.sleep(0.3)
    assert s["status"] == "completed" and "# Lease Check" in s["result"] and "₹" in s["result"]
    app.state.engine.tick()
    assert fake.hash == result_hash_mip004(s["result"], nonce), "the submitted on-chain hash covers exactly the delivered text"
    assert c.get("/masumi/land_audit/status", params={"job_id": j["id"]}).status_code == 404  # wrong service
