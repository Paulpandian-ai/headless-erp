"""General ledger and period tools (DESIGN.md §7.4)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from anerp.core.context import ToolContext
from anerp.core.ids import utcnow
from anerp.core.money import Money, cents, fmt
from anerp.core.projection import Compensation, EventSpec, JournalSpec, LineSpec, Projection
from anerp.core.registry import Annotations, WriteTool, tool
from anerp.finance.models import FiscalPeriod, JournalEntry
from anerp.finance.periods import close_readiness
from anerp.ledger.posting import reversal_spec


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JELineInput(_Strict):
    account: str = Field(description="GL account code, e.g. 5100")
    debit: Money = Decimal("0")
    credit: Money = Decimal("0")
    description: str = ""

    @model_validator(mode="after")
    def _one_side(self) -> JELineInput:
        if (self.debit > 0) == (self.credit > 0):
            raise ValueError("exactly one of debit/credit must be > 0")
        return self


class PostJEPayload(_Strict):
    posting_date: date | None = None
    memo: str = Field(min_length=1, description="Why this manual entry exists")
    lines: list[JELineInput] = Field(min_length=2)


@tool
class PostJournalEntry(WriteTool):
    name = "post_journal_entry"
    module = "finance"
    scope = "finance:gl:write"
    purpose = "Post a manual, balanced journal entry to the general ledger."
    preconditions = [
        "sum of debits equals sum of credits",
        "all accounts exist and are active",
        "posting date in an open period",
    ]
    effects = "JournalEntry posted with its lines; GL: as specified; inventory: none; events: journal_entry.posted."
    compensating_tool = "reverse_journal_entry"
    compensating_when = "while the entry is posted and the target period is open"
    common_errors = [
        "VALIDATION_ERROR when unbalanced",
        "PERIOD_CLOSED",
        "NOT_FOUND for unknown account",
    ]
    emits = ["journal_entry.posted"]
    payload_model = PostJEPayload

    def project(self, ctx: ToolContext, payload: PostJEPayload) -> Projection:
        posting_date = payload.posting_date or utcnow().date()
        lines = []
        for line in payload.lines:
            ctx.account(line.account)
            lines.append(
                LineSpec(line.account, cents(line.debit), cents(line.credit), line.description)
            )
        spec = JournalSpec(posting_date, payload.memo, "ManualJournal", "", lines)
        spec.source_id = spec.id
        from anerp.core.errors import validation

        if spec.total_debit != spec.total_credit:
            raise validation(
                f"entry is unbalanced: debits {fmt(spec.total_debit)} vs credits {fmt(spec.total_credit)}",
                total_debit_cents=spec.total_debit,
                total_credit_cents=spec.total_credit,
            )
        p = Projection()
        p.journal = spec
        p.facts = {
            "je": {"total_debit_cents": spec.total_debit, "line_count": len(lines)},
            **ctx.period_facts(posting_date),
        }
        p.extra = {
            "balance_check": {
                "debit_cents": spec.total_debit,
                "credit_cents": spec.total_credit,
                "balanced": True,
            },
            "projected_number": ctx.number_for("JournalEntry"),
        }
        p.events.append(
            EventSpec(
                "journal_entry.posted",
                f"Manual journal {fmt(spec.total_debit)}: {payload.memo}",
                "JournalEntry",
            )
        )
        p.compensation = Compensation("reverse_journal_entry", {"je": "<number from response>"})
        return p


class ReverseJEPayload(_Strict):
    je: str = Field(description="JE number or id")
    reason: str = Field(min_length=1)
    posting_date: date | None = None


@tool
class ReverseJournalEntry(WriteTool):
    name = "reverse_journal_entry"
    module = "finance"
    scope = "finance:gl:write"
    purpose = (
        "Reverse a posted journal entry with a mirror entry (original lines are never edited)."
    )
    preconditions = [
        "entry status posted and not already reversed",
        "target posting date in an open period",
    ]
    effects = "New JournalEntry with swapped Dr/Cr and reversal_of_id set; original -> reversed; events: journal_entry.reversed."
    compensating_tool = None
    common_errors = ["PRECONDITION_FAILED if already reversed", "PERIOD_CLOSED"]
    emits = ["journal_entry.reversed"]
    payload_model = ReverseJEPayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: ReverseJEPayload) -> Projection:
        original = ctx.get_by_ref(JournalEntry, payload.je, "JournalEntry")
        ctx.require(
            original.status == "posted",
            f"{original.number} is {original.status}",
            status=original.status,
        )
        posting_date = payload.posting_date or utcnow().date()
        p = Projection()
        p.journal = reversal_spec(
            ctx.session,
            original,
            posting_date,
            f"Reversal of {original.number}: {payload.reason}",
            "JournalReversal",
            original.id,
        )
        p.update("JournalEntry", original, {"status": "reversed"})
        p.facts = {
            "je": {"total_debit_cents": original.total_debit_cents, "original": original.number},
            **ctx.period_facts(posting_date),
        }
        p.events.append(
            EventSpec(
                "journal_entry.reversed",
                f"{original.number} reversed: {payload.reason}",
                "JournalEntry",
                original,
            )
        )
        return p


class PeriodPayload(_Strict):
    period: str = Field(description="Period code YYYY-MM", pattern=r"^\d{4}-\d{2}$")
    reason: str = ""


@tool
class ClosePeriod(WriteTool):
    name = "close_period"
    module = "finance"
    scope = "finance:period:close"
    purpose = "Close a fiscal period after the close-readiness checklist passes; nothing can post into it afterwards."
    preconditions = [
        "period status open",
        "no blocked supplier invoices dated in the period",
        "trial balance balances",
    ]
    effects = "FiscalPeriod -> closed; GL: none; events: period.closed. Simulate returns the full checklist (blockers and warnings)."
    compensating_tool = "reopen_period"
    compensating_when = "with a documented reason"
    common_errors = [
        "PRECONDITION_FAILED if already closed",
        "POLICY_DENIED (close_readiness) with the checklist in details",
    ]
    emits = ["period.closed"]
    payload_model = PeriodPayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: PeriodPayload) -> Projection:
        period = ctx.get_by_ref(FiscalPeriod, payload.period, "FiscalPeriod")
        ctx.require(
            period.status == "open",
            f"period {period.code} is already {period.status}",
            status=period.status,
        )
        checklist = close_readiness(ctx.session, period)
        p = Projection()
        p.update("FiscalPeriod", period, {"status": "closed"}, primary=True)
        p.facts = {
            "close": {
                "blocked_invoices": len(checklist["blocked_supplier_invoices"]),
                "trial_balance_ok": checklist["trial_balance_ok"],
                "ready": checklist["ready"],
            }
        }
        p.extra = {"checklist": checklist}
        p.warnings.extend(checklist["warnings"])
        p.events.append(
            EventSpec("period.closed", f"Period {period.code} closed by {ctx.actor.id}")
        )
        p.compensation = Compensation("reopen_period", {"period": period.code, "reason": "<why>"})
        return p


class ReopenPayload(_Strict):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    reason: str = Field(min_length=3, description="Required: why the period is being reopened")


@tool
class ReopenPeriod(WriteTool):
    name = "reopen_period"
    module = "finance"
    scope = "finance:period:close"
    purpose = "Reopen a closed fiscal period (requires a reason) so corrections can be posted."
    preconditions = ["period status closed", "reason given"]
    effects = "FiscalPeriod -> open; events: period.reopened."
    compensating_tool = "close_period"
    compensating_when = "after corrections are posted"
    emits = ["period.reopened"]
    payload_model = ReopenPayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: ReopenPayload) -> Projection:
        period = ctx.get_by_ref(FiscalPeriod, payload.period, "FiscalPeriod")
        ctx.require(
            period.status == "closed",
            f"period {period.code} is {period.status}",
            status=period.status,
        )
        p = Projection()
        p.update("FiscalPeriod", period, {"status": "open"}, primary=True)
        p.facts = {"period": {"code": period.code, "status": period.status}}
        p.events.append(
            EventSpec(
                "period.reopened",
                f"Period {period.code} reopened by {ctx.actor.id}: {payload.reason}",
            )
        )
        p.compensation = Compensation("close_period", {"period": period.code})
        return p
