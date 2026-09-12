"""Standalone worker for the Google ADK adapter (no anerp imports on purpose).

google-adk depends on `mcp` 1.x while anerp runs on `mcp` 2.x, so the ADK loop runs in its own
interpreter (ANERP_GOOGLE_ADK_PYTHON, e.g. `.venv-adk/bin/python` created with
`uv venv .venv-adk && uv pip install --python .venv-adk/bin/python "google-adk" "mcp<2"`).
Reads one JSON job on stdin, writes one JSON trace on stdout.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any


async def run(job: dict[str, Any]) -> dict[str, Any]:
    from google.adk.agents import LlmAgent
    from google.adk.agents.invocation_context import LlmCallsLimitExceededError
    from google.adk.agents.run_config import RunConfig
    from google.adk.models.google_llm import Gemini
    from google.adk.runners import InMemoryRunner
    from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams
    from google.genai import types

    trace: dict[str, Any] = {
        "final_text": "",
        "tool_calls": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "steps": 0,
        "error": None,
        "extra": {"cache_read_input_tokens": 0, "reasoning_tokens": 0},
    }
    toolset = MCPToolset(  # type: ignore[no-untyped-call]
        connection_params=StreamableHTTPConnectionParams(
            url=job["url"].rstrip("/") + "/mcp",
            headers={"Authorization": f"Bearer {job['token']}"},
            timeout=60,
            sse_read_timeout=120,
        )
    )
    # Gemini returns 503 UNAVAILABLE ("high demand") and 429 for minutes at a time; without
    # retries most of a matrix dies on the first call. Exponential backoff up to a minute.
    model = Gemini(
        model=job["model"],
        retry_options=types.HttpRetryOptions(
            attempts=int(job.get("max_retries", 8)),
            initial_delay=2.0,
            max_delay=60.0,
            exp_base=2.0,
            jitter=0.5,
            http_status_codes=[408, 429, 500, 502, 503, 504],
        ),
    )
    agent = LlmAgent(
        name="ops_assistant",
        model=model,
        instruction=job["system_prompt"],
        tools=[toolset],
    )
    runner = InMemoryRunner(agent=agent, app_name="anerp-eval")
    session = await runner.session_service.create_session(app_name="anerp-eval", user_id="eval")
    try:
        async for event in runner.run_async(
            user_id="eval",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=job["narrative"])]),
            run_config=RunConfig(max_llm_calls=int(job["max_steps"])),
        ):
            for call in event.get_function_calls() or []:
                args = dict(call.args or {})
                trace["tool_calls"].append(
                    {
                        "name": call.name,
                        "arguments": args,
                        "ok": None,
                        "error_code": None,
                        "mode": args.get("mode"),
                        "latency_ms": 0.0,
                    }
                )
            usage = getattr(event, "usage_metadata", None)
            if usage is not None and event.author != "user":
                # One LLM response per event carrying usage; sum them.
                trace["steps"] += 1
                thoughts = int(getattr(usage, "thoughts_token_count", 0) or 0)
                trace["input_tokens"] += int(getattr(usage, "prompt_token_count", 0) or 0)
                trace["output_tokens"] += (
                    int(getattr(usage, "candidates_token_count", 0) or 0) + thoughts
                )
                trace["extra"]["cache_read_input_tokens"] += int(
                    getattr(usage, "cached_content_token_count", 0) or 0
                )
                trace["extra"]["reasoning_tokens"] += thoughts
            if event.is_final_response() and event.content and event.content.parts:
                text = "".join(p.text or "" for p in event.content.parts)
                if text.strip():
                    trace["final_text"] = text
    except LlmCallsLimitExceededError:
        trace["final_text"] = trace["final_text"] or "Stopped: step limit reached."
        trace["error"] = "max_steps"
    finally:
        await toolset.close()
    return trace


def main() -> None:
    job = json.loads(sys.stdin.read())
    try:
        trace = asyncio.run(run(job))
    except Exception as exc:  # noqa: BLE001
        trace = {
            "final_text": "",
            "tool_calls": [],
            "input_tokens": 0,
            "output_tokens": 0,
            "steps": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "extra": {},
        }
    sys.stdout.write(json.dumps(trace, default=str))


if __name__ == "__main__":
    main()
