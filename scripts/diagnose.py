"""Per-key per-day breakdown — useful when a dashboard total disagrees with
OpenAI / Anthropic billing UI. Shows every (model, purpose, api_key) row
that contributed to spend on the given date.

Usage:
    python -m scripts.diagnose                          # today
    python -m scripts.diagnose --date 2026-05-06        # specific day
    python -m scripts.diagnose --key n8n_artem          # filter by key name
    python -m scripts.diagnose --date 2026-05-06 --key n8n_artem
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from data.db import get_conn


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose spend breakdown per key/day")
    parser.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat(),
                        help="ISO date (YYYY-MM-DD), default today UTC")
    parser.add_argument("--key", default=None, help="API key name (substring match)")
    parser.add_argument("--provider", default=None, help="provider name (openai/anthropic)")
    args = parser.parse_args()

    where = ["date(ue.occurred_at) = date(?)"]
    params: list = [args.date]
    if args.key:
        where.append("(ak.name LIKE ? OR ak.external_id LIKE ?)")
        params += [f"%{args.key}%", f"%{args.key}%"]
    if args.provider:
        where.append("p.name = ?")
        params.append(args.provider)
    where_sql = " AND ".join(where)

    sql = f"""
        SELECT
            COALESCE(ak.name, '<no key>') AS api_key,
            p.name                         AS provider,
            m.name                         AS model,
            ue.purpose                     AS purpose,
            COUNT(*)                       AS events,
            SUM(ue.tokens_in)              AS tokens_in,
            SUM(ue.tokens_out)             AS tokens_out,
            SUM(ue.tokens_cached)          AS cached,
            ROUND(SUM(ue.cost_usd), 4)     AS cost_usd
        FROM usage_events ue
        JOIN providers p ON p.id = ue.provider_id
        JOIN models m ON m.id = ue.model_id
        LEFT JOIN api_keys ak ON ak.id = ue.api_key_id
        WHERE {where_sql}
        GROUP BY ak.id, p.id, m.id, ue.purpose
        ORDER BY cost_usd DESC, events DESC
    """

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        print(f"No events for {args.date}"
              + (f" key~={args.key}" if args.key else "")
              + (f" provider={args.provider}" if args.provider else ""))
        return 0

    print(
        f"\n=== Spend breakdown for {args.date} "
        f"({'key=' + args.key if args.key else 'all keys'}, "
        f"{'provider=' + args.provider if args.provider else 'all providers'}) ===\n"
    )
    fmt = "{api_key:<20} {provider:<10} {model:<32} {purpose:<24} {events:>8} {tokens_in:>14,} {tokens_out:>12,} {cached:>12,} {cost_usd:>10}"
    header = fmt.format(
        api_key="API key", provider="Provider", model="Model", purpose="Purpose",
        events="Events", tokens_in="Tokens in", tokens_out="Tokens out",
        cached="Cached", cost_usd="$ Cost",
    )
    print(header)
    print("-" * len(header))
    total = 0.0
    total_in = total_out = 0
    total_events = 0
    for r in rows:
        d = dict(r)
        d["cost_usd"] = f"${d['cost_usd']:.4f}" if d["cost_usd"] else "$0.0000"
        d["model"] = (d["model"] or "")[:32]
        d["purpose"] = (d["purpose"] or "")[:24]
        print(fmt.format(**d))
        total += float(r["cost_usd"] or 0)
        total_in += int(r["tokens_in"] or 0)
        total_out += int(r["tokens_out"] or 0)
        total_events += int(r["events"] or 0)
    print("-" * len(header))
    print(f"{'TOTAL':<20} {'':<10} {'':<32} {'':<24} {total_events:>8} {total_in:>14,} {total_out:>12,} {'':>12} ${total:>9.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
