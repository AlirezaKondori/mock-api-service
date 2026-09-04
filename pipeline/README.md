# Reliable Data Pipeline

Aggregates product data from the three mock upstream APIs in
`../mock-api-service/`, normalizes it, and writes a consolidated JSON result
plus a run summary. See `SPEC.md` for behavior/acceptance criteria and
`PLAN.md` for the implementation approach and tradeoffs.

## Setup

Requires Python 3.11+.

```bash
cd pipeline
pip install -e ".[dev]"
```

## Run

Start the mock API service first (from `mock-api-service/`):

```bash
docker compose up --build
# or: python server.py --port 8080
```

Then, from `pipeline/`:

```bash
python -m pipeline --base-url http://localhost:8080
```

Flags: `--timeout` (per-request seconds, default 5.0), `--deadline` (overall
run budget in seconds, default 30.0), `--out` (output directory, default
`output/`).

Output: a summary is printed to stdout; the full result (summary + all
normalized products + rejected records) is written to
`output/run-<timestamp>.json`.

Exit code mirrors the run status: `1` if the run status is `failure`
(zero products returned), `0` otherwise — useful for scripting/CI without
having to parse the JSON output.

To exercise a failure scenario, restart the mock service with
`MOCK_SCENARIO=source-b-down` (or `slow`, `no-failures`, `bad-data-heavy`) —
see `../mock-api-service/README.md`.

## Test

```bash
cd pipeline
python -m pytest -v
```

Unit tests (`test_normalize.py`, `test_client_retry.py`, `test_source_*.py`,
`test_run_unit.py`, `test_cli.py`) run against mocked HTTP (`respx`), no
network needed. Integration tests (`test_run_integration.py`) launch the real
mock server as a subprocess per test.

## Assumptions

See `SPEC.md` → "Assumptions / Ambiguities and How They Were Resolved" for
the full list and reasoning (service shape, concurrency model, retry policy,
malformed-record handling, partial-failure semantics, dedup, timeouts).

## Known Limitations

- No cross-source "same product" matching — dedup is exact `(source, id)`
  only (see `SPEC.md` non-goals).
- Source A's pages are fetched sequentially rather than in parallel after
  discovering `total_pages`; a real but small perf gain left undone (see
  `PLAN.md` → "What I'd Do With More Time").
- No persisted run history — each run is one output file, no index across
  runs.
- Ships as a CLI, not a long-running HTTP service; wrapping `run_pipeline`
  behind an endpoint is straightforward but not implemented.
- Each source fetcher caps at 1000 pages (`MAX_PAGES`) as a resource-exhaustion
  safeguard against a misbehaving/malicious upstream that never stops
  paginating; hitting the cap is reported as a degraded/failed source with a
  clear error, not a crash. No real run comes remotely close to this limit
  (the fixtures have 3 pages max per source).
- When the run-level deadline is exceeded, a source that was cancelled
  mid-fetch contributes zero products to the merged output — partial pages
  already fetched by that specific cancelled source are not preserved — even
  though other sources' complete results are unaffected.
- Every product from every source is held in memory for the full run, and
  the whole result is serialized in a single `json.dumps()` call — fine at
  fixture scale (18 records), not designed for result sets of millions of
  records. Would need streaming/NDJSON output and incremental per-record
  processing instead (see `PLAN.md` → "What I'd Do With More Time").

## Not Implemented (time-boxed)

- Structured/JSON logging (stdlib `logging` text output is used instead).
- Per-source-configurable retry policy (one global policy for all sources).
- CI configuration / containerization of `pipeline/` itself — intentionally
  out of scope per `task.md`'s "no extra infrastructure" guidance.
