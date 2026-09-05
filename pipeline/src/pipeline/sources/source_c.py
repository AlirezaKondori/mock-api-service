from __future__ import annotations

import time

import httpx

from pipeline.client import FetchError, RateLimiter, fetch_json
from pipeline.models import Product, RejectedRecord, SourceResult
from pipeline.normalize import RejectRecord, normalize_source_c

NAME = "source_c"
PAGE_SIZE = 2
MAX_PAGES = 1000


async def fetch(client: httpx.AsyncClient, base_url: str, rate_limiter: RateLimiter) -> SourceResult:
    start = time.monotonic()
    products: list[Product] = []
    rejected: list[RejectedRecord] = []
    pages_fetched = 0
    retries = 0
    offset = 0
    error: str | None = None
    status = "success"

    while pages_fetched < MAX_PAGES:
        try:
            outcome = await fetch_json(
                client,
                f"{base_url}/source-c/products",
                params={"offset": offset, "limit": PAGE_SIZE},
                rate_limiter=rate_limiter,
            )
        except FetchError as exc:
            retries += exc.attempts - 1
            error = str(exc)
            status = "degraded" if pages_fetched > 0 else "failed"
            break

        retries += outcome.attempts - 1
        payload = outcome.payload
        try:
            raw_data = payload["data"]
            if not isinstance(raw_data, list):
                raise TypeError(f"data is not a list: {raw_data!r}")
            for raw in raw_data:
                try:
                    products.append(normalize_source_c(raw))
                except RejectRecord as exc:
                    rejected.append(RejectedRecord(source=NAME, reason=exc.reason, raw=raw))
            offset = payload.get("next_offset")
            if offset is not None and (not isinstance(offset, int) or isinstance(offset, bool)):
                raise TypeError(f"next_offset is not an int: {offset!r}")
        except (KeyError, TypeError) as exc:
            error = f"malformed response payload: {exc}"
            status = "degraded" if pages_fetched > 0 else "failed"
            break

        pages_fetched += 1
        if offset is None:
            break

    # If loop exited due to MAX_PAGES cap while offset was still non-None, mark as degraded
    if pages_fetched >= MAX_PAGES and offset is not None:
        status = "degraded" if pages_fetched > 0 else "failed"
        error = f"stopped after {MAX_PAGES} pages (page cap reached)"

    return SourceResult(
        source=NAME,
        status=status,
        products=products,
        rejected=rejected,
        pages_fetched=pages_fetched,
        retries=retries,
        duration_seconds=time.monotonic() - start,
        error=error,
    )
