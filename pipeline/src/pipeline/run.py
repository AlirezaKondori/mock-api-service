from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

from pipeline.client import RateLimiter
from pipeline.models import Product, RejectedRecord, SourceResult
from pipeline.sources import source_a, source_b, source_c

SOURCE_C_RATE_LIMIT = 2
SOURCE_C_WINDOW_SECONDS = 1.0
DEFAULT_TIMEOUT = 5.0
DEFAULT_DEADLINE = 30.0


async def run_pipeline(base_url: str, timeout: float = DEFAULT_TIMEOUT, deadline: float = DEFAULT_DEADLINE) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    rate_limiter = RateLimiter(SOURCE_C_RATE_LIMIT, SOURCE_C_WINDOW_SECONDS)

    async with httpx.AsyncClient(timeout=timeout) as client:
        named_tasks: list[tuple[str, asyncio.Task]] = [
            (source_a.NAME, asyncio.create_task(_run_source(source_a.fetch(client, base_url), source_a.NAME))),
            (source_b.NAME, asyncio.create_task(_run_source(source_b.fetch(client, base_url), source_b.NAME))),
            (
                source_c.NAME,
                asyncio.create_task(_run_source(source_c.fetch(client, base_url, rate_limiter), source_c.NAME)),
            ),
        ]
        tasks = [t for _, t in named_tasks]

        _, pending = await asyncio.wait(tasks, timeout=deadline)
        deadline_exceeded = bool(pending)
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        results: list[SourceResult] = []
        for name, task in named_tasks:
            if task in pending:
                results.append(
                    SourceResult(source=name, status="failed", error="run deadline exceeded before this source finished")
                )
            else:
                results.append(task.result())

    products, rejected, duplicates_dropped = _merge_products(results)
    return _build_summary(
        results, products, rejected, duplicates_dropped, started_at, time.monotonic() - start, deadline_exceeded
    )


async def _run_source(coro, name: str) -> SourceResult:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 — a source must never crash the whole run
        return SourceResult(source=name, status="failed", error=f"unexpected error: {exc}")


def _merge_products(results: list[SourceResult]) -> tuple[list[Product], list[RejectedRecord], int]:
    seen: dict[str, Product] = {}
    duplicates = 0
    rejected: list[RejectedRecord] = []
    for result in results:
        for product in result.products:
            if product.unified_id in seen:
                duplicates += 1
            seen[product.unified_id] = product  # last-write-wins
        rejected.extend(result.rejected)
    return list(seen.values()), rejected, duplicates


def _build_summary(
    results: list[SourceResult],
    products: list[Product],
    rejected: list[RejectedRecord],
    duplicates_dropped: int,
    started_at: str,
    duration_seconds: float,
    deadline_exceeded: bool,
) -> dict:
    sources = {
        r.source: {
            "status": r.status,
            "pages_fetched": r.pages_fetched,
            "products": len(r.products),
            "rejected": len(r.rejected),
            "retries": r.retries,
            "duration_seconds": round(r.duration_seconds, 3),
            "error": r.error,
        }
        for r in results
    }

    all_succeeded = all(r.status == "success" for r in results)
    if products and all_succeeded:
        run_status = "success"
    elif products:
        run_status = "partial_success"
    else:
        run_status = "failure"

    return {
        "run": {
            "status": run_status,
            "started_at": started_at,
            "duration_seconds": round(duration_seconds, 3),
            "deadline_exceeded": deadline_exceeded,
            "total_products": len(products),
            "duplicates_dropped": duplicates_dropped,
            "sources": sources,
        },
        "products": [asdict(p) for p in products],
        "rejected": [{"source": r.source, "reason": r.reason, "raw": r.raw} for r in rejected],
    }


def write_output(summary: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # The timestamp alone is only second-precision, so two runs completing in
    # the same second would otherwise silently overwrite one another. The
    # random suffix keeps the human-sortable prefix while guaranteeing the
    # path is unique regardless of timing.
    run_id = uuid.uuid4().hex[:8]
    path = out_dir / f"run-{ts}-{run_id}.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path
