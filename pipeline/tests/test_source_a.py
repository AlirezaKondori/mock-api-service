import httpx
import pytest
import respx

from pipeline.sources import source_a


@pytest.mark.asyncio
async def test_fetch_paginates_through_all_pages():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-a/products", params={"page": "1"}).mock(
                return_value=httpx.Response(200, json={
                    "page": 1, "total_pages": 2,
                    "products": [{"id": "a-1", "name": "One", "price": 1.0, "category": "x"}],
                })
            )
            mock.get("/source-a/products", params={"page": "2"}).mock(
                return_value=httpx.Response(200, json={
                    "page": 2, "total_pages": 2,
                    "products": [{"id": "a-2", "name": "Two", "price": 2.0, "category": "x"}],
                })
            )
            result = await source_a.fetch(client, "http://test")

    assert result.status == "success"
    assert result.pages_fetched == 2
    assert [p.id for p in result.products] == ["a-1", "a-2"]
    assert result.rejected == []


@pytest.mark.asyncio
async def test_fetch_drops_malformed_record_but_keeps_page():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-a/products", params={"page": "1"}).mock(
                return_value=httpx.Response(200, json={
                    "page": 1, "total_pages": 1,
                    "products": [
                        {"id": "a-1", "name": "One", "price": 1.0, "category": "x"},
                        {"id": "a-2", "name": "Bad", "category": "x"},  # missing price
                    ],
                })
            )
            result = await source_a.fetch(client, "http://test")

    assert result.status == "success"
    assert [p.id for p in result.products] == ["a-1"]
    assert len(result.rejected) == 1
    assert result.rejected[0].source == "source_a"


@pytest.mark.asyncio
async def test_fetch_marks_failed_when_first_page_never_succeeds():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-a/products", params={"page": "1"}).mock(
                return_value=httpx.Response(502, json={"error": "bad_gateway"}, headers={"Retry-After": "0"})
            )
            result = await source_a.fetch(client, "http://test")

    assert result.status == "failed"
    assert result.products == []
    assert result.error is not None


@pytest.mark.asyncio
async def test_fetch_caps_at_max_pages(monkeypatch):
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            # Mock endpoint that always returns total_pages > cap, simulating unbounded pagination
            mock.get("/source-a/products").mock(
                return_value=httpx.Response(200, json={
                    "page": 1, "total_pages": 999,
                    "products": [{"id": "a-endless", "name": "Endless", "price": 1.0, "category": "x"}],
                })
            )

            # Monkeypatch MAX_PAGES to a small value for testing
            monkeypatch.setattr(source_a, "MAX_PAGES", 3)

            result = await source_a.fetch(client, "http://test")

    assert result.pages_fetched == 3
    assert result.status == "degraded"
    assert result.error is not None
    assert "cap" in result.error.lower()


@pytest.mark.asyncio
async def test_fetch_natural_completion_at_max_pages_boundary_is_not_misreported_as_cap_hit(monkeypatch):
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-a/products", params={"page": "1"}).mock(
                return_value=httpx.Response(200, json={
                    "page": 1, "total_pages": 2,
                    "products": [{"id": "a-1", "name": "One", "price": 1.0, "category": "x"}],
                })
            )
            mock.get("/source-a/products", params={"page": "2"}).mock(
                return_value=httpx.Response(200, json={
                    "page": 2, "total_pages": 2,
                    "products": [{"id": "a-2", "name": "Two", "price": 2.0, "category": "x"}],
                })
            )

            # Monkeypatch MAX_PAGES to 2, so natural completion happens exactly at the boundary
            monkeypatch.setattr(source_a, "MAX_PAGES", 2)

            result = await source_a.fetch(client, "http://test")

    # Verify: natural completion at boundary is NOT misreported as cap hit
    assert result.pages_fetched == 2
    assert result.status == "success"  # NOT degraded
    assert result.error is None  # NO error
    assert [p.id for p in result.products] == ["a-1", "a-2"]


@pytest.mark.asyncio
async def test_fetch_degrades_but_keeps_prior_pages_on_non_retryable_http_error():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-a/products", params={"page": "1"}).mock(
                return_value=httpx.Response(200, json={
                    "page": 1, "total_pages": 2,
                    "products": [{"id": "a-1", "name": "One", "price": 1.0, "category": "x"}],
                })
            )
            mock.get("/source-a/products", params={"page": "2"}).mock(
                return_value=httpx.Response(500, json={"error": "server_error"})
            )
            result = await source_a.fetch(client, "http://test")

    assert result.status == "degraded"
    assert result.pages_fetched == 1
    assert [p.id for p in result.products] == ["a-1"]
    assert result.error is not None


@pytest.mark.asyncio
async def test_fetch_reports_retries_on_exhausted_attempts():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-a/products", params={"page": "1"}).mock(
                return_value=httpx.Response(502, json={"error": "bad_gateway"}, headers={"Retry-After": "0"})
            )
            result = await source_a.fetch(client, "http://test")

    assert result.status == "failed"
    assert result.retries == 2


@pytest.mark.asyncio
async def test_fetch_degrades_but_keeps_prior_pages_on_wrong_type_total_pages():
    # total_pages arriving as a string on page 2 used to raise a raw TypeError
    # from the `page <= total_pages` loop condition, which escaped this
    # function entirely and lost page 1's already-fetched product.
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-a/products", params={"page": "1"}).mock(
                return_value=httpx.Response(200, json={
                    "page": 1, "total_pages": 2,
                    "products": [{"id": "a-1", "name": "One", "price": 1.0, "category": "x"}],
                })
            )
            mock.get("/source-a/products", params={"page": "2"}).mock(
                return_value=httpx.Response(200, json={
                    "page": 2, "total_pages": "2",
                    "products": [{"id": "a-2", "name": "Two", "price": 2.0, "category": "x"}],
                })
            )
            result = await source_a.fetch(client, "http://test")

    assert result.status == "degraded"
    assert result.pages_fetched == 1
    assert [p.id for p in result.products] == ["a-1"]
    assert result.error is not None


@pytest.mark.asyncio
async def test_fetch_degrades_but_keeps_prior_pages_on_malformed_envelope():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/source-a/products").mock(
                side_effect=[
                    httpx.Response(200, json={
                        "page": 1, "total_pages": 2,
                        "products": [{"id": "a-1", "name": "One", "price": 1.0, "category": "x"}],
                    }),
                    # page 2 is missing the "products" key entirely (malformed envelope)
                    httpx.Response(200, json={"page": 2, "total_pages": 2}),
                ]
            )
            result = await source_a.fetch(client, "http://test")

    assert result.status == "degraded"
    assert result.pages_fetched == 1
    assert [p.id for p in result.products] == ["a-1"]
    assert result.error is not None
    assert "malformed" in result.error.lower()
