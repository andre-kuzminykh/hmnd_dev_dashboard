"""CLI для cron / systemd timer.

    python -m scripts.sync --days 7
"""
from __future__ import annotations

import argparse
import json

from backend.services.sync import run_sync
from data.db import init_schema


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync usage from OpenAI / Anthropic / GitHub")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    init_schema()
    result = run_sync(period_days=args.days)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
