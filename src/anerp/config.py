"""Configuration: every value comes from the environment (see DESIGN.md §13)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANERP_", env_file=".env", extra="ignore")

    env: Literal["dev", "demo", "prod", "test"] = "dev"
    database_url: str = "sqlite:///./anerp.db"
    base_currency: str = "USD"
    bootstrap_admin_token: str | None = None
    token_pepper: str = "dev-pepper-change-me"
    signing_key_pem: str | None = None
    advertise_oauth: bool = False
    policy_path: str = "./policies/default.yaml"
    approval_ttl_hours: int = 72
    redact_fields: str = "bank_account,tax_id,notes"
    port: int = 8000
    public_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    otel_enabled: bool = False
    simulation_ttl_minutes: int = 10
    request_log_size: int = 10_000
    po_approval_threshold_cents: int = 1_000_000

    # LLM provider for the internal agent / eval (not prefixed with ANERP_)
    llm_provider: Literal["anthropic", "openai", "google", "none"] = Field(
        default="none", validation_alias="LLM_PROVIDER"
    )

    @property
    def redact_field_set(self) -> frozenset[str]:
        return frozenset(f.strip() for f in self.redact_fields.split(",") if f.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
