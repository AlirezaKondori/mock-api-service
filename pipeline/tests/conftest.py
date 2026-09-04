from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

MOCK_SERVER_PATH = Path(__file__).resolve().parents[2] / "mock-api-service" / "server.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mock_server(tmp_path, request):
    """Launches the real mock API server as a subprocess for one test.

    Function-scoped (not session-scoped) so each test can set its own
    MOCK_SCENARIO via `request.param` without cross-test contamination.
    """
    scenario = getattr(request, "param", "standard")
    port = _free_port()
    env = {"MOCK_SCENARIO": scenario}
    import os

    full_env = {**os.environ, **env}
    proc = subprocess.Popen(
        [sys.executable, str(MOCK_SERVER_PATH), "--port", str(port)],
        env=full_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_health(base_url, proc)
        yield base_url
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def _wait_for_health(base_url: str, proc: subprocess.Popen, attempts: int = 50) -> None:
    for _ in range(attempts):
        try:
            resp = httpx.get(f"{base_url}/health", timeout=0.5)
            if resp.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)

    # Server failed to start or respond; check if it crashed and include stderr
    exit_code = proc.poll()
    if exit_code is not None:
        # Process has exited (crashed); read its stderr for diagnostics
        stderr_output = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(
            f"mock server at {base_url} crashed on startup (exit code {exit_code}).\n"
            f"stderr: {stderr_output}"
        )
    else:
        # Process is still running but not responding; it's a timeout, not a crash
        raise RuntimeError(
            f"mock server at {base_url} never became healthy (process still running, "
            f"likely a startup delay or host connectivity issue)"
        )
