"""AgroLand gateway: the single API behind the website, the Masumi MIP-003 agents and the Sokosumi Coworker."""
from __future__ import annotations

import hmac
import json
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from shapely.affinity import translate
from shapely.geometry import mapping, shape, box

from . import alkis, auth, cropwatch, farm, parcels as parcels_mod
from .db import Database, jdump, new_id, now
from .geoclient import Geo, GeoUnavailable, in_country
from .hashing import report_sha256
from .listings import Listings, sample_pdf
from . import mip003
from .masumi import verify_tx_on_blockfrost
from .orders import Engine
from .pool import PoolAccessRunner, PoolService
from .services import LandAuditRunner, LeaseCheckRunner
from .settings import ROOT, Settings, get_settings

WEB = ROOT / "web"

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob: https://tile.openstreetmap.org https://*.tile.openstreetmap.org https://server.arcgisonline.com https://*.basemaps.cartocdn.com; "
       "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


class Limiter:
    """In-memory sliding-window limiter. One process, so it is per-process by design; Caddy/nginx should rate-limit too on a public host."""
    def __init__(self):
        self.hits: dict[str, list[float]] = {}
        self.lock = __import__("threading").Lock()

    def allow(self, key: str, limit: int, window: float = 3600.0) -> bool:
        now_ = __import__("time").monotonic()
        with self.lock:
            q = [t for t in self.hits.get(key, []) if now_ - t < window]
            ok = len(q) < limit
            if ok:
                q.append(now_)
            self.hits[key] = q
            if len(self.hits) > 50_000:  # bound memory: drop idle keys
                self.hits = {k: v for k, v in self.hits.items() if v and now_ - v[-1] < window}
            return ok


class Workspace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80)
    role: Literal["owner", "farm", "developer"]
    country: Literal["DE", "IN"]


class OrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: Literal["land_audit", "lease_check", "pool_access"]
    input: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=80)


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    db = Database(s.state_dir)
    geo = {c: Geo(stack) for c, stack in s.geo.items()}
    holder: dict = {}
    limiter = Limiter()
    pool = PoolService(db, geo, lambda: holder["engine"])
    crop = cropwatch.Fetcher(cache_dir=s.state_dir / "cropwatch") if s.cropwatch == "live" else None
    runners = {"land_audit": LandAuditRunner(db, geo), "lease_check": LeaseCheckRunner(db, crop, geo["IN"].registry_verify),
               "pool_access": PoolAccessRunner(pool, s.state_dir)}
    engine = Engine(db, s, runners)
    holder["engine"] = engine
    listings = Listings(db, engine)
    me = auth.make_dependency(db)

    @asynccontextmanager
    async def lifespan(app):
        engine.start()
        yield
        engine.stop()

    app = FastAPI(title="AgroLand API", version="1.0.0", lifespan=lifespan)
    app.state.engine, app.state.db, app.state.settings = engine, db, s

    def client_ip(request: Request) -> str:
        if s.trust_proxy:
            fwd = request.headers.get("x-forwarded-for", "")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    @app.middleware("http")
    async def security(request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > s.max_body_bytes:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        if request.method == "POST" and request.url.path == "/api/session" and not limiter.allow("session:" + client_ip(request), s.rate_sessions_per_hour):
            return JSONResponse({"detail": "Too many workspaces created from this address. Try again later."}, status_code=429, headers={"Retry-After": "3600"})
        if request.method not in ("GET", "HEAD", "OPTIONS") and not request.url.path.startswith(("/internal/", "/masumi/")):
            origin = request.headers.get("origin")
            host = request.headers.get("host", "")
            if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin.split("://", 1)[-1].rstrip("/") != host):
                return JSONResponse({"detail": "Cross-origin changes are not allowed"}, status_code=403)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"  # map tile servers require a Referer
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not request.url.path.startswith(("/api/", "/internal/", "/masumi/")):
            resp.headers["Content-Security-Policy"] = CSP
        if request.url.path.startswith(("/api/", "/internal/")):
            resp.headers["Cache-Control"] = "no-store"
        elif not request.url.path.startswith("/masumi/"):
            resp.headers["Cache-Control"] = "no-cache"  # pages/scripts/styles: always revalidate (ETag), so a redeploy is never hidden by a stale browser cache
        return resp

    def internal(x_internal_key: str = Header(default="")):
        if not s.internal_key or not hmac.compare_digest(x_internal_key, s.internal_key):
            raise HTTPException(401, "invalid internal key")

    # ---------------------------------------------------------------- public config / health
    @app.get("/api/health")
    def health():
        def probe(url):
            try:
                return httpx.get(url.rstrip("/") + "/health", timeout=3).status_code == 200
            except httpx.HTTPError:
                return False
        return {"status": "ok", "payment_mode": s.payment_mode,
                "geo": {c: {"audit": probe(g.audit_url), "matcher": probe(g.matcher_url), "escrow": probe(g.escrow_url), "architect": probe(g.architect_url)} for c, g in s.geo.items()},
                "agents_registered": {k: bool(v) for k, v in s.agent_identifiers.items()}, "demo_wallet_configured": bool(s.buyer_mps_url and s.buyer_mps_key)}

    @app.get("/api/config")
    def config():
        t = s.catalog["payment"]["token"]
        svc = {k: {**{kk: vv for kk, vv in v.items() if kk != "price"}, "price": engine.price(k)} for k, v in s.catalog["services"].items()}
        return {"payment_mode": s.payment_mode, "network": s.catalog["payment"]["network"], "token": t["symbol"], "services": svc,
                "coverage": {"DE": {"name": "Germany", "currency": "EUR", "area_unit": "ha", "notes": ["Open ALKIS fragment: Magdeburg / Sachsen-Anhalt (191 agricultural parcels) with A14 corridor screening",
                                                                                                       "Live audits use BKG, OSM, BfN, PVGIS, Open-Meteo; ALKIS closed in some states (e.g. Bavaria)"]},
                             "IN": {"name": "India", "currency": "INR", "area_unit": "acre / ha", "notes": ["Audits: Gujarat and Andhra Pradesh carry state knowledge; other states get a site-wide condition",
                                                                                                         "Protected-area and habitation screens are OpenStreetMap-based and not measured for completeness",
                                                                                                         "Title is never verified; revenue records are not conclusive proof of title"]}}}

    # ---------------------------------------------------------------- identity
    @app.post("/api/session", status_code=201)
    def create_session(w: Workspace):
        user, token = auth.create_user(db, w.name, w.role, w.country)
        return {"token": token, "user": user}

    @app.get("/api/me")
    def whoami(u=Depends(me)):
        return {k: u[k] for k in ("id", "name", "role", "country", "persona")}

    # ---------------------------------------------------------------- parcels & geo
    @app.get("/api/parcels")
    def my_parcels(u=Depends(me)):
        return parcels_mod.list_for(db, u["id"])

    @app.post("/api/parcels", status_code=201)
    def add_parcel(body: dict, u=Depends(me)):
        return parcels_mod.add(db, u, body)

    @app.delete("/api/parcels/{pid}", status_code=204)
    def del_parcel(pid: str, u=Depends(me)):
        parcels_mod.remove(db, u["id"], pid)

    @app.get("/api/geo/de/map")
    def de_map(min_lat: float = -90, min_lng: float = -180, max_lat: float = 90, max_lng: float = 180):
        if min_lng > max_lng or min_lat > max_lat:
            raise HTTPException(422, "Invalid bounds")
        vp = box(min_lng, min_lat, max_lng, max_lat)
        return {"type": "FeatureCollection", "features": [f for f in alkis.PARCELS if shape(f["geometry"]).intersects(vp)]}

    @app.get("/api/geo/de/corridors")
    def de_corridors():
        return {"corridors": alkis.corridor_geojson(), "roads": alkis.ROADS, "signals": alkis.zone_signals(), "metadata": alkis.METADATA}

    @app.get("/api/geo/in/demo-parcels")
    def in_parcels():
        return {"type": "FeatureCollection", "features": list(parcels_mod.in_demo().values()),
                "note": "Illustrative rectangles at real coordinates. Not survey boundaries. Survey numbers invented."}

    # ---------------------------------------------------------------- orders
    @app.post("/api/orders", status_code=201)
    def create_order(body: OrderIn, u=Depends(me)):
        if not limiter.allow("orders:" + u["id"], s.rate_orders_per_hour):
            raise HTTPException(429, "Too many orders in the last hour for this workspace")
        return engine.create(u, body.service, u["country"], body.input, idem_key=body.idempotency_key)

    @app.get("/api/orders")
    def list_orders(u=Depends(me)):
        return engine.list_for(u["id"])

    @app.get("/api/orders/{oid}")
    def get_order(oid: str, u=Depends(me)):
        engine.advance(oid) if engine.get(oid, u["id"])["state"] in ("awaiting_payment",) else None
        return {**engine.public(engine.get(oid, u["id"])), "events": engine.events(oid)}

    @app.post("/api/orders/{oid}/pay")
    def pay(oid: str, u=Depends(me)):
        return engine.pay(oid, u["id"])

    @app.post("/api/orders/{oid}/pay-demo-wallet")
    def pay_demo(oid: str, u=Depends(me)):
        return engine.pay_with_demo_wallet(oid, u["id"])

    def _delivered(oid, uid):
        o = engine.get(oid, uid)
        if not o["result"]:
            raise HTTPException(409, "No result yet")
        return o

    @app.get("/api/orders/{oid}/result")
    def result(oid: str, u=Depends(me)):
        o = _delivered(oid, u["id"])
        d = o["result"]["deliverable"]
        return {"order": engine.public(o), "report": d["report"], "report_sha256": d["report_sha256"], "result_hash": o["result_hash"], "markdown": o["result"]["markdown"],
                "unpaid_dev_mode": not s.paid}

    @app.get("/api/orders/{oid}/verify")
    def verify(oid: str, u=Depends(me)):
        """Recompute what can be recomputed and compare hashes. A hash proves the stored report is unchanged, not that its data is true."""
        o = _delivered(oid, u["id"])
        d = o["result"]["deliverable"]
        out = {"report_hash_matches": report_sha256(d["report"]) == d["report_sha256"], "stored_report_sha256": d["report_sha256"],
               "what_a_hash_proves": "The stored report is unchanged since delivery. It does not prove that the underlying data is true."}
        if o["service"] == "lease_check":
            ds = o["input"]["dataset"]
            out["recomputation"] = farm.verify_report(d["report"], ds, o["input"]["today"])
            if d["report"].get("crop_monitoring") is not None:
                out["crop_recomputation"] = cropwatch.verify(d["report"]["crop_monitoring"], ds, o["input"]["today"])
        p = o["payment"]
        if p.get("mode") == "masumi":
            chain = {}
            for k in ("funds_locked_tx", "result_confirmed_tx", "settlement_tx"):
                if p.get(k):
                    chain[k] = verify_tx_on_blockfrost(p[k], s.blockfrost_key)
            out["chain"] = chain or {"note": "No confirmed transaction recorded yet"}
        else:
            out["chain"] = {"note": "UNPAID DEV MODE: no Cardano transaction exists for this order"}
        return out

    @app.get("/api/orders/{oid}/reminders.ics")
    def ics(oid: str, u=Depends(me)):
        o = _delivered(oid, u["id"])
        if o["service"] != "lease_check":
            raise HTTPException(404, "Only lease checks have reminders")
        rep = o["result"]["deliverable"]["report"]
        stamp = datetime.fromisoformat(o["created_at"])
        return Response(farm.to_ics(rep["reminders"], f"{rep['meta']['farm_name']} - lease reminders", stamp), media_type="text/calendar; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="lease-reminders.ics"'})

    # ---------------------------------------------------------------- farm
    @app.get("/api/farm/demo")
    def farm_demo(demo: str | None = None, u=Depends(me)):
        try:
            d = farm.load_demo(u["country"], demo)
        except farm.DataError as exc:
            raise HTTPException(404, str(exc))
        st = d["settings"]
        return {"settings": st, "contracts": d["contracts"], "cadastre": d["cadastre"], "fields": d["fields"], "boundaries": d.get("boundaries"), "demo": True,
                "demo_id": demo or farm.DEMOS[u["country"]][0]}

    @app.get("/api/farm/demos")
    def farm_demos(u=Depends(me)):
        return farm.demo_list(u["country"])

    @app.put("/api/farm/dataset")
    def save_farm(body: dict, u=Depends(me)):
        if u["role"] != "farm":
            raise HTTPException(403, "Farm workspaces only")
        if any(len(body.get(k, "")) > 1_000_000 for k in ("contracts_csv", "cadastre_csv", "fields_csv", "boundaries_geojson") if isinstance(body.get(k, ""), str)):
            raise HTTPException(413, "Each file may be at most 1 MB")
        try:
            base = farm.load_demo(u["country"])["settings"]
            st = {**base, **{k: v for k, v in (body.get("settings") or {}).items() if k in base and k not in ("country", "currency", "currency_symbol", "area_unit")}}
            st["farm_name"] = str(st["farm_name"])[:80]
            ds = farm.build_dataset(body.get("contracts_csv", ""), body.get("cadastre_csv", ""), body.get("fields_csv", ""), st)
            raw = body.get("boundaries_geojson")
            if raw:  # optional field outlines: unlock the crop-and-biomass section of the Lease Check
                fc = json.loads(raw) if isinstance(raw, str) else raw
                ds["boundaries"] = cropwatch.validate_boundaries(fc, ds, lambda la, lo: in_country(u["country"], la, lo))
        except (farm.DataError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc))
        except ValueError as exc:  # JSON syntax or boundary validation
            raise HTTPException(422, f"boundaries: {exc}" if not str(exc).startswith("boundaries") else str(exc))
        payload = jdump(ds)
        with db.tx() as c:
            c.execute("INSERT OR REPLACE INTO farm_datasets VALUES(?,?,?,?,?,?,?)", (u["id"], u["country"], st["farm_name"], 0, payload, report_sha256(ds), now()))
        return {"saved": True, "contracts": len(ds["contracts"]), "sha256": report_sha256(ds)}

    @app.get("/api/farm/dataset")
    def get_farm(u=Depends(me)):
        with db.tx() as c:
            r = c.execute("SELECT * FROM farm_datasets WHERE user_id=?", (u["id"],)).fetchone()
        return {"saved": False} if not r else {"saved": True, "label": r["label"], "sha256": r["sha256"], "updated_at": r["updated_at"], "dataset": json.loads(r["payload"])}

    @app.post("/api/farm/outcomes")
    def record_outcome(body: dict, u=Depends(me)):
        """Savings ACHIEVED are recorded by the user after acting; the engine never computes them."""
        o = engine.get(str(body.get("order_id", "")), u["id"])
        if o["service"] != "lease_check" or not o["result"]:
            raise HTTPException(422, "Needs a delivered lease check")
        key = str(body.get("finding_key", ""))
        rep = o["result"]["deliverable"]["report"]
        f = next((x for x in rep["findings"] if f"{x['type']}:{x['contract_id']}" == key), None)
        if not f:
            raise HTTPException(404, "Unknown finding")
        try:
            amt = float(body.get("amount_per_year"))
        except (TypeError, ValueError):
            raise HTTPException(422, "amount_per_year must be a number")
        if amt < 0:
            raise HTTPException(422, "amount must not be negative")
        with db.tx() as c:
            c.execute("INSERT OR REPLACE INTO farm_outcomes VALUES(?,?,?,?,?,?,?)", (new_id(), u["id"], o["id"], key, amt, str(body.get("note", ""))[:300], now()))
        return farm_outcomes(o["id"], u)

    @app.get("/api/farm/outcomes/{oid}")
    def farm_outcomes(oid: str, u=Depends(me)):
        engine.get(oid, u["id"])
        with db.tx() as c:
            rows = [dict(r) for r in c.execute("SELECT finding_key,amount_per_year,note,created_at FROM farm_outcomes WHERE user_id=? AND order_id=?", (u["id"], oid))]
        return {"outcomes": rows, "achieved_per_year": round(sum(r["amount_per_year"] for r in rows), 2)}

    @app.get("/api/registry/verify")
    def registry_verify(tx_hash: str = Query(..., min_length=64, max_length=64), u=Depends(me)):
        """Read-only lookup of a 5am.earth (Project Swaminathan) registration on Cardano mainnet and its IPFS boundary. A lookup, not a paid analysis."""
        if not limiter.allow("registry:" + u["id"], 60):
            raise HTTPException(429, "Too many registry lookups in the last hour")
        try:
            return geo["IN"].registry_verify(tx_hash.lower())
        except GeoUnavailable as exc:
            raise HTTPException(503, f"Registry lookup unavailable: {exc}")

    # ---------------------------------------------------------------- owner
    @app.post("/api/documents", status_code=201)
    async def upload_doc(file: UploadFile = File(...), u=Depends(me)):
        content = await file.read(10 * 1024 * 1024 + 1)
        return listings.save_document(u, content, file.filename or "extract.pdf")

    @app.post("/api/documents/sample")
    def sample_doc(body: dict, u=Depends(me)):
        label = str(body.get("label", "Demonstration parcel"))
        return listings.save_document(u, sample_pdf(label, u["country"]), "SAMPLE-ownership-extract.pdf", sample=True)

    @app.get("/api/documents/{did}")
    def get_doc(did: str, u=Depends(me)):
        path, name = listings.document_path(u["id"], did)
        return FileResponse(path, media_type="application/pdf", filename=name)

    @app.get("/api/listings")
    def my_listings(u=Depends(me)):
        return listings.mine(u["id"])

    @app.post("/api/listings", status_code=201)
    def new_listing(body: dict, u=Depends(me)):
        if u["role"] != "owner":
            raise HTTPException(403, "Owner workspaces only")
        return listings.create(u, body)

    @app.patch("/api/listings/{lid}")
    def patch_listing(lid: str, body: dict, u=Depends(me)):
        if "consent" in body:
            listings.set_consent(u, lid, bool(body["consent"]))
        if body.get("audit_order_id"):
            listings.attach_audit(u, lid, body["audit_order_id"])
        return listings.view(lid, u["id"])

    @app.delete("/api/listings/{lid}", status_code=204)
    def del_listing(lid: str, u=Depends(me)):
        listings.withdraw(u, lid)

    @app.post("/api/listings/{lid}/interests/{iid}")
    def decide(lid: str, iid: str, body: dict, u=Depends(me)):
        return listings.decide(u, lid, iid, body.get("decision", ""))

    @app.get("/api/marketplace")
    def marketplace(u=Depends(me)):
        if u["role"] != "developer":
            raise HTTPException(403, "Developer workspaces only")
        return [{**m, "my_interest": listings.interest_status(u, m["id"])} for m in listings.marketplace(u["country"])]

    @app.post("/api/marketplace/{lid}/interest")
    def interest(lid: str, body: dict, u=Depends(me)):
        if u["role"] != "developer":
            raise HTTPException(403, "Developer workspaces only")
        return listings.express_interest(u, lid, str(body.get("message", "")))

    # ---------------------------------------------------------------- developer pool
    def dev(u=Depends(me)):
        if u["role"] != "developer":
            raise HTTPException(403, "Developer workspaces only")
        return u

    @app.get("/api/pool/portfolio")
    def portfolio(u=Depends(dev)):
        return pool.portfolio(u)

    @app.post("/api/pool/portfolio", status_code=201)
    def register_site(body: dict, u=Depends(dev)):
        return pool.register(u, body.get("parcel_id", ""), body.get("project_type", "hybrid"))

    @app.delete("/api/pool/portfolio/{pid}", status_code=204)
    def withdraw_site(pid: str, u=Depends(dev)):
        pool.withdraw(u, pid)

    @app.get("/api/pool/teasers")
    def teasers(u=Depends(dev)):
        return pool.teasers(u)

    @app.put("/api/pool/profile")
    def profile(body: dict, u=Depends(dev)):
        return pool.put_profile(u, body)

    @app.get("/api/pool/deals")
    def deals(u=Depends(dev)):
        return pool.deals(u)

    @app.get("/api/pool/deals/{mid}")
    def deal(mid: str, u=Depends(dev)):
        return pool.deal(u, mid)

    @app.post("/api/pool/deals/{mid}/consent")
    def consent(mid: str, body: dict, u=Depends(dev)):
        return pool.consent(u, mid, body.get("decision", ""))

    @app.get("/api/pool/deals/{mid}/nda.pdf")
    def nda(mid: str, u=Depends(dev)):
        return Response(pool.nda_pdf(u, mid), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="nda.pdf"'})

    @app.post("/api/pool/deals/{mid}/sign")
    def sign(mid: str, body: dict, u=Depends(dev)):
        return pool.sign(u, mid, body)

    @app.get("/api/pool/deals/{mid}/documents/{kind}.pdf")
    def pool_doc(mid: str, kind: str, u=Depends(dev)):
        data, name = pool.document(u, mid, kind)
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    def shifted(geom: dict, metres_east: float) -> dict:
        import math
        g = shape(parcels_mod.largest_polygon(geom))
        return mapping(translate(g, xoff=metres_east / (111_320.0 * math.cos(math.radians(g.centroid.y)))))

    def make_counterpart(u, mine: dict) -> tuple[dict, str, dict]:
        with db.tx() as c:
            src = c.execute("SELECT * FROM parcels WHERE user_id=? AND label=? ORDER BY created_at DESC", (u["id"], mine["label"])).fetchone()
        other = shifted(json.loads(src["geometry"]), 800)
        name = "Solarpark Süd GmbH (demo)" if u["country"] == "DE" else "Surya Solar LLP (demo)"
        cu, token = auth.create_user(db, name, "developer", u["country"], persona="demo-counterpart")
        p = parcels_mod.add(db, cu, {"source": "drawn", "geometry": other, "label": f"Demo counterpart site next to '{mine['label'][:60]}' (illustrative)", "ref": f"demo-{new_id()[:8]}"})
        reg = pool.register(cu, p["id"], "solar" if mine["project_type"] == "wind" else "wind")
        prof = ({"company_name": name, "street": "Musterstraße 12", "postal_code": "39104", "city": "Magdeburg", "representative": "Jörg Schäfer, Prokurist",
                 "commercial_register": "Amtsgericht Stendal, HRB 00000 (demo)", "email": "demo-counterpart@example.invalid", "phone": ""} if u["country"] == "DE" else
                {"company_name": name, "address": "Plot 12, Demo Industrial Area, Bhuj", "state": "Gujarat", "pin_code": "370001", "representative": "Meera Shah, Designated Partner",
                 "registration_no": "AAA-0000 (demo)", "gstin": "", "email": "demo-counterpart@example.invalid", "phone": ""})
        pool.put_profile(cu, prof)
        return cu, token, reg

    @app.post("/api/demo/counterpart", status_code=201)
    def demo_counterpart(body: dict, u=Depends(dev)):
        """Creates a second, clearly labelled DEMO developer next to one of your registered sites so a genuine two-party deal can be walked through
        with two identities. The counterpart is a real workspace: it registers its parcel with the real matcher and must consent and sign itself."""
        mine = next((p for p in pool.portfolio(u) if p["id"] == body.get("pool_parcel_id") and p["status"] == "registered"), None)
        if not mine:
            raise HTTPException(422, "Register a site first, then add a demo counterpart next to it")
        cu, token, reg = make_counterpart(u, mine)
        return {"token": token, "user": cu, "registration": reg, "note": "Demo counterpart. Switch to it to give its consent and signature; nothing is done on its behalf."}

    # ---- demo neighbourhood: our site + another developer's site + a landowner's parcel, all adjacent, created through the real services
    neighbourhood: dict[str, dict] = {}

    def run_neighbourhood(u, job):
        import threading
        import time as _t
        def step(sid, status, detail=None):
            for s_ in job["steps"]:
                if s_["id"] == sid:
                    s_["status"], s_["detail"] = status, detail
        try:
            step("site", "running")
            mine = next((p for p in pool.portfolio(u) if p["status"] == "registered"), None)
            if not mine:
                ref = {"source": "alkis-demo", "ref": alkis.demo_id()} if u["country"] == "DE" else {"source": "in-demo", "ref": "IN-DEMO-1"}
                p = parcels_mod.add(db, u, ref)
                reg = pool.register(u, p["id"], "wind")
                if reg["status"] != "registered":
                    raise RuntimeError("Your demo site was not accepted by the matcher: " + "; ".join(reg.get("reasons") or []))
                mine = next(x for x in pool.portfolio(u) if x["id"] == reg["id"])
            step("site", "done", mine["label"])
            with db.tx() as c:
                src = c.execute("SELECT * FROM parcels WHERE user_id=? AND label=? ORDER BY created_at DESC", (u["id"], mine["label"])).fetchone()
            site_geom = json.loads(src["geometry"])
            out: dict = {}
            errors: list = []

            def other_developer():
                try:
                    step("developer", "running")
                    cu, token, reg = make_counterpart(u, mine)
                    out["counterpart"] = {"token": token, "user": cu}
                    step("developer", "done", cu["name"] + (" - teaser sent to both sides" if reg.get("status") == "registered" else " - not matched: " + "; ".join(reg.get("reasons") or [])))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"developer: {exc}")
                    step("developer", "error", str(exc)[:200])

            def landowner():
                try:
                    step("owner", "running")
                    name = "Landowner agent (demo)"
                    ou, _tok = auth.create_user(db, name, "owner", u["country"], persona="demo-owner")
                    p = parcels_mod.add(db, ou, {"source": "drawn", "geometry": shifted(site_geom, -650), "label": "Parcel offered by the Landowner agent (demo, illustrative boundary)", "ref": f"demo-{new_id()[:8]}"})
                    doc = listings.save_document(ou, sample_pdf(p["label"], ou["country"]), "SAMPLE-ownership-extract.pdf", sample=True)
                    o = engine.create(ou, "land_audit", ou["country"], {"parcel_id": p["id"], "project_type": "solar"})
                    engine.seed_pay(o["id"])
                    step("owner", "running", "auditing the parcel with live data (up to two minutes)")
                    end = _t.time() + 420
                    while _t.time() < end:
                        st = engine.get(o["id"])["state"]
                        if st == "delivered":
                            break
                        if st == "failed":
                            raise RuntimeError("the audit of the owner's parcel failed: " + str(engine.get(o["id"])["error"]))
                        _t.sleep(2)
                    else:
                        raise RuntimeError("the audit of the owner's parcel timed out")
                    price = 1800 if u["country"] == "DE" else 45000
                    l = listings.create(ou, {"parcel_id": p["id"], "deal_type": "lease", "price": price, "consent": True, "document_id": doc["id"], "audit_order_id": o["id"]})
                    out["listing_id"] = l["id"]
                    step("owner", "done", "listed for lease")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"owner: {exc}")
                    step("owner", "error", str(exc)[:200])

            ts = [threading.Thread(target=other_developer), threading.Thread(target=landowner)]
            [x.start() for x in ts]
            [x.join() for x in ts]
            job["result"] = out
            job["status"] = "error" if errors else "done"
            job["error"] = "; ".join(errors) or None
        except Exception as exc:  # noqa: BLE001
            job["status"], job["error"] = "error", str(exc)[:300]
            step("site", "error", str(exc)[:200])

    @app.post("/api/demo/neighbourhood", status_code=202)
    def start_neighbourhood(u=Depends(dev)):
        """Builds a demo neighbourhood next to the caller's site through the REAL services (matcher, audit, listings). Platform-provided example
        parties are labelled demo; the Landowner agent's audit is a `demo-seed` order. Runs in the background (live audits take minutes)."""
        cur = neighbourhood.get(u["id"])
        if cur and cur["status"] == "running":
            return cur
        job = {"status": "running", "error": None, "result": None, "started": now(), "steps": [
            {"id": "site", "label": "Your site registered in the pool", "status": "pending", "detail": None},
            {"id": "developer", "label": "Another developer's site next to yours", "status": "pending", "detail": None},
            {"id": "owner", "label": "Landowner agent's parcel next to yours, listed for lease", "status": "pending", "detail": None}]}
        neighbourhood[u["id"]] = job
        import threading
        threading.Thread(target=run_neighbourhood, args=(u, job), daemon=True).start()
        return job

    @app.get("/api/demo/neighbourhood")
    def neighbourhood_status(u=Depends(dev)):
        return neighbourhood.get(u["id"]) or {"status": "none", "steps": []}

    # ---------------------------------------------------------------- internal (Node agent layer / Sokosumi Coworker)
    def channel_user(ref: str, country: str, role: str):
        with db.tx() as c:
            r = c.execute("SELECT * FROM users WHERE persona=?", (f"sokosumi:{ref}",)).fetchone()
        if r:
            return dict(r)
        user, _ = auth.create_user(db, f"Sokosumi user {ref[:12]}", role, country, persona=f"sokosumi:{ref}")
        return auth.user_by_id(db, user["id"])

    @app.post("/internal/orders", status_code=201, dependencies=[Depends(internal)])
    def internal_create(body: dict):
        service, country, ref = body.get("service"), body.get("country"), str(body.get("external_ref", ""))
        if service not in ("land_audit", "lease_check") or country not in ("DE", "IN") or not ref:
            raise HTTPException(422, "service land_audit|lease_check, country DE|IN and external_ref are required "
                                     "(Pool Access starts on the website: it needs both parties' consent and signatures)")
        u = channel_user(str(body.get("user_ref", ref)), country, "farm" if service == "lease_check" else "developer")
        return engine.create(u, service, country, body.get("input") or {}, idem_key=f"sokosumi:{ref}", channel="sokosumi", external_ref=ref)

    @app.post("/internal/validate", dependencies=[Depends(internal)])
    def internal_validate(body: dict):
        """Dry-run of input validation for the Coworker's planning step: nothing is created, computed or charged."""
        service, country = body.get("service"), body.get("country")
        if service not in ("land_audit", "lease_check") or country not in ("DE", "IN"):
            return {"ok": False, "error": "service must be land_audit or lease_check and country DE or IN (Pool Access starts on the website)"}
        u = channel_user(f"validate:{service}:{country}", country, "farm" if service == "lease_check" else "developer")
        try:
            norm, subject = runners[service].validate(u, country, body.get("input") or {})
        except HTTPException as exc:
            return {"ok": False, "error": str(exc.detail)}
        return {"ok": True, "subject": subject, "price": engine.price(service)["display"], "valid_input_keys": sorted(k for k in norm if k != "dataset")}

    @app.post("/internal/orders/{oid}/pay", dependencies=[Depends(internal)])
    def internal_pay(oid: str):
        return engine.pay(oid, None)

    @app.get("/internal/orders/{oid}", dependencies=[Depends(internal)])
    def internal_get(oid: str):
        engine.advance(oid)
        o = engine.get(oid)
        out = {**engine.public(o), "events": engine.events(oid)}
        if o["result"]:
            out["markdown"] = o["result"]["markdown"]
            out["hashed_text_is_markdown"] = o["channel"] == "sokosumi"
        return out

    @app.get("/internal/orders/{oid}/core-payload", dependencies=[Depends(internal)])
    def core_payload(oid: str):
        """Payment terms in the exact shape Sokosumi Core expects in a task event (`masumiPayment`)."""
        o = engine.get(oid)
        p = o["payment"]
        t = p.get("terms")
        if not t:
            raise HTTPException(409, "No payment request yet; call /pay first")
        if t.get("sellerReturnAddress") is not None or t.get("forceLayer") not in (None,):
            raise HTTPException(409, "Core task events cannot carry a non-null sellerReturnAddress or forceLayer")
        src = t.get("PaymentSource") or {}
        return {"blockchainIdentifier": t["blockchainIdentifier"], "agentIdentifier": t["agentIdentifier"], "sellerVkey": p.get("seller_vkey"),
                "submitResultTime": t["submitResultTime"], "payByTime": t["payByTime"], "unlockTime": t["unlockTime"], "externalDisputeUnlockTime": t["externalDisputeUnlockTime"],
                "inputHash": o["input_hash"], "identifierFromPurchaser": o["nonce"], "paymentSourceType": s.catalog["payment"]["paymentSourceType"],
                "supportedPaymentSourceIndex": s.payment_source_index, "Amounts": [{"amount": o["price_amount"], "unit": o["price_unit"]}],
                "PaymentSource": {"network": s.catalog["payment"]["network"], "smartContractAddress": src.get("smartContractAddress"), "policyId": src.get("policyId")}}

    app.include_router(mip003.build(engine, db))

    # ---------------------------------------------------------------- static web app
    if WEB.exists():
        app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    return app


app = create_app() if not __import__("os").environ.get("AGROLAND_NO_AUTOAPP") else None
