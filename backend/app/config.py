"""Runtime configuration. Everything comes from the environment; nothing is hard-coded."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Database — Postgres in dev/prod. Tests may point at a throwaway cluster.
    database_url: str = "postgresql+psycopg://ledgerline:ledgerline@localhost:5432/ledgerline"

    # PayPal
    paypal_env: Literal["sandbox", "live"] = "sandbox"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""  # from the developer dashboard; required to verify signatures
    allow_live: bool = False  # hard safety: live mutations refuse to run unless explicitly enabled
    paypal_dry_run: bool = False  # executor logs intended PayPal mutations instead of sending them (fixture demos)
    demo_seed_on_start: bool = False  # worker replays the bundled fixture once if the ledger is empty (hosted demos)
    paypal_mcp_enabled: bool = True  # give agents PayPal's official MCP server (@paypal/mcp) as read-only tools when Node is present

    # Agents
    llm_model: str = "anthropic:claude-sonnet-4-5"
    llm_api_key: str = ""  # provider-agnostic; exported to ANTHROPIC_API_KEY / OPENAI_API_KEY etc. based on llm_model
    llm_temperature: float = 0.0
    policy_path: Path = BACKEND_DIR / "policy.yaml"
    agent_max_tool_calls: int = 12

    # Worker
    poll_interval_seconds: int = 300
    job_batch_size: int = 20
    job_max_attempts: int = 6

    # Recon tunables
    stale_auth_days: int = 29
    dispute_sla_hours: int = 72
    settlement_lag_hours: int = 24
    payout_fee_band_bps: int = 300  # ±3% of expected fee
    duplicate_order_window_minutes: int = 10

    # Web
    operator_token: str = ""  # when set, every /api request must carry X-Operator-Token; always set this in prod
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    serve_frontend: bool = True
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    @property
    def paypal_base_url(self) -> str:
        return (
            "https://api-m.sandbox.paypal.com"
            if self.paypal_env == "sandbox"
            else "https://api-m.paypal.com"
        )

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)

    @model_validator(mode="after")
    def _guard_live(self) -> Settings:
        if self.paypal_env == "live" and not self.allow_live:
            raise ValueError("PAYPAL_ENV=live requires ALLOW_LIVE=true. Refusing to start.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
