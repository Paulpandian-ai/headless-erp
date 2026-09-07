"""Signed receipts: independent records, no chaining (DESIGN.md §8.3, §16)."""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlmodel import Session, select

from anerp.config import get_settings
from anerp.core.hashing import canonical_json, hash_obj
from anerp.core.ids import iso, utcnow
from anerp.ledger.models import Receipt, ServerKey

log = logging.getLogger("anerp.keys")


def generate_private_key_pem() -> str:
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def public_pem(private_pem: str) -> str:
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    return (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


class KeyRing:
    """Holds the active Ed25519 private key in memory; public keys live in `server_key`."""

    def __init__(self) -> None:
        self._active_id: str | None = None
        self._private: Ed25519PrivateKey | None = None

    def ensure_active(self, session: Session) -> ServerKey:
        active = session.exec(select(ServerKey).where(ServerKey.retired_at.is_(None))).first()  # type: ignore[union-attr]
        settings = get_settings()
        if active is None:
            # No key yet: use ANERP_SIGNING_KEY_PEM when set; otherwise generate one and persist
            # its private material in server_key so it survives restarts (single-host POC).
            private_pem = settings.signing_key_pem or generate_private_key_pem()
            active = ServerKey(
                public_key_pem=public_pem(private_pem),
                private_key_pem=None if settings.signing_key_pem else private_pem,
            )
            session.add(active)
            session.flush()
            log.warning(
                "signing key %s created (%s)",
                active.id,
                "from ANERP_SIGNING_KEY_PEM"
                if settings.signing_key_pem
                else "generated and stored in server_key",
            )
        if self._active_id != active.id:
            active_pem: str | None = active.private_key_pem or settings.signing_key_pem
            if active_pem is None:
                raise RuntimeError(
                    "active signing key has no private material: set ANERP_SIGNING_KEY_PEM"
                )
            loaded = serialization.load_pem_private_key(active_pem.encode(), password=None)
            assert isinstance(loaded, Ed25519PrivateKey)
            self._private = loaded
            self._active_id = active.id
        return active

    def rotate(self, session: Session) -> ServerKey:
        now = utcnow()
        for key in session.exec(select(ServerKey).where(ServerKey.retired_at.is_(None))).all():  # type: ignore[union-attr]
            key.retired_at = now
            session.add(key)
        private_pem = generate_private_key_pem()
        new_key = ServerKey(public_key_pem=public_pem(private_pem), private_key_pem=private_pem)
        session.add(new_key)
        session.flush()
        self._active_id = None
        self.ensure_active(session)
        return new_key

    def sign(self, session: Session, message: dict[str, Any]) -> tuple[str, str]:
        key = self.ensure_active(session)
        assert self._private is not None
        sig = self._private.sign(canonical_json(message).encode())
        return base64.b64encode(sig).decode(), key.id

    @staticmethod
    def verify(public_key_pem: str, message: dict[str, Any], signature_b64: str) -> bool:
        pub = serialization.load_pem_public_key(public_key_pem.encode())
        assert isinstance(pub, Ed25519PublicKey)
        try:
            pub.verify(base64.b64decode(signature_b64), canonical_json(message).encode())
            return True
        except InvalidSignature:
            return False

    def reset(self) -> None:
        self._active_id = None
        self._private = None


keyring = KeyRing()


def receipt_message(
    tool_name: str,
    document_id: str | None,
    before_hash: str,
    action_hash: str,
    after_hash: str,
    signed_at: datetime,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "document_id": document_id,
        "before_hash": before_hash,
        "action_hash": action_hash,
        "after_hash": after_hash,
        "signed_at": iso(signed_at),
    }


def snapshot_hash(rows: list[Any]) -> str:
    """Hash of the touched documents: ids + state_versions + all business fields."""
    items = []
    for row in rows:
        data = row.model_dump(mode="json")
        data.pop("created_at", None)
        data.pop("updated_at", None)
        data.pop("private_key_pem", None)
        items.append({"type": type(row).__name__, **data})
    items.sort(key=lambda d: (d["type"], str(d.get("id") or d.get("key") or "")))
    return hash_obj(items)


def receipt_to_dict(r: Receipt) -> dict[str, Any]:
    return {
        "id": r.id,
        "tool_name": r.tool_name,
        "actor_id": r.actor_id,
        "actor_kind": r.actor_kind,
        "on_behalf_of": r.on_behalf_of,
        "document_type": r.document_type,
        "document_id": r.document_id,
        "document_number": r.document_number,
        "before_hash": r.before_hash,
        "action_hash": r.action_hash,
        "after_hash": r.after_hash,
        "signature": r.signature,
        "signed_at": iso(r.signed_at),
        "public_key_id": r.public_key_id,
    }


def verify_receipt(session: Session, receipt_id: str) -> dict[str, Any]:
    receipt = session.get(Receipt, receipt_id)
    if receipt is None:
        return {"valid": False, "receipt_id": receipt_id, "reason": "receipt not found"}
    key = session.get(ServerKey, receipt.public_key_id)
    if key is None:
        return {"valid": False, "receipt_id": receipt_id, "reason": "signing key not found"}
    message = receipt_message(
        receipt.tool_name,
        receipt.document_id,
        receipt.before_hash,
        receipt.action_hash,
        receipt.after_hash,
        receipt.signed_at,
    )
    signature_ok = KeyRing.verify(key.public_key_pem, message, receipt.signature)
    recomputed_action = hash_obj(
        {
            "tool_name": receipt.tool_name,
            "payload": receipt.payload_json,
            "actor": {
                "id": receipt.actor_id,
                "kind": receipt.actor_kind,
                "on_behalf_of": receipt.on_behalf_of,
            },
        }
    )
    action_ok = recomputed_action == receipt.action_hash
    return {
        "valid": signature_ok and action_ok,
        "receipt_id": receipt_id,
        "signature_valid": signature_ok,
        "action_hash_valid": action_ok,
        "public_key_id": key.id,
        "key_retired": key.retired_at is not None,
        "receipt": receipt_to_dict(receipt),
    }
