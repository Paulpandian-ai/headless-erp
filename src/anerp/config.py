"""Configuration: every value comes from the environment (see DESIGN.md §13).

Railway conveniences: `DATABASE_URL` (a plain `postgresql://` URL from the Postgres plugin) is
accepted when `ANERP_DATABASE_URL` is unset, `PORT` when `ANERP_PORT` is unset, and
`RAILWAY_PUBLIC_DOMAIN` becomes the public URL when `ANERP_PUBLIC_URL` is unset.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """SQLAlchemy needs the driver in the scheme: postgresql:// and postgres:// -> postgresql+psycopg://."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANERP_", env_file=".env", extra="ignore")

    env: Literal["dev", "demo", "prod", "test"] = "dev"
    database_url: str = Field(
        default="sqlite:///./anerp.db",
        validation_alias=AliasChoices("ANERP_DATABASE_URL", "DATABASE_URL"),
    )
    base_currency: str = "USD"
    bootstrap_admin_token: str | None = None
    token_pepper: str = "dev-pepper-change-me"
    signing_key_pem: str | None = None
    advertise_oauth: bool = False
    policy_path: str = "./policies/default.yaml"
    approval_ttl_hours: int = 72
    redact_fields: str = "bank_account,tax_id,notes"
    port: int = Field(default=8000, validation_alias=AliasChoices("ANERP_PORT", "PORT"))
    public_url: str = Field(
        default="http://localhost:8000",
        validation_alias=AliasChoices("ANERP_PUBLIC_URL", "RAILWAY_PUBLIC_DOMAIN"),
    )
    log_level: str = "INFO"
    otel_enabled: bool = False
    simulation_ttl_minutes: int = 10
    request_log_size: int = 10_000
    po_approval_threshold_cents: int = 1_000_000

    # LLM provider for the internal agent / eval (not prefixed with ANERP_)
    llm_provider: Literal["anthropic", "openai", "google", "none"] = Field(
        default="none", validation_alias="LLM_PROVIDER"
    )

    @field_validator("database_url")
    @classmethod
    def _database_url(cls, value: str) -> str:
        return normalize_database_url(value)

    @field_validator("public_url")
    @classmethod
    def _public_url(cls, value: str) -> str:
        # RAILWAY_PUBLIC_DOMAIN is a bare host name; the app is always served over https there.
        value = value.strip().rstrip("/")
        if value and not value.startswith(("http://", "https://")):
            return "https://" + value
        return value

    @property
    def redact_field_set(self) -> frozenset[str]:
        return frozenset(f.strip() for f in self.redact_fields.split(",") if f.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
