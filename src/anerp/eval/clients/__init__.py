"""Client adapters. Each connects the same neutral prompt to a tool surface."""

from __future__ import annotations

from typing import Any


def make_client(name: str) -> Any:
    if name == "in_process":
        from anerp.eval.clients.llm_loop import InProcessLLMClient

        return InProcessLLMClient()
    if name == "scripted":
        from anerp.eval.clients.scripted import ScriptedClient

        return ScriptedClient()
    if name == "claude_agent_sdk":
        from anerp.eval.clients.claude_agent_sdk import ClaudeAgentSDKClient

        return ClaudeAgentSDKClient()
    if name == "openai_agents_sdk":
        from anerp.eval.clients.openai_agents_sdk import OpenAIAgentsClient

        return OpenAIAgentsClient()
    if name == "google_adk":
        from anerp.eval.clients.google_adk import GoogleADKClient

        return GoogleADKClient()
    raise ValueError(f"unknown client {name}")


ALL_CLIENTS = ["in_process", "claude_agent_sdk", "openai_agents_sdk", "google_adk"]
