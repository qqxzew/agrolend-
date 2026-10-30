"""Live end-to-end test of the India audit agent: real locations in Gujarat and Andhra Pradesh, full JSON reports.

    python test_worker_india.py                      # in-process (payment bypass forced on, temp DB)
    python test_worker_india.py --url http://localhost:9000   # against a running worker

Needs internet access: it calls the real OSM Nominatim / Overpass, PVGIS and Open-Meteo endpoints.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import httpx

LOCATIONS = [
    {
        "name": "Wind + solar site - Kutch, Gujarat (open arid land near the Lakhpat/Abdasa wind belt)",
        "payload": {"lat": 23.3000, "lon": 69.5000, "radius_m": 400, "project_type": "hybrid"},
        "expect": "state IN-GJ, strong solar yield, wind > 5 m/s, no protected-area veto expected",
    },
    {
        "name": "Solar site - Anantapur district, Andhra Pradesh (Ananthapuramu solar belt)",
        "payload": {"lat": 14.6500, "lon": 77.6500, "radius_m": 300, "project_type": "solar", "survey_number": "245/2"},
        "expect": "state IN-AP, solar yield > 1500 kWh/kWp, land-record reference present",
    },
    {
        "name": "Forbidden site - inside Gir National Park, Gujarat",
        "payload": {"lat": 21.1300, "lon": 70.8000, "radius_m": 200, "project_type": "hybrid"},
        "expect": "environmental veto -> NO_GO (if OSM maps the park polygon here)",
    },
]


async def run(base_url: str | None) -> int:
    if base_url:
        client = httpx.AsyncClient(base_url=base_url, timeout=300)
        lifespan = None
    else:
        sys.path.insert(0, str(Path(__file__).parent))
        from india.audit.config import AuditSettings
        from india.audit.main import create_app

        tmp = tempfile.mkdtemp(prefix="india-audit-test-")
        app = create_app(AuditSettings(_env_file=None, bypass_payment=True, database_path=f"{tmp}/jobs.sqlite3"))
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=300)

    failures = 0
    try:
        print("availability:", (await client.get("/availability")).json())
        for loc in LOCATIONS:
            print("\n" + "=" * 100 + f"\n{loc['name']}\nexpect: {loc['expect']}\n" + "=" * 100)
            t0 = time.time()
            r = await client.post("/start_job", json=loc["payload"])
            if r.status_code != 200:
                print("start_job FAILED:", r.status_code, r.text)
                failures += 1
                continue
            job = r.json()
            if job["status"] != "completed":  # only when payment is enabled
                job = (await client.get("/status", params={"job_id": job["job_id"]})).json()
            print(f"job {job['job_id']} -> {job['status']} in {time.time() - t0:.1f}s")
            report = job.get("report")
            if not report:
                print("no report:", job)
                failures += 1
                continue
            print(json.dumps(report, indent=2, ensure_ascii=False))
            print(f"\n>>> VERDICT {report['overall_verdict']}  SCORE {report['score']}/100  hash={job['result_hash'][:16]}...")
            if "unavailable" in " ".join(report["data_quality"].values()):
                print("    (some data sources were unavailable - see data_quality)")
    finally:
        await client.aclose()
        if lifespan:
            await lifespan.__aexit__(None, None, None)
    return failures


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="base URL of a running worker (default: run in-process)")
    sys.exit(1 if asyncio.run(run(ap.parse_args().url)) else 0)
