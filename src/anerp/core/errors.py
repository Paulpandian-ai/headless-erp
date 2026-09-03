"""Stable error taxonomy (DESIGN.md §6.5)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    POLICY_DENIED = "POLICY_DENIED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    PERIOD_CLOSED = "PERIOD_CLOSED"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    MATCH_VARIANCE_EXCEEDED = "MATCH_VARIANCE_EXCEEDED"
    CREDIT_LIMIT_EXCEEDED = "CREDIT_LIMIT_EXCEEDED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    STALE_SIMULATION = "STALE_SIMULATION"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    INTERNAL_ERROR = "INTERNAL_ERROR"


RETRY_ADVICE: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: "Fix the payload and retry.",
    ErrorCode.NOT_FOUND: "Check ids with get_document / search_documents, then retry.",
    ErrorCode.PRECONDITION_FAILED: "Query the document status and choose the correct tool for that status.",
    ErrorCode.POLICY_DENIED: "Do not retry unchanged; escalate to a human.",
    ErrorCode.REQUIRES_APPROVAL: "Call the approval tool with a human token, or hand off to a human.",
    ErrorCode.PERIOD_CLOSED: "Change the posting date to an open period or ask to reopen the period.",
    ErrorCode.INSUFFICIENT_STOCK: "Reduce the quantity or receive goods first.",
    ErrorCode.MATCH_VARIANCE_EXCEEDED: "Correct the invoice or escalate the variance.",
    ErrorCode.CREDIT_LIMIT_EXCEEDED: "Reduce the order or record a customer payment first.",
    ErrorCode.IDEMPOTENCY_CONFLICT: "Use a new idempotency_key for a different payload.",
    ErrorCode.STALE_SIMULATION: "Re-simulate and commit with the new simulation_id.",
    ErrorCode.UNAUTHORIZED: "Obtain a valid bearer token.",
    ErrorCode.FORBIDDEN: "Obtain a token with the required scope.",
    ErrorCode.INTERNAL_ERROR: "Retry once; if it persists report the request_id.",
}


class AnerpError(Exception):
    """Business error carried through the dispatcher and returned (never raised) in simulate."""

    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = ErrorCode(code)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
            "retry_advice": RETRY_ADVICE[self.code],
        }


def not_found(what: str, ref: str) -> AnerpError:
    return AnerpError(ErrorCode.NOT_FOUND, f"{what} '{ref}' not found", {"type": what, "ref": ref})


def precondition(message: str, **details: Any) -> AnerpError:
    return AnerpError(ErrorCode.PRECONDITION_FAILED, message, details)


def validation(message: str, **details: Any) -> AnerpError:
    return AnerpError(ErrorCode.VALIDATION_ERROR, message, details)
