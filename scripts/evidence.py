#!/usr/bin/env python3
"""Exports REAL payment evidence from the gateway database: orders whose funds-locked / result-hash / settlement transactions were observed on-chain.
Prints PENDING when there is none. It never invents anything: values come only from the payment service's confirmed state, stored by the gateway.

    python scripts/evidence.py [--state state/gateway] [--write docs/evidence/orders.json]
"""
import argparse, json, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPLORER = "https://preprod.cardanoscan.io/transaction/"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--state", default=str(ROOT / "state" / "gateway")); ap.add_argument("--write")
    a = ap.parse_args()
    db = Path(a.state) / "agroland.sqlite3"
    if not db.exists():
        sys.exit(f"no database at {db}")
    con = sqlite3.connect(db); con.row_factory = sqlite3.Row
    out = []
    for r in con.execute("SELECT * FROM orders ORDER BY created_at"):
        p = json.loads(r["payment"] or "{}")
        if p.get("mode") != "masumi" or not (p.get("funds_locked_tx") or p.get("result_confirmed_tx") or p.get("settlement_tx")):
            continue
        out.append({"order_id": r["id"], "service": r["service"], "country": r["country"], "channel": r["channel"], "external_task_or_job": r["external_ref"],
                    "price_units": r["price_amount"], "unit": r["price_unit"], "state": r["state"], "input_hash": r["input_hash"], "result_hash": r["result_hash"],
                    "blockchain_identifier": p.get("blockchain_identifier"), "funds_locked_tx": p.get("funds_locked_tx"), "result_hash_tx": p.get("result_confirmed_tx"),
                    "settlement_tx": p.get("settlement_tx"), "explorer": {k: EXPLORER + v for k, v in (("funds_locked", p.get("funds_locked_tx")), ("result_hash", p.get("result_confirmed_tx")), ("settlement", p.get("settlement_tx"))) if v}})
    if not out:
        print("PENDING: no order with an observed on-chain payment transaction exists in this database.")
        return
    print(json.dumps(out, indent=2))
    settled = [o for o in out if o["settlement_tx"]]
    print(f"\n{len(out)} order(s) with chain evidence; {len(settled)} with seller settlement. Verify seller receipt separately (Sokosumi receipt / Blockfrost) before submitting.")
    if a.write:
        Path(a.write).parent.mkdir(parents=True, exist_ok=True); Path(a.write).write_text(json.dumps(out, indent=2))


main()
