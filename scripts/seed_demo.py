#!/usr/bin/env python3
"""Creates the reproducible demonstration workspaces on a RUNNING gateway, for both countries, and writes their tokens to state/demo-tokens.json (0600).

Everything created here is labelled demo: the farms, owners and contracts are fictional, the Magdeburg parcels are real open ALKIS geometry with no owner
information, the India parcels are illustrative rectangles. It calls the real API; it does not pay for anything. Re-running creates NEW workspaces.

    python scripts/seed_demo.py --url http://127.0.0.1:8080 [--pool]     # --pool also registers developer sites (real audits, takes minutes)
"""
import argparse, json, os, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))


def call(url, path, token=None, method="GET", body=None):
    req = urllib.request.Request(url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=400) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode()[:300]}")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--url", default="http://127.0.0.1:8080"); ap.add_argument("--pool", action="store_true"); a = ap.parse_args()
    from agroland import alkis
    tokens = {}
    def ws(key, name, role, country):
        r = call(a.url, "/api/session", method="POST", body={"name": name, "role": role, "country": country})
        tokens[key] = {"name": name, "role": role, "country": country, "token": r["token"], "id": r["user"]["id"]}
        return r["token"]
    for c, owner, farm, dev in (("DE", "Maria Beispiel (demo)", "Hans Farm (demo)", "Windkraft Nord GmbH (demo)"), ("IN", "Ramesh Patel (demo owner)", "Patel Agro Farms (demo)", "Vayu Wind Energy Pvt Ltd (demo)")):
        t = ws(f"{c}_owner", owner, "owner", c)
        call(a.url, "/api/parcels", t, "POST", {"source": "alkis-demo", "ref": alkis.demo_id()} if c == "DE" else {"source": "in-demo", "ref": "IN-DEMO-3"})
        ws(f"{c}_farm", farm, "farm", c)
        t = ws(f"{c}_developer", dev, "developer", c)
        p = call(a.url, "/api/parcels", t, "POST", {"source": "alkis-demo", "ref": alkis.demo_id()} if c == "DE" else {"source": "in-demo", "ref": "IN-DEMO-1"})
        if a.pool:
            print(f"{c}: registering the developer site (real audit through the matcher; this can take a few minutes)...")
            reg = call(a.url, "/api/pool/portfolio", t, "POST", {"parcel_id": p["id"], "project_type": "wind"})
            print("  ", reg["status"], reg.get("reasons") or "")
            if reg["status"] == "registered":
                cp = call(a.url, "/api/demo/counterpart", t, "POST", {"pool_parcel_id": reg["id"]})
                tokens[f"{c}_developer_counterpart"] = {"name": cp["user"]["name"], "role": "developer", "country": c, "token": cp["token"], "id": cp["user"]["id"]}
    out = ROOT / "state" / "demo-tokens.json"
    out.parent.mkdir(exist_ok=True); out.write_text(json.dumps(tokens, indent=2)); os.chmod(out, 0o600)
    print(f"Wrote {out} ({len(tokens)} workspaces). To use one in the browser console:\n  const s={{list:[],current:null}}; /* then push {{...user, token}} and set current */")
    print("Easier: open the app and create workspaces by hand, or paste a token with:  localStorage.setItem('agroland.workspaces.v1', JSON.stringify({list:[{id,name,role,country,token}],current:id}))")


main()
