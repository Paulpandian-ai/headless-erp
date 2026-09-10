"""Hosted-database checks (DESIGN.md §19): run only with ANERP_DATABASE_URL pointing at Postgres.

Covers what SQLite cannot: column length enforcement (the `(projected)` overflow) and the atomic
reset_and_seed against a real transactional database.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

URL = os.environ.get("ANERP_DATABASE_URL", "")


@pytest.fixture
def pg():
    if not URL.startswith("postgresql"):
        pytest.skip("ANERP_DATABASE_URL is not a Postgres URL")
    from anerp import db
    from anerp.config import reset_settings_cache
    from anerp.core.requestlog import request_log, simulations
    from anerp.ledger.receipts import keyring
    from anerp.policy import engine as policy_engine

    reset_settings_cache()
    engine = db.make_engine(URL)
    db.set_engine(engine)
    from alembic import command
    from alembic.config import Config

    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    command.upgrade(Config("alembic.ini"), "head")
    keyring.reset()
    policy_engine.set_engine(None)
    request_log.clear()
    simulations.clear()
    yield engine
    db.set_engine(None)


def test_seed_and_reset_on_postgres(pg) -> None:
    from anerp import db
    from anerp.core.dispatch import dispatch, run_query
    from anerp.core.envelope import Actor, Envelope, local_principal
    from anerp.seed import CLOSED_PERIOD, seed_fixture

    admin = Actor(id="admin:ops", kind="admin")
    principal = local_principal("admin:ops")
    with db.session_scope() as s:
        seed_fixture(s, "baseline")

    def q(name: str, **payload):
        r = run_query(name, payload, admin, principal=principal)
        assert r["ok"], r
        return r["result"]

    assert q("get_period", period_code=CLOSED_PERIOD)["period"]["status"] == "closed"
    assert q("get_account_balance", account_code="1400")["net_cents"] == 0
    assert q("get_reconciliation", kind="inventory")["reconciled"]
    # a full P2P cycle: every derived number must fit the VARCHAR(16) columns
    po = dispatch(
        Envelope(
            tool="create_purchase_order",
            mode="commit",
            idempotency_key=f"pg-po-{uuid.uuid4().hex}",
            actor=admin,
            payload={
                "supplier": "ACME",
                "lines": [{"sku": "VALVE-2IN", "qty": 2, "unit_cost": "50.00"}],
            },
        ),
        principal=principal,
    )
    assert po["ok"], po
    grn = dispatch(
        Envelope(
            tool="receive_goods",
            mode="commit",
            idempotency_key=f"pg-grn-{uuid.uuid4().hex}",
            actor=admin,
            payload={"po": po["document"]["number"]},
        ),
        principal=principal,
    )
    assert grn["ok"], grn
    inv = dispatch(
        Envelope(
            tool="post_supplier_invoice",
            mode="commit",
            idempotency_key=f"pg-inv-{uuid.uuid4().hex}",
            actor=admin,
            payload={
                "po": po["document"]["number"],
                "supplier_reference": "PG-1",
                "lines": [{"sku": "VALVE-2IN", "qty": 2, "unit_cost": "50.00"}],
            },
        ),
        principal=principal,
    )
    assert inv["ok"], inv
    reset = dispatch(
        Envelope(
            tool="reset_and_seed",
            mode="commit",
            idempotency_key=f"pg-reset-{uuid.uuid4().hex}",
            actor=admin,
            payload={"fixture_name": "baseline", "confirm": "RESET"},
        ),
        principal=principal,
    )
    assert reset["ok"], reset
    assert q("search_documents", type="PurchaseOrder")["count"] == 0
    events = q("poll_events", after_seq=0)["events"]
    assert events[-1]["type"] == "system.reset"
    assert q("get_trial_balance")["is_balanced"]
