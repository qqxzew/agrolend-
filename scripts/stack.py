"""Process definitions for the whole AgroLand stack, shared by `scripts/dev.py` (local run) and the integration tests.

Internal services bind to 127.0.0.1 and run with payment bypass ON: money is handled only by the gateway's orders.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEO = ROOT / "services" / "geo"


def keys(env=os.environ) -> dict:
    g = lambda k: env.get(k) or secrets.token_hex(24)  # noqa: E731
    return {k: g(k) for k in ("GEO_DE_INTERNAL_KEY", "GEO_DE_ESCROW_KEY", "GEO_DE_ARCHITECT_KEY", "GEO_IN_INTERNAL_KEY", "GEO_IN_ESCROW_KEY", "GEO_IN_ARCHITECT_KEY", "AGROLAND_INTERNAL_KEY")}


def geo_processes(state: Path, k: dict, de_ports=(8000, 8001, 8002, 8003), in_ports=(9000, 9001, 9002, 9003), countries=("DE", "IN"), audit_module_de="app.main:app") -> list[dict]:
    """[{name, args, env, cwd}] for the internal geo services."""
    py = sys.executable
    procs = []
    base = {"PYTHONDONTWRITEBYTECODE": "1", "PATH": os.environ.get("PATH", "")}
    if "DE" in countries:
        a, m, e, r = de_ports
        di, de_, dr = k["GEO_DE_INTERNAL_KEY"], k["GEO_DE_ESCROW_KEY"], k["GEO_DE_ARCHITECT_KEY"]
        procs += [
            {"name": "de-audit", "port": a, "mod": audit_module_de, "env": {**base, "INTERNAL_API_KEY": di, "BYPASS_PAYMENT": "true", "DATABASE_PATH": str(state / "de_jobs.sqlite3")}},
            {"name": "de-matcher", "port": m, "mod": "matcher.main:app", "env": {**base, "VALIDATOR_URL": f"http://127.0.0.1:{a}", "VALIDATOR_API_KEY": di, "MATCHER_API_KEY": di, "MATCHER_DATABASE_PATH": str(state / "de_matcher.sqlite3")}},
            {"name": "de-escrow", "port": e, "mod": "escrow.main:app", "env": {**base, "MATCHER_URL": f"http://127.0.0.1:{m}", "MATCHER_API_KEY": di, "ESCROW_API_KEY": de_, "ESCROW_DATABASE_PATH": str(state / "de_escrow.sqlite3"), "ESCROW_BYPASS_PAYMENT": "true"}},
            {"name": "de-architect", "port": r, "mod": "architect.main:app", "env": {**base, "ESCROW_URL": f"http://127.0.0.1:{e}", "ESCROW_API_KEY": de_, "ARCHITECT_API_KEY": dr, "ARCHITECT_DATABASE_PATH": str(state / "de_architect.sqlite3")}},
        ]
    if "IN" in countries:
        a, m, e, r = in_ports
        ii, ie, ir = k["GEO_IN_INTERNAL_KEY"], k["GEO_IN_ESCROW_KEY"], k["GEO_IN_ARCHITECT_KEY"]
        procs += [
            {"name": "in-audit", "port": a, "mod": "india.audit.main:app", "env": {**base, "IN_AUDIT_INTERNAL_API_KEY": ii, "IN_AUDIT_BYPASS_PAYMENT": "true", "IN_AUDIT_DATABASE_PATH": str(state / "in_jobs.sqlite3")}},
            {"name": "in-matcher", "port": m, "mod": "india.matcher.main:app", "env": {**base, "IN_MATCHER_VALIDATOR_URL": f"http://127.0.0.1:{a}", "IN_MATCHER_VALIDATOR_API_KEY": ii, "IN_MATCHER_API_KEY": ii, "IN_MATCHER_DATABASE_PATH": str(state / "in_matcher.sqlite3")}},
            {"name": "in-escrow", "port": e, "mod": "india.escrow.main:app", "env": {**base, "IN_ESCROW_MATCHER_URL": f"http://127.0.0.1:{m}", "IN_ESCROW_MATCHER_API_KEY": ii, "IN_ESCROW_API_KEY": ie, "IN_ESCROW_DATABASE_PATH": str(state / "in_escrow.sqlite3"), "IN_ESCROW_BYPASS_PAYMENT": "true"}},
            {"name": "in-architect", "port": r, "mod": "india.architect.main:app", "env": {**base, "IN_ARCHITECT_ESCROW_URL": f"http://127.0.0.1:{e}", "IN_ARCHITECT_ESCROW_API_KEY": ie, "IN_ARCHITECT_API_KEY": ir, "IN_ARCHITECT_DATABASE_PATH": str(state / "in_architect.sqlite3")}},
        ]
    for p in procs:
        p["args"] = [py, "-m", "uvicorn", p["mod"], "--host", "127.0.0.1", "--port", str(p["port"]), "--log-level", "warning"]
        p["cwd"] = str(GEO)
    return procs


def gateway_env(k: dict, state: Path, port: int, de_ports=(8000, 8001, 8002, 8003), in_ports=(9000, 9001, 9002, 9003)) -> dict:
    u = lambda p: f"http://127.0.0.1:{p}"  # noqa: E731
    return {
        "AGROLAND_STATE_DIR": str(state / "gateway"), "AGROLAND_INTERNAL_KEY": k["AGROLAND_INTERNAL_KEY"],
        "GEO_DE_AUDIT_URL": u(de_ports[0]), "GEO_DE_MATCHER_URL": u(de_ports[1]), "GEO_DE_ESCROW_URL": u(de_ports[2]), "GEO_DE_ARCHITECT_URL": u(de_ports[3]),
        "GEO_DE_INTERNAL_KEY": k["GEO_DE_INTERNAL_KEY"], "GEO_DE_ESCROW_KEY": k["GEO_DE_ESCROW_KEY"], "GEO_DE_ARCHITECT_KEY": k["GEO_DE_ARCHITECT_KEY"],
        "GEO_IN_AUDIT_URL": u(in_ports[0]), "GEO_IN_MATCHER_URL": u(in_ports[1]), "GEO_IN_ESCROW_URL": u(in_ports[2]), "GEO_IN_ARCHITECT_URL": u(in_ports[3]),
        "GEO_IN_INTERNAL_KEY": k["GEO_IN_INTERNAL_KEY"], "GEO_IN_ESCROW_KEY": k["GEO_IN_ESCROW_KEY"], "GEO_IN_ARCHITECT_KEY": k["GEO_IN_ARCHITECT_KEY"],
        "AGROLAND_PUBLIC_URL": f"http://127.0.0.1:{port}",
    }
