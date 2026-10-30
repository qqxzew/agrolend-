"""India Agent 3 (Escrow & NDA) settings, read from environment / .env (variables are `IN_ESCROW_*`)."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _a(name: str) -> str:
    return f"IN_ESCROW_{name}"


class EscrowSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True,
                                      env_prefix="IN_ESCROW_")

    # India Agent 2 - source of the un-anonymised match data (needs IN_MATCHER_API_KEY on both sides).
    matcher_url: str = Field("http://localhost:9001", validation_alias=_a("MATCHER_URL"))
    matcher_api_key: str = Field("", validation_alias=_a("MATCHER_API_KEY"))

    escrow_database_path: str = Field("data/in_escrow.sqlite3", validation_alias=_a("DATABASE_PATH"))
    # Shared secret the (future) orchestrator sends as `X-API-Key`. Empty = auth disabled (dev only).
    escrow_api_key: str = Field("", validation_alias=_a("API_KEY"))

    # --- Masumi: each developer buys the "reveal" service from this agent (one payment per side) ---
    escrow_bypass_payment: bool = Field(True, validation_alias=_a("BYPASS_PAYMENT"))  # true = deposits locked immediately (dev)
    escrow_agent_identifier: str = Field("", validation_alias=_a("AGENT_IDENTIFIER"))
    masumi_network: str = Field("Preprod", validation_alias="MASUMI_NETWORK")
    masumi_payment_service_url: str = Field("http://localhost:3001", validation_alias="MASUMI_PAYMENT_SERVICE_URL")
    masumi_api_key: str = Field("", validation_alias="MASUMI_API_KEY")
    masumi_payment_source_type: str = Field("", validation_alias="MASUMI_PAYMENT_SOURCE_TYPE")
    masumi_supported_payment_source_index: str = Field("", validation_alias="MASUMI_SUPPORTED_PAYMENT_SOURCE_INDEX")
    masumi_requested_funds_lovelace: str = Field("", validation_alias="MASUMI_REQUESTED_FUNDS_LOVELACE")
    deposit_tada: float = Field(10.0, validation_alias=_a("DEPOSIT_TADA"))  # informational; price lives in the registry entry

    # --- process deadlines (hours) ---
    consent_window_h: int = 168
    deposit_window_h: int = 48
    signature_window_h: int = 168

    # --- NDA template parameters ---
    platform_name: str = Field("India Land Pooling Platform", validation_alias=_a("PLATFORM_NAME"))
    nda_arbitration_seat: str = Field("New Delhi", validation_alias=_a("ARBITRATION_SEAT"))
    nda_court_city: str = Field("New Delhi", validation_alias=_a("COURT_CITY"))
    nda_term_years: int = 2
    nda_aftereffect_years: int = 5
    nda_non_circumvention_months: int = 24
    # Indian Contract Act s.74: a stipulated sum is only recoverable as reasonable compensation up to this cap.
    nda_max_compensation_inr: int = 2_500_000


@lru_cache
def get_escrow_settings() -> EscrowSettings:
    return EscrowSettings()
