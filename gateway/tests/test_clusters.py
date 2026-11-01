"""Land discovery and unanimous cluster consent, with real geometry and SQLite."""
import json

import pytest

from agroland.clusters import LandNetwork
from agroland.db import Database
from conftest import workspace


def site(c, headers, longitude, tech="solar", country="DE", consent=True):
    lat = 52.1 if country == "DE" else 23.35
    polygon = {"type": "Polygon", "coordinates": [[[longitude, lat], [longitude + .003, lat], [longitude + .003, lat + .003], [longitude, lat + .003], [longitude, lat]]]}
    p = c.post("/api/parcels", headers=headers, json={"source": "drawn", "label": "Private site name", "geometry": polygon}).json()
    r = c.post("/api/land/sites", headers=headers, json={"parcel_id": p["id"], "project_type": tech, "consent": consent})
    return r, p


def proposals(c, headers):
    return [x for x in c.get("/api/land/clusters", headers=headers).json() if x["status"] == "proposed"]


@pytest.mark.parametrize("country,lon", [("DE", 11.5), ("IN", 70.56)])
def test_three_participants_must_each_agree_and_private_data_stays_private(make_client, country, lon):
    c, app = make_client()
    participants = [workspace(c, f"Participant {i}", "developer", country) for i in range(3)]
    sites = [site(c, headers, lon + i * .008, country=country)[0].json() for i, (headers, _) in enumerate(participants)]
    ha, hb, hc = [x[0] for x in participants]
    proposal = proposals(c, ha)[0]
    assert proposal["participant_count"] == proposal["site_count"] == 3
    assert proposal["accepted_count"] == 0 and proposal["own_decision"] == "pending"
    mid = proposal["id"]
    for i, headers in enumerate([ha, hb, hc]):
        result = c.post(f"/api/land/clusters/{mid}/decision", headers=headers, json={"decision": "accept", "user_id": participants[-1][1]["id"]}).json()
        assert result["accepted_count"] == i + 1
        assert result["status"] == ("agreed" if i == 2 else "proposed")
    directory = c.get("/api/land/sites", headers=ha).json()
    foreign = [s for s in directory if not s["own"]]
    assert len(foreign) == 2
    for record in foreign:
        assert not {"geometry", "parcel_id", "user_id", "consent_at"} & record.keys()
        assert "Private site name" not in json.dumps(record)
    assert "geometry" not in json.dumps(proposal) and "user_id" not in json.dumps(proposal)
    outsider, _ = workspace(c, "Outsider", "developer", country)
    assert c.get("/api/land/clusters", headers=outsider).json() == []
    assert c.post(f"/api/land/clusters/{mid}/decision", headers=outsider, json={"decision": "accept"}).status_code == 404
    # Joining a directory or agreeing to a cluster must never create a paid order.
    assert all(c.get("/api/orders", headers=headers).json() == [] for headers in [ha, hb, hc])
    # Consent and the exact membership survive opening the database again.
    reopened = LandNetwork(Database(app.state.settings.state_dir))
    assert reopened.cluster(participants[0][1], mid)["status"] == "agreed"
    assert set(s["id"] for s in sites).issubset({m["site_id"] for m in result["members"]})


def test_registration_requires_explicit_consent_and_is_idempotent(make_client):
    c, _ = make_client()
    h, _ = workspace(c, "Developer", "developer", "DE")
    rejected, parcel = site(c, h, 11.5, consent=False)
    assert rejected.status_code == 422 and c.get("/api/land/sites", headers=h).json() == []
    for invalid in (None, 1, "true"):
        assert c.post("/api/land/sites", headers=h, json={"parcel_id": parcel["id"], "project_type": "solar", "consent": invalid}).status_code == 422
    body = {"parcel_id": parcel["id"], "project_type": "solar", "consent": True}
    a = c.post("/api/land/sites", headers=h, json=body).json()
    b = c.post("/api/land/sites", headers=h, json=body).json()
    assert a["id"] == b["id"] and a["consent_at"] == b["consent_at"]
    assert len(c.get("/api/land/sites", headers=h).json()) == 1
    other, _ = workspace(c, "Other developer", "developer", "DE")
    assert c.post("/api/land/sites", headers=other, json=body).status_code == 404
    owner, _ = workspace(c, "Owner", "owner", "DE")
    assert c.get("/api/land/sites", headers=owner).status_code == 403
    assert c.delete(f"/api/parcels/{parcel['id']}", headers=h).status_code == 409


def test_country_technology_and_distance_filters_are_real(make_client):
    c, _ = make_client()
    ha, _ = workspace(c, "Solar", "developer", "DE")
    hb, _ = workspace(c, "Wind", "developer", "DE")
    hc, _ = workspace(c, "Distant solar", "developer", "DE")
    hi, _ = workspace(c, "India", "developer", "IN")
    site(c, ha, 11.5)
    site(c, hb, 11.508, tech="wind")
    site(c, hc, 12.5)
    site(c, hi, 70.56, country="IN")
    assert proposals(c, ha) == []
    assert len(c.get("/api/land/sites?project_type=solar", headers=ha).json()) == 2
    assert len(c.get("/api/land/sites?project_type=wind", headers=ha).json()) == 1
    assert len(c.get("/api/land/sites", headers=hi).json()) == 1
    assert c.get("/api/land/sites?region=missing", headers=ha).json() == []
    assert c.get("/api/land/sites?min_area_ha=1000", headers=ha).json() == []
    assert c.get("/api/land/sites?min_area_ha=-1", headers=ha).status_code == 422


def test_new_members_need_new_consent_without_expanding_an_existing_agreement(make_client):
    c, _ = make_client()
    participants = [workspace(c, f"Developer {i}", "developer", "DE")[0] for i in range(3)]
    site(c, participants[0], 11.5)
    site(c, participants[1], 11.508)
    first = proposals(c, participants[0])[0]["id"]
    for headers in participants[:2]:
        c.post(f"/api/land/clusters/{first}/decision", headers=headers, json={"decision": "accept"})
    site(c, participants[2], 11.516)
    all_clusters = c.get("/api/land/clusters", headers=participants[0]).json()
    original = next(x for x in all_clusters if x["id"] == first)
    new = next(x for x in all_clusters if x["status"] == "proposed")
    assert original["status"] == "agreed" and original["site_count"] == 2
    assert new["site_count"] == 3 and new["accepted_count"] == 0
    assert all(m["decision"] == "pending" for m in new["members"])


def test_withdrawal_cancels_agreements_and_reproposal_resets_all_decisions(make_client):
    c, _ = make_client()
    headers = [workspace(c, f"Developer {i}", "developer", "DE")[0] for i in range(3)]
    for i in range(2):
        site(c, headers[i], 11.5 + i * .008)
    pair = proposals(c, headers[0])[0]
    c.post(f"/api/land/clusters/{pair['id']}/decision", headers=headers[0], json={"decision": "accept"})
    third, _ = site(c, headers[2], 11.516)
    triple = proposals(c, headers[0])[0]
    for h in headers:
        c.post(f"/api/land/clusters/{triple['id']}/decision", headers=h, json={"decision": "accept"})
    sid = third.json()["id"]
    assert c.delete(f"/api/land/sites/{sid}", headers=headers[0]).status_code == 404
    assert c.delete(f"/api/land/sites/{sid}", headers=headers[2]).status_code == 204
    states = c.get("/api/land/clusters", headers=headers[0]).json()
    assert next(x for x in states if x["id"] == triple["id"])["status"] == "cancelled"
    replacement = proposals(c, headers[0])[0]
    assert replacement["site_count"] == 2 and replacement["accepted_count"] == 0
    assert all(m["decided_at"] is None for m in replacement["members"])
    assert all(s["id"] != sid for s in c.get("/api/land/sites", headers=headers[0]).json())


def test_one_participant_cannot_approve_for_another_and_decline_ends_the_proposal(make_client):
    c, _ = make_client()
    ha, _ = workspace(c, "First", "developer", "DE")
    hb, _ = workspace(c, "Second", "developer", "DE")
    site(c, ha, 11.5)
    site(c, ha, 11.504)
    site(c, hb, 11.512)
    cluster = proposals(c, ha)[0]
    assert cluster["site_count"] == 3 and cluster["participant_count"] == 2
    agreed = c.post(f"/api/land/clusters/{cluster['id']}/decision", headers=ha, json={"decision": "accept"}).json()
    assert agreed["accepted_count"] == 1 and agreed["status"] == "proposed"
    declined = c.post(f"/api/land/clusters/{cluster['id']}/decision", headers=hb, json={"decision": "decline"}).json()
    assert declined["status"] == "declined"
    assert c.post(f"/api/land/clusters/{cluster['id']}/decision", headers=ha, json={"decision": "accept"}).status_code == 409
