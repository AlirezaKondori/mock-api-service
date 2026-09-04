from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pipeline.run import DEFAULT_DEADLINE, DEFAULT_TIMEOUT, run_pipeline, write_output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch, normalize, and summarize product data from all sources.")
    parser.add_argument("--base-url", default="http://localhost:8080", help="Base URL of the mock API service")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Per-request timeout in seconds")
    parser.add_argument("--deadline", type=float, default=DEFAULT_DEADLINE, help="Overall run deadline in seconds")
    parser.add_argument("--out", default="output", help="Directory to write the run's JSON output to")
    args = parser.parse_args(argv)

    summary = asyncio.run(run_pipeline(args.base_url, timeout=args.timeout, deadline=args.deadline))
    out_path = write_output(summary, Path(args.out))

    print(json.dumps(summary["run"], indent=2))
    print(f"\nFull output written to {out_path}")

    return 0 if summary["run"]["status"] != "failure" else 1


if __name__ == "__main__":
    sys.exit(main())
