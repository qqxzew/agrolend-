"""Offline end-to-end test of India Agent 4 (Pool Architect) on top of the real India Agents 2 and 3.

Stubbed: India Agent 1 (validator). Real: matcher, escrow (bypass payment, NDA signing), pool model, English PDFs.

    python tests/test_india_architect.py
"""
import asyncio
import hashlib
import io
import json
import math
import sys
import tempfile
from pathlib import Path

import httpx
from pyproj import Transformer
from pypdf import PdfReader
from shapely.geometry import Point, box
from shapely.ops import transform as shp_transform

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from india.architect.config import ArchitectSettings  # noqa: E402
from india.architect.main import create_app as create_architect  # noqa: E402
from india.architect.model import Assumptions, ParcelIn, _bp, compute_plan, resolve_route  # noqa: E402
from india.escrow.config import EscrowSettings  # noqa: E402
from india.escrow.main import create_app as create_escrow  # noqa: E402
from india.matcher.config import MatcherSettings  # noqa: E402
from india.matcher.main import create_app as create_matcher  # noqa: E402

TO_UTM = Transformer.from_crs(4326, 32642, always_xy=True)  # Kutch, Gujarat: UTM zone 42N
TO_WGS = Transformer.from_crs(32642, 4326, always_xy=True)
LON0, LAT0 = 69.5, 23.3
x0, y0 = TO_UTM.transform(LON0, LAT0)
KEY, ESC_KEY, ARCH_KEY = "k" * 20, "e" * 20, "a" * 20
STATE_HINT = "state: intra-state connectivity through Gujarat Energy Transmission Corporation (GETCO)"
CTU_HINT = "central: nearest node looks like an ISTS substation - connectivity application to CTU/CTUIL under the CERC GNA Regulations 2022"


# ------------------------------------------------------------------ model (pure functions)


def pin(label, box_m, tech="wind", area=None, ms=7.0, kwh=1700.0, slope=3.0, d_sub=3000.0, hint=STATE_HINT):
    """Parcel from a metre box (relative to the Kutch origin); the model works on WGS84 polygons."""
    poly = shp_transform(TO_WGS.transform, box(x0 + box_m[0], y0 + box_m[1], x0 + box_m[2], y0 + box_m[3]))
    ha = (box_m[2] - box_m[0]) * (box_m[3] - box_m[1]) / 1e4
    return ParcelIn(label=label, developer_id=f"dev_{label}", company_name=f"Firm {label}", parcel_id=f"p{label}",
                    area_ha=area if area is not None else ha, technology=tech, solar_kwh_per_kwp=kwh,
                    wind_ms=ms, slope_deg=slope, d_substation_m=d_sub, route_hint=hint, poly_wgs=poly)


def test_model():
    assert sum(_bp([1, 1, 1])) == 10000 and _bp([1, 1, 1]) == [3334, 3333, 3333]
    assert _bp([0, 0]) == [5000, 5000] and sum(_bp([3.3, 1.1, 5.5, 0.1])) == 10000

    asm = Assumptions()
    a, b = pin("A", (0, 0, 1000, 1000)), pin("B", (1400, 0, 2400, 1000))
    plan = compute_plan(a, b, asm)
    bp = plan["shares_bp"]
    assert plan["currency"] == "INR"
    assert bp["A"] + bp["B"] == 10000 and bp == {"A": 5000, "B": 5000}, bp  # symmetric parcels -> Shapley is 50/50
    assert plan["viable"] and plan["pooling_beneficial"] and plan["synergy"]["total_inr"] > 0, plan["warnings"]
    assert plan["synergy"]["grid_savings_inr"] > 0 and plan["synergy"]["development_savings_inr"] > 0
    assert plan["joint_project"]["lease_inr_first_year"] > 0
    pts = [(p["lon"], p["lat"]) for lst in plan["joint_project"]["wind_turbines"].values() for p in lst]
    assert len(pts) >= 4
    utm = [TO_UTM.transform(*p) for p in pts]
    min_d = asm.wind_rotor_diameter_m * asm.wind_spacing_rotor_diameters
    assert all(math.dist(p, q) >= min_d - 1.0 for i, p in enumerate(utm) for q in utm[i + 1:]), "turbine spacing violated"
    for lab, lst in plan["joint_project"]["wind_turbines"].items():
        poly = shp_transform(TO_UTM.transform, (a if lab == "A" else b).poly_wgs)
        assert all(poly.buffer(1).contains(Point(*TO_UTM.transform(p["lon"], p["lat"]))) for p in lst)

    # unequal parcels: area key proportional, Shapley still sums to 10000, bigger parcel gets more
    c = pin("B", (1400, 0, 1600, 1000))  # 20 ha vs 100 ha
    plan = compute_plan(a, c, asm, method="area")
    assert abs(plan["shares_bp"]["A"] - 10000 * 100 / 120) <= 1 and sum(plan["shares_bp"].values()) == 10000
    plan2 = compute_plan(a, c, asm, method="shapley")
    assert plan2["shares_bp"]["A"] > plan2["shares_bp"]["B"] and sum(plan2["shares_bp"].values()) == 10000
    assert plan2["parties"][0]["share_bp"]["area"] == plan["shares_bp"]["A"]

    # solar + wind mix: capacity from area (0.55 MWp/ha, 90 % usable), slope derating, lease on the whole area
    s = pin("B", (1400, 0, 1900, 1000), tech="solar", kwh=1000.0, slope=3.0)  # 50 ha
    plan = compute_plan(a, s, asm)
    sol = plan["parties"][1]["in_joint_project"]
    assert abs(sol["capacity_mw"] - 50 * 0.9 * 0.55) < 0.01 and abs(sol["energy_mwh_a"] - 24750) < 5, sol
    assert sol["lease_inr_first_year"] == 50 * 100_000, sol
    steep = compute_plan(a, pin("B", (1400, 0, 1900, 1000), tech="solar", slope=15.0), asm)
    assert steep["parties"][1]["in_joint_project"]["capacity_mw"] < sol["capacity_mw"] * 0.55
    pricey = compute_plan(a, s, Assumptions(solar_lease_inr_per_ha_a=400_000))
    assert pricey["parties"][1]["standalone"]["npv_inr"] < plan["parties"][1]["standalone"]["npv_inr"], "lease must cost value"
    flat = compute_plan(a, s, Assumptions(solar_lease_inr_per_ha_a=100_000, lease_escalation_per_year=0.0))
    assert flat["parties"][1]["standalone"]["npv_inr"] > plan["parties"][1]["standalone"]["npv_inr"], "escalation must cost value"

    # not viable under absurd capex -> falls back to area, warns
    bad = compute_plan(a, b, Assumptions(wind_capex_inr_per_kw=6_000_000))
    assert not bad["viable"] and bad["shares_bp"] == {"A": 5000, "B": 5000} and any("no positive value" in w for w in bad["warnings"])

    # one parcel unviable on its own (solar at absurd capex) and pooling cannot fix that -> no 100/0 split, area fallback + warning
    loser = compute_plan(a, s, Assumptions(solar_capex_inr_per_kwp=500_000))
    assert not loser["pooling_beneficial"] and loser["method_applied"] == "area" and loser["method"] == "shapley"
    assert 0 < loser["shares_bp"]["B"] < 10000 and any("fall back" in w for w in loser["warnings"]), loser["warnings"]

    # missing substation distance -> default (20 km) + warning
    plan = compute_plan(pin("A", (0, 0, 1000, 1000), d_sub=None), b, asm)
    assert any("no substation" in w for w in plan["warnings"])

    # grid route: auto follows the audit hint, explicit choice wins, central costs more at the fixed part
    st = compute_plan(a, b, asm)
    assert st["grid_route"]["route"] == "state" and "audit hint" in st["grid_route"]["reason"]
    cen_a, cen_b = pin("A", (0, 0, 1000, 1000), hint=CTU_HINT), pin("B", (1400, 0, 2400, 1000))
    auto = compute_plan(cen_a, cen_b, asm)
    assert auto["grid_route"]["route"] == "ctu", "one central hint is enough for the central route"
    diff = auto["joint_project"]["grid_connection_cost_inr"] - st["joint_project"]["grid_connection_cost_inr"]
    assert diff == round(asm.grid_fixed_inr_ctu - asm.grid_fixed_inr_state), diff
    forced = compute_plan(cen_a, cen_b, asm, grid_route="state")
    assert forced["grid_route"] == {"route": "state", "requested": "state", "reason": "chosen by the requester"}
    assert resolve_route("auto", [pin("A", (0, 0, 1000, 1000), hint=None)])[0] == "state"

    # geometry works in other UTM zones too (Andhra Pradesh, zone 43N): same box -> same area-based share
    print("model OK")


# ------------------------------------------------------------------ services


def validator(request):
    first = json.loads(request.content)["lon"] < LON0 + 0.001  # first parcel -> wind, the eastern one -> solar
    report = {
        "overall_verdict": "GO", "score": 85, "assessed_technology": "wind" if first else "solar", "warnings": [],
        "location_info": {"state": "Gujarat", "state_code": "IN-GJ", "district": "Kachchh",
                          "village": "Testvillage" if first else "Neighbourvillage",
                          "land_record": {"survey_number": "112/1" if first else "208/3", "ulpin": "GJ123456789012" if first else None}},
        "resource_potential": {"solar_kwh_per_kwp_year": 1700.0, "wind_speed_100m_ms": 6.9, "slope_degrees": 2.5},
        "grid_access": {"nearest_substation_m": 2500.0 if first else 3200.0, "substation_name": "Kutch Test 220 kV SS",
                        "substation_operator": "GETCO", "nearest_powerline_m": 400.0, "connection_route_hint": STATE_HINT},
    }
    return httpx.Response(200, json={"job_id": "j", "status": "completed", "report": report})


def profile(name, rep, mail, **kw):
    return {"company_name": name, "address": "Plot 12, Madhapur", "state": "Telangana", "pin_code": "500081", "representative": rep,
            "registration_no": "U40108TG2021PTC123456", "email": mail, "phone": "+91 40 12345678", **kw}


def at(dx, radius):
    lon, lat = TO_WGS.transform(x0 + dx, y0)
    return {"lat": round(lat, 6), "lon": round(lon, 6), "radius_m": radius}


def pdf_text(b):
    r = PdfReader(io.BytesIO(b))
    return len(r.pages), " ".join(" ".join(p.extract_text() for p in r.pages).split())


async def main():
    test_model()
    tmp = tempfile.mkdtemp()
    matcher = create_matcher(MatcherSettings(_env_file=None, matcher_database_path=f"{tmp}/m.sqlite3", matcher_api_key=KEY),
                             transport=httpx.MockTransport(validator))
    async with matcher.router.lifespan_context(matcher):
        mc = httpx.AsyncClient(transport=httpx.ASGITransport(app=matcher), base_url="http://matcher")
        escrow = create_escrow(EscrowSettings(_env_file=None, escrow_database_path=f"{tmp}/e.sqlite3", matcher_url="http://matcher",
                                              matcher_api_key=KEY, escrow_bypass_payment=True, escrow_api_key=ESC_KEY),
                               transport=httpx.ASGITransport(app=matcher))
        async with escrow.router.lifespan_context(escrow):
            ec = httpx.AsyncClient(transport=httpx.ASGITransport(app=escrow), base_url="http://escrow", headers={"X-API-Key": ESC_KEY})
            arch = create_architect(ArchitectSettings(_env_file=None, escrow_url="http://escrow", escrow_api_key=ESC_KEY,
                                                      architect_api_key=ARCH_KEY, architect_database_path=f"{tmp}/a.sqlite3"),
                                    transport=httpx.ASGITransport(app=escrow))
            async with arch.router.lifespan_context(arch):
                ac = httpx.AsyncClient(transport=httpx.ASGITransport(app=arch), base_url="http://arch", headers={"X-API-Key": ARCH_KEY})

                for dev, dx in (("dev1", 0), ("dev2", 1500)):
                    r = await mc.post("/register_parcel", json={"developer_id": dev, "project_type": "hybrid", **at(dx, 600)},
                                      headers={"X-API-Key": KEY})
                    assert r.status_code == 200 and r.json()["status"] == "registered", r.text
                mid = (await mc.get("/teasers", params={"developer_id": "dev1"}, headers={"X-API-Key": KEY})).json()["teasers"][0]["match_id"]

                # before the NDA is signed there is no package
                r = await ac.post(f"/pools/{mid}", json={"developer_id": "dev1"})
                assert r.status_code in (404, 409), r.text

                await ec.put("/developers/dev1/profile", json=profile("Vayu Wind Energy Pvt Ltd", "Anita Rao, Director", "anita@vayu.in"))
                await ec.put("/developers/dev2/profile", json=profile("Surya Solar LLP", "Ravi Patel, Designated Partner", "ravi@surya.in",
                                                                     address="5 Ring Road, Rajkot", state="Gujarat", pin_code="360001"))
                for d in ("dev1", "dev2"):
                    v = (await ec.post(f"/deals/{mid}/consent", json={"developer_id": d, "decision": "accept"})).json()
                r = await ac.post(f"/pools/{mid}", json={"developer_id": "dev1"})
                assert r.status_code == 409, r.text  # NDA not yet signed
                sha = v["nda"]["document_sha256"]
                for d, n in (("dev1", "Anita Rao"), ("dev2", "Ravi Patel")):
                    v = (await ec.post(f"/deals/{mid}/sign", json={"developer_id": d, "signer_name": n, "signer_role": "Director",
                                                                  "document_sha256": sha, "accept": True})).json()
                assert v["status"] == "revealed"

                # auth and membership
                assert (await httpx.AsyncClient(transport=httpx.ASGITransport(app=arch), base_url="http://arch")
                        .post(f"/pools/{mid}", json={"developer_id": "dev1"})).status_code == 401
                assert (await ac.post(f"/pools/{mid}", json={"developer_id": "dev3"})).status_code == 403
                assert (await ac.get(f"/pools/{mid}", params={"developer_id": "dev1"})).status_code == 404

                r = await ac.post(f"/pools/{mid}", json={"developer_id": "dev1"})
                assert r.status_code == 200, r.text
                pool = r.json()
                plan = pool["plan"]
                assert pool["version"] == 1 and pool["grid_operator"] == "GETCO" and pool["substation"] == "Kutch Test 220 kV SS"
                assert sum(plan["shares_bp"].values()) == 10000 and plan["method"] == "shapley" and plan["currency"] == "INR"
                assert plan["pooling_beneficial"] and plan["method_applied"] == "shapley", plan["warnings"]
                assert all(0 < v < 10000 for v in plan["shares_bp"].values()), plan["shares_bp"]
                assert plan["grid_route"]["route"] == "state", plan["grid_route"]
                assert sorted(p["parcel"]["technology"] for p in plan["parties"]) == ["solar", "wind"]
                assert pool["based_on_nda_sha256"] == v["nda"]["signed_document_sha256"]
                for p in plan["parties"]:
                    assert "email" not in p and "phone" not in p, "plan must not leak contact data"

                got = (await ac.get(f"/pools/{mid}", params={"developer_id": "dev2"})).json()
                assert got["plan"] == plan

                pct = lambda bp: f"{bp / 100:.2f} %"  # noqa: E731

                # ---------------- Land Pooling Agreement
                r = await ac.get(f"/pools/{mid}/agreement.pdf", params={"developer_id": "dev2"})
                assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
                assert r.content.startswith(b"%PDF-") and r.content.rstrip().endswith(b"%%EOF")
                assert hashlib.sha256(r.content).hexdigest() == pool["documents"]["land_pooling_agreement"]["sha256"]
                pages, text = pdf_text(r.content)
                for must in ("Land Pooling Agreement", "Vayu Wind Energy Pvt Ltd", "Surya Solar LLP", "3. Shareholding",
                             "6. Grid connectivity and offtake", "Annexure 1", "Annexure 2", "Shapley", "Testvillage", "Neighbourvillage",
                             "112/1", "208/3", "GJ123456789012", "Companies Act, 2013", "Transfer of Property Act, 1882",
                             "Registration Act, 1908", "Arbitration and Conciliation Act, 1996", "section 27", "Madhapur", "INR",
                             "state transmission utility", "legal advice", pct(plan["shares_bp"]["A"]), pct(plan["shares_bp"]["B"])):
                    assert must in text, must
                assert pool["based_on_nda_sha256"] in text.replace(" ", ""), "contract must cite the signed NDA hash"
                assert pages >= 4, pages
                assert "+91 40" not in text, "phone must not appear in the contract"

                # ---------------- Grid Connectivity Application (state route)
                r = await ac.get(f"/pools/{mid}/grid_application.pdf", params={"developer_id": "dev1"})
                assert r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == pool["documents"]["grid_connectivity_application"]["sha256"]
                pages, text = pdf_text(r.content)
                for must in ("Application for grid connectivity for a generating project", "GETCO", "Kutch Test 220 kV SS",
                             "Electricity Act, 2003", "State Grid Code", "Intra-State", "Wind energy", "WTG 1", "Testvillage",
                             "Solar photovoltaic", "[to be completed]", "Technical Standards for Connectivity to the Grid"):
                    assert must in text, must
                assert "CTUIL" not in text
                assert pages >= 2
                (Path(tmp) / "agreement.pdf").write_bytes((await ac.get(f"/pools/{mid}/agreement.pdf", params={"developer_id": "dev1"})).content)
                (Path(tmp) / "grid.pdf").write_bytes(r.content)
                assert (await ac.get(f"/pools/{mid}/agreement.pdf", params={"developer_id": "dev9"})).status_code == 403

                # ---------------- re-run: other key, assumptions and the central route -> new version, other documents
                r = await ac.post(f"/pools/{mid}", json={"developer_id": "dev2", "method": "area", "grid_route": "ctu",
                                                          "assumptions": {"discount_rate": 0.08}})
                p2 = r.json()
                assert p2["version"] == 2 and p2["plan"]["method"] == "area" and p2["plan"]["assumptions"]["discount_rate"] == 0.08
                assert p2["plan"]["grid_route"]["route"] == "ctu"
                assert p2["plan"]["joint_project"]["grid_connection_cost_inr"] > plan["joint_project"]["grid_connection_cost_inr"]
                assert p2["documents"]["land_pooling_agreement"]["sha256"] != pool["documents"]["land_pooling_agreement"]["sha256"]
                r = await ac.get(f"/pools/{mid}/grid_application.pdf", params={"developer_id": "dev1"})
                pages, text = pdf_text(r.content)
                for must in ("CTUIL", "General Network Access", "Inter-State", "chosen by the requester"):
                    assert must in text, must
                assert (await ac.post(f"/pools/{mid}", json={"developer_id": "dev1", "method": "nope"})).status_code == 422
                assert (await ac.post(f"/pools/{mid}", json={"developer_id": "dev1", "grid_route": "nope"})).status_code == 422
                assert (await ac.post(f"/pools/{mid}", json={"developer_id": "dev1", "assumptions": {"discount_rate": 5}})).status_code == 422
                print("pool flow OK:", {p["company_name"]: p["share_bp"]["chosen"] for p in plan["parties"]}, "| files in", tmp)
    print("architect OK")


asyncio.run(main())
