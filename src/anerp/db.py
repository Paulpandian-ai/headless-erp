"""Database engine and session management (SQLModel on SQLAlchemy 2, sync)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine

from anerp.config import get_settings
from anerp.core.ids import new_ulid, utcnow

_engine: Engine | None = None


def make_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    kwargs: dict[str, Any] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url == "sqlite://":
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn: Any, _: Any) -> None:  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            if ":memory:" not in url:
                cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def set_engine(engine: Engine | None) -> None:
    """Override the process-wide engine (tests use an in-memory SQLite engine)."""
    global _engine
    _engine = engine


def init_db(engine: Engine | None = None) -> None:
    """Create all tables. Production deployments use Alembic; tests and dev use this."""
    import anerp.models  # noqa: F401  (registers every table on SQLModel.metadata)

    SQLModel.metadata.create_all(engine or get_engine())


def new_session() -> Session:
    return Session(get_engine(), autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class KernelRow(SQLModel):
    """Common columns for every table (DESIGN.md §5.1)."""

    id: str = Field(default_factory=new_ulid, primary_key=True, max_length=26)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    state_version: int = Field(default=1)

    def touch(self) -> None:
        self.updated_at = utcnow()
        self.state_version += 1
