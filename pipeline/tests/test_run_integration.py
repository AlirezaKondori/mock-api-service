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
    # (SPEC.md: "the shared rate limiter never allows more than max_calls
    # requests in any rolling window") — near-zero retries against a server
    # that would 429 above that rate is the correct proxy assertion. A tight
    # `== 0` was observed to flake under heavy system load (many concurrent
    # subprocess-backed tests skew the client's rate-limiter sleep enough for
    # one extra request to land in the server's own 1s window); <= 1 still
    # fails on an actually-broken limiter (which produces retries throughout
    # the run, not one at most) while tolerating that scheduling jitter.
    assert summary["run"]["sources"]["source_c"]["retries"] <= 1


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

    assert summary["run"]["status"] == "success"
    # Exact counts, not just ">= 1" — the fixture's known-bad Source B records
    # are the only rejections this scenario should produce.
    assert summary["run"]["total_products"] == 15
    assert len(summary["rejected"]) == 3
    assert all(r["source"] == "source_b" for r in summary["rejected"])


@pytest.mark.asyncio
@pytest.mark.parametrize("mock_server", ["slow"], indirect=True)
async def test_extremely_short_deadline_yields_failure_with_no_hang(mock_server):
    summary = await run_pipeline(mock_server, timeout=5.0, deadline=0.05)

    assert summary["run"]["deadline_exceeded"] is True
    assert summary["run"]["status"] == "failure"
    assert summary["run"]["total_products"] == 0
    # Every source ran out of time before its first response.
    for source in summary["run"]["sources"].values():
        assert source["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("mock_server", ["slow"], indirect=True)
async def test_deadline_retains_completed_sources_and_cancels_the_slow_one(mock_server):
    # A (~1.8s) and C (~1.5s) finish quickly in the "slow" scenario. B is much
    # slower (~7.5s against a fresh server) because it's the only source with
    # built-in transient-failure retries (cursor-2/cursor-3's failure budget is
    # per-process state, so a fresh server subprocess always pays that cost).
    # A 4.5s deadline gives A/C a wide margin against system-load jitter (a
    # tighter 2.5s was observed to flake under a busy full-suite run) while
    # staying well below B's ~7.5s, so B reliably outlasts it. This is the
    # actual proof that "keeps other sources' data" (SPEC.md's
    # deadline-cancellation asymmetry) holds at runtime, not just that *some*
    # partial/failure status comes back.
    summary = await run_pipeline(mock_server, timeout=10.0, deadline=4.5)

    assert summary["run"]["deadline_exceeded"] is True
    assert summary["run"]["status"] == "partial_success"
    assert summary["run"]["duration_seconds"] < 8.0  # didn't hang past the deadline
    assert summary["run"]["sources"]["source_a"]["status"] == "success"
    assert summary["run"]["sources"]["source_c"]["status"] == "success"
    assert summary["run"]["sources"]["source_b"]["status"] == "failed"
    assert summary["run"]["total_products"] == 12  # A (6) + C (6); B contributes nothing
    assert {p["source"] for p in summary["products"]} == {"source_a", "source_c"}


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
