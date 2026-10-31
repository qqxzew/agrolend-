"""MIP-003 endpoints of the India land-audit agent: pay (Masumi Preprod, V2) -> run audit -> submit result hash."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from pydantic import ValidationError

from ..common.jobstore import JobStore
from ..registry.swaminathan import SwaminathanRegistry
from ..common.masumi import DEAD_STATES, PAID_STATES, PaymentClient, input_hash, output_hash, unix
from .config import AuditSettings
from .gis_engine import GisEngine, build_site
from .models import AuditReport, LandCheckInput
from .scoring import build_report

log = logging.getLogger("india-land-audit")


def canonical_report(report: AuditReport) -> str:
    """Stable string form of the report: sorted keys, no whitespace."""
    return json.dumps(report.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class JobService:
    def __init__(self, store: JobStore, engine: GisEngine, payment: PaymentClient, settings: AuditSettings):
        self.store, self.engine, self.payment, self.s = store, engine, payment, settings
        self._tasks: dict[str, asyncio.Task] = {}

    async def run_pipeline(self, job_id: str) -> None:
        """Run the GIS audit for a stored job, persist the report and (when paid) submit its hash."""
        job = await self.store.get(job_id)
        if job is None:
            return
        try:
            await self.store.update(job_id, status="running")
            inp = LandCheckInput.model_validate_json(job["input_json"])
            site = build_site(inp, self.s)
            gis = await self.engine.run(site)
            result = canonical_report(build_report(inp, site, gis))
            rhash = output_hash(result, job["identifier_from_purchaser"])
            await self.store.update(job_id, status="completed", result_json=result, result_hash=rhash, error=None)
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed", job_id)
            await self.store.update(job_id, status="failed", error=f"{type(e).__name__}: {e}"[:500])
            return
        await self.submit_hash(job_id)

    async def submit_hash(self, job_id: str) -> None:
        job = await self.store.get(job_id)
        if not job or self.s.bypass_payment or job["result_submitted"] or not job["blockchain_identifier"]:
            return
        try:
            await self.payment.submit_result(job["blockchain_identifier"], job["result_hash"])
            await self.store.update(job_id, result_submitted=1)
        except Exception as e:  # noqa: BLE001 - retried on the next /status poll
            log.warning("submit-result for %s failed: %s", job_id, e)
            await self.store.update(job_id, error=f"submit-result pending: {e}"[:500])

    def spawn(self, job_id: str) -> None:
        t = self._tasks.get(job_id)
        if t is None or t.done():
            self._tasks[job_id] = asyncio.create_task(self.run_pipeline(job_id))


def _service(request: Request) -> JobService:
    return request.app.state.jobs


def _view(job: dict[str, Any], extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": job["job_id"], "job_id": job["job_id"], "status": job["status"]}
    if job["result_json"]:
        out["result"] = job["result_json"]  # MIP-003: result is a string
        out["report"] = json.loads(job["result_json"])  # convenience: parsed
        out["result_hash"] = job["result_hash"]
        out["result_hash_submitted"] = bool(job["result_submitted"])
    if job["error"]:
        out["error"] = job["error"]
    out.update(extra or {})
    return out


def _input_errors(e: Exception) -> Any:
    return e.errors(include_url=False, include_context=False) if isinstance(e, ValidationError) else str(e)


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/availability")
    async def availability(request: Request):
        s = _service(request).s
        return {"status": "available", "type": "masumi-agent", "network": s.masumi_network,
                "message": "Renewable-energy land due diligence for India (wind & solar PV) - Andhra Pradesh and Gujarat"}

    @router.get("/input_schema")
    async def input_schema():
        schema = LandCheckInput.model_json_schema()
        schema["examples"] = [{"lat": 23.30, "lon": 69.50, "radius_m": 300, "project_type": "hybrid", "survey_number": "112/1"}]
        num = lambda i, n, d, lo, hi: {  # noqa: E731
            "id": i, "type": "number", "name": n, "data": {"description": d},
            "validations": [{"validation": "min", "value": str(lo)}, {"validation": "max", "value": str(hi)}],
        }
        optional = [{"validation": "optional", "value": "true"}]
        schema["input_data"] = [  # MIP-003 form description
            num("lat", "Latitude", "WGS84, India 6.0..37.5", 6.0, 37.5),
            num("lon", "Longitude", "WGS84, India 68.0..97.5", 68.0, 97.5),
            {**num("radius_m", "Radius (m)", "Analysed radius around the point, default 300", 1, 5000), "validations": optional},
            {"id": "project_type", "type": "option", "name": "Project type",
             "data": {"values": ["wind", "solar", "hybrid"], "default": "hybrid"}},
            {"id": "survey_number", "type": "string", "name": "Survey number",
             "data": {"description": "Survey / block number from the state land record (unverified)"}, "validations": optional},
            {"id": "ulpin", "type": "string", "name": "ULPIN",
             "data": {"description": "14-character Bhu-Aadhaar / ULPIN, if available"}, "validations": optional},
        ]
        return schema

    @router.post("/start_job")
    async def start_job(request: Request, body: dict[str, Any] = Body(...)):
        svc = _service(request)
        s = svc.s
        # Accept MIP-003 {identifier_from_purchaser, input_data:{...}} or a flat body.
        data = body.get("input_data") if isinstance(body.get("input_data"), dict) else {
            k: v for k, v in body.items() if k != "identifier_from_purchaser"
        }
        identifier = body.get("identifier_from_purchaser")
        try:
            inp = LandCheckInput.model_validate(data)
            build_site(inp, s)  # full geometry validation up front -> 422 instead of failed job
        except (ValidationError, ValueError) as e:
            raise HTTPException(422, detail=_input_errors(e))

        job_id = str(uuid.uuid4())
        if not identifier:
            if not s.bypass_payment:
                raise HTTPException(422, detail="identifier_from_purchaser is required (14-26 chars)")
            identifier = job_id.replace("-", "")[:20]
        if not s.bypass_payment and not (14 <= len(identifier) <= 26):
            raise HTTPException(422, detail="identifier_from_purchaser must be 14-26 characters")
        # The payment service rejects anything that is not a hex string; fail fast with a clear 422.
        if not s.bypass_payment and not all(c in "0123456789abcdefABCDEF" for c in identifier):
            raise HTTPException(422, detail="identifier_from_purchaser must be a hex string")

        job = {"job_id": job_id, "status": "awaiting_payment", "identifier_from_purchaser": identifier,
               "input_json": inp.model_dump_json()}

        if s.bypass_payment:
            await svc.store.create({**job, "status": "running"})
            await svc.run_pipeline(job_id)  # immediate, per spec
            done = await svc.store.get(job_id)
            return _view(done, {"identifierFromPurchaser": identifier, "payment": "bypassed (IN_AUDIT_BYPASS_PAYMENT=true)"})

        if not (s.agent_identifier and s.masumi_api_key):
            raise HTTPException(503, detail="IN_AUDIT_AGENT_IDENTIFIER and MASUMI_API_KEY must be set when payment is enabled")
        try:
            in_hash = input_hash(inp.model_dump(mode="json"), identifier)
            pay = await svc.payment.create(identifier, in_hash, metadata=f"india-land-audit job {job_id}")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, detail=f"payment service error: {e}")
        await svc.store.create({**job, "blockchain_identifier": pay["blockchainIdentifier"],
                                "payment_json": json.dumps(pay)})
        return {
            "id": job_id, "job_id": job_id, "status": "awaiting_payment",
            "blockchainIdentifier": pay["blockchainIdentifier"],
            "payByTime": unix(pay.get("payByTime")), "submitResultTime": unix(pay.get("submitResultTime")),
            "unlockTime": unix(pay.get("unlockTime")),
            "externalDisputeUnlockTime": unix(pay.get("externalDisputeUnlockTime")),
            "agentIdentifier": s.agent_identifier,
            "sellerVKey": (pay.get("SmartContractWallet") or {}).get("walletVkey") or pay.get("sellerVKey"),
            "identifierFromPurchaser": identifier, "input_hash": in_hash,
            "price": {"amount": s.price_tada, "unit": "tADA"},
        }

    @router.post("/internal/audit")
    async def internal_audit(request: Request, body: dict[str, Any] = Body(...), x_api_key: str = Header(default="")):
        """Unpaid audit for the platform's own agents (India matcher). Same report as a paid job; nothing goes on-chain."""
        svc = _service(request)
        if not svc.s.internal_api_key:
            raise HTTPException(503, detail="set IN_AUDIT_INTERNAL_API_KEY to enable the internal audit endpoint")
        if not hmac.compare_digest(x_api_key, svc.s.internal_api_key):
            raise HTTPException(401, detail="invalid API key")
        try:
            inp = LandCheckInput.model_validate(body)
            site = build_site(inp, svc.s)
        except (ValidationError, ValueError) as e:
            raise HTTPException(422, detail=_input_errors(e))
        gis = await svc.engine.run(site)
        return {"status": "completed", "report": json.loads(canonical_report(build_report(inp, site, gis)))}

    @router.get("/registry/verify")
    async def registry_verify(request: Request, tx_hash: str = Query(...), with_document: bool = Query(False)):
        """Check that a transaction is a 5am.earth (Project Swaminathan) registration on Cardano mainnet. Read-only, free."""
        return await SwaminathanRegistry(_service(request).engine.client).verify_tx(tx_hash, with_document)

    @router.get("/registry/records")
    async def registry_records(request: Request, limit: int = Query(10, ge=1, le=25)):
        """Latest registrations anchored by the registry (not tied to a parcel)."""
        return await SwaminathanRegistry(_service(request).engine.client).recent_records(limit)

    @router.get("/status")
    async def status(request: Request, job_id: str = Query(...)):
        svc = _service(request)
        job = await svc.store.get(job_id)
        if job is None:
            raise HTTPException(404, detail="unknown job_id")

        if job["status"] == "awaiting_payment":
            try:
                state = await svc.payment.state(job["blockchain_identifier"])
            except Exception as e:  # noqa: BLE001
                return _view(job, {"payment_state": None, "warning": f"payment status unavailable: {e}"[:300]})
            if state in DEAD_STATES:
                await svc.store.update(job_id, status="failed", error=f"payment state {state}")
                return _view(await svc.store.get(job_id), {"payment_state": state})
            if state in PAID_STATES:
                await svc.store.update(job_id, status="running")
                svc.spawn(job_id)
                return _view(await svc.store.get(job_id), {"payment_state": state})
            return _view(job, {"payment_state": state or "NotYetOnChain"})

        if job["status"] == "running":
            svc.spawn(job_id)  # no-op while the task is alive; restarts it if the worker was restarted mid-run
        if job["status"] == "completed" and not job["result_submitted"] and not svc.s.bypass_payment:
            await svc.submit_hash(job_id)
            job = await svc.store.get(job_id)
        return _view(job)

    return router
