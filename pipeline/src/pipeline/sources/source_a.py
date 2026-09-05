from __future__ import annotations

import time

import httpx

from pipeline.client import FetchError, fetch_json
from pipeline.models import Product, RejectedRecord, SourceResult
from pipeline.normalize import RejectRecord, normalize_source_a

NAME = "source_a"
MAX_PAGES = 1000


async def fetch(client: httpx.AsyncClient, base_url: str) -> SourceResult:
    start = time.monotonic()
    products: list[Product] = []
    rejected: list[RejectedRecord] = []
    pages_fetched = 0
    retries = 0
    page = 1
    total_pages: int | None = None
    error: str | None = None
    status = "success"

    while pages_fetched < MAX_PAGES and (total_pages is None or page <= total_pages):
        try:
            outcome = await fetch_json(client, f"{base_url}/source-a/products", params={"page": page})
        except FetchError as exc:
            retries += exc.attempts - 1
            error = str(exc)
            status = "degraded" if pages_fetched > 0 else "failed"
            break

        retries += outcome.attempts - 1
        payload = outcome.payload
        try:
            total_pages = payload["total_pages"]
            if not isinstance(total_pages, int) or isinstance(total_pages, bool):
                raise TypeError(f"total_pages is not an int: {total_pages!r}")
            raw_products = payload["products"]
            if not isinstance(raw_products, list):
                raise TypeError(f"products is not a list: {raw_products!r}")
            for raw in raw_products:
                try:
                    products.append(normalize_source_a(raw))
                except RejectRecord as exc:
                    rejected.append(RejectedRecord(source=NAME, reason=exc.reason, raw=raw))
        except (KeyError, TypeError) as exc:
            error = f"malformed response payload: {exc}"
            status = "degraded" if pages_fetched > 0 else "failed"
            break

        pages_fetched += 1
        page += 1

    # If loop exited due to MAX_PAGES cap while there are still more pages to fetch
    if pages_fetched >= MAX_PAGES and (total_pages is None or page <= total_pages):
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
