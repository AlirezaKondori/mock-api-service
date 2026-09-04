# SPEC — Reliable Data Pipeline

## Goals

- Fetch product data from all three mock sources (`source-a`, `source-b`, `source-c`).
- Normalize each source's records into a single `Product` shape.
- Survive partial upstream failure: one bad/down source must not lose data
  already collected from the others, and must not crash the run.
- Respect Source C's rate limit and Source B's transient-failure/retry contract.
- Produce a run summary that makes success/failure/degradation legible without
  reading logs line by line.
- Stay within a bounded time and resource budget per run.

## Non-Goals

- Not a long-running server for this submission. Ships as a CLI/one-shot job;
  wrapping it behind an HTTP endpoint (e.g. `POST /aggregate`) is a same-shape
  follow-up, not implemented here (see PLAN.md "What I'd do with more time").
- No persistence layer (database, queue). Output is a JSON file on disk.
- No cross-source identity resolution (e.g. matching "the same product" sold
  under different titles/ids across sources by fuzzy title match). Records are
  deduplicated only by exact `(source, id)` — see "Duplicates" below.
- No horizontal scaling / multi-run coordination. One run, one process.
- Not modifying the provided mock service.

## Normalized Product

```json
{
  "id": "a-101",
  "unified_id": "source_a:a-101",
  "title": "Mechanical Keyboard",
  "source": "source_a",
  "price": 89.99,
  "category": "electronics"
}
```

- `id`: the source's own record id, unchanged (e.g. `a-101`, `b-201`, `c-301`).
- `unified_id`: `"{source}:{id}"` — the actual dedup/identity key, since raw
  ids are already namespaced per source in the fixtures but nothing guarantees
  that in general.
- `price`: always a `float`, in the same unit (dollars) regardless of source
  representation (Source A: float dollars; Source B: integer cents; Source C:
  decimal string).
- `category`: source's category/department/type field, normalized to this one
  key. Not otherwise validated against a fixed taxonomy (out of scope).

## Run Summary Output

One JSON file per run (`output/run-<timestamp>.json`), plus the `run` object
also printed to stdout. Top-level shape:

```json
{
  "run": {
    "status": "partial_success",
    "started_at": "2026-09-03T18:04:11.123456+00:00",
    "duration_seconds": 4.201,
    "deadline_exceeded": false,
    "total_products": 12,
    "duplicates_dropped": 0,
    "sources": {
      "source_a": {
        "status": "success",
        "pages_fetched": 1,
        "products": 6,
        "rejected": 0,
        "retries": 0,
        "duration_seconds": 0.042,
        "error": null
      }
    }
  },
  "products": [ { "...": "Normalized Product, one per unique unified_id" } ],
  "rejected": [ { "source": "source_b", "reason": "invalid source_b record: ...", "raw": { "...": "the original raw record" } } ]
}
```

- `run.status`: see "Run-level status" below.
- `run.sources.<name>.retries`: total extra attempts beyond the first try,
  summed across every page fetched from that source (0 means every request
  succeeded first try).
- `products`: the deduplicated, merged product list across all sources.
- `rejected`: every dropped record, from every source, with the reason and
  the original raw payload — nothing is silently discarded, it's either in
  `products` or in `rejected`.

## Source Behavior Assumptions

| | Source A | Source B | Source C |
|---|---|---|---|
| Pagination | page number | opaque cursor (sequential — each cursor is only known from the previous response) | offset/limit (sequential — next_offset only known from previous response) |
| Failure mode | none | `cursor-2` fails once (503), `cursor-3` fails twice (502), both with `Retry-After` | 429 when >2 req/sec, with `Retry-After` |
| Data quality | clean | one record with non-numeric `amount_cents` in the standard fixture | clean, but price is a string |

Pages within one source are fetched **sequentially** by necessity (B/C's
pagination is inherently sequential; A is kept sequential too for uniformity —
see PLAN.md for the tradeoff). The three sources run **concurrently** as
independent asyncio tasks.

## Failure Behavior

- **Transient HTTP failure** (429/502/503) or **request timeout**: retried up
  to 3 attempts total per request, honoring `Retry-After` when the response
  provides one, otherwise exponential backoff (`0.5s * 2^attempt` + jitter).
- **Retries exhausted on a page**: that source is marked `degraded` (if some
  pages already succeeded) or `failed` (if none did) for this run. Pages
  already fetched from that source are **kept**, not discarded.
- **Malformed page envelope** (the response itself is missing an expected key
  like `total_pages`/`items`/`data`, or it's the wrong type): distinct from a
  malformed *record* below — this fails the whole page, not one record, since
  there's nothing to iterate. Same `degraded`/`failed` + "keep prior pages"
  handling as a retry exhaustion.
- **Malformed record** (wrong type / missing required field, e.g. Source B's
  non-numeric price): the individual record is dropped, the reason is
  recorded, and the rest of the page/source keeps processing. One bad record
  never fails a whole page or source.
- **Pagination cap reached** (`MAX_PAGES=1000` per source): defense against a
  misbehaving/adversarial upstream that never stops paginating. Treated the
  same as retries-exhausted — `degraded`/`failed` with pages fetched so far
  kept. No real run comes close to this; the fixtures top out at 3 pages.
- **Duplicate `unified_id`** (same source re-returning a record, e.g. across a
  retried page): last-seen copy is kept, duplicate is counted, not treated as
  an error.
- **Source C rate limit**: paced client-side (minimum gap between requests to
  source C) as the primary defense; a 429 that still occurs is handled via the
  standard retry path.
- **Run deadline** (default 30s, overridable): at the deadline, in-flight work
  is cancelled and the run finishes with whatever was collected so far. This
  counts as a form of partial failure (`deadline_exceeded: true` in the
  summary), never a crash. **Unlike** the "retries exhausted" / "pagination
  cap" cases above, a source that's still mid-fetch when the deadline hits
  contributes **zero** products — its task is cancelled outright, so pages it
  had already fetched before cancellation are not preserved. Other sources
  that finished within the deadline are unaffected.

### Run-level status

- `success` — all 3 sources fully succeeded (no failed/degraded sources).
- `partial_success` — at least one source degraded or failed, but at least one
  product was returned overall.
- `failure` — zero products returned (e.g. all sources failed, or the
  deadline hit before anything completed).

A run **never raises/crashes** due to upstream behavior; it always produces a
summary reflecting what happened. The CLI's process exit code mirrors this:
`1` if `run.status == "failure"`, `0` otherwise — so the run itself can never
throw, but a caller/CI script can still detect total failure without parsing
JSON.

## Assumptions / Ambiguities and How They Were Resolved

1. **Service shape** — built as a one-shot CLI, not a long-running HTTP
   server. `task.md` calls it a "service" but the acceptance criteria
   ("produces a consolidated result", "run-level summary") read as a job, not
   a server. Documented as a non-goal rather than silently skipped.
2. **Concurrency model** — asyncio + httpx, source-level concurrency,
   page-level sequential fetch. Chosen because B/C's pagination is genuinely
   sequential (cursor/offset only known from the prior response), so the only
   real parallelism available is across sources.
3. **Retries** — bounded (3 attempts), honoring `Retry-After`. Chosen because
   the mock is explicitly designed to succeed on retry (B's failure budget,
   C's rate-limit reset), and the header tells us exactly how long to wait —
   ignoring it would be strictly worse for no benefit.
4. **Malformed records** — skip + log, don't fail the page/source. A pipeline
   whose entire output disappears because of one bad price field is worse
   than one that reports "5 of 6 records normalized, 1 rejected: bad price".
5. **Partial source failure** — `partial_success` status, not a hard failure.
   Losing all data because one of three independent sources is down is a
   worse outcome than surfacing what's known plus a clear "source B is down"
   signal.
6. **Duplicates** — deduped by `(source, id)`, last-write-wins, no cross-source
   fuzzy matching. The fixtures don't exercise cross-source duplicates, and
   title-based matching is a heuristic that would need its own validation the
   4-hour budget doesn't allow.
7. **Timeouts/run limits** — per-request timeout (5s) + overall run deadline
   (30s default, configurable). Chosen so a hung/slow source degrades the run
   gracefully instead of the whole job hanging indefinitely (relevant given
   `MOCK_SCENARIO=slow`).
8. **Backoff cap and hostile `Retry-After` values** — exponential backoff is
   capped at `MAX_BACKOFF_SECONDS=10s` regardless of what a source requests,
   and a non-numeric, non-finite (`nan`/`inf`), or negative `Retry-After`
   falls back to normal exponential backoff rather than being trusted
   verbatim. A source (real or malfunctioning) that returns `Retry-After:
   999999999` or `Retry-After: nan` must not be able to stall or corrupt the
   run's timing — `min(nan, cap)` returns `nan`, not the cap, since NaN
   comparisons are always `False`, which is why this needed an explicit
   fallback rather than relying on `min()` alone.

## Acceptance Criteria (testable)

All verified by `tests/test_run_integration.py` against the real mock server
(`python -m pytest -v`, 50/50 passing as of this writing).

- [x] Running against `MOCK_SCENARIO=standard` produces 17 normalized products
      (6 + 6 + 6, minus 1 rejected malformed Source B record), run status
      `success`.
- [x] Source B's `cursor-2`/`cursor-3` transient failures are retried and
      succeed without being reported as a source failure.
- [x] Source C never receives more than 2 requests in any rolling 1-second
      window during a normal run (verified via request timestamps).
- [x] `MOCK_SCENARIO=source-b-down` produces run status `partial_success`,
      12 products (A + C only), Source B reported as `failed` in the summary.
- [x] A record with a malformed price is dropped and counted in
      `records_rejected`, not present in output, and does not abort the page.
- [x] A source that never responds (simulated) does not block the other two;
      run finishes at the deadline with `partial_success` and
      `deadline_exceeded: true`.
- [x] Re-running twice against a reset server produces identical output
      (deterministic normalization/dedup).
