"""`anerp start` / `anerp serve` as real subprocesses: the process stays up and answers /healthz,
and startup failures exit non-zero."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _env(tmp_path: Path, port: int) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANERP_")}
    env.update(
        {
            "ANERP_ENV": "dev",
            "ANERP_TOKEN_PEPPER": "smoke",
            "PORT": str(port),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'smoke.db'}",
            "ANERP_LOG_LEVEL": "INFO",
        }
    )
    return env


def _wait_healthz(proc: subprocess.Popen[bytes], port: int, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read().decode() if proc.stdout else ""
            raise AssertionError(f"process exited early with {proc.returncode}: {out[-2000:]}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001 - not up yet
            time.sleep(0.5)
    proc.kill()
    raise AssertionError("server did not answer /healthz in time")


@pytest.mark.parametrize("command", ["start", "serve"])
def test_process_stays_up_and_serves_healthz(tmp_path: Path, command: str) -> None:
    port = _free_port()
    if command == "serve":  # serve does not migrate; create the schema first the way `start` would
        subprocess.run(
            [sys.executable, "-m", "anerp.cli", "migrate"],
            env=_env(tmp_path, port),
            check=True,
            capture_output=True,
            timeout=120,
        )
    proc = subprocess.Popen(
        [sys.executable, "-m", "anerp.cli", command],
        env=_env(tmp_path, port),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        body = _wait_healthz(proc, port)
        assert body["status"] == "ok" and body["env"] == "dev"
        time.sleep(1.0)
        assert proc.poll() is None, "server exited after answering"
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/.well-known/anerp-keys.json", timeout=5
        ) as r:
            assert json.load(r)["keys"][0]["active"]
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=20)[0].decode()
        except subprocess.TimeoutExpired:
            proc.kill()
            out = proc.communicate()[0].decode()
    assert f"anerp listening on 0.0.0.0:{port}" in out, out[-2000:]
    if command == "start":
        assert "migrated to head" in out
        assert out.index("migrated to head") < out.index("anerp listening on")


def test_serve_exits_non_zero_when_port_is_taken(tmp_path: Path) -> None:
    port = _free_port()
    with socket.socket() as blocker:
        blocker.bind(("0.0.0.0", port))
        blocker.listen(1)
        proc = subprocess.run(
            [sys.executable, "-m", "anerp.cli", "serve"],
            env=_env(tmp_path, port),
            capture_output=True,
            timeout=120,
        )
    assert proc.returncode != 0
    assert b"anerp listening on" in proc.stdout + proc.stderr  # it got as far as trying
