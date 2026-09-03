"""anerp CLI: serve | mcp --stdio | migrate | seed | keygen | token | trace | tb | verify-receipt | recon | eval.

The CLI is a thin client of the same tools (in-process dispatch or HTTP with a token), never a
privileged path (DESIGN.md §7.7).
"""

from __future__ import annotations

import json
import os
import secrets
from typing import Any

import typer

app = typer.Typer(help="anerp: agent-native headless ERP kernel", no_args_is_help=True)
token_app = typer.Typer(help="Token administration (in-process)")
app.add_typer(token_app, name="token")


def _print(obj: Any) -> None:
    typer.echo(json.dumps(obj, indent=2, default=str))


def _local_actor() -> Any:
    from anerp.core.envelope import Actor

    return Actor(id=os.environ.get("ANERP_CLI_ACTOR", "human:cli"), kind="admin")


def _local_principal() -> Any:
    """The CLI is a trusted in-process head; it states that trust explicitly."""
    from anerp.core.envelope import local_principal

    return local_principal(_local_actor().id)


def _query(name: str, **payload: Any) -> Any:
    """Run a query tool in-process (ANERP_DATABASE_URL) or over HTTP when ANERP_URL is set."""
    url = os.environ.get("ANERP_URL")
    token = os.environ.get("ANERP_TOKEN") or os.environ.get("ANERP_ADMIN_TOKEN")
    if url and token:
        from anerp.eval.clients.http import call_tool_http

        return call_tool_http(url, token, name, payload)
    from anerp.core.dispatch import run_query
    from anerp.server import startup_checks

    startup_checks()
    return run_query(name, payload, _local_actor(), principal=_local_principal())


@app.command()
def serve(host: str = "0.0.0.0", port: int | None = None, reload: bool = False) -> None:
    """Run the HTTP server (MCP at /mcp, A2A at /a2a, SSE at /events/stream)."""
    import uvicorn

    from anerp.config import get_settings

    uvicorn.run(
        "anerp.server:app",
        factory=True,
        host=host,
        port=port or get_settings().port,
        reload=reload,
        log_level=get_settings().log_level.lower(),
    )


@app.command()
def mcp(
    stdio: bool = typer.Option(
        True, "--stdio", help="Serve MCP over stdio (for local Claude Code)"
    ),
) -> None:
    """Serve MCP over stdio. Needs ANERP_TOKEN (or ANERP_ADMIN_TOKEN)."""
    import anyio

    from anerp.mcp_server.app import run_stdio
    from anerp.server import startup_checks

    startup_checks()
    anyio.run(run_stdio)


@app.command()
def migrate(revision: str = "head") -> None:
    """Apply Alembic migrations to ANERP_DATABASE_URL."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "alembic.ini")
    )
    command.upgrade(cfg, revision)
    typer.echo(f"migrated to {revision}")


@app.command()
def seed(fixture: str = "baseline") -> None:
    """Seed the database (kernel data directly, business data through the dispatcher)."""
    from anerp.db import session_scope
    from anerp.seed import seed_fixture
    from anerp.server import startup_checks

    startup_checks()
    with session_scope() as s:
        _print(seed_fixture(s, fixture))


@app.command()
def keygen() -> None:
    """Print a fresh Ed25519 private key PEM for ANERP_SIGNING_KEY_PEM."""
    from anerp.ledger.receipts import generate_private_key_pem

    typer.echo(generate_private_key_pem())


@token_app.command("bootstrap")
def token_bootstrap() -> None:
    """Print a random token suitable for ANERP_BOOTSTRAP_ADMIN_TOKEN (does not store it)."""
    typer.echo("anerp_" + secrets.token_urlsafe(32))


@token_app.command("mint")
def token_mint(subject: str, kind: str = "agent", scopes: str = "*:read") -> None:
    """Mint a token in-process as the local admin (prints the clear token once)."""
    from anerp.core.dispatch import dispatch
    from anerp.core.envelope import Envelope
    from anerp.server import startup_checks

    startup_checks()
    r = dispatch(
        Envelope(
            tool="mint_token",
            mode="commit",
            idempotency_key=f"cli-mint-{secrets.token_hex(8)}",
            actor=_local_actor(),
            payload={
                "subject": subject,
                "kind": kind,
                "scopes": [s.strip() for s in scopes.split(",")],
            },
        ),
        principal=_local_principal(),
    )
    _print(
        r
        if not r.get("ok")
        else {
            "token": r["secret"]["token"],
            "token_id": r["secret"]["token_id"],
            "receipt_id": r["receipt"]["id"],
        }
    )


@token_app.command("list")
def token_list() -> None:
    _print(_query("list_tokens"))


@app.command()
def trace(ref: str) -> None:
    """anerp trace PO-000124"""
    _print(_query("trace_document", id_or_number=ref))


@app.command()
def tb(period: str | None = typer.Argument(None)) -> None:
    """anerp tb 2026-09"""
    _print(_query("get_trial_balance", period_code=period))


@app.command("verify-receipt")
def verify_receipt(receipt_id: str) -> None:
    _print(_query("verify_receipt", receipt_id=receipt_id))


@app.command()
def recon(kind: str = typer.Argument("gr_ir")) -> None:
    """anerp recon gr_ir|ap|ar|inventory"""
    _print(_query("get_reconciliation", kind=kind))


@app.command()
def status() -> None:
    _print(_query("get_system_status"))


@app.command("eval")
def eval_cmd(
    clients: str = typer.Option(
        "in_process",
        help="Comma-separated: in_process,claude_agent_sdk,openai_agents_sdk,google_adk",
    ),
    servers: str = typer.Option(
        "treatment,control", help="treatment (agent-native) and/or control (CRUD baseline)"
    ),
    tasks: str = typer.Option("all"),
    runs: int = typer.Option(3),
    output: str = typer.Option("results"),
    all_: bool = typer.Option(
        False, "--all", help="Full matrix: every client with credentials, both servers, all tasks"
    ),
) -> None:
    """Run the evaluation matrix (DESIGN.md §14) and write raw.jsonl, summary.csv, report.md."""
    from anerp.eval.runner import run_matrix

    result = run_matrix(
        clients=[c.strip() for c in clients.split(",")],
        servers=[s.strip() for s in servers.split(",")],
        tasks=None if tasks == "all" else [t.strip() for t in tasks.split(",")],
        runs=runs,
        output_dir=output,
        everything=all_,
    )
    _print(result)


if __name__ == "__main__":
    app()
