# pipeline/tests/test_run_integration.py
import pytest

from pipeline.run import run_pipeline


@pytest.mark.asyncio
@pytest.mark.parametrize("mock_server", ["standard"], indirect=True)
async def test_standard_scenario_end_to_end(mock_server):
    summary = await run_pipeline(mock_server)

    assert summary["run"]["status"] == "success"
    assert summary["run"]["total_products"] == 17  # 18 fixture records - 1 malformed B price
    assert len(summary["rejected"]) == 1
    assert summary["run"]["sources"]["source_a"]["status"] == "success"
    assert summary["run"]["sources"]["source_b"]["status"] == "success"
    assert summary["run"]["sources"]["source_b"]["retries"] >= 3  # cursor-2 (1) + cursor-3 (2)
    assert summary["run"]["sources"]["source_c"]["status"] == "success"
    # Proves the 2 req/sec client-side rate limiter actually prevents 429s
    # (SPEC.md: "Source C never receives more than 2 requests in any rolling
    # 1-second window") — zero retries against a server that would 429 above
    # that rate is the correct proxy assertion.
    assert summary["run"]["sources"]["source_c"]["retries"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mock_server", ["source-b-down"], indirect=True)
async def test_source_b_down_yields_partial_success(mock_server):
    summary = await run_pipeline(mock_server)

    assert summary["run"]["status"] == "partial_success"
    assert summary["run"]["sources"]["source_b"]["status"] == "failed"
    assert summary["run"]["sources"]["source_a"]["status"] == "success"
    assert summary["run"]["sources"]["source_c"]["status"] == "success"
    assert summary["run"]["total_products"] == 12  # A (6) + C (6), B contributes nothing


@pytest.mark.asyncio
@pytest.mark.parametrize("mock_server", ["bad-data-heavy"], indirect=True)
async def test_bad_data_heavy_increases_rejections_without_failing(mock_server):
    summary = await run_pipeline(mock_server)

    assert summary["run"]["status"] in {"success", "partial_success"}
    assert len(summary["rejected"]) >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mock_server", ["slow"], indirect=True)
async def test_short_deadline_cuts_off_a_slow_run_gracefully(mock_server):
    summary = await run_pipeline(mock_server, timeout=5.0, deadline=0.05)

    assert summary["run"]["deadline_exceeded"] is True
    assert summary["run"]["status"] in {"partial_success", "failure"}


@pytest.mark.asyncio
@pytest.mark.parametrize("mock_server", ["standard"], indirect=True)
async def test_two_runs_against_a_fresh_server_are_deterministic(mock_server):
    first = await run_pipeline(mock_server)
    # reset server-side transient-failure/rate-limit state before the second run
    import httpx

    async with httpx.AsyncClient() as client:
        await client.post(f"{mock_server}/admin/reset")

    second = await run_pipeline(mock_server)

    assert first["run"]["total_products"] == second["run"]["total_products"]
    assert {p["unified_id"] for p in first["products"]} == {p["unified_id"] for p in second["products"]}
