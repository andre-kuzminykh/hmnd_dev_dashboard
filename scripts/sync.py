"""CLI для cron / systemd timer / docker compose exec.

    python -m scripts.sync --days 7
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

# Streamlit при импорте навешивает шумные warnings, когда run без runtime;
# глушим их в bare-mode.
logging.getLogger("streamlit").setLevel(logging.ERROR)
logging.getLogger("streamlit.runtime.scriptrunner").setLevel(logging.ERROR)

from backend.services.sync import run_sync
from data.db import init_schema


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync usage from OpenAI / Anthropic / GitHub")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--quiet", action="store_true", help="JSON only on stdout")
    args = parser.parse_args()

    init_schema()

    if not args.quiet:
        print(f"[sync] starting · days={args.days}", file=sys.stderr, flush=True)

    t0 = time.time()
    result = run_sync(period_days=args.days)
    elapsed = time.time() - t0

    if not args.quiet:
        print(f"[sync] done in {elapsed:.1f}s", file=sys.stderr, flush=True)

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
