import httpx
import pytest
import respx

from pipeline.client import RateLimiter
from pipeline.sources import source_c


@pytest.mark.asyncio
async def test_fetch_paginates_via_offset_until_next_offset_is_none():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-c/products", params={"offset": "0", "limit": "2"}).mock(
                return_value=httpx.Response(200, json={
                    "data": [
                        {"product_id": "c-1", "product_name": "One", "price": "1.00", "type": "x"},
                        {"product_id": "c-2", "product_name": "Two", "price": "2.00", "type": "x"},
                    ],
                    "next_offset": 2, "max_page_size": 2,
                })
            )
            mock.get("/source-c/products", params={"offset": "2", "limit": "2"}).mock(
                return_value=httpx.Response(200, json={
                    "data": [{"product_id": "c-3", "product_name": "Three", "price": "3.00", "type": "x"}],
                    "next_offset": None, "max_page_size": 2,
                })
            )
            result = await source_c.fetch(client, "http://test", RateLimiter(max_calls=100, period=1.0))

    assert result.status == "success"
    assert result.pages_fetched == 2
    assert [p.id for p in result.products] == ["c-1", "c-2", "c-3"]


@pytest.mark.asyncio
async def test_fetch_uses_the_shared_rate_limiter():
    calls: list[float] = []

    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-c/products", params={"offset": "0", "limit": "2"}).mock(
                return_value=httpx.Response(200, json={
                    "data": [{"product_id": "c-1", "product_name": "One", "price": "1.00", "type": "x"}],
                    "next_offset": None, "max_page_size": 2,
                })
            )
            limiter = RateLimiter(max_calls=1, period=0.05)
            await limiter.acquire()  # pre-consume the only slot in this window
            result = await source_c.fetch(client, "http://test", limiter)

    assert result.status == "success"  # still succeeds, just paced by the limiter


@pytest.mark.asyncio
async def test_fetch_caps_at_max_pages(monkeypatch):
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            # Mock endpoint that always returns a next_offset, simulating infinite pagination
            mock.get("/source-c/products").mock(
                side_effect=lambda request: httpx.Response(200, json={
                    "data": [{"product_id": "c-endless", "product_name": "Endless", "price": "1.00", "type": "x"}],
                    "next_offset": 999,
                })
            )

            # Monkeypatch MAX_PAGES to a small value for testing
            monkeypatch.setattr(source_c, "MAX_PAGES", 3)

            result = await source_c.fetch(client, "http://test", RateLimiter(max_calls=100, period=1.0))

    assert result.pages_fetched == 3
    assert result.status == "degraded"
    assert result.error is not None
    assert "cap" in result.error.lower()


@pytest.mark.asyncio
async def test_fetch_natural_completion_at_max_pages_boundary_is_not_misreported_as_cap_hit(monkeypatch):
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-c/products", params={"offset": "0", "limit": "2"}).mock(
                return_value=httpx.Response(200, json={
                    "data": [
                        {"product_id": "c-1", "product_name": "One", "price": "1.00", "type": "x"},
                        {"product_id": "c-2", "product_name": "Two", "price": "2.00", "type": "x"},
                    ],
                    "next_offset": 2, "max_page_size": 2,
                })
            )
            mock.get("/source-c/products", params={"offset": "2", "limit": "2"}).mock(
                return_value=httpx.Response(200, json={
                    "data": [
                        {"product_id": "c-3", "product_name": "Three", "price": "3.00", "type": "x"},
                        {"product_id": "c-4", "product_name": "Four", "price": "4.00", "type": "x"},
                    ],
                    "next_offset": None,
                })
            )

            # Monkeypatch MAX_PAGES to 2, so natural completion happens exactly at the boundary
            monkeypatch.setattr(source_c, "MAX_PAGES", 2)

            result = await source_c.fetch(client, "http://test", RateLimiter(max_calls=100, period=1.0))

    # Verify: natural completion at boundary is NOT misreported as cap hit
    assert result.pages_fetched == 2
    assert result.status == "success"  # NOT degraded
    assert result.error is None  # NO error
    assert [p.id for p in result.products] == ["c-1", "c-2", "c-3", "c-4"]


@pytest.mark.asyncio
async def test_fetch_degrades_but_keeps_prior_pages_on_non_retryable_http_error():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-c/products").mock(
                side_effect=[
                    httpx.Response(200, json={
                        "data": [{"product_id": "c-1", "product_name": "One", "price": "1.00", "type": "x"}],
                        "next_offset": 1, "max_page_size": 2,
                    }),
                    httpx.Response(500, json={"error": "server_error"}),
                ]
            )
            result = await source_c.fetch(client, "http://test", RateLimiter(max_calls=100, period=1.0))

    assert result.status == "degraded"
    assert result.pages_fetched == 1
    assert [p.id for p in result.products] == ["c-1"]
    assert result.error is not None


@pytest.mark.asyncio
async def test_fetch_reports_retries_on_exhausted_attempts():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-c/products").mock(
                return_value=httpx.Response(503, json={"error": "unavailable"}, headers={"Retry-After": "0"})
            )
            result = await source_c.fetch(client, "http://test", RateLimiter(max_calls=100, period=1.0))

    assert result.status == "failed"
    assert result.retries == 2


@pytest.mark.asyncio
async def test_fetch_degrades_but_keeps_prior_pages_on_wrong_type_data():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-c/products").mock(
                side_effect=[
                    httpx.Response(200, json={
                        "data": [{"product_id": "c-1", "product_name": "One", "price": "1.00", "type": "x"}],
                        "next_offset": 1, "max_page_size": 2,
                    }),
                    # "data" should be a list; a string must not be silently
                    # iterated character-by-character as if it were records.
                    httpx.Response(200, json={"data": "oops", "next_offset": None}),
                ]
            )
            result = await source_c.fetch(client, "http://test", RateLimiter(max_calls=100, period=1.0))

    assert result.status == "degraded"
    assert result.pages_fetched == 1
    assert [p.id for p in result.products] == ["c-1"]
    assert result.error is not None


@pytest.mark.asyncio
async def test_fetch_degrades_but_keeps_prior_pages_on_malformed_envelope():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-c/products").mock(
                side_effect=[
                    httpx.Response(200, json={
                        "data": [{"product_id": "c-1", "product_name": "One", "price": "1.00", "type": "x"}],
                        "next_offset": 1, "max_page_size": 2,
                    }),
                    # page 2 is missing the "data" key entirely (malformed envelope)
                    httpx.Response(200, json={"next_offset": None, "max_page_size": 2}),
                ]
            )
            result = await source_c.fetch(client, "http://test", RateLimiter(max_calls=100, period=1.0))

    assert result.status == "degraded"
    assert result.pages_fetched == 1
    assert [p.id for p in result.products] == ["c-1"]
    assert result.error is not None
    assert "malformed" in result.error.lower()
