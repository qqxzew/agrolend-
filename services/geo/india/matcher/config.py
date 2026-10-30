"""India Agent 2 (Matcher) settings, read from environment / .env (variables are `IN_MATCHER_*`)."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _a(name: str) -> str:
    return f"IN_MATCHER_{name}"


class MatcherSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True,
                                      env_prefix="IN_MATCHER_")

    # India Agent 1 (validator) - called over HTTP so it can later move behind the orchestrator.
    validator_url: str = Field("http://localhost:9000", validation_alias=_a("VALIDATOR_URL"))
    # A real audit queries several public services one after another (Overpass is serialised): allow 5 minutes.
    validator_poll_timeout_s: float = 300.0
    # India Agent 1's IN_AUDIT_INTERNAL_API_KEY. Set = unpaid POST /internal/audit (works with payment enabled);
    # empty = public /start_job, which only completes while Agent 1 runs with IN_AUDIT_BYPASS_PAYMENT=true.
    validator_api_key: str = Field("", validation_alias=_a("VALIDATOR_API_KEY"))

    matcher_database_path: str = Field("data/in_matcher.sqlite3", validation_alias=_a("DATABASE_PATH"))
    match_radius_m: float = 1500.0
    # Parcels with these verdicts never enter the pool.
    rejected_verdicts: tuple[str, ...] = ("NO_GO",)
    max_parcels_per_developer: int = 50  # limits "probe parcels" used to scan for neighbours
    # Indian holdings are small and fragmented (pooling is the point), so the floor is lower than in Germany.
    min_area_ha: float = 1.0
    max_area_ha: float = 1000.0
    duplicate_overlap_ratio: float = 0.9

    # Shared secret the (future) orchestrator sends as `X-API-Key`. Empty = auth disabled (dev only).
    matcher_api_key: str = Field("", validation_alias=_a("API_KEY"))


@lru_cache
def get_matcher_settings() -> MatcherSettings:
    return MatcherSettings()
