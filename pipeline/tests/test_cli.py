import json
from pathlib import Path

import pytest

from pipeline import __main__ as cli


def test_main_writes_output_and_returns_zero_on_success(tmp_path: Path, monkeypatch):
    async def fake_run_pipeline(base_url, timeout, deadline):
        return {"run": {"status": "success", "total_products": 1}, "products": [], "rejected": []}

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    exit_code = cli.main(["--base-url", "http://unused", "--out", str(tmp_path)])

    assert exit_code == 0
    written = list(tmp_path.glob("run-*.json"))
    assert len(written) == 1
    assert json.loads(written[0].read_text())["run"]["status"] == "success"


def test_main_returns_nonzero_on_failure_status(tmp_path: Path, monkeypatch):
    async def fake_run_pipeline(base_url, timeout, deadline):
        return {"run": {"status": "failure", "total_products": 0}, "products": [], "rejected": []}

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    exit_code = cli.main(["--out", str(tmp_path)])

    assert exit_code == 1
