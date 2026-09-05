# PLAN — Reliable Data Pipeline

## Approach

Python 3.12, `asyncio` + `httpx` for the HTTP layer. One CLI entrypoint
(`python -m pipeline`) that runs a single aggregation pass against a running
mock API instance and exits — see SPEC.md for why this is a CLI, not a
long-running server.

Layout (`pipeline/` at the repo root, alongside `mock-api-service/`):

```
pipeline/
  SPEC.md PLAN.md AI_USAGE.md README.md
  pyproject.toml            # deps: httpx; dev: pytest, pytest-asyncio, respx
  src/pipeline/
    client.py                # AsyncClient wrapper: per-request timeout, bounded retry w/ Retry-After, source-C rate limiter
    sources/
      source_a.py              # each source module implements its own async fetch(client, base_url) -> SourceResult
      source_b.py
      source_c.py
    normalize.py              # per-source raw -> Product mapping + validation
    models.py                 # Product, RejectedRecord, SourceResult (dataclasses)
    run.py                    # orchestrator: asyncio.gather over sources, dedup, deadline handling, summary
    __main__.py                # argparse CLI: --base-url --timeout --deadline --out
  tests/
    test_normalize.py
    test_client_retry.py
    test_source_a.py / test_source_b.py / test_source_c.py
    test_run_integration.py    # spins up mock server as a subprocess, real end-to-end
  output/                       # gitignored
```

## Major Technical Decisions

- **httpx over requests**: need native async + per-request timeout config;
  `respx` (httpx-native mock transport) makes unit tests clean without a real
  server.
- **Source-level concurrency, page-level sequential fetch**: see SPEC.md
  point 2. Source A's pages *could* be parallelized after learning
  `total_pages` from page 1 — not done, since it saves ~0.16s on a 6-item
  fixture and would make the three sources' fetch logic asymmetric for no
  real benefit at this scale. Documented as a "would do with more time" item.
- **Client-side rate limiting for Source C** via a sliding-window limiter
  (track last N request timestamps, sleep until the oldest ages out) rather
  than relying purely on 429+retry — avoids wasting request budget on
  responses we know will be rejected. (Not a true leaky bucket, which queues
  and drains at a constant rate — this blocks until there's room in window.)
- **Dataclasses over pydantic**: no external validation library needed for a
  handful of small, flat models; keeps dependencies minimal.
- **`bool` explicitly rejected as Source B's `amount_cents`**: `bool` is a
  subclass of `int` in Python, so without a guard `"amount_cents": true`
  would silently normalize to $0.01 instead of being rejected.
- **JSON file output + stdout summary**: task.md leaves output format open;
  JSON is trivially inspectable (`jq`, editor, or a follow-up consumer) and
  matches the normalized-product example format directly.

## Tradeoffs

- Not persisting run history — each run's output file is timestamped but
  there's no index/database of past runs. Fine for a CLI tool exercised
  by hand or in tests; would matter for a real operational service.
- No structured logging framework (e.g. `structlog`) — using stdlib
  `logging` with a consistent key=value-ish format. Sufficient at this scale;
  would reconsider for a system with multiple pipelines/log aggregation.
- Rate limiter is process-local (in-memory), not distributed. Fine for a
  single-process one-shot job; would need a shared limiter (Redis, etc.) if
  multiple pipeline instances ran concurrently against Source C.
- Cross-source "same product" detection intentionally not implemented (see
  SPEC.md non-goals) — flagged as the most likely thing a reviewer might push
  on, and I have a clear answer for why it's out of scope (heuristic, needs
  its own test data, not exercised by the fixtures).

## Testing and Verification Strategy

1. **Unit tests, no network** — `respx`-mocked httpx transport:
   - `normalize.py`: each source's happy path, plus the known-malformed
     Source B price, plus a synthetically missing-field record per source.
   - `client.py`: retry stops after 3 attempts; honors `Retry-After` when
     present vs falls back to backoff; timeout is treated as retryable.
   - Source C rate limiter: N rapid calls never exceed 2 in any 1s window
     (asserted via injected/mocked clock or timestamp capture).
2. **Integration tests, real server** — launch `mock-api-service/server.py`
   as a subprocess on a free port per test module, call `POST /admin/reset`
   between tests for determinism:
   - `MOCK_SCENARIO=standard`: full run, assert 17 products (18 fixture
     records minus 1 rejected malformed Source B price), run status
     `success` — B's transient failures are absorbed by retries, so no
     source is degraded even though the underlying requests did fail once.
   - `MOCK_SCENARIO=source-b-down`: assert `partial_success`, Source B
     `failed`, A/C unaffected, product count = 12.
   - `MOCK_SCENARIO=bad-data-heavy`: assert increased `records_rejected`,
     run still `success`/`partial_success` per the missing-field impact.
   - `MOCK_SCENARIO=slow` + a short `--deadline`: assert the run finishes
     near the deadline with `deadline_exceeded: true` rather than hanging.
3. **Determinism check** — run twice against a reset server, diff output
   (ignoring timestamps/run id) to confirm identical results.
4. Run via `python -m pytest` from `pipeline/`; no extra test runner
   infrastructure beyond `pytest` + `pytest-asyncio` + `respx`.

## Verification Before Calling This Done

- All tests pass locally (`python -m pytest -v`).
- Manual run against `docker compose up` in `mock-api-service/` plus each
  `MOCK_SCENARIO` value, eyeballing the summary output.
- Re-read the generated code for the retry/backoff and rate-limiter logic
  specifically (the parts most likely to have an off-by-one or race), since
  that's the highest-risk correctness area.

## What I'd Do With More Time

- **Parallelize Source A's pages**: fetch page 1 to learn `total_pages`, then
  `asyncio.gather` the rest — the only source where this applies, since B/C's
  pagination tokens are only known from the prior response.
- **Wrap it behind an HTTP endpoint**: a thin `POST /aggregate` adapter
  calling `run_pipeline()` directly, already side-effect-free apart from
  `write_output()`.
- **Structured logging**: JSON-line log records per event (retry, reject,
  degrade), tagged with a `run_id`, instead of stdlib `logging` text.
- **Persist run history**: append a one-line summary to `output/runs.jsonl`
  per run instead of one file per run with no cross-run view.
- **Per-source retry policy**: move retry constants into a `RetryPolicy`
  dataclass passed per source instead of one global policy for all three.
- **Scaling to much larger result sets**: `_merge_products` holds every
  product in memory and `write_output` serializes it in one `json.dumps()`
  call — fine at 18 records, not at millions. Would move to streaming NDJSON
  output, per-record generators instead of buffered lists, and (if the
  in-memory `seen` dedup map itself became the bottleneck) a streaming k-way
  merge instead of a hash map.

This list is finalized in `README.md` under "Known limitations."
