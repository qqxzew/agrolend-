"""Pydantic models: job input and the audit report (India, wind & solar)."""
from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ..common.geo import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN

ProjectType = Literal["wind", "solar", "hybrid"]
Verdict = Literal["GO", "CONDITIONAL_GO", "NO_GO"]

# States this release has state-specific knowledge for (land-record portal, blockchain pilot, grid utilities).
SUPPORTED_STATES = {"IN-AP": "Andhra Pradesh", "IN-GJ": "Gujarat"}

# ULPIN / Bhu-Aadhaar: 14-character alphanumeric parcel identifier (format check only, nothing is looked up).
_ULPIN = re.compile(r"^[A-Za-z0-9]{14}$")


class LandCheckInput(BaseModel):
    """Either (lat, lon[, radius_m]) or polygon_geojson, plus an optional land-record reference."""

    lat: Optional[float] = Field(None, description=f"Latitude (WGS84), {LAT_MIN}..{LAT_MAX}")
    lon: Optional[float] = Field(None, description=f"Longitude (WGS84), {LON_MIN}..{LON_MAX}")
    radius_m: float = Field(300.0, gt=0, le=5000, description="Radius of the analysed area around the point")
    polygon_geojson: Optional[dict[str, Any]] = Field(
        None, description="GeoJSON Polygon (or Feature wrapping one) in EPSG:4326"
    )
    project_type: ProjectType = "hybrid"
    # Land-record reference as printed on the state record (7/12 + 8A in Gujarat, Adangal/1-B in Andhra Pradesh).
    # It is NOT verified against any state system (none offers a public API) — the report says so.
    survey_number: Optional[str] = Field(None, max_length=40, description="Survey / block number of the parcel")
    ulpin: Optional[str] = Field(None, description="14-character ULPIN (Bhu-Aadhaar), if the record has one")

    @field_validator("lat")
    @classmethod
    def _lat(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (LAT_MIN <= v <= LAT_MAX):
            raise ValueError(f"lat must be within India ({LAT_MIN}..{LAT_MAX})")
        return v

    @field_validator("lon")
    @classmethod
    def _lon(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (LON_MIN <= v <= LON_MAX):
            raise ValueError(f"lon must be within India ({LON_MIN}..{LON_MAX})")
        return v

    @field_validator("ulpin")
    @classmethod
    def _ulpin(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if not _ULPIN.match(v):
            raise ValueError("ulpin must be 14 alphanumeric characters")
        return v.upper()

    @model_validator(mode="after")
    def _one_geometry(self) -> "LandCheckInput":
        has_point = self.lat is not None and self.lon is not None
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon must be given together")
        if not has_point and self.polygon_geojson is None:
            raise ValueError("provide either lat+lon or polygon_geojson")
        return self


# --- report ---------------------------------------------------------------


class LandRecordInfo(BaseModel):
    survey_number: Optional[str] = None
    ulpin: Optional[str] = None
    reference_supplied: bool = False
    title_verified: bool = False  # always false: no state offers a public API to verify title
    record_portal: Optional[str] = None  # where to obtain the state record
    blockchain_pilot: Optional[str] = None  # Andhra Pradesh: Mee Bhoomi-Blockchain pilot status for this location
    note: str = (
        "Land-record data is user-supplied and unverified. Revenue records (7/12, Adangal, RTC) are not conclusive proof "
        "of title; title needs a chain of registered documents, mutation history and encumbrance checks."
    )


class LocationInfo(BaseModel):
    state: Optional[str] = None
    state_code: Optional[str] = None
    state_supported: bool = False
    district: Optional[str] = None
    sub_district: Optional[str] = None  # taluka (Gujarat) / mandal (Andhra Pradesh) — best effort from OSM
    village: Optional[str] = None
    area_hectares: float
    land_record: LandRecordInfo = Field(default_factory=LandRecordInfo)


class GridAccess(BaseModel):
    # null = nothing found inside the search radius (substation 20 km, power line 10 km)
    nearest_substation_m: Optional[float] = None
    substation_name: Optional[str] = None
    substation_operator: Optional[str] = None  # OSM operator tag (grid utility hint)
    substation_voltage_kv: Optional[float] = None
    nearest_powerline_m: Optional[float] = None
    nearest_powerline_voltage_kv: Optional[float] = None
    connection_route_hint: Optional[str] = None  # state utility (discom/STU) vs central (CTU/ISTS)
    grid_score: int = 0


class RegulatoryChecks(BaseModel):
    # null = no habitation found within 1500 m of the site
    distance_to_habitation_m: Optional[float] = None
    habitation_basis: Optional[str] = None  # what the distance refers to (dwelling cluster / residential area / village centre)
    road_access_within_1km: bool = False
    existing_wind_turbines_within_3km: int = 0
    forest_water_overlap_pct: float = 0.0  # share of the site covered by mapped forest / wetland / water


class EnvironmentalVeto(BaseModel):
    has_veto: bool = False
    intersecting_protected_zones: list[str] = Field(default_factory=list)
    protected_zones_within_buffer: list[str] = Field(default_factory=list)  # possible eco-sensitive zone


class ResourcePotential(BaseModel):
    solar_kwh_per_kwp_year: Optional[float] = None
    wind_speed_100m_ms: Optional[float] = None
    slope_degrees: Optional[float] = None
    elevation_m: Optional[float] = None


class TechnologyAssessment(BaseModel):
    verdict: Verdict
    score: int
    score_breakdown: dict[str, float]
    blockers: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)


class AuditReport(BaseModel):
    overall_verdict: Verdict
    score: int = Field(ge=0, le=100)
    project_type: ProjectType
    assessed_technology: Optional[str] = None
    location_info: LocationInfo
    grid_access: GridAccess
    regulatory_checks: RegulatoryChecks
    environmental_veto: EnvironmentalVeto
    resource_potential: ResourcePotential
    technology_assessment: dict[str, TechnologyAssessment]
    warnings: list[str] = Field(default_factory=list)
    # per check: "ok" | "ok (fallback: ...)" | "unavailable: <reason>"
    data_quality: dict[str, str] = Field(default_factory=dict)
    methodology: str = "india-land-audit-worker/1 (see india/README.md: scoring)"
