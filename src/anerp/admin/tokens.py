"""API token hashing, resolution and bootstrap (DESIGN.md §7.8, §11)."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime

from sqlmodel import Session, select

from anerp.config import get_settings
from anerp.core.envelope import Principal
from anerp.core.ids import utcnow
from anerp.ledger.models import ApiToken

log = logging.getLogger("anerp.auth")

ADMIN_SCOPES = ["admin:*"]
TOKEN_PREFIX = "anerp_"


def hash_token(token: str) -> str:
    pepper = get_settings().token_pepper
    return "sha256:" + hashlib.sha256((pepper + token).encode()).hexdigest()


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def _naive(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo is not None else dt


def resolve_token(session: Session, token: str) -> Principal | None:
    row = session.exec(select(ApiToken).where(ApiToken.token_hash == hash_token(token))).first()
    if row is None or row.revoked_at is not None:
        return None
    now = _naive(utcnow())
    exp = _naive(row.expires_at)
    if exp is not None and now is not None and exp < now:
        return None
    return Principal(subject=row.subject, kind=row.kind, scopes=list(row.scopes), token_id=row.id)  # type: ignore[arg-type]


def bootstrap_admin(session: Session) -> ApiToken | None:
    """Store the hash of ANERP_BOOTSTRAP_ADMIN_TOKEN once. Returns the row when newly created."""
    settings = get_settings()
    token = settings.bootstrap_admin_token
    if not token:
        if not session.exec(select(ApiToken).where(ApiToken.kind == "admin")).first():
            log.warning(
                "no admin token exists and ANERP_BOOTSTRAP_ADMIN_TOKEN is unset; mint one with `anerp token bootstrap`"
            )
        return None
    h = hash_token(token)
    existing = session.exec(select(ApiToken).where(ApiToken.token_hash == h)).first()
    if existing is not None:
        return None
    row = ApiToken(
        token_hash=h,
        subject="admin:bootstrap",
        kind="admin",
        scopes=ADMIN_SCOPES,
        created_by="system:bootstrap",
    )
    session.add(row)
    session.flush()
    log.warning(
        "bootstrap admin token stored (subject admin:bootstrap): mint a personal admin token and revoke this one"
    )
    return row


def mark_used(session: Session, token_id: str) -> None:
    row = session.get(ApiToken, token_id)
    if row is not None:
        row.last_used_at = utcnow()
        session.add(row)
