"""Offline end-to-end test of India Agent 3 (Escrow & NDA) on top of the real India Agent 2.

Stubbed: India Agent 1 (validator) and the Masumi payment service (only in the paid-mode test).
Real: matcher, escrow state machine, English NDA PDF generation/validation, hashing.

    python tests/test_india_escrow.py
"""
import asyncio
import hashlib
import io
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pyproj import Transformer
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from india.common.masumi import PaymentClient, output_hash  # noqa: E402
from india.escrow.config import EscrowSettings  # noqa: E402
from india.escrow.main import create_app as create_escrow  # noqa: E402
from india.escrow.service import DealService  # noqa: E402
from india.escrow.store import EscrowStore  # noqa: E402
from india.matcher.config import MatcherSettings  # noqa: E402
from india.matcher.main import create_app as create_matcher  # noqa: E402

TO_UTM = Transformer.from_crs(4326, 32643, always_xy=True)  # Anantapur, Andhra Pradesh: UTM zone 43N
TO_WGS = Transformer.from_crs(32643, 4326, always_xy=True)
x0, y0 = TO_UTM.transform(77.6, 14.68)
KEY = "k" * 20


def at(dx, dy=0.0):
    lon, lat = TO_WGS.transform(x0 + dx, y0 + dy)
    return {"lat": round(lat, 6), "lon": round(lon, 6), "radius_m": 300}


def fake_validator(request):
    report = {"overall_verdict": "GO", "score": 85, "assessed_technology": "wind", "warnings": [],
              "location_info": {"state": "Andhra Pradesh", "state_code": "IN-AP", "district": "Anantapur", "village": "Testpalli",
                                "land_record": {"survey_number": "245/2", "ulpin": "AP123456789012"}}}
    return httpx.Response(200, json={"job_id": "j", "status": "completed", "report": report})


def profile(name, rep, mail, **kw):
    return {"company_name": name, "address": "Plot 12, Madhapur", "state": "Telangana", "pin_code": "500081", "representative": rep,
            "registration_no": "U40108TG2021PTC123456", "gstin": "36ABCDE1234F1Z5", "email": mail, "phone": "+91 40 12345678", **kw}


async def make_match(mc, dev_a, dev_b, dy):
    for dev, dx in ((dev_a, 0), (dev_b, 1400)):
        r = await mc.post("/register_parcel", json={"developer_id": dev, "project_type": "wind", **at(dx, dy)},
                          headers={"X-API-Key": KEY})
        assert r.status_code == 200 and r.json()["status"] == "registered", r.text
    t = (await mc.get("/teasers", params={"developer_id": dev_a}, headers={"X-API-Key": KEY})).json()["teasers"][0]
    return t["match_id"]


def pdf_text(b):
    r = PdfReader(io.BytesIO(b))
    return len(r.pages), " ".join(" ".join(p.extract_text() for p in r.pages).split())


async def main():
    tmp = tempfile.mkdtemp()
    matcher = create_matcher(MatcherSettings(_env_file=None, matcher_database_path=f"{tmp}/m.sqlite3", matcher_api_key=KEY),
                             transport=httpx.MockTransport(fake_validator))
    async with matcher.router.lifespan_context(matcher):
        mc = httpx.AsyncClient(transport=httpx.ASGITransport(app=matcher), base_url="http://matcher")
        transport = httpx.ASGITransport(app=matcher)

        # ------------------------------------------------------------ happy path (bypass payment)
        s = EscrowSettings(_env_file=None, escrow_database_path=f"{tmp}/e.sqlite3", matcher_url="http://matcher",
                           matcher_api_key=KEY, escrow_bypass_payment=True)
        escrow = create_escrow(s, transport=transport)
        async with escrow.router.lifespan_context(escrow):
            ec = httpx.AsyncClient(transport=httpx.ASGITransport(app=escrow), base_url="http://escrow")
            mid = await make_match(mc, "dev1", "dev2", 0)

            r = await ec.post(f"/deals/{mid}/consent", json={"developer_id": "dev1", "decision": "accept"})
            assert r.status_code == 422, "consent must require a profile"
            assert (await ec.put("/developers/dev1/profile", json=profile("Vayu Wind Energy Pvt Ltd", "Anita Rao, Director", "anita@vayu.in"))).status_code == 200
            assert (await ec.put("/developers/dev2/profile", json=profile("Surya Solar LLP", "Ravi Patel, Designated Partner", "ravi@surya.in",
                                                                         address="5 Ring Road, Rajkot", state="Gujarat", pin_code="360001"))).status_code == 200
            assert (await ec.put("/developers/dev2/profile", json={**profile("X", "Y", "bad"), "pin_code": "012345"})).status_code == 422
            assert (await ec.put("/developers/dev2/profile", json={**profile("Xx", "Yyy", "a@b.in"), "gstin": "123"})).status_code == 422

            v = (await ec.post(f"/deals/{mid}/consent", json={"developer_id": "dev1", "decision": "accept"})).json()
            assert v["status"] == "pending_consent" and not v["counterpart"]["consented"], v
            assert (await ec.post(f"/deals/{mid}/consent", json={"developer_id": "dev3", "decision": "accept"})).status_code == 403
            v = (await ec.post(f"/deals/{mid}/consent", json={"developer_id": "dev2", "decision": "accept"})).json()
            assert v["status"] == "awaiting_signatures" and v["nda"]["language"] == "en", v
            assert (await ec.get(f"/deals/{mid}/reveal", params={"developer_id": "dev1"})).status_code == 403

            r = await ec.get(f"/deals/{mid}/nda.pdf", params={"developer_id": "dev1"})
            assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
            assert r.content.startswith(b"%PDF-") and r.content.rstrip().endswith(b"%%EOF")
            assert hashlib.sha256(r.content).hexdigest() == v["nda"]["document_sha256"]
            pages, text = pdf_text(r.content)
            for must in ("Mutual Non-Disclosure and Non-Circumvention Agreement", "Vayu Wind Energy Pvt Ltd", "Surya Solar LLP",
                         "4. Non-circumvention", "5. Compensation for breach", "section 74 of the Indian Contract Act, 1872",
                         "section 27", "Arbitration and Conciliation Act, 1996", "Digital Personal Data Protection Act, 2023",
                         "Information Technology Act, 2000", "stamp duty", "INR 25,00,000", "U40108TG2021PTC123456",
                         "GSTIN: 36ABCDE1234F1Z5", "Madhapur", "Ravi Patel", "NDA-IN-1.0"):
                assert must in text, must
            assert pages >= 4
            assert "anita@vayu.in" in text and "+91 40" not in text, "phone must not be printed in the NDA"
            assert r.content == (await ec.get(f"/deals/{mid}/nda.pdf", params={"developer_id": "dev2"})).content, "PDF must be deterministic"
            sha = v["nda"]["document_sha256"]

            def sign(dev, h=None):
                return ec.post(f"/deals/{mid}/sign", json={
                    "developer_id": dev, "signer_name": "Anita Rao" if dev == "dev1" else "Ravi Patel",
                    "signer_role": "Director" if dev == "dev1" else "Designated Partner",
                    "document_sha256": h or sha, "accept": True})

            assert (await sign("dev1", "0" * 64)).status_code == 409
            r = await ec.post(f"/deals/{mid}/sign", json={"developer_id": "dev1", "signer_name": "A B C", "signer_role": "GF",
                                                          "document_sha256": sha, "accept": False})
            assert r.status_code == 422
            v = (await sign("dev1")).json()
            assert v["status"] == "awaiting_signatures" and v["you"]["signed"] and not v["counterpart"]["signed"]
            assert (await ec.get(f"/deals/{mid}/reveal", params={"developer_id": "dev1"})).status_code == 403
            v = (await sign("dev2")).json()
            assert v["status"] == "revealed" and v["nda"]["signed_document_sha256"], v

            rv = (await ec.get(f"/deals/{mid}/reveal", params={"developer_id": "dev1"})).json()
            assert rv["counterpart"]["company"]["email"] == "ravi@surya.in" and rv["counterpart"]["company"]["phone"].startswith("+91")
            assert rv["counterpart"]["parcel"]["geometry"]["type"] == "Polygon"
            cp = rv["counterpart"]["parcel"]
            assert cp["village"] == "Testpalli" and cp["district"] == "Anantapur" and cp["state"] == "Andhra Pradesh"
            assert cp["survey_number"] == "245/2" and cp["ulpin"] == "AP123456789012"
            rv2 = (await ec.get(f"/deals/{mid}/reveal", params={"developer_id": "dev2"})).json()
            assert rv2["counterpart"]["company"]["company_name"].startswith("Vayu")
            assert (await ec.get(f"/deals/{mid}/reveal", params={"developer_id": "dev3"})).status_code == 403

            r = await ec.get(f"/deals/{mid}/nda.pdf", params={"developer_id": "dev2"})
            assert hashlib.sha256(r.content).hexdigest() == v["nda"]["signed_document_sha256"]
            pages, text = pdf_text(r.content)
            assert pages >= 5 and "Signature log" in text and "Accepted electronically" in text
            assert sha in text.replace("\n", "") and "not an Aadhaar-based" in text
            print("happy path OK:", pages, "pages, signed")

            # the internal package for Agent 4 needs a key
            assert (await ec.get(f"/internal/deals/{mid}/package")).status_code == 503

            # decline
            mid2 = await make_match(mc, "dev4", "dev5", 5000)
            for d in ("dev4", "dev5"):
                await ec.put(f"/developers/{d}/profile", json=profile(f"Firm {d} Pvt Ltd", "Max Muster, Director", f"{d}@x.in"))
            r = await ec.post(f"/deals/{mid2}/consent", json={"developer_id": "dev4", "decision": "decline"})
            assert r.json()["status"] == "declined"
            r = await ec.post(f"/deals/{mid2}/consent", json={"developer_id": "dev5", "decision": "accept"})
            assert r.status_code == 409
            assert (await ec.get(f"/deals/{mid2}/nda.pdf", params={"developer_id": "dev5"})).status_code == 409
            print("decline OK")

        # ------------------------------------------------------------ expiry
        s_exp = EscrowSettings(_env_file=None, escrow_database_path=f"{tmp}/e2.sqlite3", matcher_url="http://matcher", matcher_api_key=KEY)
        escrow2 = create_escrow(s_exp, transport=transport)
        async with escrow2.router.lifespan_context(escrow2):
            ec2 = httpx.AsyncClient(transport=httpx.ASGITransport(app=escrow2), base_url="http://escrow")
            mid3 = await make_match(mc, "dev6", "dev7", 9000)
            await ec2.put("/developers/dev6/profile", json=profile("Firm 6 Pvt Ltd", "Max Muster, Director", "a@b.in"))
            r = await ec2.post(f"/deals/{mid3}/consent", json={"developer_id": "dev6", "decision": "accept"})
            assert r.status_code == 200
            deal = await escrow2.state.deals.store.load_deal(mid3)
            deal["data"]["deadline"] = 1.0  # simulate that the consent window has passed
            await escrow2.state.deals.store.save_deal(deal)
            assert (await ec2.get(f"/deals/{mid3}", params={"developer_id": "dev6"})).json()["status"] == "expired"
            print("expiry OK")

        # ------------------------------------------------------------ paid mode against a fake Masumi payment service (V2)
        calls, state = [], {}

        def fake_masumi(request):
            body = json.loads(request.content)
            calls.append((request.url.path, body))
            if request.url.path.endswith("/payment/"):
                n = sum(1 for p, _ in calls if p.endswith("/payment/"))
                return httpx.Response(200, json={"data": {
                    "blockchainIdentifier": f"bc-{n}", "payByTime": "2026-11-01T10:00:00.000Z",
                    "submitResultTime": "2026-11-02T10:00:00.000Z", "unlockTime": "2026-11-03T10:00:00.000Z"}})
            if request.url.path.endswith("resolve-blockchain-identifier"):
                return httpx.Response(200, json={"data": {"onChainState": state.get(body["blockchainIdentifier"])}})
            return httpx.Response(200, json={"status": "success"})

        s_paid = EscrowSettings(_env_file=None, escrow_database_path=f"{tmp}/e3.sqlite3", matcher_url="http://matcher",
                                matcher_api_key=KEY, escrow_bypass_payment=False, escrow_agent_identifier="e" * 60,
                                masumi_api_key="m" * 20, masumi_payment_service_url="http://masumi",
                                masumi_payment_source_type="Web3CardanoV2", masumi_supported_payment_source_index="0",
                                masumi_requested_funds_lovelace="10000000")
        pay = PaymentClient(httpx.AsyncClient(transport=httpx.MockTransport(fake_masumi)), s_paid, s_paid.escrow_agent_identifier)
        svc = DealService(EscrowStore(s_paid.escrow_database_path), httpx.AsyncClient(transport=transport), s_paid, payment=pay)
        escrow3 = create_escrow(s_paid, service=svc)
        async with escrow3.router.lifespan_context(escrow3):
            ec3 = httpx.AsyncClient(transport=httpx.ASGITransport(app=escrow3), base_url="http://escrow")
            mid4 = await make_match(mc, "dev8", "dev9", 13000)
            for d in ("dev8", "dev9"):
                await ec3.put(f"/developers/{d}/profile", json=profile(f"Firm {d} Pvt Ltd", "Max Muster, Director", f"{d}@x.in"))
            await ec3.post(f"/deals/{mid4}/consent", json={"developer_id": "dev8", "decision": "accept"})
            v = (await ec3.post(f"/deals/{mid4}/consent", json={"developer_id": "dev9", "decision": "accept"})).json()
            assert v["status"] == "awaiting_deposits" and v["you"]["payment"]["blockchainIdentifier"].startswith("bc-"), v
            assert len(v["you"]["payment"]["identifier_from_purchaser"]) == 20
            created = [b for p, b in calls if p.endswith("/payment/")]
            assert len(created) == 2 and all(b["paymentSourceType"] == "Web3CardanoV2" and "paymentType" not in b for b in created), created
            assert all(b["supportedPaymentSourceIndex"] == 0 and b["RequestedFunds"] == [{"amount": "10000000", "unit": ""}] for b in created)
            assert all(b["agentIdentifier"] == "e" * 60 and b["network"] == "Preprod" and len(b["inputHash"]) == 64 for b in created)
            bc = {}
            for d in ("dev8", "dev9"):
                bc[d] = (await ec3.get(f"/deals/{mid4}", params={"developer_id": d})).json()["you"]["payment"]
            state[bc["dev8"]["blockchainIdentifier"]] = "FundsLocked"
            v = (await ec3.get(f"/deals/{mid4}", params={"developer_id": "dev8"})).json()
            assert v["status"] == "awaiting_deposits" and v["you"]["deposit_locked"] and not v["counterpart"]["deposit_locked"], v
            state[bc["dev9"]["blockchainIdentifier"]] = "FundsLocked"
            v = (await ec3.get(f"/deals/{mid4}", params={"developer_id": "dev9"})).json()
            assert v["status"] == "awaiting_signatures", v
            assert not [c for c in calls if c[0].endswith("submit-result")], "no funds may be released before signing"
            sha = v["nda"]["document_sha256"]
            for d in ("dev8", "dev9"):
                r = await ec3.post(f"/deals/{mid4}/sign", json={"developer_id": d, "signer_name": "Max Muster", "signer_role": "Director",
                                                               "document_sha256": sha, "accept": True})
            v = r.json()
            assert v["status"] == "revealed", v
            subs = [b for p, b in calls if p.endswith("submit-result")]
            assert len(subs) == 2, subs
            for b in subs:
                dev = next(d for d in bc if bc[d]["blockchainIdentifier"] == b["blockchainIdentifier"])
                assert len(b["submitResultHash"]) == 64 and bc[dev]["identifier_from_purchaser"]
            # hash = MIP-004 over the canonical result string
            deal = await svc.store.load_deal(mid4)
            d = deal["data"]
            result = json.dumps({"match_id": mid4, "signed_nda_sha256": d["signed_sha256"],
                                 "revealed_at": datetime.fromtimestamp(d["revealed_at"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                                sort_keys=True, separators=(",", ":"))
            for b in subs:
                dev = next(x for x in bc if bc[x]["blockchainIdentifier"] == b["blockchainIdentifier"])
                assert b["submitResultHash"] == output_hash(result, bc[dev]["identifier_from_purchaser"])
            print("paid mode OK: V2 payload, funds released only after both signatures; result hashes verified")
    print("escrow OK")


asyncio.run(main())
