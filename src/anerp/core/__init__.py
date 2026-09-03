"""anerp.core: the operation dispatcher and envelope models (import submodules directly)."""

from __future__ import annotations

from typing import Any

__all__ = ["Actor", "AnerpError", "Envelope", "ErrorCode", "Principal", "dispatch", "run_query"]


def __getattr__(name: str) -> Any:  # lazy to avoid import cycles with anerp.db
    if name in ("dispatch", "run_query"):
        from anerp.core import dispatch as _d

        return getattr(_d, name)
    if name in ("Actor", "Envelope", "Principal"):
        from anerp.core import envelope as _e

        return getattr(_e, name)
    if name in ("AnerpError", "ErrorCode"):
        from anerp.core import errors as _err

        return getattr(_err, name)
    raise AttributeError(name)
