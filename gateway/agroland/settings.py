"""Gateway configuration. Everything comes from environment variables (see .env.example); nothing secret has a default."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _bundled_assistant_key() -> str:
    """Fallback key of the home-page assistant, kept in config/assistant.env (AGROLAND_ASSISTANT_ENV overrides the path; tests point it nowhere)."""
    path = Path(os.environ.get("AGROLAND_ASSISTANT_ENV", ROOT / "config" / "assistant.env"))
    try:
        for line in path.read_text("utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def load_catalog(path: Path | None = None) -> dict:
    return json.loads((path or Path(os.environ.get("AGROLAND_SERVICES_FILE", ROOT / "config" / "services.json"))).read_text("utf-8"))


@dataclass(frozen=True)
class GeoStack:
    """URLs and internal keys of the four internal services of one country pack."""
    audit_url: str
    audit_key: str
    matcher_url: str
    matcher_key: str
    escrow_url: str
    escrow_key: str
    architect_url: str
    architect_key: str


@dataclass(frozen=True)
class Settings:
    state_dir: Path
    # payment_mode: "masumi" = real Masumi/Cardano preprod payment gates execution.
    #               "dev-unpaid" = no payment; every order and result is labelled UNPAID in API and UI. Never use in the public demo.
    payment_mode: str
    public_url: str
    internal_key: str          # shared secret for /internal/* routes used by the Node agent layer
    admin_key: str
    mps_url: str               # Masumi payment service (seller side)
    mps_key: str               # scoped runtime/ReadAndPay key of the seller wallet
    buyer_mps_url: str         # optional second payment service / wallet that pays on behalf of web demo customers
    buyer_mps_key: str
    agent_identifiers: dict    # {"land_audit": "...", "lease_check": "...", "pool_access": "..."}
    seller_vkey: str
    payment_source_index: int
    blockfrost_key: str
    geo: dict                  # {"DE": GeoStack, "IN": GeoStack}
    catalog: dict = field(default_factory=dict)
    trust_proxy: bool = False             # read the client IP from X-Forwarded-For (set only behind Caddy/nginx)
    rate_sessions_per_hour: int = 30      # workspace creations per client IP
    rate_orders_per_hour: int = 120       # order creations per workspace
    max_body_bytes: int = 12 * 1024 * 1024
    max_parcels_per_user: int = 200
    openai_api_key: str = ""              # home-page assistant (chat.py); empty = the page falls back to keyword routing
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"
    rate_chat_per_hour: int = 60          # assistant messages per client IP
    cropwatch: str = "live"               # "live": Lease Check reads Sentinel-2 / Open-Meteo for parcels with boundaries; "off": section marked unavailable

    @property
    def paid(self) -> bool:
        return self.payment_mode == "masumi"


def get_settings() -> Settings:
    e = lambda name, default=None: os.environ.get(name) or default  # an empty value (compose passes unset names as "") means "not set"
    geo = {
        "DE": GeoStack(e("GEO_DE_AUDIT_URL", "http://127.0.0.1:8000"), e("GEO_DE_INTERNAL_KEY", ""),
                       e("GEO_DE_MATCHER_URL", "http://127.0.0.1:8001"), e("GEO_DE_INTERNAL_KEY", ""),
                       e("GEO_DE_ESCROW_URL", "http://127.0.0.1:8002"), e("GEO_DE_ESCROW_KEY", ""),
                       e("GEO_DE_ARCHITECT_URL", "http://127.0.0.1:8003"), e("GEO_DE_ARCHITECT_KEY", "")),
        "IN": GeoStack(e("GEO_IN_AUDIT_URL", "http://127.0.0.1:9000"), e("GEO_IN_INTERNAL_KEY", ""),
                       e("GEO_IN_MATCHER_URL", "http://127.0.0.1:9001"), e("GEO_IN_INTERNAL_KEY", ""),
                       e("GEO_IN_ESCROW_URL", "http://127.0.0.1:9002"), e("GEO_IN_ESCROW_KEY", ""),
                       e("GEO_IN_ARCHITECT_URL", "http://127.0.0.1:9003"), e("GEO_IN_ARCHITECT_KEY", "")),
    }
    mode = e("AGROLAND_PAYMENT_MODE", "masumi").strip().lower()
    if mode not in {"masumi", "dev-unpaid"}:
        raise RuntimeError("AGROLAND_PAYMENT_MODE must be 'masumi' or 'dev-unpaid'")
    crop = e("AGROLAND_CROPWATCH", "live").strip().lower()
    if crop not in {"live", "off"}:
        raise RuntimeError("AGROLAND_CROPWATCH must be 'live' or 'off'")
    return Settings(
        state_dir=Path(e("AGROLAND_STATE_DIR", str(ROOT / "state"))),
        payment_mode=mode,
        public_url=e("AGROLAND_PUBLIC_URL", "http://127.0.0.1:8080").rstrip("/"),
        internal_key=e("AGROLAND_INTERNAL_KEY", ""),
        admin_key=e("AGROLAND_ADMIN_KEY", ""),
        mps_url=e("MPS_URL", "http://127.0.0.1:38127").rstrip("/"),
        mps_key=e("MPS_RUNTIME_TOKEN", ""),
        buyer_mps_url=e("BUYER_MPS_URL", "").rstrip("/"),
        buyer_mps_key=e("BUYER_MPS_TOKEN", ""),
        agent_identifiers={k: e(f"AGENT_IDENTIFIER_{k.upper()}", "") for k in ("land_audit", "lease_check", "pool_access")},
        seller_vkey=e("SELLER_VKEY", ""),
        payment_source_index=int(e("PAYMENT_SOURCE_INDEX", "0")),
        blockfrost_key=e("BLOCKFROST_API_KEY_PREPROD", ""),
        geo=geo,
        catalog=load_catalog(),
        trust_proxy=_flag("AGROLAND_TRUST_PROXY"),
        rate_sessions_per_hour=int(e("AGROLAND_RATE_SESSIONS_PER_HOUR", "30")),
        rate_orders_per_hour=int(e("AGROLAND_RATE_ORDERS_PER_HOUR", "120")),
        openai_api_key=e("OPENAI_API_KEY") or _bundled_assistant_key(),
        openai_base_url=e("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        openai_model=e("OPENAI_MODEL", "gpt-4.1-mini"),
        rate_chat_per_hour=int(e("AGROLAND_RATE_CHAT_PER_HOUR", "60")),
        cropwatch=crop,
    )
