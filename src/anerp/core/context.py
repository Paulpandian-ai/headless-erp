"""Per-operation context handed to tools: session, actor, loaders, and precondition helpers."""

from __future__ import annotations

from datetime import date
from typing import Any, TypeVar

from sqlmodel import Session, SQLModel, select

from anerp.config import Settings, get_settings
from anerp.core.envelope import Actor, Mode, Principal
from anerp.core.errors import AnerpError, ErrorCode, not_found, precondition
from anerp.core.ids import new_ulid, utcnow

T = TypeVar("T", bound=SQLModel)


class ToolContext:
    def __init__(
        self,
        session: Session,
        actor: Actor,
        mode: Mode,
        request_id: str | None = None,
        settings: Settings | None = None,
        principal: Principal | None = None,
    ) -> None:
        self.session = session
        self.actor = actor
        self.mode = mode
        self.principal = principal
        self.request_id = request_id or new_ulid()
        self.settings = settings or get_settings()
        self.touched: list[SQLModel] = []
        self.now = utcnow()

    # ---- loading -----------------------------------------------------------------
    def touch(self, row: T) -> T:
        if all(r is not row for r in self.touched):
            self.touched.append(row)
        return row

    def get(self, model: type[T], id_: str, what: str | None = None) -> T:
        row = self.session.get(model, id_)
        if row is None:
            raise not_found(what or model.__name__, id_)
        return self.touch(row)

    def get_by_ref(self, model: type[T], ref: str, what: str | None = None) -> T:
        """Load by ULID or by human number/code (PO-000123, ACME, 1000)."""
        row = self.session.get(model, ref)
        if row is None:
            for attr in ("number", "code", "sku"):
                if hasattr(model, attr):
                    stmt = select(model).where(getattr(model, attr) == ref)
                    row = self.session.exec(stmt).first()
                    if row is not None:
                        break
        if row is None:
            raise not_found(what or model.__name__, ref)
        return self.touch(row)

    def find(self, model: type[T], **filters: Any) -> list[T]:
        stmt = select(model)
        for key, value in filters.items():
            stmt = stmt.where(getattr(model, key) == value)
        return list(self.session.exec(stmt).all())

    def account(self, code: str) -> Any:
        from anerp.masterdata.models import Account

        acct = self.session.exec(select(Account).where(Account.code == code)).first()
        if acct is None:
            raise not_found("Account", code)
        if not acct.is_active:
            raise precondition(f"Account {code} is inactive", account=code)
        return acct

    def period_for(self, posting_date: date) -> Any:
        from anerp.finance.models import FiscalPeriod

        stmt = select(FiscalPeriod).where(
            FiscalPeriod.start_date <= posting_date, FiscalPeriod.end_date >= posting_date
        )
        period = self.session.exec(stmt).first()
        if period is None:
            raise AnerpError(
                ErrorCode.NOT_FOUND,
                f"No fiscal period covers posting date {posting_date.isoformat()}",
                {"posting_date": posting_date.isoformat()},
            )
        return self.touch(period)

    def period_facts(self, posting_date: date) -> dict[str, Any]:
        period = self.period_for(posting_date)
        return {
            "posting_date": posting_date.isoformat(),
            "period": {"code": period.code, "status": period.status, "id": period.id},
        }

    # ---- preconditions ---------------------------------------------------------------
    @staticmethod
    def require(condition: bool, message: str, **details: Any) -> None:
        if not condition:
            raise precondition(message, **details)

    def require_active(self, row: Any, what: str) -> None:
        if not getattr(row, "is_active", True):
            ref = getattr(row, "code", None) or getattr(row, "sku", None) or row.id
            raise precondition(f"{what} {ref} is inactive", **{what.lower(): ref})

    def actor_facts(self) -> dict[str, Any]:
        return {
            "id": self.actor.id,
            "kind": self.actor.kind,
            "on_behalf_of": self.actor.on_behalf_of,
        }

    # ---- numbering -------------------------------------------------------------------
    def number_for(self, document_type: str) -> str:
        """Document number for a new document.

        In commit mode the number is allocated for real, inside the commit transaction, so every
        derived value (journal memos, open-item references, event summaries, compensating hints)
        carries the final number; a failed commit rolls the allocation back. In simulate mode it
        is a projection (`PO-000124 (projected)`) and nothing is written.
        """
        from anerp.ledger.sequences import allocate_number, peek_number

        if self.mode == "commit":
            return allocate_number(self.session, document_type)
        return peek_number(self.session, document_type)
