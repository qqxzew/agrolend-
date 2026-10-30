"""India Agent 1 (Land Audit) settings, read from environment / .env.

Variables are namespaced `IN_AUDIT_*` so they never collide with the German worker's; the Masumi payment-service
connection (`MASUMI_*`) is shared with the German stack on purpose (same payment service, same Preprod wallet).
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _a(name: str) -> str:
    return f"IN_AUDIT_{name}"


class AuditSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True,
                                      env_prefix="IN_AUDIT_")

    # --- Masumi -----------------------------------------------------------
    bypass_payment: bool = Field(True, validation_alias=_a("BYPASS_PAYMENT"))
    masumi_network: str = Field("Preprod", validation_alias="MASUMI_NETWORK")
    masumi_payment_service_url: str = Field("http://localhost:3001", validation_alias="MASUMI_PAYMENT_SERVICE_URL")
    masumi_api_key: str = Field("", validation_alias="MASUMI_API_KEY")
    # Registry identifier of THIS agent (register it separately from the German Agent 1).
    agent_identifier: str = Field("", validation_alias=_a("AGENT_IDENTIFIER"))
    price_tada: float = Field(10.0, validation_alias=_a("PRICE_TADA"))
    masumi_payment_source_type: str = Field("", validation_alias="MASUMI_PAYMENT_SOURCE_TYPE")
    masumi_supported_payment_source_index: str = Field("", validation_alias="MASUMI_SUPPORTED_PAYMENT_SOURCE_INDEX")
    masumi_requested_funds_lovelace: str = Field("", validation_alias="MASUMI_REQUESTED_FUNDS_LOVELACE")
    # Shared secret for POST /internal/audit (the India matcher asks for audits without paying). Empty = disabled.
    internal_api_key: str = Field("", validation_alias=_a("INTERNAL_API_KEY"))

    # --- Storage ------------------------------------------------------------
    database_path: str = Field("data/in_jobs.sqlite3", validation_alias=_a("DATABASE_PATH"))

    # --- GIS ------------------------------------------------------------------
    http_timeout_s: float = 45.0
    http_retries: int = 2
    max_area_ha: float = Field(1000.0, validation_alias=_a("MAX_AREA_HA"))
    overpass_endpoints: list[str] = Field(
        default_factory=lambda: [
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
        ]
    )
    nominatim_url: str = "https://nominatim.openstreetmap.org/reverse"
    pvgis_url: str = "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc"
    # Wind: annual mean of ERA5 hourly 100 m speed over a FIXED reference period (deterministic reports).
    wind_start_date: str = Field("2022-01-01", validation_alias=_a("WIND_START_DATE"))
    wind_end_date: str = Field("2024-12-31", validation_alias=_a("WIND_END_DATE"))
    # The free Open-Meteo API is non-commercial only. A paid key switches to the customer endpoints.
    open_meteo_api_key: str = Field("", validation_alias=_a("OPEN_METEO_API_KEY"))
    user_agent: str = "india-land-audit-worker/0.1 (Masumi agent; contact via repository)"

    @property
    def open_meteo_archive_url(self) -> str:
        host = "customer-archive-api" if self.open_meteo_api_key else "archive-api"
        return f"https://{host}.open-meteo.com/v1/archive"

    @property
    def open_meteo_elevation_url(self) -> str:
        host = "customer-api" if self.open_meteo_api_key else "api"
        return f"https://{host}.open-meteo.com/v1/elevation"


@lru_cache
def get_audit_settings() -> AuditSettings:
    return AuditSettings()
