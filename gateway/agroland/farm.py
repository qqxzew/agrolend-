"""Lease Check engine: deterministic, country-aware, no language model.

Ported from the maintained AgroLand backend (itself a port of the original `case3-farm` JavaScript; both give identical numbers on
the German demo data, see tests/test_farm.py). Generalised so that units, currency and benchmark come from the dataset settings, which
lets one engine serve Germany (ha, EUR) and India (acre, INR).

Every finding carries the numbers and source rows it came from, and `verify_report` recomputes each of them from the source rows.
The service is considered delivered correctly only when verification passes.

Vocabulary used in the product:
  identified   - a discrepancy that follows from the user's own documents (paid but not farmed, billed area above the official record)
  negotiable   - an opportunity (rent above the benchmark); not a loss until renegotiated
  achieved     - savings the user records after acting; never computed by the engine
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "farm"
# Demonstration farms per country; the first one is the default. "in-mh" has real 5am.earth field boundaries (boundaries.geojson).
DEMOS = {"DE": ["de"], "IN": ["in", "in-mh"]}
RULES = ["paid_not_farmed", "area_mismatch", "above_market_rent", "expiring_soon"]
COLS = {
    "contracts": ["contract_id", "owner", "parcel_id", "area_contract", "rent_per_unit", "start_date", "end_date", "payment_due"],
    "cadastre": ["parcel_id", "area_cadastre", "land_use"],
    "fields": ["field_id", "parcel_id", "crop"],
}
MAX_ROWS = 500


class DataError(ValueError):
    pass


def _clean(x):
    return int(x) if float(x).is_integer() else x


def round2(x):
    return _clean(math.floor(x * 100 + 0.5) / 100)  # floor(x+.5): same rounding as the original JS Math.round


def money(n, s):
    sym = s["currency_symbol"]
    return f"{sym}{int(n):,}" if float(n).is_integer() else f"{sym}{n:,.2f}"


def area(n, s):
    t = f"{n:,.2f}"
    return (t[:-1] if t.endswith("0") else t) + f" {s['area_unit']}"


def parse_csv(text: str, name: str) -> list[dict]:
    try:
        rows = list(csv.reader(io.StringIO(str(text).strip("\ufeff\n "))))
    except csv.Error as exc:
        raise DataError(f"{name}: not a readable CSV file ({exc})")
    if not rows:
        raise DataError(f"{name}: empty file")
    header = [c.strip() for c in rows[0]]
    if header != COLS[name]:
        raise DataError(f"{name}: header must be exactly {','.join(COLS[name])}")
    out = []
    for i, cells in enumerate(rows[1:], 2):
        if not any(c.strip() for c in cells):
            continue
        if len(cells) != len(header):
            raise DataError(f"{name}:{i}: expected {len(header)} columns, got {len(cells)}")
        out.append({"line": i, **{h: c.strip() for h, c in zip(header, cells)}})
    if len(out) > MAX_ROWS:
        raise DataError(f"{name}: at most {MAX_ROWS} rows")
    return out


def _num(row, col, name):
    try:
        v = float(row[col])
    except ValueError:
        raise DataError(f'{name}:{row["line"]}: "{col}" is not a number')
    if not math.isfinite(v) or v < 0:
        raise DataError(f'{name}:{row["line"]}: "{col}" must be a non-negative number')
    return _clean(v)


def build_dataset(contracts_csv: str, cadastre_csv: str, fields_csv: str, settings: dict) -> dict:
    """Validated dataset in the shape the engine and the order input use."""
    for k in ("currency", "currency_symbol", "area_unit", "benchmark_rent_per_unit", "overpriced_threshold_pct", "area_tolerance",
              "expiry_window_days", "payment_alarm_days_before", "expiry_reminder_days_before_end", "farm_name", "region", "country"):
        if k not in settings:
            raise DataError(f"settings.{k} is missing")
    contracts = []
    for r in parse_csv(contracts_csv, "contracts"):
        if not re.fullmatch(r"\d{2}-\d{2}", r["payment_due"]):
            raise DataError(f'contracts:{r["line"]}: payment_due must be MM-DD')
        try:
            date.fromisoformat(r["start_date"]); date.fromisoformat(r["end_date"])
        except ValueError:
            raise DataError(f'contracts:{r["line"]}: dates must be YYYY-MM-DD')
        contracts.append({**r, "area_contract": _num(r, "area_contract", "contracts"),
                          "rent_per_unit": None if r["rent_per_unit"] == "" else _num(r, "rent_per_unit", "contracts")})
    cadastre = [{**r, "area_cadastre": _num(r, "area_cadastre", "cadastre")} for r in parse_csv(cadastre_csv, "cadastre")]
    fields = parse_csv(fields_csv, "fields")
    return {"contracts": contracts, "cadastre": cadastre, "fields": fields, "settings": settings}


def load_demo(country: str, demo: str | None = None) -> dict:
    ids = DEMOS.get(country.upper(), [country.lower()])
    if demo not in (None, "", *ids):
        raise DataError(f"unknown demonstration farm {demo!r} for {country}")
    d = DATA / (demo or ids[0])
    ds = build_dataset((d / "contracts.csv").read_text("utf-8"), (d / "cadastre.csv").read_text("utf-8"),
                       (d / "fields.csv").read_text("utf-8"), json.loads((d / "settings.json").read_text("utf-8")))
    if (d / "boundaries.geojson").exists():  # field outlines (demo files are trusted; uploads go through cropwatch.validate_boundaries)
        fc = json.loads((d / "boundaries.geojson").read_text("utf-8"))
        ds["boundaries"] = {"type": "FeatureCollection", "features": fc["features"]}
    return ds


def demo_list(country: str) -> list[dict]:
    out = []
    for i in DEMOS.get(country.upper(), []):
        ds = load_demo(country, i)
        feats = (ds.get("boundaries") or {}).get("features", [])
        out.append({"id": i, "farm_name": ds["settings"]["farm_name"], "region": ds["settings"]["region"], "leases": len(ds["contracts"]),
                    "boundaries": len(feats), "registry_linked": sum(1 for f in feats if f["properties"].get("registry"))})
    return out


def rent_of(c, s):
    return s["benchmark_rent_per_unit"] if c["rent_per_unit"] is None else c["rent_per_unit"]


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def finding(kind, c, data, today):
    """Check one rule against one contract straight from the source rows (used by analyze and verify_report)."""
    s = data["settings"]
    rent = rent_of(c, s)
    farmed = any(f["parcel_id"] == c["parcel_id"] for f in data["fields"])
    cad = next((p for p in data["cadastre"] if p["parcel_id"] == c["parcel_id"]), None)
    src = [{"file": "contracts", "line": c["line"]}]

    def make(category, amount, numbers, text, extra=()):
        return {"type": kind, "category": category, "contract_id": c["contract_id"], "parcel_id": c["parcel_id"], "owner": c["owner"],
                "explanation": text, "numbers": numbers, "amount_per_year": amount, "source": src + list(extra)}

    if kind == "paid_not_farmed":
        if farmed:
            return None
        amt = round2(c["area_contract"] * rent)
        return make("identified", amt, {"area_contract": c["area_contract"], "rent_per_unit": rent, "farmed": False},
                    f"You pay {money(amt, s)}/year for parcel {c['parcel_id']} ({area(c['area_contract'], s)}) under lease {c['contract_id']}, "
                    f"but it is not on your list of farmed fields.", [{"file": "fields", "line": None, "note": "parcel not listed"}])
    if kind == "area_mismatch":
        if not farmed or not cad:
            return None
        diff = round2(c["area_contract"] - cad["area_cadastre"])
        if diff <= s["area_tolerance"]:
            return None
        amt = round2(diff * rent)
        return make("identified", amt, {"area_contract": c["area_contract"], "area_cadastre": cad["area_cadastre"], "diff": diff, "rent_per_unit": rent},
                    f"Lease {c['contract_id']} bills {area(c['area_contract'], s)}, but the {s['record_name']} records only "
                    f"{area(cad['area_cadastre'], s)} - you pay {money(amt, s)}/year for {area(diff, s)} that the record does not show.",
                    [{"file": "cadastre", "line": cad["line"]}])
    if kind == "above_market_rent":
        avg = s["benchmark_rent_per_unit"]
        if not farmed or rent <= avg * (1 + s["overpriced_threshold_pct"] / 100):
            return None
        amt = round2((rent - avg) * c["area_contract"])
        return make("negotiable", amt, {"area_contract": c["area_contract"], "rent_per_unit": rent, "benchmark_rent_per_unit": avg,
                                        "threshold_pct": s["overpriced_threshold_pct"]},
                    f"Lease {c['contract_id']} costs {money(rent, s)}/{s['area_unit']} vs. the {money(avg, s)}/{s['area_unit']} benchmark - "
                    f"renegotiating could save up to {money(amt, s)}/year (an opportunity, not a confirmed loss).",
                    [{"file": "settings", "line": None, "note": "benchmark_rent_per_unit (labelled demo value)"}])
    if kind == "expiring_soon":
        days = _days(today, c["end_date"])
        if days < 0 or days > s["expiry_window_days"]:
            return None
        return make("expiring", 0, {"end_date": c["end_date"], "today": today, "days_left": days, "window_days": s["expiry_window_days"]},
                    f"Lease {c['contract_id']} with {c['owner']} ends on {c['end_date']} (in {days} days) - renegotiate or extend now.")
    raise ValueError(f"unknown finding type: {kind}")


def analyze(data, today: str):
    s = data["settings"]
    findings = [f for kind in RULES for c in data["contracts"] if (f := finding(kind, c, data, today))]
    total = lambda rows: round2(sum(f["amount_per_year"] for f in rows))  # noqa: E731
    identified = total([f for f in findings if f["category"] == "identified"])
    warnings = [f"contracts:{c['line']}: parcel {c['parcel_id']} not found in the official record extract (cannot compare area)"
                for c in data["contracts"] if not any(p["parcel_id"] == c["parcel_id"] for p in data["cadastre"])]
    parcels = []
    for c in data["contracts"]:
        cad = next((p for p in data["cadastre"] if p["parcel_id"] == c["parcel_id"]), None)
        parcels.append({"parcel_id": c["parcel_id"], "contract_id": c["contract_id"], "owner": c["owner"], "area_contract": c["area_contract"],
                        "area_cadastre": cad["area_cadastre"] if cad else None, "farmed": any(f["parcel_id"] == c["parcel_id"] for f in data["fields"]),
                        "finding_types": [f["type"] for f in findings if f["contract_id"] == c["contract_id"]]})
    return {
        "meta": {"farm_name": s["farm_name"], "region": s["region"], "country": s["country"], "currency": s["currency"], "area_unit": s["area_unit"],
                 "today": today, "benchmark_rent_per_unit": s["benchmark_rent_per_unit"], "benchmark_note": s["benchmark_note"],
                 "record_name": s["record_name"], "rules": RULES, "legal_notes": s.get("legal_notes", [])},
        "summary": {"contracts_count": len(data["contracts"]), "total_area_contract": round2(sum(c["area_contract"] for c in data["contracts"])),
                    "total_rent_per_year": round2(sum(c["area_contract"] * rent_of(c, s) for c in data["contracts"])),
                    "identified_per_year": identified, "negotiable_per_year": total([f for f in findings if f["category"] == "negotiable"]),
                    "achieved_per_year": 0,  # savings actually achieved are recorded by the user, never computed here
                    "expiring_contracts": [{"contract_id": f["contract_id"], "owner": f["owner"], "parcel_id": f["parcel_id"],
                                            "end_date": f["numbers"]["end_date"], "days_left": f["numbers"]["days_left"]} for f in findings if f["type"] == "expiring_soon"]},
        "findings": findings, "parcels": parcels, "warnings": warnings,
    }


def _same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def verify_report(report, data, today: str) -> dict:
    """Recompute every claimed finding from the source rows. 'pass' means the report is exactly what the rules produce."""
    reasons, seen = [], set()
    findings = report.get("findings") if isinstance(report, dict) else None
    if not isinstance(findings, list):
        reasons.append("report has no findings array")
        findings = []
    for f in findings:
        if not isinstance(f, dict):
            reasons.append("finding is not an object"); continue
        key = f"{f.get('type')}:{f.get('contract_id')}"
        if key in seen:
            reasons.append(f"{key}: duplicate finding"); continue
        seen.add(key)
        c = next((x for x in data["contracts"] if x["contract_id"] == f.get("contract_id")), None)
        if not c:
            reasons.append(f"{key}: contract not found"); continue
        try:
            fresh = finding(f.get("type"), c, data, today)
        except ValueError as exc:
            reasons.append(f"{key}: {exc}"); continue
        if not fresh:
            reasons.append(f"{key}: source data does not support this finding"); continue
        for k in ("parcel_id", "owner", "category", "amount_per_year", "explanation"):
            if not _same(f.get(k), fresh[k]):
                reasons.append(f"{key}: {k} is {json.dumps(f.get(k), ensure_ascii=False)}, recomputed {json.dumps(fresh[k], ensure_ascii=False)}")
        nums = f.get("numbers") if isinstance(f.get("numbers"), dict) else {}
        for n in fresh["numbers"].keys() | nums.keys():
            if not _same(nums.get(n), fresh["numbers"].get(n)):
                reasons.append(f"{key}: numbers.{n} is {json.dumps(nums.get(n))}, recomputed {json.dumps(fresh['numbers'].get(n))}")
    truth = analyze(data, today)
    reasons += [f"{f['type']}:{f['contract_id']}: finding missing from report" for f in truth["findings"] if f"{f['type']}:{f['contract_id']}" not in seen]
    summary = report.get("summary") if isinstance(report, dict) and isinstance(report.get("summary"), dict) else {}
    for k, v in truth["summary"].items():
        if not _same(summary.get(k), v):
            reasons.append(f"summary.{k} is {json.dumps(summary.get(k))}, recomputed {json.dumps(v)}")
    return {"status": "fail" if reasons else "pass", "checked_findings": len(findings), "reasons": reasons}


def reminders(report, data, today: str):
    s = data["settings"]
    out = []
    for c in data["contracts"]:
        year = int(today[:4])
        when = f"{year}-{c['payment_due']}"
        if when < today:
            when = f"{year + 1}-{c['payment_due']}"
        if when < c["start_date"] or when > c["end_date"]:
            continue
        rent = rent_of(c, s)
        amt = round2(c["area_contract"] * rent)
        notes = ["Note: " + f["explanation"] for f in report["findings"] if f["contract_id"] == c["contract_id"] and f["category"] != "expiring"]
        out.append({"kind": "payment", "date": when, "contract_id": c["contract_id"], "owner": c["owner"], "parcel_id": c["parcel_id"], "amount": amt,
                    "flagged": bool(notes), "title": f"Rent {money(amt, s)} - {c['owner']} (lease {c['contract_id']})",
                    "description": "\n".join([f"Annual rent for lease {c['contract_id']}.", f"Owner: {c['owner']}", f"Parcel: {c['parcel_id']}",
                                              f"{area(c['area_contract'], s)} x {money(rent, s)}/{s['area_unit']} = {money(amt, s)}", *notes]),
                    "alarm_days_before": s["payment_alarm_days_before"], "alarm_text": f"Rent due in {s['payment_alarm_days_before']} days: {money(amt, s)} to {c['owner']}",
                    "uid": f"pay-{c['contract_id']}-{when}@agroland"})
    for e in report["summary"]["expiring_contracts"]:
        d = (date.fromisoformat(e["end_date"]) - timedelta(days=s["expiry_reminder_days_before_end"])).isoformat()
        out.append({"kind": "expiry", "date": max(d, today), "contract_id": e["contract_id"], "owner": e["owner"], "parcel_id": e["parcel_id"], "amount": None,
                    "flagged": True, "title": f"Lease {e['contract_id']} expires {e['end_date']} - talk to {e['owner']}",
                    "description": f"Lease {e['contract_id']} for parcel {e['parcel_id']} ends on {e['end_date']}.\nOwner: {e['owner']}\nStart renegotiation now.",
                    "alarm_days_before": s["payment_alarm_days_before"], "alarm_text": f"Lease {e['contract_id']} renegotiation reminder",
                    "uid": f"expiry-{e['contract_id']}-{e['end_date']}@agroland"})
    return sorted(out, key=lambda r: (r["date"], r["uid"]))


def _esc(t):
    return str(t).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line):
    parts, cur, size = [], "", 0
    for ch in line:
        w = len(ch.encode())
        if size + w > 75:
            parts.append(cur); cur, size = " ", 1
        cur += ch; size += w
    return "\r\n".join(parts + [cur])


def to_ics(rem, name="Lease reminders", stamp: datetime | None = None):
    st = (stamp or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    nxt = lambda d: (date.fromisoformat(d) + timedelta(days=1)).isoformat().replace("-", "")  # noqa: E731
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AgroLand//Lease Reminders//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(name)}"]
    for r in rem:
        lines += ["BEGIN:VEVENT", f"UID:{r['uid']}", f"DTSTAMP:{st}", f"DTSTART;VALUE=DATE:{r['date'].replace('-', '')}", f"DTEND;VALUE=DATE:{nxt(r['date'])}",
                  f"SUMMARY:{_esc(r['title'])}", f"DESCRIPTION:{_esc(r['description'])}", f"CATEGORIES:{'Lease payment' if r['kind'] == 'payment' else 'Lease expiry'}",
                  "TRANSP:TRANSPARENT", "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(r['alarm_text'])}", f"TRIGGER:-P{r['alarm_days_before']}D", "END:VALARM", "END:VEVENT"]
    return "\r\n".join(_fold(x) for x in lines + ["END:VCALENDAR"]) + "\r\n"


def full_report(data, today: str):
    report = analyze(data, today)
    report["reminders"] = reminders(report, data, today)
    report["verification"] = verify_report(json.loads(json.dumps(report)), data, today)  # as an outside party sees it: after a JSON round trip
    return report
