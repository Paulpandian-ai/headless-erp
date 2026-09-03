"""In-memory request log and simulation store.

Kept in process memory (not the database) so that `simulate` provably writes nothing
(DESIGN.md §6.2, §18.2). Bounded ring buffers; the eval harness and troubleshooting
tools read from here.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from anerp.config import get_settings
from anerp.core.ids import iso, utcnow


@dataclass
class RequestLogEntry:
    request_id: str
    tool: str
    mode: str  # simulate | commit | query
    actor_id: str
    actor_kind: str
    outcome: str  # simulated | applied | replayed | error
    started_at: datetime
    latency_ms: float
    error_code: str | None = None
    error_message: str | None = None
    policy_decision: str | None = None
    policy: dict[str, Any] | None = None
    payload: dict[str, Any] = field(default_factory=dict)  # redacted
    document_id: str | None = None
    document_number: str | None = None
    receipt_id: str | None = None
    simulation_id: str | None = None
    idempotency_key: str | None = None
    on_behalf_of: str | None = None
    state_snapshot: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["started_at"] = iso(self.started_at)
        return d


class RequestLog:
    def __init__(self, maxlen: int | None = None) -> None:
        self._entries: deque[RequestLogEntry] = deque(
            maxlen=maxlen or get_settings().request_log_size
        )
        self._lock = threading.Lock()

    def add(self, entry: RequestLogEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def get(self, request_id: str) -> RequestLogEntry | None:
        with self._lock:
            for e in reversed(self._entries):
                if e.request_id == request_id:
                    return e
        return None

    def query(
        self,
        *,
        since: datetime | None = None,
        actor: str | None = None,
        tool: str | None = None,
        error_code: str | None = None,
        mode: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RequestLogEntry]:
        with self._lock:
            items = list(self._entries)
        out = []
        for e in reversed(items):
            if since and e.started_at < since:
                continue
            if actor and e.actor_id != actor:
                continue
            if tool and e.tool != tool:
                continue
            if error_code and e.error_code != error_code:
                continue
            if mode and e.mode != mode:
                continue
            out.append(e)
        return out[offset : offset + limit]

    def all(self) -> list[RequestLogEntry]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


@dataclass
class SimulationRecord:
    simulation_id: str
    tool: str
    request_hash: str
    state_versions: dict[str, int]
    created_at: datetime
    expires_at: datetime
    projection: dict[str, Any]


class SimulationStore:
    def __init__(self, maxlen: int = 5000) -> None:
        self._items: dict[str, SimulationRecord] = {}
        self._order: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def put(self, record: SimulationRecord) -> None:
        with self._lock:
            if len(self._order) == self._order.maxlen:
                oldest = self._order[0]
                self._items.pop(oldest, None)
            self._items[record.simulation_id] = record
            self._order.append(record.simulation_id)

    def get(self, simulation_id: str) -> SimulationRecord | None:
        with self._lock:
            return self._items.get(simulation_id)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._order.clear()


request_log = RequestLog()
simulations = SimulationStore()


def redact(payload: dict[str, Any], fields: frozenset[str] | None = None) -> dict[str, Any]:
    fields = fields if fields is not None else get_settings().redact_field_set

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: ("[redacted]" if k in fields else walk(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(payload)


def simulation_expiry() -> datetime:
    return utcnow() + timedelta(minutes=get_settings().simulation_ttl_minutes)
