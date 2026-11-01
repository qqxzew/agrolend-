#!/usr/bin/env python3
"""Pre-flight check before enabling payments. Reads .env (or the environment) and probes the running gateway. Prints what is missing; changes nothing.

    python scripts/preflight.py [--url http://127.0.0.1:8080]
"""
import argparse, json, os, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ["AGROLAND_PUBLIC_URL", "AGROLAND_INTERNAL_KEY", "GEO_DE_INTERNAL_KEY", "GEO_DE_ESCROW_KEY", "GEO_DE_ARCHITECT_KEY", "GEO_IN_INTERNAL_KEY", "GEO_IN_ESCROW_KEY", "GEO_IN_ARCHITECT_KEY",
            "MPS_URL", "MPS_RUNTIME_TOKEN", "SELLER_VKEY", "AGENT_IDENTIFIER_LAND_AUDIT", "AGENT_IDENTIFIER_LEASE_CHECK", "AGENT_IDENTIFIER_POOL_ACCESS", "BLOCKFROST_API_KEY_PREPROD"]


def dotenv(path):
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); out[k.strip()] = v.split("#")[0].strip().strip('"')
    return out


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return r.status, json.loads(r.read() or b"{}")
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)[:120]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--url", default="http://127.0.0.1:8080"); a = ap.parse_args()
    env = {**dotenv(ROOT / ".env"), **os.environ}
    bad = 0
    def check(ok, msg, hint=""):
        nonlocal bad
        print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"  -> {hint}")); bad += 0 if ok else 1
    print("Configuration")
    print("  ok   OPENAI_API_KEY (home-page assistant)" if env.get("OPENAI_API_KEY") else "  note OPENAI_API_KEY is empty: the home-page chat falls back to keyword routing (optional)")
    for k in REQUIRED:
        check(bool(env.get(k)), k, "set it in .env")
    check(env.get("AGROLAND_PAYMENT_MODE", "masumi") == "masumi", "AGROLAND_PAYMENT_MODE is masumi", "dev-unpaid must never serve a demo")
    check(env.get("AGROLAND_PUBLIC_URL", "").startswith("https://"), "public URL is https", "Masumi buyers and Sokosumi need a public https URL")
    print("Gateway", a.url)
    code, h = get(a.url + "/api/health")
    check(code == 200, "gateway reachable", "start the stack")
    if code == 200:
        check(h["payment_mode"] == "masumi", "gateway runs in masumi payment mode", "")
        for c, s in h["geo"].items():
            check(all(s.values()), f"geo services {c}: {s}", "a geo service is down; see logs")
        check(all(h["agents_registered"].values()), f"agents registered: {h['agents_registered']}", "run `npm run register`, wait for confirmation, then `npm run register:status`")
    for svc in ("land_audit", "lease_check"):
        code, j = get(f"{a.url}/masumi/{svc}/availability")
        check(code == 200 and j.get("status") == "available", f"MIP-003 /masumi/{svc}/availability = {j.get('status')}", "needs the registered identifier and masumi mode")
    mps = env.get("MPS_URL", "")
    if mps:
        code, _ = get(mps.rstrip("/") + "/api/v1/health")
        check(code == 200, "payment service health", "start masumi-payment-service")
    print("\nRESULT:", "READY" if bad == 0 else f"{bad} item(s) missing")
    sys.exit(1 if bad else 0)


main()
