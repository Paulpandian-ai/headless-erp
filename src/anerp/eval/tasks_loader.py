"""Load task YAML files and substitute date placeholders."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Any

import yaml

TASK_DIR = Path(__file__).resolve().parent / "tasks"


def placeholders(today: date | None = None) -> dict[str, str]:
    today = today or date.today()
    year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    prev_end = date(year, month, monthrange(year, month)[1])
    return {
        "today": today.isoformat(),
        "current_period": today.strftime("%Y-%m"),
        "previous_period": prev_end.strftime("%Y-%m"),
        "previous_period_end": prev_end.isoformat(),
    }


def _sub(value: Any, vars_: dict[str, str]) -> Any:
    if isinstance(value, str):
        for k, v in vars_.items():
            value = value.replace("{" + k + "}", v)
        return value
    if isinstance(value, dict):
        return {k: _sub(v, vars_) for k, v in value.items()}
    if isinstance(value, list):
        return [_sub(v, vars_) for v in value]
    return value


def load_tasks(ids: list[str] | None = None, today: date | None = None) -> list[dict[str, Any]]:
    vars_ = placeholders(today)
    tasks = []
    for path in sorted(TASK_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if ids and data["id"] not in ids:
            continue
        data = _sub(data, vars_)
        data["narrative"] = " ".join(str(data["narrative"]).split())
        data.setdefault("traps", [])
        data.setdefault("setup", [])
        data.setdefault("repeat", 1)
        data.setdefault("human_loop", [])
        data.setdefault("acceptance", [])
        data.setdefault("max_steps", 20)
        tasks.append(data)
    return tasks
