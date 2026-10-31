"""Deterministic scoring and verdict logic: GisResult + Site -> AuditReport (India).

Same inputs always give the same report. All thresholds are in this file. Thresholds marked SCREENING are
engineering assumptions for a first filter — India has no national habitation setback for wind and the state norms
were not verified, so they are conservative placeholders to be replaced per state.
"""
from __future__ import annotations

import re
from typing import Optional

from ..registry.swaminathan import report_context
from .gis_engine import ESZ_BUFFER_M, GisResult, Site
from .models import (
    SUPPORTED_STATES,
    AuditReport,
    EnvironmentalVeto,
    GridAccess,
    LandCheckInput,
    LandRecordInfo,
    LocationInfo,
    RegulatoryChecks,
    ResourcePotential,
    TechnologyAssessment,
    Verdict,
)

GO_MIN_SCORE = 65
NO_GO_MAX_SCORE = 40
VETO_SCORE_CAP = 10
PROTECTED_PENALTY = 15  # protected / conservation area overlap that is not an outright veto

# solar yield, kWh/kWp/year at optimal tilt (PVGIS, ERA5-based in India): 0 points at ZERO, full points at FULL
SOLAR_ZERO_KWH, SOLAR_FULL_KWH = 1300.0, 1750.0
# wind: mean 100 m speed (m/s)
WIND_ZERO_MS, WIND_FULL_MS = 4.5, 7.0
WIND_HARD_FLOOR_MS = 4.5  # below: not viable
WIND_MIN_MS = 5.5  # below: conditional (ERA5 ~25 km grid usually under-reads hills and coasts)
# SCREENING habitation setback for wind, metres
HAB_GO_M, HAB_COND_M = 500.0, 250.0
COVER_BLOCK_PCT, COVER_COND_PCT = 50.0, 5.0  # share of the site mapped as forest / wetland / water

_RANK = {"GO": 2, "CONDITIONAL_GO": 1, "NO_GO": 0}

# Where the state land record can be obtained (user supplies the reference; nothing is queried).
RECORD_PORTALS = {
    "IN-AP": "Mee Bhoomi, Andhra Pradesh (meebhoomi.ap.gov.in) - Adangal / 1-B",
    "IN-GJ": "AnyROR Gujarat (anyror.gujarat.gov.in) - 7/12 and 8A extracts",
}
# Mee Bhoomi-Blockchain pilot (launched 23 July 2026, permissioned Hyperledger Fabric, 89 re-surveyed villages).
AP_PILOT_MANDALS = ("Aspari", "Penumuru", "Repalle", "Gannavaram", "Kadiyam", "Gummalakshmipuram", "Kothavalasa")
STATE_UTILITIES = {
    "IN-AP": "APTRANSCO (STU) / discoms APSPDCL, APEPDCL, APCPDCL",
    "IN-GJ": "GETCO (STU) / discoms UGVCL, MGVCL, DGVCL, PGVCL",
}


def _lin(x: float, zero_at: float, full_at: float) -> float:
    """0..1 ramp: 0 at `zero_at`, 1 at `full_at` (works for either direction)."""
    if zero_at == full_at:
        return 1.0
    return max(0.0, min(1.0, (x - zero_at) / (full_at - zero_at)))


def grid_score(sub_m: Optional[float], line_m: Optional[float]) -> int:
    """0-100: 60% substation proximity (full <=2 km, zero >=20 km), 40% power line (full <=500 m, zero >=10 km)."""
    s = 100 * _lin(sub_m, 20_000, 2_000) if sub_m is not None else 0.0
    ln = 100 * _lin(line_m, 10_000, 500) if line_m is not None else 0.0
    return round(0.6 * s + 0.4 * ln)


def connection_route(state_code: Optional[str], operator: Optional[str], kv: Optional[float]) -> str:
    central = bool(operator and re.search(r"power\s?grid|pgcil", operator, re.I)) or (kv is not None and kv >= 400)
    if central:
        return ("central: nearest node looks like an ISTS substation - connectivity application to CTU/CTUIL under the "
                "CERC GNA Regulations 2022 (check the capacity threshold for your project)")
    util = STATE_UTILITIES.get(state_code or "", "the state transmission utility (STU) or the distribution licensee")
    return f"state: intra-state connectivity through {util}"


def _verdict(score: float, blockers: list[str], conditions: list[str]) -> Verdict:
    if blockers or score < NO_GO_MAX_SCORE:
        return "NO_GO"
    if score >= GO_MIN_SCORE and not conditions:
        return "GO"
    return "CONDITIONAL_GO"


def _solar(e_y, slope, area_ha, grid, road, overlap, missing) -> TechnologyAssessment:
    b: dict[str, float] = {}
    blockers: list[str] = []
    conds: list[str] = []
    b["resource"] = 30 * _lin(e_y, SOLAR_ZERO_KWH, SOLAR_FULL_KWH) if e_y is not None else 0.0
    b["grid"] = 25 * grid / 100
    b["terrain"] = 15 * _lin(slope, 15, 5) if slope is not None else 7.5
    b["access_and_cover"] = (8.0 if road else 0.0) + 12 * _lin(overlap, COVER_COND_PCT * 5, 0)
    b["size"] = 10 * _lin(area_ha, 0, 2)
    if e_y is None:
        conds.append("solar yield unavailable (PVGIS)")
    if slope is not None and slope > 20:
        blockers.append(f"terrain too steep for PV ({slope:.1f} deg > 20 deg)")
    elif slope is not None and slope > 10:
        conds.append(f"steep terrain ({slope:.1f} deg) raises mounting cost")
    if area_ha < 0.5:
        conds.append(f"very small site ({area_ha:.2f} ha)")
    if overlap >= COVER_BLOCK_PCT:
        blockers.append(f"{overlap:.0f}% of the site is mapped as forest / wetland / water")
    elif overlap > COVER_COND_PCT:
        conds.append(f"{overlap:.0f}% of the site is mapped as forest / wetland / water - forest or water-body restrictions apply")
    if not road:
        conds.append("no road within 1 km in OSM - access road and right of way needed")
    conds += [f"{m} unavailable" for m in missing]
    score = round(sum(b.values()))
    return TechnologyAssessment(
        verdict=_verdict(score, blockers, conds), score=score,
        score_breakdown={k: round(v, 1) for k, v in b.items()}, blockers=blockers, conditions=conds,
    )


def _wind(v100, slope, hab_m, turbines, grid, road, overlap, missing) -> TechnologyAssessment:
    b: dict[str, float] = {}
    blockers: list[str] = []
    conds: list[str] = []
    b["wind_speed"] = 35 * _lin(v100, WIND_ZERO_MS, WIND_FULL_MS) if v100 is not None else 0.0
    if hab_m is None or hab_m >= HAB_GO_M:
        b["setback"] = 25.0
    elif hab_m >= HAB_COND_M:
        b["setback"] = 12.0
        conds.append(f"habitation {hab_m:.0f} m away (< {HAB_GO_M:.0f} m) - noise / shadow-flicker and state setback norms to check")
    else:
        b["setback"] = 0.0
        blockers.append(f"habitation only {hab_m:.0f} m away (< {HAB_COND_M:.0f} m)")
    b["grid"] = 20 * grid / 100
    b["terrain"] = 10 * _lin(slope, 20, 10) if slope is not None else 5.0
    # access road matters for blades / cranes; existing turbines hint at a proven wind corridor and evacuation
    b["access_neighbourhood"] = (5.0 if road else 0.0) + (2.0 if turbines == 0 else (5.0 if turbines <= 8 else 3.0))
    if v100 is None:
        conds.append("wind speed unavailable (Open-Meteo ERA5)")
    elif v100 < WIND_HARD_FLOOR_MS:
        blockers.append(f"mean wind {v100:.2f} m/s at 100 m (< {WIND_HARD_FLOOR_MS} m/s)")
    elif v100 < WIND_MIN_MS:
        conds.append(f"mean wind {v100:.2f} m/s at 100 m below {WIND_MIN_MS} m/s - confirm with an on-site / NIWE wind study")
    if slope is not None and slope > 25:
        blockers.append(f"terrain too steep for turbine foundations/cranes ({slope:.1f} deg > 25 deg)")
    if overlap >= COVER_BLOCK_PCT:
        blockers.append(f"{overlap:.0f}% of the site is mapped as forest / wetland / water")
    elif overlap > COVER_COND_PCT:
        conds.append(f"{overlap:.0f}% of the site is mapped as forest / wetland / water - forest or water-body restrictions apply")
    if not road:
        conds.append("no road within 1 km in OSM - heavy-haul access road needed")
    conds += [f"{m} unavailable" for m in missing]
    score = round(sum(b.values()))
    return TechnologyAssessment(
        verdict=_verdict(score, blockers, conds), score=score,
        score_breakdown={k: round(v, 1) for k, v in b.items()}, blockers=blockers, conditions=conds,
    )


def _land_record(inp: LandCheckInput, state_code: Optional[str], sub_district: Optional[str], village: Optional[str]) -> LandRecordInfo:
    info = LandRecordInfo(
        survey_number=inp.survey_number, ulpin=inp.ulpin,
        reference_supplied=bool(inp.survey_number or inp.ulpin),
        record_portal=RECORD_PORTALS.get(state_code or ""),
    )
    if state_code == "IN-AP":
        hay = f"{sub_district or ''} {village or ''}"
        hit = next((m for m in AP_PILOT_MANDALS if re.search(m, hay, re.I)), None)
        if hit:
            info.blockchain_pilot = (
                f"location appears to be in the Mee Bhoomi-Blockchain pilot mandal {hit}; the ledger is a permissioned "
                "Hyperledger Fabric network without public read access - obtain the record through Mee Bhoomi / the revenue office"
            )
        else:
            info.blockchain_pilot = (
                "Andhra Pradesh runs the Mee Bhoomi-Blockchain pilot (permissioned Hyperledger Fabric, 7 mandals, launched "
                "23 July 2026); this location does not match a pilot mandal by its OSM name (verify)"
            )
    return info


def build_report(inp: LandCheckInput, site: Site, gis: GisResult) -> AuditReport:
    warnings: list[str] = []
    dq: dict[str, str] = {}
    extra_conditions: list[str] = []  # apply to the whole site: they block an unconditional GO

    def status(key: str, ok_note: str = "ok") -> str:
        return f"unavailable: {gis.errors[key]}" if key in gis.errors else ok_note

    # ---- location
    admin = gis.admin or {}
    dq["admin_boundaries"] = status("admin", "ok (OSM Nominatim reverse geocoding, best effort)")
    state_code = admin.get("state_code")
    supported = state_code in SUPPORTED_STATES
    if gis.admin is None:
        extra_conditions.append("state could not be determined - state-specific rules were not applied")
    elif not supported:
        extra_conditions.append(
            f"state '{admin.get('state')}' is outside this release's coverage ({', '.join(SUPPORTED_STATES.values())}): "
            "no state-specific land-record, grid-utility or setback knowledge was applied"
        )
    record = _land_record(inp, state_code, admin.get("sub_district"), admin.get("village"))
    dq["land_record"] = "user-supplied reference, not verified (no public state API)" if record.reference_supplied \
        else "no reference supplied"
    if not record.reference_supplied:
        extra_conditions.append("no survey number / ULPIN supplied - the parcel cannot be tied to a land record")
    warnings.append("title is NOT verified: revenue records are not conclusive proof of title - run legal title due diligence")
    location = LocationInfo(
        state=admin.get("state"), state_code=state_code, state_supported=supported, district=admin.get("district"),
        sub_district=admin.get("sub_district"), village=admin.get("village"), area_hectares=round(site.area_ha, 2),
        land_record=record,
    )

    # ---- grid / habitation / access (OSM)
    infra, hab = gis.infra, gis.habitation
    dq["osm_infrastructure"] = status("infra", "ok (OpenStreetMap)")
    dq["osm_habitation"] = status("habitation", "ok (OpenStreetMap places, residential areas, buildings)")
    if infra:
        gscore = grid_score(infra["substation_m"], infra["powerline_m"])
        grid = GridAccess(
            nearest_substation_m=infra["substation_m"], substation_name=infra["substation_name"] or "none within 20 km",
            substation_operator=infra["substation_operator"], substation_voltage_kv=infra["substation_kv"],
            nearest_powerline_m=infra["powerline_m"], nearest_powerline_voltage_kv=infra["powerline_kv"], grid_score=gscore,
            connection_route_hint=connection_route(state_code, infra["substation_operator"], infra["substation_kv"])
            if infra["substation_m"] is not None else None,
        )
        if infra["substation_m"] is None:
            warnings.append("no substation within 20 km in OpenStreetMap (OSM completeness varies - ask the utility)")
        elif infra["substation_kv"] is None:
            warnings.append("nearest substation has no voltage tag in OSM - connection voltage level must be confirmed with the utility")
    else:
        grid, gscore = GridAccess(), 0
        warnings.append("grid and access data unavailable (OpenStreetMap/Overpass query failed)")
    reg = RegulatoryChecks(
        distance_to_habitation_m=hab["habitation_m"] if hab else None,
        habitation_basis=hab["basis"] if hab else None,
        road_access_within_1km=bool(infra and infra["road_access"]),
        existing_wind_turbines_within_3km=infra["wind_turbines_3km"] if infra else 0,
        forest_water_overlap_pct=(gis.environment or {}).get("cover_overlap_pct", 0.0),
    )
    if hab is None:
        warnings.append("habitation data unavailable (OpenStreetMap/Overpass query failed) - setback not checked")
    elif hab["habitation_m"] is None and hab["buildings_seen"] == 0:
        warnings.append("no buildings, residential areas or settlements mapped within 1.5 km - OSM may simply be incomplete here")

    # ---- environment
    env = gis.environment
    dq["protected_areas"] = status(
        "environment", "ok (OpenStreetMap only - no authoritative open layer for India; WDPA withholds many Indian polygons)")
    zones = env["zones"] if env else []
    inside = [z for z in zones if z.within_site]
    veto_zones = [z for z in inside if z.veto]
    soft_zones = [z for z in inside if not z.veto]
    nearby = [z for z in zones if not z.within_site]
    ev = EnvironmentalVeto(
        has_veto=bool(veto_zones), intersecting_protected_zones=[z.label() for z in inside],
        protected_zones_within_buffer=[z.label() for z in nearby],
    )
    if soft_zones:
        warnings.append("site intersects protected / conserved area(s): " + "; ".join(z.label() for z in soft_zones)
                        + " - clearance from the forest / wildlife authority needed")
    if nearby:
        extra_conditions.append(
            f"protected area within ~{ESZ_BUFFER_M} m (possible eco-sensitive zone): " + "; ".join(z.label() for z in nearby)
            + " - check the notified ESZ with the state forest department / MoEFCC"
        )
    if env is None:
        warnings.append("protected-area check unavailable - veto status could not be verified")
    else:
        warnings.append("protected-area screen is OpenStreetMap-based: verify forest and protected-area status on PARIVESH / with the state forest department")

    # ---- resources
    solar, wind, slope = gis.solar, gis.wind, gis.slope
    dq["solar_pvgis"] = status("solar", f"ok (EU JRC PVGIS 5.3, {solar['database']})" if solar else "n/a")
    dq["wind_open_meteo"] = status("wind", f"ok ({wind['method']})" if wind else "n/a")
    dq["terrain_slope"] = status("slope", "ok (Copernicus DEM 90 m via Open-Meteo, 3x3 Horn)")
    elevation = (slope or {}).get("elevation") or (solar or {}).get("elevation") or (wind or {}).get("elevation")
    res = ResourcePotential(
        solar_kwh_per_kwp_year=round(solar["e_y"], 1) if solar else None,
        wind_speed_100m_ms=round(wind["v100"], 2) if wind else None,
        slope_degrees=round(slope["slope_deg"], 1) if slope else None,
        elevation_m=round(elevation, 0) if elevation is not None else None,
    )
    if wind:
        warnings.append("wind speed is an ERA5 reanalysis mean on a ~25 km grid - confirm with an annual on-site / NIWE wind study")

    # ---- per-technology assessment
    missing = []
    if infra is None:
        missing.append("grid/access data (OSM)")
    if hab is None:
        missing.append("habitation data (OSM)")
    tech: dict[str, TechnologyAssessment] = {}
    overlap = reg.forest_water_overlap_pct
    if inp.project_type in ("solar", "hybrid"):
        tech["solar"] = _solar(res.solar_kwh_per_kwp_year, res.slope_degrees, site.area_ha, gscore,
                               reg.road_access_within_1km, overlap, missing)
    if inp.project_type in ("wind", "hybrid"):
        tech["wind"] = _wind(res.wind_speed_100m_ms, res.slope_degrees, reg.distance_to_habitation_m,
                             reg.existing_wind_turbines_within_3km, gscore, reg.road_access_within_1km, overlap, missing)
    if "wind" in tech and reg.existing_wind_turbines_within_3km > 8:
        warnings.append(f"{reg.existing_wind_turbines_within_3km} wind turbines within 3 km: likely an existing wind corridor, "
                        "but check wake losses and remaining evacuation capacity")
    best_name = max(tech, key=lambda k: (_RANK[tech[k].verdict], tech[k].score))  # ties -> first (solar)
    best = tech[best_name]
    verdict, score = best.verdict, best.score

    # ---- overlays (applied last, always win)
    if ev.has_veto:
        verdict, score = "NO_GO", min(score, VETO_SCORE_CAP)
        warnings.append("environmental veto: site intersects " + "; ".join(z.label() for z in veto_zones))
    else:
        if soft_zones:
            score = max(0, score - PROTECTED_PENALTY)
            if verdict == "GO":
                verdict = "CONDITIONAL_GO"
        if verdict == "GO" and (extra_conditions or env is None or infra is None or hab is None):
            verdict = "CONDITIONAL_GO"  # an unverifiable core check or an open site-wide condition can never give an unconditional GO
        if score < NO_GO_MAX_SCORE:
            verdict = "NO_GO"
    warnings += [f"[site] {c}" for c in extra_conditions]
    warnings += [f"[{best_name}] {c}" for c in best.conditions] + [f"[{best_name}] BLOCKER: {x}" for x in best.blockers]

    return AuditReport(
        overall_verdict=verdict, score=max(0, min(100, int(score))), project_type=inp.project_type,
        assessed_technology=best_name, location_info=location, grid_access=grid, regulatory_checks=reg,
        environmental_veto=ev, resource_potential=res, technology_assessment=tech, warnings=warnings, data_quality=dq,
        onchain_registry=report_context(site.lat, site.lon, state_code),
    )
