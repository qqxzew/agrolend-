#!/usr/bin/env python3
"""Walks one complete two-party pool deal on a RUNNING gateway using the workspaces from state/demo-tokens.json (see seed_demo.py).
Both parties are driven by this script for a demonstration; in the product each party acts in its own browser session.
In `masumi` payment mode the script stops at the payment step and tells you what to pay; in `dev-unpaid` mode it continues.

    python scripts/walk_deal.py --country DE
"""
import argparse, hashlib, json, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8080"


def call(token, path, method="GET", body=None, raw=False):
    req = urllib.request.Request(URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = r.read()
            return d if raw else json.loads(d or b"null")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode()[:300]}")


def main():
    global URL
    ap = argparse.ArgumentParser(); ap.add_argument("--country", default="DE"); ap.add_argument("--url", default=URL); a = ap.parse_args(); URL = a.url
    tk = json.loads((ROOT / "state" / "demo-tokens.json").read_text())
    A, B = tk[f"{a.country}_developer"]["token"], tk[f"{a.country}_developer_counterpart"]["token"]
    teasers = call(A, "/api/pool/teasers")
    if not teasers:
        sys.exit("no teaser yet: the matcher found no neighbour")
    mid = teasers[0]["match_id"]
    print("teaser (anonymous):", json.dumps(teasers[0])[:300])
    prof = {"DE": lambda n, e: {"company_name": n, "street": "Musterstraße 1", "postal_code": "39104", "city": "Magdeburg", "representative": "Anna Müller, Geschäftsführerin", "commercial_register": "AG Stendal HRB 1 (demo)", "email": e, "phone": "+49 391 000"},
            "IN": lambda n, e: {"company_name": n, "address": "Plot 4, Industrial Area, Bhuj", "state": "Gujarat", "pin_code": "370001", "representative": "Meera Shah, Director", "registration_no": "U00000GJ2020PTC000000 (demo)", "gstin": "", "email": e, "phone": "+91 98000 00000"}}[a.country]
    call(A, "/api/pool/profile", "PUT", prof(tk[f"{a.country}_developer"]["name"], "a@demo.invalid"))
    call(A, f"/api/pool/deals/{mid}/consent", "POST", {"decision": "accept"})
    d = call(B, f"/api/pool/deals/{mid}/consent", "POST", {"decision": "accept"})
    print("both consented ->", d["status"], "| price", d["order"]["price"]["display"])
    for tok in (A, B):
        deal = call(tok, f"/api/pool/deals/{mid}")
        o = call(tok, f"/api/orders/{deal['order']['id']}/pay", "POST")
        if o["payment"]["mode"] == "masumi":
            sys.exit(f"masumi mode: lock {o['price']['display']} for identifier {o['payment']['blockchain_identifier']} and re-run to continue")
    nda = call(A, f"/api/pool/deals/{mid}/nda.pdf", raw=True)
    sha = hashlib.sha256(nda).hexdigest()
    for tok, nm in ((A, "Anna Müller"), (B, "Jörg Schäfer")):
        call(tok, f"/api/pool/deals/{mid}/sign", "POST", {"signer_name": nm, "signer_role": "Director", "document_sha256": sha, "accept": True})
    print("both signed NDA", sha[:16])
    oid = call(A, f"/api/pool/deals/{mid}")["order"]["id"]
    for _ in range(60):
        o = call(A, f"/api/orders/{oid}")
        if o["state"] == "delivered":
            break
        time.sleep(2)
    res = call(A, f"/api/orders/{oid}/result")["report"]
    print("disclosed counterpart:", res["disclosure"]["counterpart"]["company"]["company_name"])
    plan = res["joint_plan"]["plan"]
    print("viable:", plan.get("viable"), "| pooling beneficial:", plan.get("pooling_beneficial"), "| joint NPV:", plan["joint_project"].get("npv_eur"))
    print("shares (basis points):", plan.get("shares_bp"), "| method applied:", plan.get("method_applied"), "| warnings:", plan.get("warnings"))
    print("documents:", [(x["kind"], x["sha256"][:12]) for x in res["documents"]])


main()
