import time

import httpx
import pytest
import respx

from pipeline.client import FetchError, RateLimiter, fetch_json


@pytest.mark.asyncio
async def test_fetch_json_succeeds_first_try():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/thing").mock(return_value=httpx.Response(200, json={"ok": True}))
            outcome = await fetch_json(client, "http://test/thing")
    assert outcome.payload == {"ok": True}
    assert outcome.attempts == 1


@pytest.mark.asyncio
async def test_fetch_json_retries_on_503_then_succeeds():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            route = mock.get("/thing")
            route.side_effect = [
                httpx.Response(503, json={"error": "unavailable"}, headers={"Retry-After": "0"}),
                httpx.Response(200, json={"ok": True}),
            ]
            outcome = await fetch_json(client, "http://test/thing")
    assert outcome.payload == {"ok": True}
    assert outcome.attempts == 2


@pytest.mark.asyncio
async def test_fetch_json_retries_on_timeout():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            route = mock.get("/thing")
            route.side_effect = [
                httpx.TimeoutException("timed out"),
                httpx.Response(200, json={"ok": True}),
            ]
            outcome = await fetch_json(client, "http://test/thing")
    assert outcome.payload == {"ok": True}
    assert outcome.attempts == 2


@pytest.mark.asyncio
async def test_fetch_json_gives_up_after_max_attempts():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/thing").mock(
                return_value=httpx.Response(502, json={"error": "bad gateway"}, headers={"Retry-After": "0"})
            )
            with pytest.raises(FetchError) as exc_info:
                await fetch_json(client, "http://test/thing", max_attempts=3)
    assert exc_info.value.attempts == 3


@pytest.mark.asyncio
async def test_fetch_json_does_not_retry_non_retryable_status():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            mock.get("/thing").mock(return_value=httpx.Response(400, json={"error": "bad_request"}))
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_json(client, "http://test/thing")


@pytest.mark.asyncio
async def test_rate_limiter_paces_calls_beyond_the_limit():
    limiter = RateLimiter(max_calls=2, period=0.2)
    start = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()  # 3rd call in the same window must wait
    elapsed = time.monotonic() - start
    assert elapsed >= 0.19


@pytest.mark.asyncio
async def test_fetch_json_caps_an_excessive_retry_after_value():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            route = mock.get("/thing")
            route.side_effect = [
                httpx.Response(503, json={"error": "unavailable"}, headers={"Retry-After": "999999"}),
                httpx.Response(200, json={"ok": True}),
            ]
            start = time.monotonic()
            outcome = await fetch_json(client, "http://test/thing")
            elapsed = time.monotonic() - start
    assert outcome.payload == {"ok": True}
    assert elapsed < 11.0  # capped well below the bogus 999999s Retry-After


@pytest.mark.asyncio
async def test_fetch_json_caps_a_non_finite_retry_after_value():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            route = mock.get("/thing")
            route.side_effect = [
                httpx.Response(503, json={"error": "unavailable"}, headers={"Retry-After": "nan"}),
                httpx.Response(200, json={"ok": True}),
            ]
            start = time.monotonic()
            outcome = await fetch_json(client, "http://test/thing")
            elapsed = time.monotonic() - start
    assert outcome.payload == {"ok": True}
    # nan is not < MAX_BACKOFF_SECONDS (NaN comparisons are always False), so
    # min(nan, cap) would silently return nan; asyncio.sleep(nan) does not hang
    # or error, it fires on the very next loop iteration (no backoff at all).
    # Falling back to normal exponential backoff means attempt 1 sleeps
    # BASE_BACKOFF * 2**0 == 0.5s — assert both bounds so a regression back to
    # "no backoff" (elapsed ~0s) is caught, not just an excessive one.
    assert 0.4 <= elapsed < 11.0


@pytest.mark.asyncio
async def test_fetch_json_falls_back_on_a_negative_retry_after_value():
    async with httpx.AsyncClient() as client:
        with respx.mock(base_url="http://test") as mock:
            route = mock.get("/thing")
            route.side_effect = [
                httpx.Response(503, json={"error": "unavailable"}, headers={"Retry-After": "-5"}),
                httpx.Response(200, json={"ok": True}),
            ]
            start = time.monotonic()
            outcome = await fetch_json(client, "http://test/thing")
            elapsed = time.monotonic() - start
    assert outcome.payload == {"ok": True}
    # Same rationale as the non-finite case: a negative Retry-After must fall
    # back to exponential backoff (~0.5s on attempt 1), not sleep ~0s.
    assert 0.4 <= elapsed < 11.0
