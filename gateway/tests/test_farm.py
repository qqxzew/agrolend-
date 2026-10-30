import json
from pathlib import Path

from agroland import farm


def test_german_demo_matches_original_javascript_numbers():
    r = farm.full_report(farm.load_demo("DE"), "2026-10-30")
    assert r["verification"]["status"] == "pass"
    assert r["summary"]["identified_per_year"] == 1440 and r["summary"]["negotiable_per_year"] == 720
    assert sorted((f["type"], f["contract_id"]) for f in r["findings"]) == sorted([
        ("paid_not_farmed", "HF-04"), ("area_mismatch", "HF-02"), ("above_market_rent", "HF-03"), ("expiring_soon", "HF-11"), ("expiring_soon", "HF-16")])
    assert r["summary"]["achieved_per_year"] == 0  # never computed by the engine


def test_indian_demo_uses_acre_and_inr():
    r = farm.full_report(farm.load_demo("IN"), "2026-10-30")
    assert r["verification"]["status"] == "pass" and r["meta"]["currency"] == "INR" and r["meta"]["area_unit"] == "acre"
    assert r["summary"]["identified_per_year"] == 460800 and r["summary"]["negotiable_per_year"] == 154000
    assert "₹" in next(f["explanation"] for f in r["findings"] if f["type"] == "paid_not_farmed")


def test_forged_report_fails_verification():
    d = farm.load_demo("DE")
    r = farm.full_report(d, "2026-10-30")
    forged = json.loads(json.dumps(r))
    forged["findings"][0]["amount_per_year"] += 1
    assert farm.verify_report(forged, d, "2026-10-30")["status"] == "fail"
    forged = json.loads(json.dumps(r)); forged["findings"].pop()
    assert farm.verify_report(forged, d, "2026-10-30")["status"] == "fail"
    forged = json.loads(json.dumps(r)); forged["summary"]["achieved_per_year"] = 99999
    assert farm.verify_report(forged, d, "2026-10-30")["status"] == "fail"


def test_csv_validation_rejects_bad_input():
    import pytest
    s = farm.load_demo("DE")["settings"]
    good = Path(farm.DATA, "de")
    c, a, f = (good / "contracts.csv").read_text(), (good / "cadastre.csv").read_text(), (good / "fields.csv").read_text()
    with pytest.raises(farm.DataError):
        farm.build_dataset(c.replace("2019-10-01", "01.10.2019"), a, f, s)
    with pytest.raises(farm.DataError):
        farm.build_dataset(c.replace("410", "abc", 1), a, f, s)
    with pytest.raises(farm.DataError):
        farm.build_dataset("wrong,header\n1,2", a, f, s)
    with pytest.raises(farm.DataError):
        farm.build_dataset(c.replace("410", "-5", 1), a, f, s)


def test_calendar_syntax():
    d = farm.load_demo("DE")
    r = farm.full_report(d, "2026-10-30")
    ics = farm.to_ics(r["reminders"])
    assert ics.startswith("BEGIN:VCALENDAR") and ics.count("BEGIN:VEVENT") == ics.count("END:VEVENT") == len(r["reminders"])
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
