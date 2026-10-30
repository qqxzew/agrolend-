"""FastAPI entrypoint of India Agent 1: `uvicorn india.audit.main:app --port 9000`."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from ..common.jobstore import JobStore
from ..common.masumi import PaymentClient
from .api import JobService, build_router
from .config import AuditSettings, get_audit_settings
from .gis_engine import GisEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: AuditSettings | None = None) -> FastAPI:
    s = settings or get_audit_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(s.http_timeout_s, connect=10.0),
            headers={"User-Agent": s.user_agent},
            limits=httpx.Limits(max_connections=40),
        ) as client:
            app.state.jobs = JobService(JobStore(s.database_path), GisEngine(client, s),
                                        PaymentClient(client, s, s.agent_identifier), s)
            logging.getLogger("india-land-audit").info(
                "ready - network=%s bypass_payment=%s", s.masumi_network, s.bypass_payment
            )
            yield

    app = FastAPI(title="India Land Audit Worker (Masumi agent)", version="0.1.0", lifespan=lifespan)
    app.include_router(build_router())

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app


app = create_app()
