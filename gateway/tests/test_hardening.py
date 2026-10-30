import time

from conftest import workspace


def test_session_creation_is_rate_limited(make_client):
    c, _ = make_client(AGROLAND_RATE_SESSIONS_PER_HOUR="3")
    for i in range(3):
        assert c.post("/api/session", json={"name": f"User {i}", "role": "owner", "country": "DE"}).status_code == 201
    r = c.post("/api/session", json={"name": "User X", "role": "owner", "country": "DE"})
    assert r.status_code == 429 and r.headers["retry-after"]


def test_order_creation_is_rate_limited_per_workspace(make_client):
    c, _ = make_client(AGROLAND_RATE_ORDERS_PER_HOUR="2")
    h, _ = workspace(c, "Farm A", "farm", "DE")
    h2, _ = workspace(c, "Farm B", "farm", "DE")
    body = {"service": "lease_check", "input": {"source": "demo"}}
    assert [c.post("/api/orders", headers=h, json=body).status_code for _ in range(3)] == [201, 201, 429]
    assert c.post("/api/orders", headers=h2, json=body).status_code == 201, "another workspace is not affected"


def test_oversized_body_and_csv_rejected(make_client):
    c, _ = make_client()
    h, _ = workspace(c, "Farm A", "farm", "DE")
    r = c.post("/api/session", content=b"x", headers={"content-length": str(50 * 1024 * 1024), "content-type": "application/json"})
    assert r.status_code == 413
    big = "contract_id\n" + "a" * 1_100_000
    assert c.put("/api/farm/dataset", headers=h, json={"contracts_csv": big, "cadastre_csv": "", "fields_csv": ""}).status_code in (413, 422)


def test_parcel_cap(make_client, monkeypatch):
    from agroland import parcels
    monkeypatch.setattr(parcels, "MAX_PER_USER", 2)
    c, _ = make_client()
    h, _ = workspace(c, "Dev A", "developer", "IN")
    sq = lambda i: {"source": "drawn", "label": f"s{i}", "ref": f"r{i}", "geometry": {"type": "Polygon", "coordinates": [[[70.5 + i * .01, 23.3], [70.51 + i * .01, 23.3], [70.51 + i * .01, 23.31], [70.5 + i * .01, 23.3]]]}}
    assert [c.post("/api/parcels", headers=h, json=sq(i)).status_code for i in range(3)] == [201, 201, 409]


def test_security_headers_and_csp_on_pages_not_api(make_client):
    c, _ = make_client()
    page = c.get("/")
    assert page.status_code == 200 and "script-src 'self'" in page.headers["content-security-policy"] and page.headers["x-frame-options"] == "DENY"
    assert "<script>" not in page.text, "no inline scripts: the CSP forbids them"
    assert "content-security-policy" not in c.get("/api/config").headers
    assert c.get("/api/config").headers["cache-control"] == "no-store"


def test_cross_origin_writes_blocked(make_client):
    c, _ = make_client()
    r = c.post("/api/session", json={"name": "Evil Co", "role": "owner", "country": "DE"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_orders_survive_a_restart_and_resume(make_client, monkeypatch):
    """A second app on the same state directory (a restart) picks up an order that was waiting for payment and finishes it."""
    import httpx
    from agroland import masumi
    from test_orders import FakeMps
    fake = FakeMps()
    real = masumi.Mps.__init__
    def init(self, base, token, network="Preprod", timeout=30.0):
        real(self, base, token, network, timeout)
        self.http = httpx.Client(transport=httpx.MockTransport(fake))
    monkeypatch.setattr(masumi.Mps, "__init__", init)
    env = dict(mode="masumi", MPS_URL="http://mps", MPS_RUNTIME_TOKEN="t", AGENT_IDENTIFIER_LEASE_CHECK="agent-lease")
    c1, app1 = make_client(**env)
    h, _ = workspace(c1, "Hans", "farm", "DE")
    o = c1.post("/api/orders", headers=h, json={"service": "lease_check", "input": {"source": "demo"}}).json()
    c1.post(f"/api/orders/{o['id']}/pay", headers=h)
    app1.state.engine.stop()
    n_requests = len([1 for p, _ in fake.calls if p.endswith("/payment")])
    c2, app2 = make_client(**env)  # same state dir (the fixture reuses tmp_path)
    fake.state = "FundsLocked"
    end = time.time() + 20
    while time.time() < end:
        app2.state.engine.tick()
        st = c2.get(f"/api/orders/{o['id']}", headers=h).json()
        if st["state"] == "delivered":
            break
        time.sleep(0.3)
    assert st["state"] == "delivered" and st["payment"]["funds_locked"]
    assert len([1 for p, _ in fake.calls if p.endswith("/payment")]) == n_requests, "the restart must not create another payment request"
