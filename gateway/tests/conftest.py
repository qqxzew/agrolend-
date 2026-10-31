import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["AGROLAND_NO_AUTOAPP"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from agroland.main import create_app  # noqa: E402
from agroland.settings import get_settings  # noqa: E402


def wait_state(client, headers, oid, states, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        o = client.get(f"/api/orders/{oid}", headers=headers).json()
        if o["state"] in states:
            return o
        time.sleep(0.2)
    raise AssertionError(f"order {oid} stuck in {o['state']}: {o.get('events', [])[-3:]}")


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    clients = []

    def _make(**env):
        monkeypatch.setenv("AGROLAND_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("AGROLAND_PAYMENT_MODE", env.pop("mode", "dev-unpaid"))
        monkeypatch.setenv("AGROLAND_INTERNAL_KEY", "internal-test-key")
        monkeypatch.setenv("AGROLAND_CROPWATCH", env.pop("cropwatch", "off"))  # tests stay offline; test_cropwatch.py uses recorded responses
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        app = create_app(get_settings())
        c = TestClient(app, base_url="http://testserver")
        c.__enter__()
        clients.append(c)
        return c, app
    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def workspace(c, name, role, country):
    r = c.post("/api/session", json={"name": name, "role": role, "country": country})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user"]
