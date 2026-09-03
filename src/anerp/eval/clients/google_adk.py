"""Google ADK adapter (package `google-adk`), MCP over streamable HTTP. Not run in CI."""

from __future__ import annotations

import os

from anerp.eval.clients.base import NEUTRAL_SYSTEM_PROMPT, RunTrace, ToolCallRecord
from anerp.eval.surface import RemoteSurface, ToolSurface


class GoogleADKClient:
    name = "google_adk"

    def available(self) -> bool:
        try:
            import google.adk  # noqa: F401
        except ImportError:
            return False
        return bool(os.environ.get("GOOGLE_API_KEY"))

    def run(
        self, narrative: str, surface: ToolSurface, *, max_steps: int, task_id: str
    ) -> RunTrace:
        import anyio
        from google.adk.agents import LlmAgent
        from google.adk.runners import InMemoryRunner
        from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams
        from google.genai import types

        if not isinstance(surface, RemoteSurface):
            return RunTrace(
                final_text="google_adk needs a remote MCP endpoint (ANERP_URL)",
                error="needs_remote",
            )
        trace = RunTrace()

        async def go() -> None:
            toolset = MCPToolset(
                connection_params=StreamableHTTPConnectionParams(
                    url=surface.url.rstrip("/") + "/mcp",
                    headers={"Authorization": f"Bearer {surface.token}"},
                )
            )
            agent = LlmAgent(
                name="ops_assistant",
                model=os.environ.get("ANERP_LLM_MODEL", "gemini-2.5-pro"),
                instruction=NEUTRAL_SYSTEM_PROMPT,
                tools=[toolset],
            )
            runner = InMemoryRunner(agent=agent, app_name="anerp-eval")
            session = await runner.session_service.create_session(
                app_name="anerp-eval", user_id="eval"
            )
            async for event in runner.run_async(
                user_id="eval",
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=narrative)]),
            ):
                for call in event.get_function_calls() or []:
                    args = dict(call.args or {})
                    trace.tool_calls.append(
                        ToolCallRecord(call.name, args, None, None, args.get("mode"))
                    )
                if event.is_final_response() and event.content and event.content.parts:
                    trace.final_text = "".join(p.text or "" for p in event.content.parts)
                trace.steps += 1
            await toolset.close()

        anyio.run(go)
        return trace
