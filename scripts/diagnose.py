"""Per-key per-day breakdown — useful when a dashboard total disagrees with
OpenAI / Anthropic billing UI.

Examples:
    python -m scripts.diagnose                                    # today
    python -m scripts.diagnose --date 2026-05-06
    python -m scripts.diagnose --key n8n_artem
    python -m scripts.diagnose --date 2026-05-06 --key n8n_artem
    python -m scripts.diagnose --prices                           # dump model prices
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from data.db import get_conn


def _print_prices() -> None:
    sql = """
        SELECT m.name AS model, p.name AS provider,
               mp.input_per_1k, mp.output_per_1k, mp.cache_read_per_1k
        FROM models m
        JOIN providers p ON p.id = m.provider_id
        LEFT JOIN model_prices mp ON mp.model_id = m.id
        ORDER BY p.name, m.name
    """
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    print(f"\n=== model_prices (per 1K tokens) ===\n")
    print(f"{'Provider':<10} {'Model':<40} {'in/1K':>10} {'out/1K':>10} {'cache/1K':>10}")
    print("-" * 84)
    for r in rows:
        in_p = r["input_per_1k"]
        out_p = r["output_per_1k"]
        cache_p = r["cache_read_per_1k"]
        if in_p is None:
            print(f"{r['provider']:<10} {r['model'][:40]:<40} {'(none)':>10} {'(none)':>10} {'(none)':>10}")
        else:
            print(f"{r['provider']:<10} {r['model'][:40]:<40} {in_p:>10.6f} {out_p:>10.6f} {cache_p:>10.6f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose spend breakdown per key/day")
    parser.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat(),
                        help="ISO date (YYYY-MM-DD), default today UTC")
    parser.add_argument("--key", default=None, help="API key name (substring match)")
    parser.add_argument("--provider", default=None, help="provider name (openai/anthropic)")
    parser.add_argument("--prices", action="store_true",
                        help="dump model_prices and exit")
    args = parser.parse_args()

    if args.prices:
        _print_prices()
        return 0

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

    title = (
        f"\n=== Spend breakdown for {args.date} ("
        + ("key=" + args.key if args.key else "all keys")
        + ", "
        + ("provider=" + args.provider if args.provider else "all providers")
        + ") ===\n"
    )
    print(title)

    # Two format strings: one for the header (strings only), one for rows (with thousands sep on ints).
    HDR = "{:<20} {:<10} {:<36} {:<26} {:>8} {:>14} {:>12} {:>12} {:>10}"
    ROW = "{:<20} {:<10} {:<36} {:<26} {:>8,} {:>14,} {:>12,} {:>12,} {:>10}"
    header = HDR.format("API key", "Provider", "Model", "Purpose",
                        "Events", "Tokens in", "Tokens out", "Cached", "$ Cost")
    print(header)
    print("-" * len(header))

    total_cost = 0.0
    total_events = 0
    total_in = 0
    total_out = 0
    total_cached = 0
    for r in rows:
        cost = float(r["cost_usd"] or 0)
        events = int(r["events"] or 0)
        in_  = int(r["tokens_in"] or 0)
        out  = int(r["tokens_out"] or 0)
        cch  = int(r["cached"] or 0)
        print(ROW.format(
            (r["api_key"] or "<no key>")[:20],
            (r["provider"] or "")[:10],
            (r["model"] or "")[:36],
            (r["purpose"] or "")[:26],
            events, in_, out, cch,
            f"${cost:.4f}",
        ))
        total_cost += cost
        total_events += events
        total_in += in_
        total_out += out
        total_cached += cch

    print("-" * len(header))
    print(ROW.format("TOTAL", "", "", "",
                     total_events, total_in, total_out, total_cached,
                     f"${total_cost:.4f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
