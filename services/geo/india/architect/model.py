"""Pool economics for India: layout estimate, project value (NPV in INR) and each firm's share.

Deterministic and fully transparent - every number comes from the revealed parcels/audit reports and the
`Assumptions` below (defaults are screening values for utility-scale projects in Andhra Pradesh and Gujarat, NOT a
bankable model; check against current SECI/state auction results, capex quotes and lease rates).

Fair split: a two-player cooperative game. v(A), v(B) = value of developing a parcel alone, v(AB) = value of the joint
project (shared evacuation line, one permitting effort for the same technology, wake-aware layout). Shapley value:
phi_A = v(A) + (v(AB) - v(A) - v(B)) / 2 - each firm keeps what it could achieve alone and the synergy is split
equally. Alternative keys: by area, by contributed annual revenue.

India specifics versus the German model: INR and a higher discount rate; a lease cost per hectare (land is leased
from farmers, not owned) that escalates yearly; the grid route is either state (STU/discom) or central (CTU) and
changes the fixed connection cost; geometry is measured in the local UTM zone.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from shapely.geometry import Point, shape
from shapely.prepared import prep

from ..common.geo import project_pair

Method = Literal["shapley", "area", "revenue"]
GridRoute = Literal["auto", "state", "ctu"]
DEFAULT_GRID_DISTANCE_M = 20_000.0  # the audit searches substations up to 20 km; used when none was found


class Assumptions(BaseModel):
    # wind (typical 2.5-3.3 MW class machines in AP/Gujarat)
    wind_rated_mw: float = Field(3.0, gt=0)
    wind_rotor_diameter_m: float = Field(130.0, gt=0)
    wind_spacing_rotor_diameters: float = Field(4.0, gt=0, description="min. turbine distance in rotor diameters")
    wind_cf_at_6ms: float = Field(0.30, gt=0, lt=1)
    wind_cf_per_ms: float = Field(0.07, ge=0)
    wind_capex_inr_per_kw: float = Field(70_000.0, gt=0)
    wind_opex_inr_per_kw_a: float = Field(900.0, ge=0)
    wind_price_inr_mwh: float = Field(3_300.0, gt=0)
    wind_dev_fixed_inr: float = Field(12_000_000.0, ge=0, description="permitting, surveys, legal - once per project")
    wind_lease_inr_per_mw_a: float = Field(250_000.0, ge=0, description="turbine-site lease/royalty per installed MW and year")
    # solar
    solar_mwp_per_ha: float = Field(0.55, gt=0)
    solar_usable_fraction: float = Field(0.90, gt=0, le=1)
    solar_capex_inr_per_kwp: float = Field(30_000.0, gt=0, description="per kWp DC")
    solar_opex_inr_per_kwp_a: float = Field(600.0, ge=0)
    solar_price_inr_mwh: float = Field(2_600.0, gt=0)
    solar_degradation_per_year: float = Field(0.005, ge=0, lt=0.05)
    solar_dev_fixed_inr: float = Field(5_000_000.0, ge=0)
    solar_lease_inr_per_ha_a: float = Field(100_000.0, ge=0, description="land lease per hectare and year")
    lease_escalation_per_year: float = Field(0.03, ge=0, lt=0.2)
    # grid & finance (screening placeholders; the real figures come from the STU/CTU connectivity study)
    grid_fixed_inr_state: float = Field(15_000_000.0, ge=0, description="bay, metering, protection - state route")
    grid_fixed_inr_ctu: float = Field(30_000_000.0, ge=0, description="same, central route (bigger scope, higher voltage)")
    cable_inr_per_m: float = Field(1_500.0, ge=0, description="33/66 kV line incl. right-of-way and civil works")
    discount_rate: float = Field(0.09, gt=0, lt=0.5)
    lifetime_years: int = Field(25, ge=5, le=40)


@dataclass
class ParcelIn:
    label: str  # "A" | "B"
    developer_id: str
    company_name: str
    parcel_id: str
    area_ha: float
    technology: str  # "wind" | "solar"
    solar_kwh_per_kwp: Optional[float]
    wind_ms: Optional[float]
    slope_deg: Optional[float]
    d_substation_m: Optional[float]
    route_hint: Optional[str]
    poly_wgs: Any  # shapely polygon, EPSG:4326


@dataclass
class Econ:
    capacity_mw: float = 0.0
    energy_mwh: float = 0.0
    revenue: float = 0.0
    opex: float = 0.0
    capex: float = 0.0
    lease: float = 0.0  # first-year lease cost (escalates)


def parcel_from_package(label: str, party: dict[str, Any]) -> ParcelIn:
    p, rep = party["parcel"], party["parcel"]["report"]
    res, grid = rep.get("resource_potential", {}), rep.get("grid_access", {})
    return ParcelIn(
        label=label, developer_id=party["developer_id"], company_name=party["company"]["company_name"],
        parcel_id=p["id"], area_ha=p["area_ha"], technology=p["assessed_technology"],
        solar_kwh_per_kwp=res.get("solar_kwh_per_kwp_year"), wind_ms=res.get("wind_speed_100m_ms"),
        slope_deg=res.get("slope_degrees"), d_substation_m=grid.get("nearest_substation_m"),
        route_hint=grid.get("connection_route_hint"), poly_wgs=shape(p["geometry"]))


def resolve_route(requested: str, parcels: list[ParcelIn]) -> tuple[str, str]:
    """(route, why). `auto` follows the audit's hint: central if any parcel's nearest node looks like an ISTS station."""
    if requested in ("state", "ctu"):
        return requested, "chosen by the requester"
    hints = [p.route_hint for p in parcels if p.route_hint]
    if any(h.startswith("central") for h in hints):
        return "ctu", "audit hint: nearest node looks like a central (ISTS) substation"
    return "state", "audit hint: state transmission utility / distribution licensee" if hints else "default (no audit hint)"


# ---------------------------------------------------------------- layout & energy


def _candidates(poly, d: float, step: float = 25.0) -> list[tuple[float, float]]:
    inner = poly.buffer(-d / 2)  # rotor must not oversail the pool boundary
    if inner.is_empty:
        return []
    pp = prep(inner)
    minx, miny, maxx, maxy = inner.bounds
    pts, x = [], minx
    while x <= maxx:
        y = miny
        while y <= maxy:
            if pp.contains(Point(x, y)):
                pts.append((round(x, 1), round(y, 1)))
            y += step
        x += step
    return pts


def _greedy(cands: list[tuple[float, float]], chosen: list[tuple[float, float]], min_d: float) -> list[tuple[float, float]]:
    out = list(chosen)
    for c in cands:
        if all(math.dist(c, o) >= min_d for o in out):
            out.append(c)
    return out[len(chosen):]


def wind_layout(polys: dict[str, Any], labels: list[str], asm: Assumptions) -> dict[str, list[tuple[float, float]]]:
    """Turbine positions (local UTM) per label. With two labels: best of both placement orders, spacing enforced across."""
    D, min_d = asm.wind_rotor_diameter_m, asm.wind_rotor_diameter_m * asm.wind_spacing_rotor_diameters
    cands = {lab: _candidates(polys[lab], D) for lab in labels}
    if len(labels) == 1:
        return {labels[0]: _greedy(cands[labels[0]], [], min_d)}
    a, b = labels
    best = None
    for f_lab, s_lab in ((a, b), (b, a)):
        p1 = _greedy(cands[f_lab], [], min_d)
        p2 = _greedy(cands[s_lab], p1, min_d)
        if best is None or len(p1) + len(p2) > len(best[f_lab]) + len(best[s_lab]):
            best = {f_lab: p1, s_lab: p2}
    return best  # type: ignore[return-value]


def econ_wind(n: int, ms: Optional[float], asm: Assumptions) -> Econ:
    if n == 0 or ms is None:
        return Econ()
    cf = min(max(asm.wind_cf_at_6ms + asm.wind_cf_per_ms * (ms - 6.0), 0.12), 0.55)
    mw = n * asm.wind_rated_mw
    mwh = mw * 8760 * cf
    return Econ(mw, mwh, mwh * asm.wind_price_inr_mwh, mw * 1000 * asm.wind_opex_inr_per_kw_a,
                mw * 1000 * asm.wind_capex_inr_per_kw, mw * asm.wind_lease_inr_per_mw_a)


def econ_solar(area_ha: float, slope: Optional[float], kwh_per_kwp: Optional[float], asm: Assumptions) -> Econ:
    if kwh_per_kwp is None:
        return Econ()
    derate = 1.0 if slope is None else 0.5 + 0.5 * min(max((15.0 - slope) / 10.0, 0.0), 1.0)  # 5 deg -> 1.0, 15 deg -> 0.5
    mwp = area_ha * asm.solar_usable_fraction * asm.solar_mwp_per_ha * derate
    mwh = mwp * kwh_per_kwp  # kWh/kWp == MWh/MWp
    # the whole leased area is paid for, usable or not
    return Econ(mwp, mwh, mwh * asm.solar_price_inr_mwh, mwp * 1000 * asm.solar_opex_inr_per_kwp_a,
                mwp * 1000 * asm.solar_capex_inr_per_kwp, area_ha * asm.solar_lease_inr_per_ha_a)


def _annuity(asm: Assumptions, growth: float = 0.0) -> float:
    """Present value of 1 per year for `lifetime_years`, optionally growing at `growth` (first payment = 1)."""
    r, t = asm.discount_rate, asm.lifetime_years
    if abs(r - growth) < 1e-12:
        return t / (1 + r)
    return (1 - ((1 + growth) / (1 + r)) ** t) / (r - growth)


def _operating_value(e: Econ, tech: str, asm: Assumptions) -> float:
    deg = 1 - asm.solar_degradation_per_year * (asm.lifetime_years - 1) / 2 if tech == "solar" else 1.0
    return _annuity(asm) * (e.revenue * deg - e.opex) - _annuity(asm, asm.lease_escalation_per_year) * e.lease


def _dev_cost(techs: set[str], asm: Assumptions) -> float:
    return sum(asm.wind_dev_fixed_inr if t == "wind" else asm.solar_dev_fixed_inr for t in techs)


# ---------------------------------------------------------------- shares


def _bp(weights: list[float]) -> list[int]:
    """Largest-remainder rounding to basis points (0.01 %), summing to exactly 10 000."""
    total = sum(weights)
    if total <= 0:
        weights, total = [1.0] * len(weights), float(len(weights))
    raw = [Decimal(repr(w)) / Decimal(repr(total)) * 10000 for w in weights]
    floors = [int(r.to_integral_value(ROUND_FLOOR)) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
    for i in order[: 10000 - sum(floors)]:
        floors[i] += 1
    return floors


def compute_plan(a: ParcelIn, b: ParcelIn, asm: Assumptions, method: Method = "shapley",
                 grid_route: GridRoute = "auto") -> dict[str, Any]:
    warnings: list[str] = []
    for p in (a, b):
        if p.d_substation_m is None:
            warnings.append(f"Party {p.label}: no substation within 20 km in the audit; {DEFAULT_GRID_DISTANCE_M:.0f} m assumed")
        if p.technology not in ("wind", "solar"):
            raise ValueError(f"unsupported technology '{p.technology}'")
    route, route_why = resolve_route(grid_route, [a, b])
    grid_fixed = asm.grid_fixed_inr_ctu if route == "ctu" else asm.grid_fixed_inr_state
    dist = {p.label: p.d_substation_m if p.d_substation_m is not None else DEFAULT_GRID_DISTANCE_M for p in (a, b)}

    a_m, b_m, proj = project_pair(a.poly_wgs, b.poly_wgs)
    polys = {a.label: a_m, b.label: b_m}
    gap = a_m.distance(b_m)

    # --- standalone
    alone: dict[str, dict[str, Any]] = {}
    layouts_alone = {p.label: wind_layout(polys, [p.label], asm)[p.label] if p.technology == "wind" else [] for p in (a, b)}
    for p in (a, b):
        e = (econ_wind(len(layouts_alone[p.label]), p.wind_ms, asm) if p.technology == "wind"
             else econ_solar(p.area_ha, p.slope_deg, p.solar_kwh_per_kwp, asm))
        grid = grid_fixed + asm.cable_inr_per_m * dist[p.label]
        dev = _dev_cost({p.technology}, asm)
        npv = _operating_value(e, p.technology, asm) - e.capex - grid - dev if e.capacity_mw > 0 else -(grid + dev)
        alone[p.label] = {"econ": e, "grid": grid, "dev": dev, "npv": npv}

    # --- joint
    lay = wind_layout(polys, [a.label, b.label], asm) if a.technology == b.technology == "wind" else {
        p.label: layouts_alone[p.label] for p in (a, b)}
    joint_econ: dict[str, Econ] = {}
    for p in (a, b):
        joint_econ[p.label] = (econ_wind(len(lay[p.label]), p.wind_ms, asm) if p.technology == "wind"
                               else econ_solar(p.area_ha, p.slope_deg, p.solar_kwh_per_kwp, asm))
    grid_joint = grid_fixed + asm.cable_inr_per_m * (min(dist.values()) + gap)
    dev_joint = _dev_cost({a.technology, b.technology}, asm)
    op_joint = sum(_operating_value(joint_econ[p.label], p.technology, asm) - joint_econ[p.label].capex for p in (a, b))
    npv_joint = op_joint - grid_joint - dev_joint if any(e.capacity_mw > 0 for e in joint_econ.values()) else -(grid_joint + dev_joint)

    # --- Shapley and alternative keys
    vA, vB = max(alone[a.label]["npv"], 0.0), max(alone[b.label]["npv"], 0.0)
    vAB = max(npv_joint, 0.0)
    synergy = npv_joint - vA - vB  # reported as computed; negative = pooling is worse than going separate
    viable = vAB > 0
    beneficial = viable and synergy > 0
    phi = [vA + synergy / 2, vB + synergy / 2] if beneficial else [vA, vB]
    if not viable:
        warnings.append("joint project has no positive value under these assumptions")
    elif not beneficial:
        warnings.append("pooling does not create value versus developing the parcels separately (e.g. one parcel is unviable "
                        "on its own or a joint layout loses turbines) - reconsider the pool or the assumptions")
    area_bp = _bp([a.area_ha, b.area_ha])
    rev = [joint_econ[a.label].revenue, joint_econ[b.label].revenue]
    keys = {"shapley": _bp(phi) if beneficial else area_bp, "area": area_bp,
            "revenue": _bp(rev if sum(rev) > 0 else [a.area_ha, b.area_ha])}
    method_applied = method
    if method == "shapley" and not beneficial:
        method_applied = "area"
        warnings.append("Shapley split is only meaningful when pooling creates value - shares fall back to the area key")
    chosen = keys[method_applied]

    total_rev = sum(rev)
    parties = []
    for i, p in enumerate((a, b)):
        s, j = alone[p.label], joint_econ[p.label]
        parties.append({
            "label": p.label, "developer_id": p.developer_id, "company_name": p.company_name,
            "parcel": {"parcel_id": p.parcel_id, "area_ha": p.area_ha, "technology": p.technology,
                       "distance_to_substation_m": p.d_substation_m},
            "standalone": {"capacity_mw": round(s["econ"].capacity_mw, 2), "energy_mwh_a": round(s["econ"].energy_mwh),
                           "npv_inr": round(s["npv"]), "viable": s["npv"] > 0, "grid_cost_inr": round(s["grid"]),
                           "development_cost_inr": round(s["dev"])},
            "in_joint_project": {"capacity_mw": round(j.capacity_mw, 2), "energy_mwh_a": round(j.energy_mwh),
                                 "revenue_inr_a": round(j.revenue), "capex_inr": round(j.capex),
                                 "lease_inr_first_year": round(j.lease)},
            "value_contribution_shapley_inr": round(phi[i]),
            "share_bp": {"chosen": chosen[i], "shapley": keys["shapley"][i], "area": keys["area"][i], "revenue": keys["revenue"][i]},
            "indicative_revenue_share_inr_a": round(total_rev * chosen[i] / 10000),
        })
    grid_alone = alone[a.label]["grid"] + alone[b.label]["grid"]
    dev_alone = alone[a.label]["dev"] + alone[b.label]["dev"]

    def lonlat(xy: tuple[float, float]) -> dict[str, float]:
        lon, lat = proj.lonlat(*xy)
        return {"lon": round(lon, 6), "lat": round(lat, 6)}

    return {
        "currency": "INR", "method": method, "method_applied": method_applied, "viable": viable,
        "pooling_beneficial": beneficial, "shares_bp": {a.label: chosen[0], b.label: chosen[1]},
        "grid_route": {"route": route, "requested": grid_route, "reason": route_why},
        "joint_project": {
            "capacity_mw": round(sum(e.capacity_mw for e in joint_econ.values()), 2),
            "energy_mwh_a": round(sum(e.energy_mwh for e in joint_econ.values())),
            "revenue_inr_a": round(total_rev), "capex_inr": round(sum(e.capex for e in joint_econ.values())),
            "lease_inr_first_year": round(sum(e.lease for e in joint_econ.values())),
            "grid_connection_cost_inr": round(grid_joint), "development_cost_inr": round(dev_joint),
            "internal_line_m": round(gap), "npv_inr": round(npv_joint),
            "wind_turbines": {lab: [lonlat(xy) for xy in pts] for lab, pts in lay.items() if pts},
        },
        "synergy": {"total_inr": round(synergy), "grid_savings_inr": round(grid_alone - grid_joint),
                    "development_savings_inr": round(dev_alone - dev_joint),
                    "layout_and_other_inr": round(synergy - (grid_alone - grid_joint) - (dev_alone - dev_joint))},
        "parties": parties, "assumptions": asm.model_dump(), "warnings": warnings,
        "disclaimer": "Screening model with default assumptions; not a bankable financial model.",
    }
