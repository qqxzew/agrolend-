"""Owner workflow: documents, listings, interest requests and controlled disclosure.

Publishing a listing transfers no right to the land. Ownership is never verified: a listing says so, and the document is an owner-declared
attachment visible only to its owner. A developer sees an allow-listed card (region, area, price, audit summary); the exact boundary is
disclosed per interested developer only when the owner accepts that developer's interest.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from fastapi import HTTPException

from . import alkis
from .db import Database, jdump, new_id, now
from .orders import Engine

MAX_PDF = 10 * 1024 * 1024


def sample_pdf(label: str, country: str) -> bytes:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    import reportlab
    fonts = Path(reportlab.__file__).parent / "fonts"
    if "SampleVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("SampleVera", str(fonts / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("SampleVeraBold", str(fonts / "VeraBd.ttf")))
    b = io.BytesIO()
    c = Canvas(b, pagesize=(595, 842))
    c.setTitle("SAMPLE - NOT A LAND-REGISTRY EXTRACT")
    c.setFillColorRGB(.7, .1, .1); c.setFont("SampleVeraBold", 23); c.drawString(50, 780, "SAMPLE / DEMO DOCUMENT")
    c.setFillColorRGB(.1, .1, .1); c.setFont("SampleVera", 10)
    kind = "Grundbuch extract" if country == "DE" else "Record of Rights (7/12 / Adangal) extract"
    for i, line in enumerate([f"NOT an official {kind}. No proof of ownership.", f"Demonstration parcel: {label[:80]}",
                              "The fictional owner has no asserted rights to any real parcel.", "No court seal, signature or official register number.",
                              "Purpose: demonstrate the document step of the listing workflow only."]):
        c.drawString(50, 720 - i * 30, line)
    c.save()
    return b.getvalue()


class Listings:
    def __init__(self, db: Database, engine: Engine):
        self.db, self.engine = db, engine

    # ---- documents (owner-only)
    def save_document(self, user, content: bytes, filename: str, sample: bool = False) -> dict:
        if not sample:
            if len(content) > MAX_PDF:
                raise HTTPException(413, "Maximum 10 MB")
            if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
                raise HTTPException(422, "A PDF file is needed")
        did, sha = new_id(), hashlib.sha256(content).hexdigest()
        (self.db.documents / f"{did}.pdf").write_bytes(content)
        with self.db.tx() as c:
            c.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)", (did, user["id"], Path(filename).name[:160], sha, "ownership-evidence", int(sample), now()))
        return {"id": did, "filename": Path(filename).name[:160], "sha256": sha, "sample": sample, "note": "Owner-declared attachment. Not verified."}

    def document_path(self, user_id: str, did: str) -> tuple[Path, str]:
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM documents WHERE id=? AND user_id=?", (did, user_id)).fetchone()
        if not r:
            raise HTTPException(404, "Document not found")
        return self.db.documents / f"{did}.pdf", r["filename"]

    # ---- listings
    def _row(self, lid: str, owner_id: str | None = None):
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
        if not r or (owner_id and r["user_id"] != owner_id):
            raise HTTPException(404, "Listing not found")
        return r

    def _parcel(self, pid: str) -> dict:
        with self.db.tx() as c:
            return dict(c.execute("SELECT * FROM parcels WHERE id=?", (pid,)).fetchone())

    def _audit_summary(self, order_id: str | None) -> dict | None:
        if not order_id:
            return None
        o = self.engine.get(order_id)
        if o["state"] != "delivered" or not o["result"]:
            return None
        rep = o["result"]["deliverable"]["report"]
        return {"order_id": order_id, "verdict": rep["audit_conclusion"]["verdict"], "score": rep["audit_conclusion"]["score"], "project_type": rep["project_type"],
                "data_complete": rep["data_quality"]["complete"], "report_sha256": o["result"]["deliverable"]["report_sha256"],
                "geometric_signal": (rep.get("geometric_signal") or {}).get("geometry_signal")}

    def create(self, user, body: dict) -> dict:
        from .parcels import get as get_parcel
        p = get_parcel(self.db, user["id"], body.get("parcel_id", ""))
        deal = body.get("deal_type")
        if deal not in ("lease", "sale"):
            raise HTTPException(422, "deal_type must be lease or sale")
        try:
            price = float(body.get("price"))
        except (TypeError, ValueError):
            raise HTTPException(422, "price must be a number")
        if not 0 < price <= 100_000_000_000:
            raise HTTPException(422, "price must be positive")
        audit_id = body.get("audit_order_id")
        if audit_id:
            o = self.engine.get(audit_id, user["id"])
            if o["service"] != "land_audit" or o["input"].get("parcel", {}).get("id") != p["id"]:
                raise HTTPException(422, "That audit belongs to another parcel")
        did = body.get("document_id")
        if did:
            self.document_path(user["id"], did)
        consent = bool(body.get("consent"))
        lid, st = new_id(), now()
        with self.db.tx() as c:
            try:
                c.execute("INSERT INTO listings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (lid, user["id"], p["id"], audit_id, did, deal, price, int(consent), st if consent else None, "draft", st, st))
            except Exception:
                raise HTTPException(409, "There is already a listing for this parcel")
        return self.view(lid, user["id"])

    def set_consent(self, user, lid: str, consent: bool) -> dict:
        self._row(lid, user["id"])
        with self.db.tx() as c:
            c.execute("UPDATE listings SET consent=?,consent_at=?,updated_at=? WHERE id=?", (int(consent), now() if consent else None, now(), lid))
        return self.view(lid, user["id"])

    def attach_audit(self, user, lid: str, audit_order_id: str) -> dict:
        r = self._row(lid, user["id"])
        o = self.engine.get(audit_order_id, user["id"])
        if o["service"] != "land_audit" or o["input"].get("parcel", {}).get("id") != r["parcel_id"]:
            raise HTTPException(422, "That audit belongs to another parcel")
        with self.db.tx() as c:
            c.execute("UPDATE listings SET audit_order_id=?,updated_at=? WHERE id=?", (audit_order_id, now(), lid))
        return self.view(lid, user["id"])

    def withdraw(self, user, lid: str) -> None:
        self._row(lid, user["id"])
        with self.db.tx() as c:
            c.execute("DELETE FROM interests WHERE listing_id=?", (lid,))
            c.execute("DELETE FROM listings WHERE id=?", (lid,))

    def status(self, r) -> str:
        audit = self._audit_summary(r["audit_order_id"])
        if not r["consent"]:
            return "private"
        if not audit:
            return "needs_audit"
        return "published"

    def view(self, lid: str, owner_id: str) -> dict:
        r = self._row(lid, owner_id)
        p = self._parcel(r["parcel_id"])
        with self.db.tx() as c:
            ints = [dict(i) for i in c.execute("SELECT i.*,u.name AS developer_name FROM interests i JOIN users u ON u.id=i.developer_id WHERE listing_id=? ORDER BY created_at", (lid,))]
        return {"id": r["id"], "parcel": {"id": p["id"], "label": p["label"], "area_ha": p["area_ha"], "ref": p["ref"], "demo": bool(p["demo"]), "source": p["source"]},
                "deal_type": r["deal_type"], "price": r["price_amount"], "consent": bool(r["consent"]), "consent_at": r["consent_at"], "status": self.status(r),
                "visible_to_developers": self.status(r) == "published", "audit": self._audit_summary(r["audit_order_id"]), "document_id": r["document_id"],
                "ownership": "not verified", "interests": ints, "created_at": r["created_at"]}

    def mine(self, owner_id: str) -> list[dict]:
        with self.db.tx() as c:
            ids = [r["id"] for r in c.execute("SELECT id FROM listings WHERE user_id=? ORDER BY created_at DESC", (owner_id,))]
        return [self.view(i, owner_id) for i in ids]

    # ---- developer side
    def marketplace(self, country: str) -> list[dict]:
        with self.db.tx() as c:
            rows = c.execute("SELECT l.*,p.country AS pcountry FROM listings l JOIN parcels p ON p.id=l.parcel_id WHERE l.consent=1 AND p.country=?", (country,)).fetchall()
        out = []
        for r in rows:
            audit = self._audit_summary(r["audit_order_id"])
            if not audit:
                continue
            p = self._parcel(r["parcel_id"])
            region = (alkis.METADATA["region"] if country == "DE" else (p["label"].rsplit(",", 1)[-1].strip()))
            out.append({"id": r["id"], "country": country, "deal_type": r["deal_type"], "price": r["price_amount"], "area_ha": p["area_ha"], "region": region,
                        "audit": audit, "demo": bool(p["demo"]) or p["source"] == "alkis-demo", "ownership": "not verified by AgroLand",
                        "agent_demo": self._is_demo_owner(r["user_id"])})
        return out  # allow-list: no owner name, no document, no exact geometry

    def _is_demo_owner(self, uid: str) -> bool:
        with self.db.tx() as c:
            r = c.execute("SELECT persona FROM users WHERE id=?", (uid,)).fetchone()
        return bool(r and r["persona"] == "demo-owner")

    def express_interest(self, dev, lid: str, message: str) -> dict:
        with self.db.tx() as c:
            r = c.execute("SELECT l.id,l.consent,l.audit_order_id FROM listings l JOIN parcels p ON p.id=l.parcel_id WHERE l.id=? AND p.country=?", (lid, dev["country"])).fetchone()
            if not r or not r["consent"] or not self._audit_summary(r["audit_order_id"]):
                raise HTTPException(404, "Listing not found")
            iid = new_id()
            owner = c.execute("SELECT u.persona FROM users u JOIN listings l ON l.user_id=u.id WHERE l.id=?", (lid,)).fetchone()
            # The platform-provided demo Landowner agent accepts at once (labelled in the UI); real owners always decide themselves.
            auto = bool(owner and owner["persona"] == "demo-owner")
            try:
                c.execute("INSERT INTO interests VALUES(?,?,?,?,?,?,?)", (iid, lid, dev["id"], (message or "")[:500], "accepted" if auto else "pending", now(), now() if auto else None))
            except Exception:
                pass
        return self.interest_status(dev, lid)

    def interest_status(self, dev, lid: str) -> dict:
        with self.db.tx() as c:
            i = c.execute("SELECT * FROM interests WHERE listing_id=? AND developer_id=?", (lid, dev["id"])).fetchone()
        if not i:
            return {"status": "none"}
        out = {"status": i["status"], "message": i["message"]}
        if i["status"] == "accepted":
            r = self._row(lid)
            out["disclosed_boundary"] = json.loads(self._parcel(r["parcel_id"])["geometry"])
        return out

    def decide(self, owner, lid: str, interest_id: str, decision: str) -> dict:
        self._row(lid, owner["id"])
        if decision not in ("accepted", "declined"):
            raise HTTPException(422, "decision must be accepted or declined")
        with self.db.tx() as c:
            n = c.execute("UPDATE interests SET status=?,decided_at=? WHERE id=? AND listing_id=?", (decision, now(), interest_id, lid)).rowcount
        if not n:
            raise HTTPException(404, "Interest request not found")
        return self.view(lid, owner["id"])
