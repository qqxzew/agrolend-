"""India Agent 4 (Pool Architect) settings, read from environment / .env (variables are `IN_ARCHITECT_*`)."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _a(name: str) -> str:
    return f"IN_ARCHITECT_{name}"


class ArchitectSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True,
                                      env_prefix="IN_ARCHITECT_")

    # India Agent 3 - source of the revealed parcels/companies (needs IN_ESCROW_API_KEY on both sides).
    escrow_url: str = Field("http://localhost:9002", validation_alias=_a("ESCROW_URL"))
    escrow_api_key: str = Field("", validation_alias=_a("ESCROW_API_KEY"))

    architect_database_path: str = Field("data/in_architect.sqlite3", validation_alias=_a("DATABASE_PATH"))
    # Shared secret the (future) orchestrator sends as `X-API-Key`. Empty = auth disabled (dev only).
    architect_api_key: str = Field("", validation_alias=_a("API_KEY"))

    # --- document parameters ---
    platform_name: str = Field("India Land Pooling Platform", validation_alias=_a("PLATFORM_NAME"))
    pool_arbitration_seat: str = Field("New Delhi", validation_alias=_a("ARBITRATION_SEAT"))
    pool_exclusivity_months: int = 24
    pool_term_years: int = 30


@lru_cache
def get_architect_settings() -> ArchitectSettings:
    return ArchitectSettings()
