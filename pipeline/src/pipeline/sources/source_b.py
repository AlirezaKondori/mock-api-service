from __future__ import annotations

import time

import httpx

from pipeline.client import FetchError, fetch_json
from pipeline.models import Product, RejectedRecord, SourceResult
from pipeline.normalize import RejectRecord, normalize_source_b

NAME = "source_b"
MAX_PAGES = 1000


async def fetch(client: httpx.AsyncClient, base_url: str) -> SourceResult:
    start = time.monotonic()
    products: list[Product] = []
    rejected: list[RejectedRecord] = []
    pages_fetched = 0
    retries = 0
    cursor: str | None = None
    error: str | None = None
    status = "success"

    while pages_fetched < MAX_PAGES:
        params = {"cursor": cursor} if cursor else {}
        try:
            outcome = await fetch_json(client, f"{base_url}/source-b/products", params=params)
        except FetchError as exc:
            error = str(exc)
            status = "degraded" if pages_fetched > 0 else "failed"
            break

        retries += outcome.attempts - 1
        payload = outcome.payload
        try:
            raw_items = payload["items"]
            for raw in raw_items:
                try:
                    products.append(normalize_source_b(raw))
                except RejectRecord as exc:
                    rejected.append(RejectedRecord(source=NAME, reason=exc.reason, raw=raw))
            cursor = payload.get("next_cursor")
        except (KeyError, TypeError) as exc:
            error = f"malformed response payload: {exc}"
            status = "degraded" if pages_fetched > 0 else "failed"
            break

        pages_fetched += 1
        if not cursor:
            break

    # If loop exited due to MAX_PAGES cap while cursor was still truthy, mark as degraded
    if pages_fetched >= MAX_PAGES and cursor:
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
