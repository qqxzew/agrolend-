"""Orders: the single execution + payment path shared by the website, Masumi MIP-003 jobs and the Sokosumi Coworker.

order.state
  quoted            price and input hash fixed, nothing paid
  awaiting_payment  Masumi payment request exists; waiting for the buyer's funds to be locked on-chain (confirmed)
  paid              funds locked (or payment mode is dev-unpaid, labelled UNPAID everywhere)
  waiting           paid, but the service needs another party first (e.g. second NDA signature)
  running           the service is computing the deliverable
  delivered         deliverable stored and hashed; result hash submission/confirmation tracked in payment.stage
  failed            execution could not produce a deliverable; nothing is submitted, the buyer uses the protocol refund
  expired           payment window passed without locked funds

payment.stage (masumi mode) is a journal written BEFORE every external write. Stages ending in "-pending" mean the outcome of the last
write is unknown; the order is then frozen for inspection instead of being replayed (no duplicate payment requests).
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Protocol

from fastapi import HTTPException

from . import masumi as mps
from .db import Database, jdump, new_id, now
from .hashing import canonical, input_hash, report_sha256, result_hash_mip004, result_hash_raw
from .settings import Settings

ACTIVE = ("awaiting_payment", "paid", "waiting", "running", "delivered")


class Runner(Protocol):
    service: str

    def validate(self, user: dict, country: str, data: dict) -> tuple[dict, str]: ...
    def ready(self, order: dict) -> tuple[bool, str | None]: ...
    def execute(self, order: dict) -> dict: ...
    def markdown(self, order: dict, report: dict) -> str: ...


class Engine:
    def __init__(self, db: Database, settings: Settings, runners: dict[str, Runner]):
        self.db, self.s, self.runners = db, settings, runners
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="exec")
        self._stop = threading.Event()
        self._busy: set[str] = set()
        self._executing: set[str] = set()
        self._lock = threading.Lock()
        self._seller: mps.Mps | None = None
        self._buyer: mps.Mps | None = None

    # ------------------------------------------------------------------ helpers
    def seller(self) -> mps.Mps:
        if self._seller is None:
            self._seller = mps.seller_client(self.s)
        return self._seller

    def buyer(self) -> mps.Mps | None:
        if self._buyer is None:
            self._buyer = mps.buyer_client(self.s)
        return self._buyer

    def get(self, oid: str, user_id: str | None = None) -> dict:
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not r or (user_id and r["user_id"] != user_id):
            raise HTTPException(404, "Order not found")  # same answer for foreign orders: no existence leak
        d = dict(r)
        for k in ("input", "payment", "result"):
            d[k] = json.loads(d[k]) if d[k] else None
        return d

    def _save(self, oid: str, **fields: Any) -> None:
        sets, vals = [], []
        for k, v in fields.items():
            sets.append(f"{k}=?")
            vals.append(jdump(v) if k in ("input", "payment", "result") and v is not None else v)
        sets.append("updated_at=?")
        vals += [now(), oid]
        with self.db.tx() as c:
            c.execute(f"UPDATE orders SET {','.join(sets)} WHERE id=?", vals)

    def event(self, oid: str, event: str, data: dict | None = None) -> None:
        with self.db.tx() as c:
            c.execute("INSERT INTO order_events(order_id,at,event,data) VALUES(?,?,?,?)", (oid, now(), event, jdump(data or {})))

    def events(self, oid: str) -> list[dict]:
        with self.db.tx() as c:
            return [{"at": r["at"], "event": r["event"], "data": json.loads(r["data"])} for r in
                    c.execute("SELECT * FROM order_events WHERE order_id=? ORDER BY id", (oid,))]

    def list_for(self, user_id: str, limit: int = 100) -> list[dict]:
        with self.db.tx() as c:
            ids = [r["id"] for r in c.execute("SELECT id FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit))]
        return [self.public(self.get(i)) for i in ids]

    def price(self, service: str) -> dict:
        t = self.s.catalog["payment"]["token"]
        amt = self.s.catalog["services"][service]["price"]["amount"]
        return {"amount": amt, "unit": t["unit"], "symbol": t["symbol"], "display": f"{int(amt) / 10 ** t['decimals']:.2f} {t['symbol']}"}

    # ------------------------------------------------------------------ create
    def create(self, user: dict, service: str, country: str, data: dict, *, idem_key: str | None = None,
               channel: str = "web", external_ref: str | None = None, nonce: str | None = None, hash_over: dict | None = None) -> dict:
        """`nonce` + `hash_over`: for MIP-003 jobs the buyer fixes identifier_from_purchaser and hashes its RAW input (MIP-004), so the
        input hash must be computed over exactly that, not over our normalised input."""
        cat = self.s.catalog["services"].get(service)
        if not cat:
            raise HTTPException(404, "Unknown service")
        if country not in cat["countries"]:
            raise HTTPException(422, f"{cat['title']} is not available for {country}")
        if idem_key:
            with self.db.tx() as c:
                r = c.execute("SELECT id FROM orders WHERE user_id=? AND idem_key=?", (user["id"], idem_key)).fetchone()
            if r:
                return self.public(self.get(r["id"]))
        normalized, subject = self.runners[service].validate(user, country, data)
        oid, nonce = new_id(), nonce or secrets.token_hex(10)  # 20 hex chars: valid MIP-003 identifier_from_purchaser
        p = self.price(service)
        stamp = now()
        with self.db.tx() as c:
            c.execute("INSERT INTO orders(id,user_id,service,country,channel,external_ref,idem_key,input,input_hash,nonce,price_amount,price_unit,"
                      "state,payment,subject,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (oid, user["id"], service, country, channel, external_ref, idem_key, jdump(normalized), input_hash(hash_over if hash_over is not None else normalized, nonce), nonce,
                       p["amount"], p["unit"], "quoted", jdump({"mode": self.s.payment_mode}), subject, stamp, stamp))
        self.event(oid, "quoted", {"price": p["display"], "subject": subject})
        return self.public(self.get(oid))

    # ------------------------------------------------------------------ payment
    def pay(self, oid: str, user_id: str | None) -> dict:
        """Idempotent: creates the Masumi payment request once; later calls return the stored one."""
        o = self.get(oid, user_id)
        if o["state"] != "quoted":
            return self.public(o)
        if not self.s.paid:
            pay = {"mode": "dev-unpaid", "stage": "unpaid", "label": "UNPAID DEV MODE - no Cardano transaction exists for this order"}
            self._save(oid, payment=pay, state="paid")
            self.event(oid, "paid", pay)
            return self.public(self.get(oid))
        cfg = self.s.catalog
        agent = self.s.agent_identifiers.get(o["service"])
        if not agent:
            raise HTTPException(503, f"The {o['service']} agent is not registered yet (AGENT_IDENTIFIER_{o['service'].upper()} is empty)")
        pay = {"mode": "masumi", "stage": "terms-pending", "agent": agent}
        self._save(oid, payment=pay)  # journal first
        try:
            terms = self.seller().create_payment(agent_identifier=agent, source_index=self.s.payment_source_index, input_hash=o["input_hash"],
                                                 nonce=o["nonce"], unit=o["price_unit"], amount=o["price_amount"],
                                                 windows=cfg["services"][o["service"]].get("windows_minutes", cfg["payment"]["windows_minutes"]), metadata=jdump({"order": oid, "service": o["service"]}))
        except mps.MasumiError as exc:
            # The request may or may not exist remotely; freeze instead of retrying blindly.
            pay.update(stage="terms-uncertain", error=str(exc)[:300])
            self._save(oid, payment=pay, state="failed", error="Payment request outcome unknown; inspect before retrying")
            self.event(oid, "payment_terms_uncertain", {"error": str(exc)[:300]})
            raise HTTPException(502, "The payment service did not confirm the payment request. Nothing was charged; contact the operator.")
        pay.update(stage="awaiting-escrow", blockchain_identifier=terms["blockchainIdentifier"], terms={k: terms.get(k) for k in (
            "blockchainIdentifier", "agentIdentifier", "payByTime", "submitResultTime", "unlockTime", "externalDisputeUnlockTime", "PaymentSource", "RequestedFunds", "sellerReturnAddress", "forceLayer")},
            seller_vkey=self.s.seller_vkey or (terms.get("SmartContractWallet") or {}).get("walletVkey"))
        self._save(oid, payment=pay, state="awaiting_payment")
        self.event(oid, "payment_requested", {"blockchain_identifier": terms["blockchainIdentifier"]})
        return self.public(self.get(oid))

    def pay_with_demo_wallet(self, oid: str, user_id: str | None) -> dict:
        """Lock funds with the operator's funded preprod buyer wallet (web demo). Real transaction, test funds."""
        o = self.get(oid, user_id)
        if o["state"] == "quoted":
            o = self.get(self.pay(oid, user_id)["id"])
        buyer = self.buyer()
        if not buyer:
            raise HTTPException(501, "No demo buyer wallet is configured on this server. Pay from your own Masumi/Sokosumi wallet instead.")
        p = o["payment"]
        if o["state"] != "awaiting_payment" or p.get("stage") != "awaiting-escrow":
            return self.public(o)
        p.update(stage="purchase-pending")
        self._save(oid, payment=p)
        try:
            res = buyer.purchase(p["terms"], nonce=o["nonce"], source_index=self.s.payment_source_index, seller_vkey=p.get("seller_vkey") or "",
                                 input_hash=o["input_hash"], unit=o["price_unit"], amount=o["price_amount"])
        except mps.MasumiError as exc:
            p.update(stage="purchase-uncertain", error=str(exc)[:300])
            self._save(oid, payment=p)
            self.event(oid, "purchase_uncertain", {"error": str(exc)[:300]})
            raise HTTPException(502, "The buyer wallet did not confirm the purchase. Check the order before retrying.")
        p.update(stage="awaiting-escrow", purchase_id=(res or {}).get("id"))
        self._save(oid, payment=p)
        self.event(oid, "purchase_submitted", {"purchase_id": p.get("purchase_id")})
        return self.public(self.get(oid))

    # ------------------------------------------------------------------ progress (called by the poller and on reads)
    def advance(self, oid: str) -> None:
        with self._lock:
            if oid in self._busy:
                return
            self._busy.add(oid)
        try:
            self._advance(oid)
        except Exception as exc:  # never kill the poller; surface in the order journal
            self.event(oid, "advance_error", {"error": f"{type(exc).__name__}: {str(exc)[:300]}"})
        finally:
            with self._lock:
                self._busy.discard(oid)

    def _advance(self, oid: str) -> None:
        o = self.get(oid)
        st, p = o["state"], o["payment"]
        runner = self.runners[o["service"]]
        if st == "awaiting_payment":
            res = self.seller().resolve(p["blockchain_identifier"])
            p["observed"] = {"onChainState": res.get("onChainState")}
            if res.get("onChainState") == mps.CONFIRMED_LOCKED and mps.confirmed(res, mps.CONFIRMED_LOCKED):
                p.update(stage="funds-locked", funds_locked_tx=mps.tx_hash_for(res, mps.CONFIRMED_LOCKED))
                self._save(oid, payment=p, state="paid")
                self.event(oid, "funds_locked", {"tx_hash": p["funds_locked_tx"]})
            elif int(p["terms"]["payByTime"]) < time.time() * 1000:
                self._save(oid, payment=p, state="expired")
                self.event(oid, "expired", {})
            else:
                self._save(oid, payment=p)
            return
        if st in ("paid", "waiting"):
            ok, why = runner.ready(o)
            if not ok:
                dead = getattr(runner, "terminal", lambda _o: None)(o)
                if dead:
                    self._save(oid, state="failed", error=dead)
                    self.event(oid, "ended_without_delivery", {"reason": dead})
                    return
                if st != "waiting" or p.get("waiting_for") != why:
                    p["waiting_for"] = why
                    self._save(oid, payment=p, state="waiting")
                    self.event(oid, "waiting", {"for": why})
                return
            with self.db.tx() as c:  # compare-and-set: exactly one executor claims the order
                n = c.execute("UPDATE orders SET state='running',updated_at=? WHERE id=? AND state IN ('paid','waiting')", (now(), oid)).rowcount
            if n:
                self.event(oid, "running", {})
                self.pool.submit(self._execute, oid)
            return
        if st == "running":
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(o["updated_at"])).total_seconds()
            if age > 600 and oid not in self._executing:  # executor died with the process: execution is read-only, safe to redo
                self._save(oid, state="paid")
            return
        if st == "delivered" and o["payment"].get("mode") == "masumi":
            self._advance_submission(o)

    def _execute(self, oid: str) -> None:
        self._executing.add(oid)
        try:
            self._execute_inner(oid)
        finally:
            self._executing.discard(oid)

    def _execute_inner(self, oid: str) -> None:
        o = self.get(oid)
        runner = self.runners[o["service"]]
        try:
            report = runner.execute(o)
        except Exception as exc:
            p = o["payment"]
            p["attempts"] = p.get("attempts", 0) + 1
            retry = p["attempts"] < 3 and not isinstance(exc, HTTPException) and not self._deadline_close(p)
            self._save(oid, payment=p, state="paid" if retry else "failed", error=None if retry else f"{type(exc).__name__}: {str(exc)[:300]}")
            self.event(oid, "execution_error", {"error": f"{type(exc).__name__}: {str(exc)[:300]}", "will_retry": retry})
            return
        deliverable = {"service": o["service"], "country": o["country"], "report": report, "report_sha256": report_sha256(report)}
        md = runner.markdown(o, report) + f"\n\n---\nReport SHA-256: `{deliverable['report_sha256']}`\n"
        # NOTE: the sha256 proves this stored report is unchanged; it does not prove that the underlying data is true.
        # Marketplace channels deliver the readable Markdown; the website delivers canonical JSON. The hash covers exactly what is delivered.
        text = md if o["channel"] in ("sokosumi", "mip003") else canonical(deliverable)
        rh = result_hash_raw(text, o["nonce"]) if o["channel"] == "sokosumi" else result_hash_mip004(text, o["nonce"])
        p = o["payment"]
        if p.get("mode") == "masumi":
            p.update(stage="result-saved")
        self._save(oid, result={"deliverable": deliverable, "markdown": md, "hashed_text": text}, result_hash=rh, payment=p, state="delivered", error=None)
        self.event(oid, "delivered", {"report_sha256": deliverable["report_sha256"], "result_hash": rh})

    def _deadline_close(self, p: dict) -> bool:
        t = (p.get("terms") or {}).get("submitResultTime")
        return bool(t) and int(t) < time.time() * 1000 + 120_000

    def _advance_submission(self, o: dict) -> None:
        oid, p = o["id"], o["payment"]
        stage = p.get("stage")
        if stage == "result-saved":
            if int(p["terms"]["submitResultTime"]) <= time.time() * 1000:
                self._save(oid, state="failed", error="Result deadline passed before submission; the buyer can claim a refund via the protocol")
                self.event(oid, "deadline_missed", {})
                return
            p["stage"] = "submit-pending"
            self._save(oid, payment=p)  # journal before the write
            try:
                self.seller().submit_result(p["blockchain_identifier"], o["result_hash"])
            except mps.MasumiError as exc:
                p.update(stage="submit-uncertain", error=str(exc)[:300])
                self._save(oid, payment=p)
                self.event(oid, "submit_uncertain", {"error": str(exc)[:300]})
                return
            p["stage"] = "awaiting-result-confirmation"
            self._save(oid, payment=p)
            self.event(oid, "result_hash_submitted", {"result_hash": o["result_hash"]})
            return
        if stage in ("awaiting-result-confirmation", "awaiting-withdrawal"):
            res = self.seller().resolve(p["blockchain_identifier"])
            p["observed"] = {"onChainState": res.get("onChainState"), "resultHash": res.get("resultHash")}
            if stage == "awaiting-result-confirmation" and res.get("onChainState") in ("ResultSubmitted", *mps.DONE_STATES) \
                    and res.get("resultHash") == o["result_hash"] and mps.confirmed(res, "ResultSubmitted"):
                p.update(stage="awaiting-withdrawal", result_confirmed_tx=mps.tx_hash_for(res, "ResultSubmitted"))
                self.event(oid, "result_hash_confirmed", {"tx_hash": p["result_confirmed_tx"]})
            if res.get("onChainState") in mps.DONE_STATES:
                tx = mps.tx_hash_for(res, res["onChainState"])
                p.update(stage="settled", settlement_tx=tx)
                self.event(oid, "settled", {"tx_hash": tx})
            if res.get("onChainState") in mps.DEAD_STATES:
                p.update(stage="refund-or-dispute", error=f"on-chain state {res.get('onChainState')}")
                self.event(oid, "refund_or_dispute", {"state": res.get("onChainState")})
            self._save(oid, payment=p)

    def tick(self) -> None:
        with self.db.tx() as c:
            ids = [r["id"] for r in c.execute(f"SELECT id FROM orders WHERE state IN ({','.join('?' * len(ACTIVE))})", ACTIVE)]
        for oid in ids:
            self.advance(oid)

    def start(self, interval: float = 4.0) -> None:
        def loop():
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception:
                    pass
                self._stop.wait(interval)
        threading.Thread(target=loop, name="order-poller", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ views
    def public(self, o: dict) -> dict:
        p = dict(o["payment"] or {})
        paid_ok = p.get("mode") == "masumi"
        pay_view = {
            "mode": p.get("mode"), "stage": p.get("stage"), "label": p.get("label"), "blockchain_identifier": p.get("blockchain_identifier"),
            "pay_by": (p.get("terms") or {}).get("payByTime"), "submit_result_by": (p.get("terms") or {}).get("submitResultTime"),
            "funds_locked_tx": p.get("funds_locked_tx"), "result_hash_tx": p.get("result_confirmed_tx"), "settlement_tx": p.get("settlement_tx"),
            "waiting_for": p.get("waiting_for"), "on_chain_state": (p.get("observed") or {}).get("onChainState"), "attempts": p.get("attempts"),
            "report_ready": o["state"] == "delivered",
            "funds_locked": bool(p.get("funds_locked_tx")) if paid_ok else None,
            "result_hash_confirmed": bool(p.get("result_confirmed_tx")) if paid_ok else None,
            "seller_paid_out": bool(p.get("settlement_tx")) if paid_ok else None,
            "buyer_can_pay_with_demo_wallet": bool(self.s.buyer_mps_url and self.s.buyer_mps_key) and paid_ok,
        }
        price = self.price(o["service"]) | {"amount": o["price_amount"]}
        return {
            "id": o["id"], "service": o["service"], "title": self.s.catalog["services"][o["service"]]["title"], "country": o["country"],
            "channel": o["channel"], "external_ref": o["external_ref"], "state": o["state"], "subject": o["subject"], "price": price,
            "input_hash": o["input_hash"], "result_hash": o["result_hash"], "nonce": o["nonce"], "error": o["error"],
            "payment": pay_view, "has_result": bool(o["result"]), "created_at": o["created_at"], "updated_at": o["updated_at"],
            "unpaid_dev_mode": not self.s.paid,
        }
