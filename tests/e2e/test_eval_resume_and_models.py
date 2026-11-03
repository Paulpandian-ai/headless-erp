"""Harness guards added before the 2026-11 re-test: resuming a cut-short matrix, recording the
model the vendor actually served, and classifying step-limit exhaustion on the Claude SDK."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from anerp.eval.clients.base import RunTrace
from anerp.eval.metrics import outcome_category
from anerp.eval.report import _category, load_raw, summarize
from anerp.eval.runner import _merge, check_served_model, run_matrix, same_model
from anerp.eval.surface import RemoteSurface

TASKS = ["gl_01_manual_je", "gl_03_closed_period"]


def test_same_model_allows_snapshot_suffix_only() -> None:
    assert same_model("claude-sonnet-5-5", "claude-sonnet-5-5")
    assert same_model("gpt-6.1-sol-2026-09-27", "gpt-6.1-sol")
    assert same_model("models/gemini-3.8-flash", "gemini-3.8-flash")
    assert not same_model("claude-opus-5", "claude-sonnet-5-5")
    assert not same_model("claude-sonnet-5", "claude-sonnet-5-5")
    assert not same_model("gpt-6.1-solar", "gpt-6.1-sol")


def test_a_run_served_by_another_model_is_void_whatever_its_outcome() -> None:
    trace = RunTrace(extra={"served_models": ["claude-opus-5"]})
    check_served_model(trace, "claude-sonnet-5-5")
    assert trace.extra["model_mismatch"] is True
    assert outcome_category(True, trace) == "model_mismatch"
    assert _category({"success": True, "model_mismatch": True}) == "model_mismatch"

    ok = RunTrace(extra={"served_models": ["claude-sonnet-5-5"]})
    check_served_model(ok, "claude-sonnet-5-5")
    assert ok.extra["model_mismatch"] is False and outcome_category(True, ok) == "success"

    unknown = RunTrace()  # an adapter that cannot report the served model is not flagged
    check_served_model(unknown, "claude-sonnet-5-5")
    assert "model_mismatch" not in unknown.extra


def test_served_models_from_every_round_are_kept() -> None:
    trace = RunTrace(extra={"served_models": ["m-a"], "cache_read_input_tokens": 5})
    _merge(trace, RunTrace(extra={"served_models": ["m-b", "m-a"], "cache_read_input_tokens": 7}))
    assert trace.extra["served_models"] == ["m-a", "m-b"]
    assert trace.extra["cache_read_input_tokens"] == 12


def test_resume_runs_only_missing_cells_and_refuses_to_overwrite(tmp_path: Path) -> None:
    first = run_matrix(
        clients=["scripted"], servers=["treatment"], tasks=TASKS, runs=1,
        output_dir=str(tmp_path), run_id="m",
    )  # fmt: skip
    assert first["runs"] == 2
    with pytest.raises(SystemExit, match="--resume"):
        run_matrix(
            clients=["scripted"], servers=["treatment"], tasks=TASKS, runs=1,
            output_dir=str(tmp_path), run_id="m",
        )  # fmt: skip
    second = run_matrix(
        clients=["scripted"], servers=["treatment"], tasks=TASKS, runs=2,
        output_dir=str(tmp_path), run_id="m", resume=True,
    )  # fmt: skip
    rows = load_raw(Path(second["raw"]))
    assert second["runs"] == 4 and len(rows) == 4
    assert sorted((r["task"], r["run"]) for r in rows) == [(t, n) for t in TASKS for n in (1, 2)]
    assert all(s["runs"] == 2 for s in summarize(rows))


def test_resume_refuses_to_mix_models(tmp_path: Path) -> None:
    result = run_matrix(
        clients=["scripted"], servers=["treatment"], tasks=TASKS[:1], runs=1,
        output_dir=str(tmp_path), run_id="m",
    )  # fmt: skip
    raw = Path(result["raw"])
    rows = load_raw(raw)
    rows[0]["model"] = "some-other-model"
    raw.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(SystemExit, match="refusing to mix models"):
        run_matrix(
            clients=["scripted"], servers=["treatment"], tasks=TASKS[:1], runs=2,
            output_dir=str(tmp_path), run_id="m", resume=True,
        )  # fmt: skip


class AssistantMessage:
    def __init__(self, model: str, content: list[Any]) -> None:
        self.model, self.content = model, content


class ToolUse:
    def __init__(self, name: str, input: dict[str, Any]) -> None:
        self.name, self.input = name, input


class ResultMessage:
    def __init__(self, subtype: str, model_usage: dict[str, Any]) -> None:
        self.subtype, self.model_usage = subtype, model_usage
        self.result, self.is_error, self.num_turns, self.total_cost_usd = None, True, 3, 0.5
        self.usage = {"input_tokens": 10, "output_tokens": 4}


def _fake_query(messages: list[Any], exc: Exception | None):
    async def query(*, prompt: str, options: Any):  # noqa: ARG001
        for m in messages:
            yield m
        if exc is not None:
            raise exc

    return query


def _claude(
    monkeypatch: pytest.MonkeyPatch, messages: list[Any], exc: Exception | None
) -> RunTrace:
    pytest.importorskip("claude_agent_sdk")
    import claude_agent_sdk

    from anerp.eval.clients.claude_agent_sdk import ClaudeAgentSDKClient

    monkeypatch.setattr(claude_agent_sdk, "query", _fake_query(messages, exc))
    surface = RemoteSurface("http://127.0.0.1:9", "t", name="control")
    return ClaudeAgentSDKClient().run("n", surface, max_steps=3, task_id="t")


def test_claude_step_limit_is_an_outcome_and_keeps_the_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = {"claude-sonnet-5-5": {"costBasis": "list"}}
    trace = _claude(
        monkeypatch,
        [
            AssistantMessage("claude-sonnet-5-5", [ToolUse("mcp__anerp__list_rows", {"t": 1})]),
            AssistantMessage("<synthetic>", []),
            ResultMessage("error_max_turns", usage),
        ],
        RuntimeError("Claude Code returned an error result: Reached maximum number of turns (3)"),
    )
    assert trace.error == "max_steps"
    assert outcome_category(False, trace) == "step_limit"
    assert [c.name for c in trace.tool_calls] == ["list_rows"]
    assert trace.extra["served_models"] == ["claude-sonnet-5-5"]
    assert trace.extra["vendor_reported_cost_usd"] == 0.5


def test_claude_other_errors_still_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        _claude(monkeypatch, [], RuntimeError("boom"))


def test_claude_cost_guessed_by_the_cli_is_not_called_vendor_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = ResultMessage("success", {"claude-sonnet-5-5": {"costBasis": "unknown"}})
    result.is_error = False
    trace = _claude(monkeypatch, [result], None)
    assert trace.extra["cost_basis"] == ["unknown"]
    assert "vendor_reported_cost_usd" not in trace.extra
    assert trace.extra["cli_estimated_cost_usd"] == 0.5
