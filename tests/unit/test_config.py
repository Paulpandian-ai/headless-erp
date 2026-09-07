"""Environment fallbacks for Railway and the persisted signing key."""

from __future__ import annotations

from anerp.config import Settings, normalize_database_url


def _settings(monkeypatch, **env: str) -> Settings:
    for key in (
        "ANERP_DATABASE_URL",
        "DATABASE_URL",
        "ANERP_PORT",
        "PORT",
        "ANERP_PUBLIC_URL",
        "RAILWAY_PUBLIC_DOMAIN",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_database_url_falls_back_to_railway_and_rewrites_scheme(monkeypatch) -> None:
    s = _settings(monkeypatch, DATABASE_URL="postgresql://u:p@host:5432/anerp")
    assert s.database_url == "postgresql+psycopg://u:p@host:5432/anerp"
    s = _settings(
        monkeypatch, DATABASE_URL="postgres://u:p@host/anerp", ANERP_DATABASE_URL="sqlite:///./x.db"
    )
    assert s.database_url == "sqlite:///./x.db"
    assert _settings(monkeypatch).database_url == "sqlite:///./anerp.db"
    assert normalize_database_url("postgresql+psycopg://a") == "postgresql+psycopg://a"


def test_port_and_public_url_fallbacks(monkeypatch) -> None:
    s = _settings(monkeypatch, PORT="6543", RAILWAY_PUBLIC_DOMAIN="anerp-dev.up.railway.app")
    assert s.port == 6543 and s.public_url == "https://anerp-dev.up.railway.app"
    s = _settings(
        monkeypatch,
        PORT="6543",
        ANERP_PORT="8001",
        RAILWAY_PUBLIC_DOMAIN="x.up.railway.app",
        ANERP_PUBLIC_URL="https://erp.example.com/",
    )
    assert s.port == 8001 and s.public_url == "https://erp.example.com"


def test_generated_signing_key_survives_restart(kernel, agent) -> None:
    from sqlmodel import select

    from anerp.config import get_settings
    from anerp.ledger.models import ServerKey
    from anerp.ledger.receipts import KeyRing, keyring

    assert get_settings().signing_key_pem is None
    first = agent.ok("create_supplier", code="K-RESTART", name="k")
    rows = kernel.exec(select(ServerKey)).all()
    assert len(rows) == 1 and rows[0].private_key_pem and rows[0].retired_at is None
    # a fresh process only has the database: a new KeyRing must load the same key
    keyring.reset()
    fresh = KeyRing()
    fresh.ensure_active(kernel)
    assert fresh._active_id == rows[0].id
    second = agent.ok("create_supplier", code="K-RESTART-2", name="k")
    assert second["receipt"]["public_key_id"] == first["receipt"]["public_key_id"]
    assert agent.query("verify_receipt", receipt_id=first["receipt"]["id"])["valid"]
