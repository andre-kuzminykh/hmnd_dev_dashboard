"""Wipe every analytical table and re-sync from real provider APIs.

Use this when the dashboard data has drifted beyond repair (duplicates from
older buggy sync runs, orphan rows, mock leftovers). It is destructive:
everything in usage_events / daily_costs / api_keys / models /
model_prices / users / alerts / providers is dropped, then the schema is
re-applied and a fresh `run_sync(period_days)` is invoked.

Usage:
    python -m scripts.reset                       # wipe + sync 30 days
    python -m scripts.reset --days 60
    python -m scripts.reset --no-sync             # wipe only, don't sync
"""
from __future__ import annotations

import argparse
import json

from data.db import get_conn, init_schema


TABLES_IN_DEPENDENCY_ORDER = [
    # children first (so FK references unwind cleanly)
    "ai_code_attribution",
    "alerts",
    "pull_requests",
    "commits",
    "repositories",
    "daily_costs",
    "usage_events",
    "api_keys",
    "seats",
    "model_prices",
    "models",
    "providers",
    "users",
    "teams",
]


def wipe() -> dict[str, int]:
    """Delete every row from analytical tables. Returns rows-deleted per table."""
    deleted: dict[str, int] = {}
    with get_conn() as conn:
        # Disable FK enforcement during the bulk wipe so we can DELETE in
        # any order without trip-wires (the schema is reasserted after).
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in TABLES_IN_DEPENDENCY_ORDER:
            try:
                cur = conn.execute(f"DELETE FROM {table}")
                deleted[table] = cur.rowcount
            except Exception as exc:  # noqa: BLE001 — keep going through every table
                deleted[table] = -1
                deleted[f"{table}_error"] = str(exc)
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Wipe all data and (optionally) resync from APIs")
    parser.add_argument("--days", type=int, default=30,
                        help="Window for the fresh sync after wipe (default 30)")
    parser.add_argument("--no-sync", action="store_true", help="Wipe only, don't run sync")
    args = parser.parse_args()

    print("[reset] wiping all analytical tables…")
    deleted = wipe()
    print(json.dumps({"deleted": deleted}, indent=2))

    print("[reset] re-applying schema (idempotent)…")
    init_schema()

    if args.no_sync:
        print("[reset] --no-sync: skipping sync; run 'python -m scripts.sync --days N' manually")
        return 0

    print(f"[reset] running fresh sync --days {args.days}…")
    from backend.services.sync import run_sync
    out = run_sync(period_days=args.days)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
