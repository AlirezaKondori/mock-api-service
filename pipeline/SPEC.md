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

One JSON file per run (`output/run-<timestamp>-<run-id>.json` — the random
id, not just the second-precision timestamp, is what guarantees two runs
never collide on the same filename), the `run` object also
printed to stdout. Top-level keys: `run` (status, timing, `deadline_exceeded`,
`total_products`, `duplicates_dropped`, and a per-source breakdown of status/
pages/products/rejected/retries/duration/error — see "Run-level status"
below), `products` (the deduplicated list), and `rejected` (every dropped
record with its `source`/`reason`/original `raw` payload). Nothing is
silently discarded — a record is always in one of those two lists.

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

- **Transient HTTP failure** (429/502/503), **request timeout**, or
  **connection error**: retried up to 3 attempts total per request, honoring
  `Retry-After` when the response provides one, otherwise exponential backoff
  (`0.5s * 2^attempt` + jitter).
- **Non-retryable HTTP status (e.g. 400/404/500) or an invalid JSON body**:
  not worth spending retries on, so this fails the request in one attempt
  rather than three — but is still a page-level failure, handled identically
  to the exhausted-retries case below, not a crash.
- **Retries exhausted on a page, malformed page envelope (missing/wrong-type
  `total_pages`/`items`/`data`), or the `MAX_PAGES=1000` pagination cap**: any
  of these marks the source `degraded` (if some pages already succeeded) or
  `failed` (if none did). Pages already fetched are **kept**, not discarded —
  every one of these failure kinds is normalized to the same `FetchError`/
  `TypeError` handling at the page boundary, so none of them can silently
  escape and wipe out a source's accumulated progress.
  (The page cap is defense against a runaway upstream — no real run comes
  close; fixtures top out at 3 pages.)
- **Malformed record** (wrong type / missing required field, e.g. Source B's
  non-numeric price): the individual record is dropped and recorded in the
  run's `rejected` output, the rest of the page/source keeps processing. One
  bad record never fails a page.
- **Duplicate `unified_id`**: last-seen copy is kept, duplicate is counted,
  not treated as an error.
- **Source C rate limit**: paced client-side as the primary defense; a 429
  that still occurs is handled via the standard retry path.
- **Run deadline** (default 30s): in-flight work is cancelled at the deadline
  and the run finishes with what was collected (`deadline_exceeded: true`),
  never a crash. Unlike the cases above, a cancelled source contributes
  **zero** products — its task is discarded outright, not drained — while
  sources that finished in time are unaffected.

### Run-level status

- `success` — all 3 sources fully succeeded (no failed/degraded sources).
- `partial_success` — at least one source degraded or failed, but at least one
  product was returned overall.
- `failure` — zero products returned (e.g. all sources failed, or the
  deadline hit before anything completed).

A run **never raises/crashes** due to upstream behavior. CLI exit code
mirrors `run.status`: `1` on `failure`, `0` otherwise.

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
4. **Malformed records** — skip + record in `rejected`, don't fail the page/source. A pipeline
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
8. **Backoff cap and hostile `Retry-After` values** — backoff is capped at
   `MAX_BACKOFF_SECONDS=10s`, and a non-finite/negative `Retry-After` falls
   back to normal exponential backoff instead of being trusted verbatim
   (`min(nan, cap)` returns `nan`, not the cap, since NaN comparisons are
   always `False`).

## Acceptance Criteria (testable)

Verified by `tests/test_run_integration.py` against the real mock server
unless noted otherwise (`python -m pytest -v`, 77/77 passing as of this
writing).

- [x] Running against `MOCK_SCENARIO=standard` produces 17 normalized products
      (6 + 6 + 6, minus 1 rejected malformed Source B record), run status
      `success`.
- [x] Source B's `cursor-2`/`cursor-3` transient failures are retried and
      succeed without being reported as a source failure.
- [x] The shared rate limiter never allows more than `max_calls` requests in
      any rolling window (verified via request timestamps in
      `tests/test_client_retry.py`, unit-level against a mocked clock, not
      against the real server's own enforcement).
- [x] `MOCK_SCENARIO=source-b-down` produces run status `partial_success`,
      12 products (A + C only), Source B reported as `failed` in the summary.
- [x] A record with a malformed price is dropped and counted in
      `records_rejected`, not present in output, and does not abort the page.
- [x] A source that never responds (simulated) does not block the other two;
      run finishes at the deadline with `partial_success` and
      `deadline_exceeded: true`.
- [x] Re-running twice against a reset server produces identical output
      (deterministic normalization/dedup).
