"""anerp CLI: serve | mcp --stdio | migrate | seed | keygen | token | trace | tb | verify-receipt | recon | eval | eval-merge.

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
    """Run the HTTP server in the foreground (MCP at /mcp, HTTP facade at /api, A2A at /a2a,
    SSE at /events/stream).

    Blocks until the server stops. Exits non-zero when startup fails (bad config, port in use).
    """
    raise typer.Exit(code=_serve(host, port, reload))


def _serve(host: str, port: int | None, reload: bool = False) -> int:
    import logging

    import uvicorn

    from anerp.config import get_settings

    settings = get_settings()
    port = port or settings.port
    logging.basicConfig(level=settings.log_level)
    log = logging.getLogger("anerp.cli")
    try:
        if reload:  # dev only: uvicorn needs an import string to reload
            log.info("anerp listening on %s:%s (reload)", host, port)
            uvicorn.run(
                "anerp.server:app",
                factory=True,
                host=host,
                port=port,
                reload=True,
                log_level=settings.log_level.lower(),
            )
            return 0
        from anerp.server import create_app

        application = create_app()
        log.info("anerp listening on %s:%s (env=%s)", host, port, settings.env)
        typer.echo(f"anerp listening on {host}:{port}", err=True)
        server = uvicorn.Server(
            uvicorn.Config(application, host=host, port=port, log_level=settings.log_level.lower())
        )
        server.run()  # blocks; returns after a clean shutdown signal
        if not server.started:
            log.error("anerp did not start on %s:%s", host, port)
            return 1
        return 0
    except Exception:
        log.exception("anerp failed to start on %s:%s", host, port)
        return 1


@app.command()
def start(host: str = "0.0.0.0", port: int | None = None) -> None:
    """Container start step: apply migrations, then serve in the foreground (one process, no shell).

    Use this as the Docker CMD / Railway start command so nothing depends on `a && b` chaining.
    """
    try:
        migrate()
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"anerp: migration failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    raise typer.Exit(code=_serve(host, port))


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
    run_id: str | None = typer.Option(None, help="Name of results/<run_id>/ (default: timestamp)"),
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
        run_id=run_id,
    )
    _print(result)


@app.command("eval-merge")
def eval_merge_cmd(
    inputs: list[str] = typer.Argument(..., help="results/<run_id>/ directories to merge"),
    output: str = typer.Option("results"),
    run_id: str = typer.Option(..., help="Name of the merged results/<run_id>/"),
) -> None:
    """Merge the raw.jsonl of several runs (e.g. one per client x server job in CI) into one
    results/<run_id>/ and regenerate summary.csv, latency.csv and report.md over all rows."""
    from pathlib import Path

    from anerp.eval.report import load_raw, write_outputs

    rows = [row for d in inputs for row in load_raw(Path(d) / "raw.jsonl")]
    run_dir = Path(output) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "raw.jsonl").open("w") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    _print({"run_id": run_id, "runs": len(rows), "inputs": inputs, **write_outputs(run_dir, rows)})


@app.command("eval-retry")
def eval_retry_cmd(
    run_dir: str = typer.Argument(..., help="results/<run_id>/ to repair in place"),
    categories: str = typer.Option(
        "vendor_unavailable", help="Comma-separated outcome categories to re-run"
    ),
) -> None:
    """Re-run the rows of a results directory whose outcome category matches (default: the
    vendor could not serve them) with the same client/server/task/run, and regenerate outputs."""
    from anerp.eval.runner import retry_rows

    _print(retry_rows(run_dir, [c.strip() for c in categories.split(",")]))


@app.command("eval-resilience")
def eval_resilience_cmd(
    experiment: str = typer.Argument(..., help="commit-failure | timeout | stale-writes"),
    clients: str = typer.Option(
        "claude_agent_sdk,openai_agents_sdk,google_adk", help="timeout: adapters to run"
    ),
    tasks: str = typer.Option(
        "", help="timeout: comma-separated task ids (default: the experiment's set)"
    ),
    runs: int = typer.Option(3, help="timeout: runs per client x task"),
    output: str = typer.Option("results/resilience"),
) -> None:
    """Resilience experiments (results/resilience/): deterministic commit-failure and stale-write
    sweeps, and the agent-in-the-loop timeout/duplicates experiment."""
    import os
    from pathlib import Path

    if experiment == "commit-failure":
        from anerp.eval.resilience.commit_failure import run

        result = run(os.environ.get("ANERP_EVAL_DATABASE_URL"))
        d = Path(output) / "commit_failure"
        d.mkdir(parents=True, exist_ok=True)
        name = "sqlite" if result["trials"][0]["backend"] == "sqlite" else "postgres"
        (d / f"{name}.json").write_text(json.dumps(result, indent=1, default=str))
        _print(
            {
                "all_pass": result["all_pass"],
                "trials": len(result["trials"]),
                "file": str(d / f"{name}.json"),
            }
        )
    elif experiment == "timeout":
        from anerp.eval.resilience.timeout_duplicates import run as run_timeout
        from anerp.eval.resilience.timeout_duplicates import summarize

        result = run_timeout(
            [c.strip() for c in clients.split(",")],
            [t.strip() for t in tasks.split(",")] if tasks else None,
            runs,
            str(Path(output) / "timeout_duplicates"),
        )
        summary = summarize(Path(result["raw"]))
        (Path(output) / "timeout_duplicates" / "summary.md").write_text(summary + "\n")
        typer.echo(summary)
        _print(result)
    elif experiment == "stale-writes":
        from anerp.eval.resilience.stale_writes import run as run_stale

        result = run_stale(os.environ.get("ANERP_EVAL_DATABASE_URL"))
        d = Path(output) / "stale_writes"
        d.mkdir(parents=True, exist_ok=True)
        (d / "trials.json").write_text(json.dumps(result, indent=1, default=str))
        typer.echo(result["summary_md"])
    else:
        raise typer.BadParameter("experiment must be commit-failure, timeout or stale-writes")


if __name__ == "__main__":
    app()
