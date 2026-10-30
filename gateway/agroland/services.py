"""Runners for the paid services Land Audit and Lease Check (Pool Access lives in pool.py)."""
from __future__ import annotations

import json
from datetime import date

from fastapi import HTTPException

from . import alkis, farm
from .db import Database
from .geoclient import Geo, in_country
from .parcels import get as get_parcel, largest_polygon

LIMITS_COMMON = [
    "Screening level only. This is not legal advice, not a planning permission, and not a grid-connection offer.",
    "Ownership is never verified. A listing or a parcel record in AgroLand does not transfer or prove any right to the land.",
    "A good verdict is not a universal guarantee: it is only as complete as the data-quality table says.",
]
VERDICT_TEXT = {"GO": "No blocking issue found by the checks that ran", "CONDITIONAL_GO": "Possible, but conditions apply", "NO_GO": "A blocking issue was found"}


def _exc(msg):
    return HTTPException(422, msg)


class LandAuditRunner:
    service = "land_audit"

    def __init__(self, db: Database, geo: dict[str, Geo]):
        self.db, self.geo = db, geo

    def validate(self, user, country, data):
        if user["country"] != country:
            raise _exc(f"Your workspace is set to {user['country']}; create a workspace for {country} to audit there")
        ptype = data.get("project_type", "hybrid")
        if ptype not in ("wind", "solar", "hybrid"):
            raise _exc("project_type must be wind, solar or hybrid")
        norm: dict = {"project_type": ptype}
        parcel_meta = None
        if data.get("parcel_id"):
            p = get_parcel(self.db, user["id"], data["parcel_id"])
            norm["polygon_geojson"] = largest_polygon(p["geometry"])
            parcel_meta = {"id": p["id"], "label": p["label"], "ref": p["ref"], "source": p["source"], "demo": p["demo"], "area_ha": p["area_ha"],
                           "split_parcel_note": "largest part audited" if p["geometry"]["type"] == "MultiPolygon" else None}
        elif data.get("polygon"):
            ring = data["polygon"].get("coordinates", [[]])[0]
            if not 4 <= len(ring) <= 500 or not all(in_country(country, y, x) for x, y in ring):
                raise _exc("Polygon must have 3-500 corners inside the selected country")
            norm["polygon_geojson"] = data["polygon"]
            parcel_meta = {"id": None, "label": "Drawn site", "ref": None, "source": "drawn", "demo": False}
        elif data.get("lat") is not None and data.get("lon") is not None:
            lat, lon = float(data["lat"]), float(data["lon"])
            if not in_country(country, lat, lon):
                raise _exc(f"The point is outside {'Germany' if country == 'DE' else 'India'}")
            norm.update(lat=lat, lon=lon, radius_m=float(data.get("radius_m", 300)))
            parcel_meta = {"id": None, "label": f"Point {lat:.4f}, {lon:.4f} (r={norm['radius_m']:.0f} m)", "ref": None, "source": "point", "demo": False}
        else:
            raise _exc("Choose a saved parcel, draw an outline, or mark a point")
        if country == "IN":
            if data.get("survey_number"):
                norm["survey_number"] = str(data["survey_number"])[:40]
            if data.get("ulpin"):
                norm["ulpin"] = str(data["ulpin"]).strip()
        norm["parcel"] = parcel_meta
        return norm, parcel_meta["label"]

    def ready(self, order):
        return True, None

    def execute(self, order):
        inp = order["input"]
        body = {k: v for k, v in inp.items() if k != "parcel"}
        audit = self.geo[order["country"]].audit(body)
        quality = audit.get("data_quality", {})
        unavailable = sorted(k for k, v in quality.items() if str(v).startswith("unavailable"))
        signal = None
        if order["country"] == "DE" and inp["parcel"].get("source") == "alkis-demo" and inp["parcel"].get("ref") in alkis.BY_ID:
            a = alkis.analyze(inp["parcel"]["ref"])
            signal = {k: a[k] for k in ("geometry_signal", "corridors", "distance_to_axis_m", "measurement_crs", "reference", "rule_version", "sources", "limitations", "legal_status")}
        return {
            "subject": inp["parcel"], "project_type": inp["project_type"], "country": order["country"],
            "audit_conclusion": {"verdict": audit["overall_verdict"], "score": audit["score"], "meaning": VERDICT_TEXT[audit["overall_verdict"]],
                                 "assessed_technology": audit.get("assessed_technology"), "technology_assessment": audit["technology_assessment"], "warnings": audit["warnings"]},
            "geometric_signal": signal,
            "data_quality": {"complete": not unavailable, "unavailable_checks": unavailable, "per_check": quality,
                             "note": "An unavailable source is a limitation, never a pass." if unavailable else "All configured sources answered. An answering source can still be incomplete (for example OpenStreetMap coverage): read the warnings."},
            "site_facts": {k: audit[k] for k in audit if k in ("location_info", "grid_access", "regulatory_checks", "environmental_veto", "resource_potential", "land_record")},
            "limitations": LIMITS_COMMON + (["Corridor signal uses OSM road axes, not the legally required outer edge."] if signal else []),
            "methodology": audit.get("methodology"),
        }

    def markdown(self, order, r):
        a, q = r["audit_conclusion"], r["data_quality"]
        lines = [f"# Land Audit - {r['subject']['label']}", f"Country: {r['country']} | Project: {r['project_type']}", "",
                 f"## Audit conclusion: **{a['verdict']}** (score {a['score']}/100)", f"{a['meaning']}.", ""]
        for t, v in a["technology_assessment"].items():
            lines.append(f"- **{t}**: {v['verdict']} ({v['score']}/100)" + (f" - blockers: {'; '.join(v['blockers'])}" if v.get("blockers") else "") + (f" - conditions: {'; '.join(v['conditions'])}" if v.get("conditions") else ""))
        if r["geometric_signal"]:
            g = r["geometric_signal"]
            lines += ["", f"## Preliminary geometric signal: **{g['geometry_signal']}**", f"Distance to motorway axis: {g['distance_to_axis_m']} m. 200 m corridor: {g['corridors']['200']['coverage']}; 500 m corridor: {g['corridors']['500']['coverage']}.", f"_{g['reference']}_"]
        lines += ["", f"## Data quality: {'complete' if q['complete'] else 'INCOMPLETE'}", q["note"]]
        for k, v in q["per_check"].items():
            lines.append(f"- {k}: {v}")
        if a["warnings"]:
            lines += ["", "## Warnings"] + [f"- {w}" for w in a["warnings"]]
        lines += ["", "## Limits"] + [f"- {x}" for x in r["limitations"]]
        return "\n".join(lines)


class LeaseCheckRunner:
    service = "lease_check"

    def __init__(self, db: Database):
        self.db = db

    def validate(self, user, country, data):
        if user["country"] != country:
            raise _exc(f"Your workspace is set to {user['country']}")
        try:
            if data.get("source") == "inline":  # MIP-003 jobs: the dataset was validated by farm.build_dataset in the router
                dataset = data["dataset"]
            elif data.get("source") == "saved":
                with self.db.tx() as c:
                    r = c.execute("SELECT * FROM farm_datasets WHERE user_id=?", (user["id"],)).fetchone()
                if not r:
                    raise _exc("No farm data saved yet")
                dataset = json.loads(r["payload"])
            else:
                dataset = farm.load_demo(country)
        except farm.DataError as exc:
            raise _exc(str(exc))
        if dataset["settings"].get("country") != country:
            raise _exc("The saved farm data belongs to another country")
        s = dataset["settings"]
        return {"dataset": dataset, "today": date.today().isoformat(), "demo": dataset["settings"].get("farm_name", "").endswith("(demo)") or s["farm_name"] == "Hans Farm"}, \
            f"{s['farm_name']} - {len(dataset['contracts'])} leases"

    def ready(self, order):
        return True, None

    def execute(self, order):
        inp = order["input"]
        rep = farm.full_report(inp["dataset"], inp["today"])
        if rep["verification"]["status"] != "pass":
            raise RuntimeError("Report failed its own recomputation; not delivered")
        rep["limitations"] = LIMITS_COMMON[:1] + inp["dataset"]["settings"].get("legal_notes", []) + [
            "'Identified' items follow from your own documents. 'Negotiable' items are opportunities against a benchmark, not losses. "
            "Savings 'achieved' are only what you record after acting."]
        return rep

    def markdown(self, order, r):
        s, m, c = r["summary"], r["meta"], r["meta"]["currency"]
        cur = lambda n: f"{c} {n:,.0f}" if float(n).is_integer() else f"{c} {n:,.2f}"  # noqa: E731
        lines = [f"# Lease Check - {m['farm_name']} ({m['country']})", f"{s['contracts_count']} leases, {s['total_area_contract']} {m['area_unit']}, rent {cur(s['total_rent_per_year'])}/year (as of {m['today']}).", "",
                 f"- **Identified from your documents:** {cur(s['identified_per_year'])}/year",
                 f"- **Negotiation opportunity:** up to {cur(s['negotiable_per_year'])}/year (not a confirmed loss)",
                 f"- **Savings achieved:** {cur(s['achieved_per_year'])} (recorded by you after acting)",
                 f"- Verification: **{r['verification']['status']}** ({r['verification']['checked_findings']} findings recomputed)", "", "## Findings"]
        for f in r["findings"]:
            lines.append(f"- [{f['category']}] {f['explanation']}")
        if s["expiring_contracts"]:
            lines += ["", "## Deadlines"] + [f"- {e['contract_id']} ends {e['end_date']} ({e['days_left']} days)" for e in s["expiring_contracts"]]
        if r["warnings"]:
            lines += ["", "## Warnings"] + [f"- {w}" for w in r["warnings"]]
        lines += ["", "## Limits"] + [f"- {x}" for x in r["limitations"]]
        return "\n".join(lines)
