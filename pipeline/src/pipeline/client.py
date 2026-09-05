from __future__ import annotations

import asyncio
import math
import random
import time
from dataclasses import dataclass

import httpx

RETRYABLE_STATUS = {429, 502, 503}
MAX_ATTEMPTS = 3
BASE_BACKOFF = 0.5
MAX_JITTER = 0.1
MAX_BACKOFF_SECONDS = 10.0


class FetchError(Exception):
    """Raised when a request exhausts all retry attempts."""

    def __init__(self, message: str, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


@dataclass
class FetchOutcome:
    payload: dict
    attempts: int  # total attempts made; 1 means it succeeded on the first try


class RateLimiter:
    """Client-side sliding window: at most `max_calls` calls per rolling `period` seconds."""

    def __init__(self, max_calls: int, period: float) -> None:
        self._max_calls = max_calls
        self._period = period
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._timestamps = [t for t in self._timestamps if now - t < self._period]
            if len(self._timestamps) >= self._max_calls:
                sleep_for = self._period - (now - self._timestamps[0])
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                now = time.monotonic()
                self._timestamps = [t for t in self._timestamps if now - t < self._period]
            self._timestamps.append(time.monotonic())


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    rate_limiter: RateLimiter | None = None,
) -> FetchOutcome:
    """GET `url` as JSON, retrying on 429/502/503, timeouts, and connection errors.

    Every other failure mode a page can hit — a non-retryable HTTP status, a
    response body that isn't valid JSON — is also normalized into
    `FetchError` here rather than left to propagate as a raw `httpx`/`json`
    exception. That keeps exactly one exception type for callers to handle at
    the page boundary, so a source's accumulated pages/products are never
    lost just because the *kind* of failure wasn't the one line the caller
    happened to catch.

    Timeout is controlled entirely by `client`'s own configured timeout, not
    by this function, so a single `--timeout` flag governs every request.
    """
    last_error = "unknown error"
    for attempt in range(1, max_attempts + 1):
        if rate_limiter is not None:
            await rate_limiter.acquire()
        try:
            response = await client.get(url, params=params)
        except httpx.RequestError as exc:
            # Covers both timeouts and lower-level transport failures (connection
            # refused/reset, DNS failure, etc.) — all are transient-looking from
            # the caller's perspective, so both get the same retry treatment.
            last_error = f"request failed: {exc}"
            if attempt == max_attempts:
                raise FetchError(last_error, attempt) from exc
            await _backoff_sleep(None, attempt)
            continue

        if response.status_code in RETRYABLE_STATUS:
            last_error = f"HTTP {response.status_code}"
            if attempt == max_attempts:
                raise FetchError(last_error, attempt)
            await _backoff_sleep(response.headers.get("Retry-After"), attempt)
            continue

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # A non-retryable status (e.g. 400/404) — not worth spending
            # attempts on, but still a page-level FetchError, not a crash.
            raise FetchError(f"HTTP {response.status_code} (non-retryable)", attempt) from exc

        try:
            payload = response.json()
        except ValueError as exc:  # json.JSONDecodeError is a ValueError subclass
            raise FetchError(f"invalid JSON response: {exc}", attempt) from exc

        return FetchOutcome(payload=payload, attempts=attempt)

    raise FetchError(last_error, max_attempts)


async def _backoff_sleep(retry_after: str | None, attempt: int) -> None:
    if retry_after is not None:
        try:
            delay = float(retry_after)
        except ValueError:
            delay = BASE_BACKOFF * (2 ** (attempt - 1))
        else:
            if not math.isfinite(delay) or delay < 0:
                # A NaN/inf/negative Retry-After (malformed or hostile) must not
                # defeat the backoff cap: min(nan, x) is nan, not x, since NaN
                # comparisons are always False. Fall back to normal backoff.
                delay = BASE_BACKOFF * (2 ** (attempt - 1))
    else:
        delay = BASE_BACKOFF * (2 ** (attempt - 1))
    delay = min(delay, MAX_BACKOFF_SECONDS)
    delay += random.uniform(0, MAX_JITTER)
    await asyncio.sleep(delay)
