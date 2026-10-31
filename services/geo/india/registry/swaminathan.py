"""Read-only client for the 5am.earth "Project Swaminathan" farm registry on Cardano mainnet.

What is verified (Koios tx_info / datum_info of real mainnet transactions): every registration is a transaction spent
from the registry address that pays ONE token (policy `POLICY_ID`, asset name `ASSET_NAME_HEX`) to a
script address, with a datum hash. The datum is a list: [ref_1, ref_2, agent_code, value_1, document_uri, value_2,
constr]; ref_2 equals the document's farm_id. There is NO transaction metadata. `value_1` equals the polygon area in m2 (checked on 64 documents, ratio 0.996); `value_2` is -20..100 with unknown meaning. `document_uri` names an IPFS JSON
document: a list of {farm_boundaries_id, farm_id, Polygon coordinates, center_point, bounds, status, timestamps}. It holds
field BOUNDARIES only; no crop, biomass or sustainability data was present in the documents inspected. Nothing here is fabricated: when a source is unreachable the answer says so.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

import httpx

REGISTRY_ADDRESS = "addr1q85m2c3neffh4d4np9hgsm622naa97ujkjem75kcu8n3c25rc9kn6q6sl4uj0ymn3xu3gxffn7gna6z32952k0axuhwsn9aj4t"
POLICY_ID = "c4f37d2bc1a955cfdc33597b3c089179ebeffdc624bbcf05b33950ef"
# The on-chain asset name is the ASCII text "676c6f62616c2d6661726d" (hex of "global-farm", stored as text), seen on mainnet.
ASSET_NAME_HEX = "36373663366636323631366332643636363137323664"
KOIOS_URL = "https://api.koios.rest/api/v1"
IPFS_GATEWAYS = ["https://c-ipfs-gw.nmkr.io/ipfs", "https://dweb.link/ipfs", "https://w3s.link/ipfs", "https://4everland.io/ipfs", "https://ipfs.io/ipfs"]
# Public gateways answer 429 to bare clients; the NMKR gateway (a registry technical partner) served both documents seen live.
USER_AGENT = "Mozilla/5.0 (compatible; AgroLand/0.1; +registry-verifier)"
_TX = re.compile(r"^[0-9a-f]{64}$")
_CID = re.compile(r"^(Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7]{50,})$")

# Approximate bounding boxes (lat_min, lat_max, lon_min, lon_max) of where registrations were actually observed on
# mainnet (64 of the latest 1000 documents sampled, Oct 2026): around Amravati/Katol and around 19N 75E (Maharashtra).
# The May 2026 proposal listed only six Amravati-area locations, so the registry has grown beyond them. Screening boxes
# derived from data, NOT administrative boundaries; re-derive when the registry grows.
DEFAULT_BBOXES = ((20.5, 21.7, 76.7, 78.7), (18.7, 19.4, 74.6, 75.3))


def in_coverage(lat: float, lon: float, state_code: Optional[str], bboxes=DEFAULT_BBOXES) -> bool:
    return state_code in (None, "IN-MH") and any(la0 <= lat <= la1 and lo0 <= lon <= lo1 for la0, la1, lo0, lo1 in bboxes)


def _text(item: dict) -> Any:
    if "bytes" in item:
        raw = bytes.fromhex(item["bytes"])
        return raw.decode("utf-8") if raw and raw.isascii() else raw.hex()
    return item.get("int", item)


def decode_farm_datum(value: dict) -> Optional[dict]:
    """Decode the 7-field datum seen on mainnet. Field meanings beyond the URI are NOT documented, so names are neutral."""
    items = (value or {}).get("list")
    if not isinstance(items, list) or len(items) != 7:
        return None
    ref_1, ref_2, agent, v1, uri, v2, _tail = (_text(i) for i in items)
    out = {"ref_1": ref_1, "ref_2": ref_2, "agent_code": agent, "value_1": v1, "value_2": v2, "document_uri": uri}
    cid = uri[len("ipfs://"):] if isinstance(uri, str) and uri.startswith("ipfs://") else None
    out["document_cid"] = cid if cid and _CID.match(cid) else None
    return out


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _varint(n: int) -> bytes:
    out = b""
    while True:
        c, n = n & 0x7F, n >> 7
        out += bytes([c | (0x80 if n else 0)])
        if not n:
            return out


def cid_v0_of(data: bytes) -> str:
    """CIDv0 of a file that fits one UnixFS block (<= 256 KiB): sha256 multihash of the dag-pb wrapper, base58."""
    uf = b"\x08\x02" + b"\x12" + _varint(len(data)) + data + b"\x18" + _varint(len(data))
    raw = b"\x12\x20" + hashlib.sha256(b"\x0a" + _varint(len(uf)) + uf).digest()
    n, s = int.from_bytes(raw, "big"), ""
    while n:
        n, r = divmod(n, 58)
        s = _B58[r] + s
    return s


def parse_document(content: Any) -> list[dict]:
    """Farm-boundary records of a registry document; entries with an unexpected shape are skipped, not guessed."""
    out = []
    for r in content if isinstance(content, list) else []:
        g = r.get("coordinates") if isinstance(r, dict) else None
        if isinstance(g, dict) and g.get("type") == "Polygon" and g.get("coordinates"):
            out.append({"farm_id": r.get("farm_id"), "farm_boundaries_id": r.get("farm_boundaries_id"), "status": r.get("status"),
                        "center_point": r.get("center_point"), "bounds": r.get("coordinate_bounds"),
                        "created_at": r.get("created_at"), "updated_at": r.get("updated_at"), "geometry": g})
    return out


def parcel_overlap(parcel_geojson: dict, farms: list[dict]) -> list[dict]:
    """Registry farms whose boundary intersects the parcel (WGS84 planar overlap share of the PARCEL; screening only)."""
    from shapely.geometry import shape

    p = shape(parcel_geojson)
    res = []
    for f in farms:
        inter = p.intersection(shape(f["geometry"]))
        if not inter.is_empty and p.area > 0:
            res.append({"farm_id": f["farm_id"], "share_of_parcel": round(inter.area / p.area, 4)})
    return res


def local_fingerprint(wkt_or_geojson: Any) -> str:
    """SHA-256 of a canonical JSON/WKT string. This is a LOCAL fingerprint, not an AgStack Geo Id (their API needs a key)."""
    s = wkt_or_geojson if isinstance(wkt_or_geojson, str) else json.dumps(wkt_or_geojson, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode()).hexdigest()


class SwaminathanRegistry:
    def __init__(self, client: httpx.AsyncClient, koios_url: str = KOIOS_URL, gateways: Optional[list[str]] = None):
        self.c, self.koios, self.gateways = client, koios_url.rstrip("/"), gateways or IPFS_GATEWAYS

    async def _post(self, path: str, body: dict) -> Any:
        r = await self.c.post(f"{self.koios}/{path}", json=body, headers={"accept": "application/json"})
        r.raise_for_status()
        return r.json()

    async def fetch_document(self, cid: str) -> dict:
        """Try each gateway (with a User-Agent). Returns the parsed farm records and whether the bytes hash to the CID."""
        if not _CID.match(cid):
            return {"status": "unavailable", "reason": "invalid CID"}
        last = "no gateway answered"
        for g in self.gateways:
            try:
                r = await self.c.get(f"{g}/{cid}", timeout=20.0, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/json,*/*"})
            except httpx.HTTPError as e:
                last = f"{g} {type(e).__name__}"
                continue
            if r.status_code != 200 or len(r.content) > 2_000_000:
                last = f"{g} HTTP {r.status_code}"
                continue
            try:
                farms = parse_document(r.json())
            except ValueError:
                farms = []
            # CIDv0 is the sha256 multihash of the content: a match proves the bytes are the ones the registry anchored.
            # Only checkable for single-block files (<= 256 KiB) and CIDv0.
            checkable = cid.startswith("Qm") and len(r.content) <= 262144
            return {"status": "ok", "gateway": g, "size": len(r.content), "farms": farms,
                    "cid_verified": (cid_v0_of(r.content) == cid) if checkable else None}
        return {"status": "unavailable", "reason": last}

    async def verify_tx(self, tx_hash: str, with_document: bool = False) -> dict:
        h = (tx_hash or "").strip().lower()
        if not _TX.match(h):
            return {"verified": False, "error": "tx_hash must be 64 hex characters"}
        try:
            info = await self._post("tx_info", {"_tx_hashes": [h], "_inputs": True, "_metadata": True, "_assets": True,
                                                "_withdrawals": False, "_certs": False, "_scripts": False, "_bytecode": False})
        except httpx.HTTPError as e:
            return {"verified": False, "tx_hash": h, "error": f"Koios unreachable: {type(e).__name__}"}
        if not info:
            return {"verified": False, "tx_hash": h, "error": "transaction not found on mainnet"}
        tx = info[0]
        from_registry = any((i.get("payment_addr") or {}).get("bech32") == REGISTRY_ADDRESS for i in tx.get("inputs") or [])
        farm_out = next((o for o in tx.get("outputs") or []
                         for a in o.get("asset_list") or []
                         if a.get("policy_id") == POLICY_ID and a.get("asset_name") == ASSET_NAME_HEX), None)
        res: dict[str, Any] = {"tx_hash": h, "network": "Cardano mainnet", "block_time": tx.get("tx_timestamp"),
                               "checks": {"spent_from_registry_address": from_registry, "pays_farm_token": farm_out is not None,
                                          "has_transaction_metadata": bool(tx.get("metadata"))},
                               "record": None}
        res["verified"] = from_registry and farm_out is not None
        if farm_out and farm_out.get("datum_hash"):
            try:
                d = await self._post("datum_info", {"_datum_hashes": [farm_out["datum_hash"]]})
                rec = decode_farm_datum(d[0]["value"]) if d else None
            except (httpx.HTTPError, KeyError, IndexError):
                rec = None
            res["record"] = rec
            res["checks"]["datum_decoded"] = rec is not None
            if rec and rec["document_cid"] and with_document:
                res["document"] = await self.fetch_document(rec["document_cid"])
        res["limits"] = ["The anchor proves the registry address issued this record, not that the farm data is correct.",
                         "The farm document is not hash-bound in the datum; its IPFS CID is the only link."]
        return res

    async def recent_records(self, limit: int = 10) -> dict:
        limit = max(1, min(limit, 25))
        try:
            txs = await self._post("address_txs", {"_addresses": [REGISTRY_ADDRESS]})
        except httpx.HTTPError as e:
            return {"status": "unavailable", "reason": f"Koios unreachable: {type(e).__name__}", "records": []}
        out = []
        for t in txs[:limit]:
            v = await self.verify_tx(t["tx_hash"])
            if v.get("verified"):
                out.append({"tx_hash": v["tx_hash"], "block_time": v["block_time"], "record": v["record"]})
        return {"status": "ok", "records": out, "note": "latest registrations, not tied to any particular parcel"}


def report_context(lat: float, lon: float, state_code: Optional[str]) -> Optional[dict]:
    """Section for the audit report. None outside the registry's working area (no section, no claims)."""
    if not in_coverage(lat, lon, state_code):
        return None
    return {
        "registry": "5am.earth Project Swaminathan (Cardano mainnet)",
        "inside_working_area": True,
        "area_basis": "approximate boxes around the areas where registrations were observed (Amravati/Katol and about 19N 75E, Maharashtra); not administrative boundaries",
        "parcel_match": "not performed",
        "reason": "boundaries are public per registration (IPFS document named in the on-chain datum) but there is no spatial index "
                  "to search by location, and the documents carry no crop data. Use /registry/verify with a registration "
                  "transaction to check an anchor and read its boundary.",
        "address": REGISTRY_ADDRESS,
        "policy_id": POLICY_ID,
        "note": "Registry data is third-party and unverified by AgroLand; it does not establish land title.",
    }
