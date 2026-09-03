"""Test harness: in-memory SQLite, fresh policy engine, fresh keyring, seeded fixture."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlmodel import Session

os.environ.setdefault("ANERP_ENV", "test")
os.environ.setdefault("ANERP_DATABASE_URL", "sqlite://")
os.environ.setdefault("ANERP_TOKEN_PEPPER", "test-pepper-not-secret")
os.environ.setdefault("ANERP_BOOTSTRAP_ADMIN_TOKEN", "anerp_test_bootstrap_admin_token")
os.environ.setdefault("LLM_PROVIDER", "none")

from anerp import db  # noqa: E402
from anerp.config import reset_settings_cache  # noqa: E402
from anerp.core.dispatch import dispatch, run_query  # noqa: E402
from anerp.core.envelope import Actor, Envelope  # noqa: E402
from anerp.core.requestlog import request_log, simulations  # noqa: E402
from anerp.ledger.receipts import keyring  # noqa: E402
from anerp.policy import engine as policy_engine  # noqa: E402

AGENT = Actor(id="agent:test", kind="agent")
HUMAN = Actor(id="human:controller", kind="human")
ADMIN = Actor(id="admin:test", kind="admin")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def kernel(request: pytest.FixtureRequest) -> Iterator[Session]:
    reset_settings_cache()
    engine = db.make_engine("sqlite://")
    db.set_engine(engine)
    db.init_db(engine)
    keyring.reset()
    policy_engine.set_engine(None)
    request_log.clear()
    simulations.clear()
    fixture = getattr(request, "param", "baseline")
    from anerp.seed import seed_fixture

    with db.session_scope() as s:
        seed_fixture(s, fixture)
    session = db.new_session()
    try:
        yield session
    finally:
        session.close()
        db.set_engine(None)


@pytest.fixture
def empty_kernel(request: pytest.FixtureRequest) -> Iterator[Session]:
    reset_settings_cache()
    engine = db.make_engine("sqlite://")
    db.set_engine(engine)
    db.init_db(engine)
    keyring.reset()
    policy_engine.set_engine(None)
    request_log.clear()
    simulations.clear()
    from anerp.seed import seed_fixture

    with db.session_scope() as s:
        seed_fixture(s, "empty")
    session = db.new_session()
    try:
        yield session
    finally:
        session.close()
        db.set_engine(None)


class Client:
    """Thin in-process client used by tests: simulate/commit/query with fresh keys."""

    def __init__(self, actor: Actor = AGENT) -> None:
        self.actor = actor

    def simulate(self, tool: str, /, **payload: Any) -> dict[str, Any]:
        return dispatch(Envelope(tool=tool, mode="simulate", actor=self.actor, payload=payload))

    def commit(
        self, tool: str, /, key: str | None = None, simulation_id: str | None = None, **payload: Any
    ) -> dict[str, Any]:
        return dispatch(
            Envelope(
                tool=tool,
                mode="commit",
                idempotency_key=key or f"k-{uuid.uuid4()}",
                simulation_id=simulation_id,
                actor=self.actor,
                payload=payload,
            )
        )

    def ok(self, tool: str, /, **payload: Any) -> dict[str, Any]:
        r = self.commit(tool, **payload)
        assert r["ok"], r
        return r

    def query(self, tool: str, /, **payload: Any) -> dict[str, Any]:
        r = run_query(tool, payload, self.actor)
        assert r["ok"], r
        return r["result"]


@pytest.fixture
def agent() -> Client:
    return Client(AGENT)


@pytest.fixture
def human() -> Client:
    return Client(HUMAN)


@pytest.fixture
def admin() -> Client:
    return Client(ADMIN)


def tb_balanced(client: Client) -> bool:
    return bool(client.query("get_trial_balance")["is_balanced"])
