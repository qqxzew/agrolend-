"""Masumi MIP-003 (Agentic Service API) for the paid services, served under /masumi/{service}/.

Registered in Masumi with API URL  https://<public host>/masumi/<service>  so that Sokosumi (and any Masumi buyer) can discover, hire and pay
the agent. It drives the SAME order engine as the website: same execution, same report, same price. Registration only records metadata
on-chain; this code is what actually runs.

Pool Access is a two-party service that needs each party's identity, consent and signature, so it cannot be hired as an anonymous
one-shot job. Its MIP-003 endpoints answer availability and explain that; /start_job returns 400 with the website path.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from . import auth
from .orders import Engine

NONCE = re.compile(r"^[a-fA-F0-9]{14,26}$")
SCHEMAS = {
    "land_audit": {"input_data": [
        {"id": "country", "type": "option", "name": "Country", "data": {"description": "Where the site is", "values": ["DE", "IN"]}},
        {"id": "project_type", "type": "option", "name": "Project type", "data": {"description": "Technology to assess", "values": ["solar", "wind", "hybrid"]}},
        {"id": "latitude", "type": "number", "name": "Latitude", "data": {"description": "WGS84 latitude of the site centre (use this with longitude, or give polygon_geojson)"}, "validations": [{"validation": "optional", "value": "true"}]},
        {"id": "longitude", "type": "number", "name": "Longitude", "data": {"description": "WGS84 longitude of the site centre"}, "validations": [{"validation": "optional", "value": "true"}]},
        {"id": "radius_m", "type": "number", "name": "Radius (m)", "data": {"description": "Radius around the point, 1-5000, default 300"}, "validations": [{"validation": "optional", "value": "true"}]},
        {"id": "polygon_geojson", "type": "string", "name": "Site outline (GeoJSON Polygon)", "data": {"description": "Optional. A GeoJSON Polygon in EPSG:4326 as text; replaces latitude/longitude."}, "validations": [{"validation": "optional", "value": "true"}]},
        {"id": "survey_number", "type": "string", "name": "Survey number (India, optional)", "data": {"description": "Land-record reference. Format-checked only, never verified."}, "validations": [{"validation": "optional", "value": "true"}]},
    ]},
    "lease_check": {"input_data": [
        {"id": "country", "type": "option", "name": "Country", "data": {"description": "Data, units and currency follow the country", "values": ["DE", "IN"]}},
        {"id": "source", "type": "option", "name": "Data source", "data": {"description": "'demo' uses the labelled demonstration farm; 'csv' uses the three CSV texts below", "values": ["demo", "csv"]}},
        {"id": "demo_farm", "type": "option", "name": "Demonstration farm (India)", "data": {"description": "'in' Gujarat (leases only); 'in-mh' Maharashtra: real 5am.earth field outlines on Cardano, adds satellite crop status and biomass", "values": ["in", "in-mh"]}, "validations": [{"validation": "optional", "value": "true"}]},
        {"id": "contracts_csv", "type": "string", "name": "contracts.csv", "data": {"description": "contract_id,owner,parcel_id,area_contract,rent_per_unit,start_date,end_date,payment_due"}, "validations": [{"validation": "optional", "value": "true"}]},
        {"id": "cadastre_csv", "type": "string", "name": "cadastre.csv (official record)", "data": {"description": "parcel_id,area_cadastre,land_use"}, "validations": [{"validation": "optional", "value": "true"}]},
        {"id": "fields_csv", "type": "string", "name": "fields.csv (what you farm)", "data": {"description": "field_id,parcel_id,crop"}, "validations": [{"validation": "optional", "value": "true"}]},
    ]},
    "pool_access": {"input_data": [{"id": "notice", "type": "none", "name": "Start from the AgroLand website",
                                    "data": {"description": "Pool Access needs both parties to consent and sign. Open the AgroLand app as a developer."}}]},
}
DEMOS = {
    "land_audit": {"input": {"country": "DE", "project_type": "solar", "latitude": 52.0746, "longitude": 12.7329, "radius_m": 300}, "output": "Markdown audit report: verdict, geometric signal, data quality, limits"},
    "lease_check": {"input": {"country": "IN", "source": "demo"}, "output": "Markdown lease report: identified / negotiable / achieved, findings, deadlines"},
    "pool_access": {"input": {}, "output": "Disclosure + joint plan (website only)"},
}


def build(engine: Engine, db) -> APIRouter:
    r = APIRouter(prefix="/masumi/{service}")

    def check(service: str):
        if service not in SCHEMAS:
            raise HTTPException(404, "Unknown service")

    @r.get("/availability")
    def availability(service: str):
        check(service)
        s = engine.s
        ok = bool(s.agent_identifiers.get(service)) and s.paid
        return {"status": "available" if ok else "unavailable", "type": "masumi-agent",
                "message": None if ok else "Not registered or payments disabled on this server"}

    @r.get("/input_schema")
    def input_schema(service: str):
        check(service)
        return SCHEMAS[service]

    @r.get("/demo")
    def demo(service: str):
        check(service)
        return DEMOS[service]

    @r.post("/start_job")
    def start_job(service: str, body: dict):
        check(service)
        if service == "pool_access":
            raise HTTPException(400, "Pool Access needs both parties' consent and signatures. Start it from the AgroLand website (developer workspace).")
        nonce = body.get("identifier_from_purchaser") or body.get("identifierFromPurchaser")
        data = body.get("input_data") or {}
        if not isinstance(nonce, str) or not NONCE.match(nonce):
            raise HTTPException(400, "identifier_from_purchaser must be 14-26 hex characters")
        country = data.get("country")
        if country not in ("DE", "IN"):
            raise HTTPException(400, "input_data.country must be DE or IN")
        with db.tx() as c:
            exists = c.execute("SELECT id FROM orders WHERE nonce=? AND channel='mip003'", (nonce,)).fetchone()
        if exists:  # idempotent: the same purchaser id returns the same job
            return _start_view(engine, engine.get(exists["id"]))
        if service == "land_audit":
            inp = {"project_type": data.get("project_type", "hybrid")}
            if data.get("polygon_geojson"):
                import json
                try:
                    inp["polygon"] = json.loads(data["polygon_geojson"]) if isinstance(data["polygon_geojson"], str) else data["polygon_geojson"]
                except ValueError:
                    raise HTTPException(400, "polygon_geojson is not valid JSON")
            else:
                inp.update(lat=data.get("latitude"), lon=data.get("longitude"), radius_m=data.get("radius_m", 300))
            if data.get("survey_number"):
                inp["survey_number"] = data["survey_number"]
            role = "developer"
        else:
            role = "farm"
            inp = {"source": "demo"}
            if data.get("demo_farm"):
                from . import farm
                if data["demo_farm"] not in farm.DEMOS.get(country, []):
                    raise HTTPException(400, f"demo_farm must be one of {farm.DEMOS.get(country, [])} for {country}")
                inp["demo"] = data["demo_farm"]
            if data.get("source") == "csv":
                from . import farm
                try:
                    st = farm.load_demo(country)["settings"]
                    ds = farm.build_dataset(data.get("contracts_csv", ""), data.get("cadastre_csv", ""), data.get("fields_csv", ""), st)
                except farm.DataError as exc:
                    raise HTTPException(400, str(exc))
                inp = {"source": "inline", "dataset": ds}
        u = _purchaser(db, nonce, country, role)
        try:
            o = engine.create(u, service, country, inp, channel="mip003", external_ref=nonce, nonce=nonce, hash_over=data, idem_key=f"mip003:{nonce}")
        except HTTPException as exc:
            raise HTTPException(400, exc.detail)
        return _start_view(engine, engine.get(engine.pay(o["id"], None)["id"]))

    @r.get("/status")
    def status(service: str, job_id: str):
        check(service)
        o = engine.get(job_id)
        if o["channel"] != "mip003" or o["service"] != service:
            raise HTTPException(404, "Job not found")
        engine.advance(job_id)
        o = engine.get(job_id)
        st = {"quoted": "awaiting_payment", "awaiting_payment": "awaiting_payment", "paid": "running", "waiting": "running", "running": "running",
              "delivered": "completed", "failed": "failed", "expired": "failed"}[o["state"]]
        out = {"job_id": job_id, "status": st}
        if o["state"] == "delivered":
            out["result"] = o["result"]["markdown"]
        if st == "failed":
            out["message"] = o["error"] or "payment window expired"
        return out

    return r


def _purchaser(db, nonce: str, country: str, role: str) -> dict:
    ref = f"mip003:{nonce}"
    with db.tx() as c:
        row = c.execute("SELECT * FROM users WHERE persona=?", (ref,)).fetchone()
    if row:
        return dict(row)
    user, _ = auth.create_user(db, f"Masumi buyer {nonce[:8]}", role, country, persona=ref)
    return auth.user_by_id(db, user["id"])


def _start_view(engine: Engine, o: dict) -> dict:
    p = o["payment"]
    t = p.get("terms") or {}
    if not t:
        raise HTTPException(503, "Payment request is not available (agent not registered or payments disabled on this server)")
    return {"id": o["id"], "blockchainIdentifier": t["blockchainIdentifier"], "payByTime": int(t["payByTime"]), "submitResultTime": int(t["submitResultTime"]),
            "unlockTime": int(t["unlockTime"]), "externalDisputeUnlockTime": int(t["externalDisputeUnlockTime"]), "agentIdentifier": t["agentIdentifier"],
            "sellerVKey": p.get("seller_vkey"), "identifierFromPurchaser": o["nonce"], "input_hash": o["input_hash"]}
