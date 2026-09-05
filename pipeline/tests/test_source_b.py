import httpx
import pytest
import respx

from pipeline.sources import source_b


@pytest.mark.asyncio
async def test_fetch_follows_cursor_chain_to_completion():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-b/products").mock(
                side_effect=[
                    httpx.Response(200, json={
                        "items": [{"sku": "b-1", "title": "One", "amount_cents": 100, "department": "x"}],
                        "next_cursor": "cursor-2",
                    }),
                    httpx.Response(200, json={
                        "items": [{"sku": "b-2", "title": "Two", "amount_cents": 200, "department": "x"}],
                        "next_cursor": None,
                    }),
                ]
            )
            result = await source_b.fetch(client, "http://test")

    assert result.status == "success"
    assert result.pages_fetched == 2
    assert [p.id for p in result.products] == ["b-1", "b-2"]


@pytest.mark.asyncio
async def test_fetch_retries_transient_failure_then_continues_cursor_chain():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-b/products").mock(
                side_effect=[
                    httpx.Response(200, json={
                        "items": [{"sku": "b-1", "title": "One", "amount_cents": 100, "department": "x"}],
                        "next_cursor": "cursor-2",
                    }),
                    httpx.Response(503, json={"error": "transient"}, headers={"Retry-After": "0"}),
                    httpx.Response(200, json={
                        "items": [{"sku": "b-2", "title": "Two", "amount_cents": 200, "department": "x"}],
                        "next_cursor": None,
                    }),
                ]
            )
            result = await source_b.fetch(client, "http://test")

    assert result.status == "success"
    assert result.retries == 1
    assert [p.id for p in result.products] == ["b-1", "b-2"]


@pytest.mark.asyncio
async def test_fetch_drops_malformed_price_but_keeps_rest_of_page():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-b/products", params={}).mock(
                return_value=httpx.Response(200, json={
                    "items": [
                        {"sku": "b-1", "title": "One", "amount_cents": 100, "department": "x"},
                        {"sku": "b-2", "title": "Broken", "amount_cents": "not-a-number", "department": "x"},
                    ],
                    "next_cursor": None,
                })
            )
            result = await source_b.fetch(client, "http://test")

    assert [p.id for p in result.products] == ["b-1"]
    assert len(result.rejected) == 1
    assert result.rejected[0].reason  # non-empty explanation


@pytest.mark.asyncio
async def test_fetch_caps_at_max_pages(monkeypatch):
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            # Mock endpoint that always returns a cursor, simulating infinite pagination
            mock.get("/source-b/products").mock(
                side_effect=lambda request: httpx.Response(200, json={
                    "items": [{"sku": "b-endless", "title": "Endless", "amount_cents": 100, "department": "x"}],
                    "next_cursor": "cursor-next",
                })
            )

            # Monkeypatch MAX_PAGES to a small value for testing
            monkeypatch.setattr(source_b, "MAX_PAGES", 3)

            result = await source_b.fetch(client, "http://test")

    assert result.pages_fetched == 3
    assert result.status == "degraded"
    assert result.error is not None
    assert "cap" in result.error.lower()


@pytest.mark.asyncio
async def test_fetch_natural_completion_at_max_pages_boundary_is_not_misreported_as_cap_hit(monkeypatch):
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-b/products").mock(
                side_effect=[
                    httpx.Response(200, json={
                        "items": [{"sku": "b-1", "title": "One", "amount_cents": 100, "department": "x"}],
                        "next_cursor": "cursor-2",
                    }),
                    httpx.Response(200, json={
                        "items": [{"sku": "b-2", "title": "Two", "amount_cents": 200, "department": "x"}],
                        "next_cursor": None,
                    }),
                ]
            )

            # Monkeypatch MAX_PAGES to 2, so natural completion happens exactly at the boundary
            monkeypatch.setattr(source_b, "MAX_PAGES", 2)

            result = await source_b.fetch(client, "http://test")

    # Verify: natural completion at boundary is NOT misreported as cap hit
    assert result.pages_fetched == 2
    assert result.status == "success"  # NOT degraded
    assert result.error is None  # NO error
    assert [p.id for p in result.products] == ["b-1", "b-2"]


@pytest.mark.asyncio
async def test_fetch_degrades_but_keeps_prior_pages_on_non_retryable_http_error():
    # A non-retryable status (500) used to raise a raw httpx.HTTPStatusError
    # that escaped this function's only `except FetchError`, so the outer
    # orchestrator would replace the whole result with an empty one. Now that
    # fetch_json() normalizes it into FetchError, page 1's product must survive.
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-b/products").mock(
                side_effect=[
                    httpx.Response(200, json={
                        "items": [{"sku": "b-1", "title": "One", "amount_cents": 100, "department": "x"}],
                        "next_cursor": "cursor-2",
                    }),
                    httpx.Response(500, json={"error": "server_error"}),
                ]
            )
            result = await source_b.fetch(client, "http://test")

    assert result.status == "degraded"
    assert result.pages_fetched == 1
    assert [p.id for p in result.products] == ["b-1"]
    assert result.error is not None


@pytest.mark.asyncio
async def test_fetch_reports_retries_on_exhausted_attempts():
    # Previously, retries were only accumulated on the success path, so a
    # source that failed after exhausting every retry reported retries == 0.
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-b/products").mock(
                return_value=httpx.Response(503, json={"error": "unavailable"}, headers={"Retry-After": "0"})
            )
            result = await source_b.fetch(client, "http://test")

    assert result.status == "failed"
    assert result.retries == 2  # 3 exhausted attempts == 2 retries


@pytest.mark.asyncio
async def test_fetch_degrades_but_keeps_prior_pages_on_wrong_type_items():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-b/products").mock(
                side_effect=[
                    httpx.Response(200, json={
                        "items": [{"sku": "b-1", "title": "One", "amount_cents": 100, "department": "x"}],
                        "next_cursor": "cursor-2",
                    }),
                    # "items" should be a list; a dict must not be silently
                    # iterated as if it were one (previously this iterated
                    # the dict's keys and returned success with 0 products).
                    httpx.Response(200, json={"items": {}, "next_cursor": None}),
                ]
            )
            result = await source_b.fetch(client, "http://test")

    assert result.status == "degraded"
    assert result.pages_fetched == 1
    assert [p.id for p in result.products] == ["b-1"]
    assert result.error is not None


@pytest.mark.asyncio
async def test_fetch_degrades_but_keeps_prior_pages_on_malformed_envelope():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-b/products").mock(
                side_effect=[
                    httpx.Response(200, json={
                        "items": [{"sku": "b-1", "title": "One", "amount_cents": 100, "department": "x"}],
                        "next_cursor": "cursor-2",
                    }),
                    # page 2 is missing the "items" key entirely (malformed envelope)
                    httpx.Response(200, json={"next_cursor": None}),
                ]
            )
            result = await source_b.fetch(client, "http://test")

    assert result.status == "degraded"
    assert result.pages_fetched == 1
    assert [p.id for p in result.products] == ["b-1"]
    assert result.error is not None
    assert "malformed" in result.error.lower()
