"""Developer pool workflow: portfolio -> anonymous teasers -> mutual consent -> payment -> NDA by both -> disclosure + joint calculation.

The geo services (matcher, escrow, architect) run the state machine and the calculation. They have payment bypass ON because money is handled
only here, through orders:

  * consent         : escrow.consent (both must accept; either decline ends the deal)
  * payment gate    : when both consented, each party gets a `pool_access` order. NDA text (it names both companies) and signing are
                      released only when BOTH orders have locked funds ("paid"), so neither side pays for a deal the other can walk away from
                      unpaid.
  * signatures      : each party signs only the NDA hash they were shown (escrow checks it); the order of a party never signs for the other.
  * delivery        : after both signed, each order computes its deliverable (reveal + joint plan + 2 PDFs) and only then the result hash is
                      submitted on-chain. A deal that is declined or expires never submits: buyers use the protocol refund.
One payment per party covers disclosure AND the calculation; nothing is charged twice for the same result.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import HTTPException

from .db import Database, jdump, new_id, now
from .geoclient import Geo, GeoUnavailable
from .orders import Engine
from .parcels import get as get_parcel, largest_polygon

PAID_STATES = ("paid", "waiting", "running", "delivered")
OPEN = ("pending_consent", "awaiting_signatures", "awaiting_deposits")


class PoolService:
    def __init__(self, db: Database, geo: dict[str, Geo], engine_ref):
        self.db, self.geo, self._engine = db, geo, engine_ref

    @property
    def engine(self) -> Engine:
        return self._engine()

    def _g(self, user) -> Geo:
        return self.geo[user["country"]]

    # ------------------------------------------------------------------ portfolio
    def register(self, user, parcel_id: str, project_type: str) -> dict:
        if project_type not in ("wind", "solar", "hybrid"):
            raise HTTPException(422, "project_type must be wind, solar or hybrid")
        p = get_parcel(self.db, user["id"], parcel_id)
        try:
            code, body = self._g(user).register_parcel(user["id"], {"polygon_geojson": largest_polygon(p["geometry"]), "project_type": project_type, "label": p["label"][:120]})
        except GeoUnavailable as exc:
            raise HTTPException(503, f"The audit service could not be reached ({exc}). Nothing was registered; try again.")
        if code == 409:
            raise HTTPException(409, "You already registered this area")
        if code >= 400:
            raise HTTPException(422 if code < 500 else 502, str(body.get("detail", body))[:300])
        status = "registered" if body.get("status") == "registered" else "rejected"
        row = (new_id(), user["id"], user["country"], p["label"], body.get("parcel_id"), project_type, jdump(body.get("audit") or {"verdict": body.get("verdict"), "score": body.get("score")}),
               status, "; ".join(body.get("reasons", []))[:500] if status == "rejected" else None, now())
        with self.db.tx() as c:
            c.execute("INSERT INTO pool_parcels VALUES(?,?,?,?,?,?,?,?,?,?)", row)
        return {"status": status, "reasons": body.get("reasons"), "audit": body.get("audit"), "new_matches": body.get("new_matches", 0), "id": row[0]}

    def portfolio(self, user) -> list[dict]:
        with self.db.tx() as c:
            rows = c.execute("SELECT * FROM pool_parcels WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
        return [{**dict(r), "audit": json.loads(r["audit"] or "{}")} for r in rows]

    def withdraw(self, user, pool_parcel_id: str) -> None:
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM pool_parcels WHERE id=? AND user_id=?", (pool_parcel_id, user["id"])).fetchone()
        if not r:
            raise HTTPException(404, "Not found")
        if r["matcher_parcel_id"]:
            self._g(user).withdraw_parcel(user["id"], r["matcher_parcel_id"])
        with self.db.tx() as c:
            c.execute("UPDATE pool_parcels SET status='withdrawn' WHERE id=?", (pool_parcel_id,))

    def teasers(self, user) -> list[dict]:
        return self._g(user).teasers(user["id"])

    def put_profile(self, user, profile: dict) -> dict:
        res = self._g(user).put_profile(user["id"], profile)
        if res["status"] >= 400:
            raise HTTPException(422, str(res["body"].get("detail", res["body"]))[:400])
        return res["body"]

    # ------------------------------------------------------------------ deals
    def _order_for(self, match_id: str, user_id: str) -> dict | None:
        with self.db.tx() as c:
            r = c.execute("SELECT order_id FROM pool_deals WHERE match_id=? AND user_id=?", (match_id, user_id)).fetchone()
        return self.engine.get(r["order_id"]) if r and r["order_id"] else None

    def _ensure_orders(self, user, match_id: str) -> None:
        """When both sides consented, create one quoted order per party (idempotent)."""
        from . import auth
        for uid in self._g(user).match_parties(match_id):
            u = auth.user_by_id(self.db, uid)
            if not u or self._order_for(match_id, uid):
                continue
            o = self.engine.create(u, "pool_access", u["country"], {"match_id": match_id}, idem_key=f"pool:{match_id}")
            with self.db.tx() as c:
                c.execute("INSERT OR REPLACE INTO pool_deals VALUES(?,?,?,?,?)", (match_id, uid, u["country"], o["id"], now()))

    def _parties_paid(self, user, match_id: str) -> tuple[bool, bool]:
        ids = self._g(user).match_parties(match_id)
        orders = {uid: self._order_for(match_id, uid) for uid in ids}
        own = orders.get(user["id"])
        others = [o for uid, o in orders.items() if uid != user["id"]]
        return bool(own and own["state"] in PAID_STATES), bool(others and all(o and o["state"] in PAID_STATES for o in others))

    def deal(self, user, match_id: str) -> dict:
        code, view = self._g(user).deal(match_id, user["id"])
        if code == 404 and "no deal" in str(view.get("detail", "")):
            # The escrow creates a deal on the first consent. Until then the party only knows the anonymous teaser.
            teaser = next((t for t in self.teasers(user) if t.get("match_id") == match_id), None)
            if not teaser:
                raise HTTPException(404, "Deal not found")
            return {"match_id": match_id, "status": "not_started", "teaser": teaser, "order": None, "own_paid": False, "counterpart_paid": False, "next": "consent"}
        if code >= 400:
            raise HTTPException(code, str(view.get("detail", view))[:300])
        if view["status"] in ("awaiting_signatures", "revealed", "awaiting_deposits"):
            self._ensure_orders(user, match_id)
        order = self._order_for(match_id, user["id"])
        own_paid, other_paid = self._parties_paid(user, match_id) if order else (False, False)
        gate = "ended" if view["status"] in ("declined", "expired", "failed") else \
            "pay" if order and not own_paid else "counterpart_pay" if order and not other_paid else "sign" if view["status"] == "awaiting_signatures" else "done" if view["status"] == "revealed" else "consent"
        return {**view, "order": self.engine.public(order) if order else None, "own_paid": own_paid, "counterpart_paid": other_paid, "next": gate}

    def deals(self, user) -> list[dict]:
        out = []
        for d in self._g(user).deals(user["id"]):
            try:
                out.append(self.deal(user, d["match_id"]))
            except HTTPException:
                out.append(d)
        return out

    def consent(self, user, match_id: str, decision: str) -> dict:
        if decision not in ("accept", "decline"):
            raise HTTPException(422, "decision must be accept or decline")
        code, body = self._g(user).consent(match_id, user["id"], decision)
        if code >= 400:
            raise HTTPException(code, str(body.get("detail", body))[:300])
        return self.deal(user, match_id)

    def nda_pdf(self, user, match_id: str) -> bytes:
        d = self.deal(user, match_id)
        if not (d["own_paid"] and d["counterpart_paid"]):
            raise HTTPException(402, "The NDA names both companies. It is released when both parties' payments are locked.")
        return self._g(user).nda_pdf(match_id, user["id"])

    def sign(self, user, match_id: str, body: dict) -> dict:
        d = self.deal(user, match_id)
        if not (d["own_paid"] and d["counterpart_paid"]):
            raise HTTPException(402, "Signing opens when both parties' payments are locked.")
        code, res = self._g(user).sign(match_id, {**body, "developer_id": user["id"]})
        if code >= 400:
            raise HTTPException(code, str(res.get("detail", res))[:300])
        return self.deal(user, match_id)

    def document(self, user, match_id: str, kind: str) -> tuple[bytes, str]:
        if kind not in ("agreement", "grid_application"):
            raise HTTPException(404, "Unknown document")
        o = self._order_for(match_id, user["id"])
        if not o or o["state"] != "delivered":
            raise HTTPException(409, "Documents are released with the delivered result")
        path = self.db.documents.parent / "pool" / o["id"] / f"{kind}.pdf"
        if not path.exists():
            raise HTTPException(404, "Document missing")
        return path.read_bytes(), f"{kind}-{match_id[:8]}.pdf"


class PoolAccessRunner:
    service = "pool_access"

    def __init__(self, pool: PoolService, state_dir: Path):
        self.pool, self.state_dir = pool, state_dir

    def validate(self, user, country, data):
        if user["country"] != country or user["role"] != "developer":
            raise HTTPException(422, "Pool access is for developer workspaces")
        mid = str(data.get("match_id", ""))
        code, view = self.pool.geo[country].deal(mid, user["id"])
        if code >= 400:
            raise HTTPException(404 if code == 403 else code, "Deal not found")
        if view["status"] not in ("awaiting_signatures", "awaiting_deposits", "revealed"):
            raise HTTPException(409, "Both parties must consent before access can be bought")
        return {"match_id": mid}, f"Pool deal {mid[:8]}"

    def ready(self, order):
        user = {"id": order["user_id"], "country": order["country"]}
        code, view = self.pool.geo[order["country"]].deal(order["input"]["match_id"], order["user_id"])
        if code >= 400 or view["status"] in ("declined", "expired", "failed"):
            return False, f"deal ended ({view.get('status', 'unknown')})"
        own, other = self.pool._parties_paid(user, order["input"]["match_id"])
        if not other:
            return False, "the other party's payment"
        if view["status"] != "revealed":
            return False, "both NDA signatures"
        return True, None

    def terminal(self, order) -> str | None:
        code, view = self.pool.geo[order["country"]].deal(order["input"]["match_id"], order["user_id"])
        if code < 400 and view["status"] in ("declined", "expired", "failed"):
            return f"The deal ended ({view['status']}) before disclosure. Nothing is delivered and no result hash is submitted; use the protocol refund."
        return None

    def execute(self, order):
        g, mid, uid = self.pool.geo[order["country"]], order["input"]["match_id"], order["user_id"]
        code, rv = g.reveal(mid, uid)
        if code >= 400:
            raise RuntimeError(f"reveal not available: {str(rv)[:200]}")
        plan = g.compute_pool(mid, uid)
        outdir = self.state_dir / "pool" / order["id"]
        outdir.mkdir(parents=True, exist_ok=True)
        docs = []
        for kind in ("agreement", "grid_application"):
            pdf = g.pool_pdf(mid, uid, kind)
            (outdir / f"{kind}.pdf").write_bytes(pdf)
            docs.append({"kind": kind, "sha256": hashlib.sha256(pdf).hexdigest(), "bytes": len(pdf)})
        return {"match_id": mid, "disclosure": rv, "joint_plan": plan, "documents": docs,
                "limitations": ["Documents are machine-generated drafts and the model is a screening model with default assumptions - not bankable, not legal or tax advice.",
                                "Proximity of two sites does not establish a continuous land block or prove the economic benefit of combining them.",
                                "Ownership of either parcel is not verified by AgroLand."]}

    def markdown(self, order, r):
        plan = r["joint_plan"]
        lines = ["# Pool Access - disclosure and joint calculation", f"Deal `{r['match_id']}`", "", "## Counterpart (revealed after both NDAs)"]
        cp = r["disclosure"].get("counterpart", {})
        co = cp.get("company", {})
        lines += [f"- Company: {co.get('company_name')}", f"- Contact: {co.get('email')}", ""]
        p = plan.get("plan", {})
        jp = p.get("joint_project", {})
        lines += ["## Joint plan (screening level)", f"- Viable on default assumptions: **{p.get('viable')}**; pooling creates value: **{p.get('pooling_beneficial')}**",
                  f"- Joint capacity {jp.get('capacity_mw')} MW, NPV {jp.get('npv_eur', jp.get('npv_inr'))} {plan.get('plan', {}).get('currency', 'EUR')} (25 years); split key applied: {p.get('method_applied')}",
                  f"- Shares (basis points, sum 10000): {json.dumps(p.get('shares_bp'))}"] + [f"- Warning: {w}" for w in p.get("warnings", [])] + ["", "## Documents"]
        lines += [f"- {d['kind']}.pdf sha256 `{d['sha256']}`" for d in r["documents"]]
        lines += ["", "## Limits"] + [f"- {x}" for x in r["limitations"]]
        return "\n".join(lines)
