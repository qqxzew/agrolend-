"""HTTP client for the internal geo services (audit / matcher / escrow / architect) of one country pack.

The geo services are internal: they bind to loopback, run with payment bypass ON (money is handled only by the gateway's orders) and are
protected by shared keys. Their MIP-003 /start_job endpoints are not exposed to users.
"""
from __future__ import annotations

import httpx
from fastapi import HTTPException

from .settings import GeoStack

BBOX = {"DE": (47.2, 55.1, 5.8, 15.1), "IN": (6.0, 37.5, 68.0, 97.5)}


class GeoUnavailable(RuntimeError):
    """An internal geo service did not answer. Orders treat this as an execution error (retry, then fail without delivery)."""


def in_country(country: str, lat: float, lon: float) -> bool:
    la0, la1, lo0, lo1 = BBOX[country]
    return la0 <= lat <= la1 and lo0 <= lon <= lo1


class Geo:
    def __init__(self, stack: GeoStack, timeout: float = 300.0):
        self.s = stack
        self.http = httpx.Client(timeout=timeout)

    def _call(self, method: str, url: str, key: str, **kw):
        headers = {"X-API-Key": key} if key else {}
        try:
            r = self.http.request(method, url, headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise GeoUnavailable(f"{type(exc).__name__} calling {url.split('/')[2]}") from exc
        if r.status_code >= 500:
            raise GeoUnavailable(f"HTTP {r.status_code} from {url.split('/')[2]}")
        return r

    def audit(self, body: dict) -> dict:
        r = self._call("POST", f"{self.s.audit_url}/internal/audit", self.s.audit_key, json=body)
        if r.status_code == 422:
            raise HTTPException(422, f"Site rejected by the auditor: {str(r.json().get('detail'))[:300]}")
        if r.status_code >= 400:
            raise GeoUnavailable(f"audit HTTP {r.status_code}")
        return r.json()["report"]

    # --- matcher
    def register_parcel(self, developer_id: str, body: dict) -> tuple[int, dict]:
        r = self._call("POST", f"{self.s.matcher_url}/register_parcel", self.s.matcher_key, json={"developer_id": developer_id, **body})
        return r.status_code, r.json()

    def teasers(self, developer_id: str) -> list[dict]:
        r = self._call("GET", f"{self.s.matcher_url}/teasers", self.s.matcher_key, params={"developer_id": developer_id})
        r.raise_for_status()
        j = r.json()
        return j if isinstance(j, list) else j.get("teasers", [])

    def parcels(self, developer_id: str) -> list[dict]:
        r = self._call("GET", f"{self.s.matcher_url}/parcels", self.s.matcher_key, params={"developer_id": developer_id})
        r.raise_for_status()
        j = r.json()
        return j if isinstance(j, list) else j.get("parcels", [])

    def withdraw_parcel(self, developer_id: str, pid: str) -> None:
        self._call("DELETE", f"{self.s.matcher_url}/parcels/{pid}", self.s.matcher_key, params={"developer_id": developer_id})

    # --- escrow
    def put_profile(self, developer_id: str, profile: dict) -> dict:
        r = self._call("PUT", f"{self.s.escrow_url}/developers/{developer_id}/profile", self.s.escrow_key, json=profile)
        return {"status": r.status_code, "body": r.json()}

    def deals(self, developer_id: str) -> list[dict]:
        r = self._call("GET", f"{self.s.escrow_url}/deals", self.s.escrow_key, params={"developer_id": developer_id})
        r.raise_for_status()
        j = r.json()
        return j if isinstance(j, list) else j.get("deals", [])

    def deal(self, match_id: str, developer_id: str) -> tuple[int, dict]:
        r = self._call("GET", f"{self.s.escrow_url}/deals/{match_id}", self.s.escrow_key, params={"developer_id": developer_id})
        return r.status_code, r.json()

    def consent(self, match_id: str, developer_id: str, decision: str) -> tuple[int, dict]:
        r = self._call("POST", f"{self.s.escrow_url}/deals/{match_id}/consent", self.s.escrow_key, json={"developer_id": developer_id, "decision": decision})
        return r.status_code, r.json()

    def nda_pdf(self, match_id: str, developer_id: str) -> bytes:
        r = self._call("GET", f"{self.s.escrow_url}/deals/{match_id}/nda.pdf", self.s.escrow_key, params={"developer_id": developer_id})
        if r.status_code != 200:
            raise HTTPException(r.status_code, str(r.text)[:300])
        return r.content

    def sign(self, match_id: str, body: dict) -> tuple[int, dict]:
        r = self._call("POST", f"{self.s.escrow_url}/deals/{match_id}/sign", self.s.escrow_key, json=body)
        return r.status_code, r.json()

    def reveal(self, match_id: str, developer_id: str) -> tuple[int, dict]:
        r = self._call("GET", f"{self.s.escrow_url}/deals/{match_id}/reveal", self.s.escrow_key, params={"developer_id": developer_id})
        return r.status_code, r.json()

    # --- architect
    def compute_pool(self, match_id: str, developer_id: str, method: str = "shapley", assumptions: dict | None = None) -> dict:
        r = self._call("POST", f"{self.s.architect_url}/pools/{match_id}", self.s.architect_key,
                       json={"developer_id": developer_id, "method": method, "assumptions": assumptions or {}})
        if r.status_code >= 400:
            raise GeoUnavailable(f"architect HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def pool_pdf(self, match_id: str, developer_id: str, kind: str) -> bytes:
        r = self._call("GET", f"{self.s.architect_url}/pools/{match_id}/{kind}.pdf", self.s.architect_key, params={"developer_id": developer_id})
        if r.status_code != 200:
            raise HTTPException(r.status_code, str(r.text)[:300])
        return r.content

    def match_parties(self, match_id: str) -> list[str]:
        """Developer ids of both sides of a match (internal, un-anonymised)."""
        r = self._call("GET", f"{self.s.matcher_url}/internal/matches/{match_id}", self.s.matcher_key)
        if r.status_code != 200:
            return []
        return sorted({p["developer_id"] for p in r.json()["parcels"]})
