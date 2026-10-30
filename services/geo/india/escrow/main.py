"""India Agent 3 (Escrow & NDA): `uvicorn india.escrow.main:app --port 9002`.

Consent of both developers -> Masumi deposits (one payment each) -> English mutual NDA (Indian law) as PDF ->
electronic acceptance by both -> release of contacts and parcel boundaries -> result hash to Masumi.
"""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Literal, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .config import EscrowSettings, get_escrow_settings
from .service import DealError, DealService
from .store import EscrowStore

log = logging.getLogger("india-escrow")
DEV_ID = Field(min_length=3, max_length=64, pattern=r"^[\w.@:-]+$")


class Profile(BaseModel):
    """Contracting-party data printed in the NDA; e-mail/phone are only shown to the counterpart after signing."""
    company_name: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=5, max_length=200, description="Registered office, street and city")
    state: str = Field(min_length=2, max_length=60)
    pin_code: str = Field(pattern=r"^[1-9]\d{5}$", description="6-digit PIN code")
    representative: str = Field(min_length=3, max_length=160,
                                description="Authorised signatory with designation, e.g. 'Anita Rao, Director'")
    registration_no: str = Field("", max_length=60, description="CIN (companies) or LLPIN (LLPs)")
    gstin: str = Field("", max_length=15, pattern=r"^([0-9]{2}[A-Z0-9]{13})?$", description="15-character GSTIN, optional")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=160)
    phone: str = Field("", max_length=40)


class ConsentBody(BaseModel):
    developer_id: str = DEV_ID
    decision: Literal["accept", "decline"]


class SignBody(BaseModel):
    developer_id: str = DEV_ID
    signer_name: str = Field(min_length=3, max_length=120)
    signer_role: str = Field(min_length=2, max_length=120, description="e.g. 'Director'")
    document_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$", description="Hash of the NDA PDF that was shown to the signer")
    accept: Literal[True] = Field(description="Must be true: the signer accepts the NDA on behalf of the company")
    signer_ip: Optional[str] = Field(None, max_length=64)


def create_app(settings: Optional[EscrowSettings] = None, service: Optional[DealService] = None,
               transport: Optional[httpx.AsyncBaseTransport] = None) -> FastAPI:
    s = settings or get_escrow_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(transport=transport) as client:
            app.state.deals = service or DealService(EscrowStore(s.escrow_database_path), client, s)
            if not s.escrow_api_key:
                log.warning("IN_ESCROW_API_KEY is empty: authentication disabled (dev only)")
            if not s.escrow_bypass_payment and not (s.escrow_agent_identifier and s.masumi_api_key):
                log.error("IN_ESCROW_BYPASS_PAYMENT=false needs IN_ESCROW_AGENT_IDENTIFIER and MASUMI_API_KEY")
            yield

    app = FastAPI(title="India Escrow & NDA (Agent 3)", version="0.1.0", lifespan=lifespan)

    async def auth(x_api_key: str = Header(default="")) -> None:
        if s.escrow_api_key and not hmac.compare_digest(x_api_key, s.escrow_api_key):
            raise HTTPException(401, detail="invalid API key")

    def svc(request: Request) -> DealService:
        return request.app.state.deals

    async def guard(coro):
        try:
            return await coro
        except DealError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.put("/developers/{developer_id}/profile", dependencies=[Depends(auth)])
    async def put_profile(request: Request, developer_id: str, profile: Profile):
        await svc(request).put_profile(developer_id, profile.model_dump())
        return {"status": "saved"}

    @app.get("/deals", dependencies=[Depends(auth)])
    async def list_deals(request: Request, developer_id: str = Query(...)):
        out = []
        for mid in await svc(request).store.deals_of(developer_id):
            out.append(await guard(svc(request).status(mid, developer_id)))
        return {"deals": out}

    @app.post("/deals/{match_id}/consent", dependencies=[Depends(auth)])
    async def consent(request: Request, match_id: str, body: ConsentBody):
        return await guard(svc(request).consent(match_id, body.developer_id, body.decision))

    @app.get("/deals/{match_id}", dependencies=[Depends(auth)])
    async def deal_status(request: Request, match_id: str, developer_id: str = Query(...)):
        return await guard(svc(request).status(match_id, developer_id))

    @app.get("/deals/{match_id}/nda.pdf", dependencies=[Depends(auth)])
    async def nda_pdf(request: Request, match_id: str, developer_id: str = Query(...)):
        pdf, name = await guard(svc(request).nda_pdf(match_id, developer_id))
        return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/deals/{match_id}/sign", dependencies=[Depends(auth)])
    async def sign(request: Request, match_id: str, body: SignBody):
        ip = body.signer_ip or (request.client.host if request.client else "")
        return await guard(svc(request).sign(match_id, body.developer_id, body.signer_name, body.signer_role,
                                             body.document_sha256, ip))

    @app.get("/deals/{match_id}/reveal", dependencies=[Depends(auth)])
    async def reveal(request: Request, match_id: str, developer_id: str = Query(...)):
        return await guard(svc(request).reveal(match_id, developer_id))

    @app.get("/internal/deals/{match_id}/package", dependencies=[Depends(auth)])
    async def package(request: Request, match_id: str):
        """Both parties + parcels of a revealed deal (Agent 4). Refuses to run without an API key."""
        if not s.escrow_api_key:
            raise HTTPException(503, detail="set IN_ESCROW_API_KEY to enable the internal package endpoint")
        return await guard(svc(request).package(match_id))

    return app


app = create_app()
