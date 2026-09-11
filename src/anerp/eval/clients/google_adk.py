"""Google ADK adapter (package `google-adk`), MCP over streamable HTTP. Not run in CI.

The ADK loop itself runs in `google_adk_worker.py` under a separate interpreter
(ANERP_GOOGLE_ADK_PYTHON, default `.venv-adk/bin/python`) because google-adk needs `mcp` 1.x.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from anerp.eval.clients.base import NEUTRAL_SYSTEM_PROMPT, RunTrace, ToolCallRecord
from anerp.eval.surface import RemoteSurface, ToolSurface

DEFAULT_MODEL = "gemini-3.1-pro-preview"
WORKER = Path(__file__).with_name("google_adk_worker.py")


class GoogleADKClient:
    name = "google_adk"
    needs_remote = True

    def __init__(self) -> None:
        self.model = os.environ.get("ANERP_GOOGLE_MODEL", DEFAULT_MODEL)
        self.python = os.environ.get("ANERP_GOOGLE_ADK_PYTHON") or self._default_python()

    @staticmethod
    def _default_python() -> str:
        candidate = Path.cwd() / ".venv-adk" / "bin" / "python"
        return str(candidate) if candidate.exists() else sys.executable

    def available(self) -> bool:
        if not os.environ.get("GOOGLE_API_KEY"):
            return False
        probe = subprocess.run(
            [self.python, "-c", "from google.adk.tools.mcp_tool import MCPToolset"],
            capture_output=True,
            timeout=120,
        )
        return probe.returncode == 0

    def run(
        self, narrative: str, surface: ToolSurface, *, max_steps: int, task_id: str
    ) -> RunTrace:
        if not isinstance(surface, RemoteSurface):
            return RunTrace(
                final_text="google_adk needs a remote MCP endpoint (ANERP_URL)",
                error="needs_remote",
            )
        job = {
            "url": surface.url,
            "token": surface.token,
            "narrative": narrative,
            "system_prompt": NEUTRAL_SYSTEM_PROMPT,
            "max_steps": max_steps,
            "model": self.model,
        }
        proc = subprocess.run(
            [self.python, "-P", str(WORKER)],
            input=json.dumps(job),
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return RunTrace(error=f"adk worker exited {proc.returncode}: {proc.stderr[-2000:]}")
        data = json.loads(proc.stdout)
        trace = RunTrace(
            final_text=data.get("final_text", ""),
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            steps=int(data.get("steps", 0)),
            error=data.get("error"),
            extra=dict(data.get("extra") or {}),
        )
        trace.tool_calls = [
            ToolCallRecord(
                c["name"], c["arguments"], c.get("ok"), c.get("error_code"), c.get("mode")
            )
            for c in data.get("tool_calls", [])
        ]
        return trace
