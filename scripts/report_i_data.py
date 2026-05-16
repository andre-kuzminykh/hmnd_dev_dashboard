"""Pull every number needed for Report I (Last 30 days) from the DB.

Output is plain text, copy-paste into chat and I'll refine Report I with
real numbers instead of estimates.

Usage:
    docker compose exec -T dashboard python -m scripts.report_i_data
    docker compose exec -T dashboard python -m scripts.report_i_data --days 30
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

from data.db import get_conn


def hr(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    end = datetime.utcnow()
    start = end - timedelta(days=args.days)
    s_iso = start.strftime("%Y-%m-%d %H:%M:%S")
    e_iso = end.strftime("%Y-%m-%d %H:%M:%S")
    print(f"Report I — data dump for last {args.days} days "
          f"({start.date()} → {end.date()})\n")

    with get_conn() as conn:
        # ─── A. Total spend + per-provider breakdown ───
        hr(f"A. Total spend (last {args.days}d)")
        rows = conn.execute(
            """SELECT p.name AS provider,
                      ROUND(SUM(ue.cost_usd), 2)         AS spend,
                      COUNT(DISTINCT ue.user_id)         AS users,
                      COUNT(*)                           AS events
               FROM usage_events ue
               JOIN providers p ON p.id = ue.provider_id
               WHERE ue.occurred_at BETWEEN ? AND ?
               GROUP BY p.name
               ORDER BY spend DESC""",
            (s_iso, e_iso),
        ).fetchall()
        total = sum(r["spend"] or 0 for r in rows)
        print(f"  {'provider':12s}  {'spend':>12s}  {'share':>6s}  {'users':>6s}  {'events':>8s}")
        for r in rows:
            share = (r["spend"] or 0) / total * 100 if total else 0
            print(f"  {r['provider']:12s}  ${r['spend']:>10,.2f}  {share:>5.1f}%  {r['users']:>6}  {r['events']:>8,}")
        print(f"  {'TOTAL':12s}  ${total:>10,.2f}")

        # ─── B. Spend by org (OpenAI multi-tenant) ───
        hr(f"B. OpenAI: per-org breakdown")
        rows = conn.execute(
            """SELECT o.label AS org, ROUND(SUM(ue.cost_usd), 2) AS spend,
                      COUNT(DISTINCT ue.user_id) AS users, COUNT(*) AS events
               FROM usage_events ue
               JOIN providers p ON p.id = ue.provider_id
               JOIN organizations o ON o.id = ue.organization_id
               WHERE p.name = 'openai' AND ue.occurred_at BETWEEN ? AND ?
               GROUP BY o.label ORDER BY spend DESC""",
            (s_iso, e_iso),
        ).fetchall()
        for r in rows:
            print(f"  {r['org']:12s}  ${r['spend']:>10,.2f}  users={r['users']:>3}  events={r['events']:>6,}")

        # ─── C. Claude split by purpose ───
        hr(f"C. Anthropic by purpose (Chat / Claude Code / etc.)")
        rows = conn.execute(
            """SELECT ue.purpose, ROUND(SUM(ue.cost_usd), 2) AS spend,
                      COUNT(*) AS requests, COUNT(DISTINCT ue.user_id) AS users
               FROM usage_events ue
               JOIN providers p ON p.id = ue.provider_id
               WHERE p.name = 'anthropic' AND ue.occurred_at BETWEEN ? AND ?
               GROUP BY ue.purpose ORDER BY spend DESC""",
            (s_iso, e_iso),
        ).fetchall()
        for r in rows:
            print(f"  {(r['purpose'] or '(none)'):20s}  ${r['spend']:>10,.2f}  reqs={r['requests']:>6,}  users={r['users']:>3}")

        # ─── D. Top 15 spenders (cross-tool) ───
        hr(f"D. Top 15 spenders (cross-tool, {args.days}d)")
        rows = conn.execute(
            """SELECT u.full_name AS name,
                      ROUND(SUM(ue.cost_usd), 2) AS spend,
                      ROUND(SUM(CASE WHEN p.name='anthropic' THEN ue.cost_usd ELSE 0 END), 2) AS claude,
                      ROUND(SUM(CASE WHEN p.name='openai'    THEN ue.cost_usd ELSE 0 END), 2) AS gpt,
                      ROUND(SUM(CASE WHEN p.name='cursor'    THEN ue.cost_usd ELSE 0 END), 2) AS cursor,
                      COUNT(*) AS events
               FROM usage_events ue
               JOIN users u    ON u.id = ue.user_id
               JOIN providers p ON p.id = ue.provider_id
               WHERE ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.id ORDER BY spend DESC LIMIT 15""",
            (s_iso, e_iso),
        ).fetchall()
        print(f"  {'#':>2}  {'name':25s}  {'total':>9s}  {'Claude':>8s}  {'GPT':>7s}  {'Cursor':>7s}  {'events':>7s}")
        for i, r in enumerate(rows, 1):
            print(f"  {i:>2}  {r['name'][:25]:25s}  ${r['spend']:>7,.0f}  ${r['claude']:>6,.0f}  ${r['gpt']:>5,.0f}  ${r['cursor']:>5,.0f}  {r['events']:>7,}")
        top5  = sum(r["spend"] for r in rows[:5])
        top10 = sum(r["spend"] for r in rows[:10])
        if total > 0:
            print(f"\n  Top-5 share:  ${top5:>10,.0f}  ({top5 /total*100:.1f}% of ${total:,.0f})")
            print(f"  Top-10 share: ${top10:>10,.0f}  ({top10/total*100:.1f}% of ${total:,.0f})")

        # ─── E. Top 10 models by spend ───
        hr(f"E. Top 10 models by spend ({args.days}d)")
        rows = conn.execute(
            """SELECT m.name AS model, p.name AS provider,
                      ROUND(SUM(ue.cost_usd), 2) AS spend,
                      COUNT(*) AS requests, COUNT(DISTINCT ue.user_id) AS users
               FROM usage_events ue
               JOIN providers p ON p.id = ue.provider_id
               JOIN models m    ON m.id = ue.model_id
               WHERE ue.occurred_at BETWEEN ? AND ?
               GROUP BY m.id ORDER BY spend DESC LIMIT 10""",
            (s_iso, e_iso),
        ).fetchall()
        for r in rows:
            print(f"  {r['provider']:10s}  {r['model'][:35]:35s}  ${r['spend']:>10,.2f}  reqs={r['requests']:>6,}  users={r['users']:>3}")

        # ─── F. ChatGPT outliers — high $/msg ───
        hr(f"F. ChatGPT (OpenAI) top spenders + $/msg ratio")
        rows = conn.execute(
            """SELECT u.full_name AS name,
                      ROUND(SUM(ue.cost_usd), 2) AS spend,
                      COUNT(*) AS messages,
                      ROUND(SUM(ue.cost_usd) / COUNT(*), 2) AS dpm
               FROM usage_events ue
               JOIN users u    ON u.id = ue.user_id
               JOIN providers p ON p.id = ue.provider_id
               WHERE p.name = 'openai' AND ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.id HAVING spend > 5 ORDER BY spend DESC LIMIT 12""",
            (s_iso, e_iso),
        ).fetchall()
        for r in rows:
            flag = "  ← HIGH $/MSG" if r["dpm"] and r["dpm"] >= 1.0 else ""
            print(f"  {r['name'][:25]:25s}  ${r['spend']:>7,.2f}  msgs={r['messages']:>5,}  ${r['dpm']:>5,.2f}/msg{flag}")

        # ─── G. Cursor leaderboard (lifetime — Cursor doesn't export by period) ───
        hr("G. Cursor leaderboard (LIFETIME — Cursor metric)")
        from backend.services.cursor_analytics import load_user_leaderboard
        leaders = load_user_leaderboard()
        active = [l for l in leaders if (l.get("agent_completions",0) or 0) + (l.get("tab_completions",0) or 0) > 0]
        print(f"  Total team members: {len(leaders)}")
        print(f"  Active (≥1 completion): {len(active)}")
        prefer_claude = sum(1 for l in leaders if "claude" in (l.get("favorite_model","") or "").lower())
        prefer_gpt    = sum(1 for l in leaders if (l.get("favorite_model","") or "").lower().startswith("gpt"))
        print(f"  Favorite model — Claude family: {prefer_claude}")
        print(f"  Favorite model — GPT family: {prefer_gpt}")
        top = sorted(active, key=lambda r: (r.get("ai_lines") or 0), reverse=True)[:10]
        print(f"\n  Top 10 by AI lines (lifetime):")
        for r in top:
            agent = r.get("agent_completions") or 0
            tab = r.get("tab_completions") or 0
            print(f"    {r.get('name', '')[:25]:25s}  AI lines={r.get('ai_lines',0):>10,}  agent={agent:>5,}  tab={tab:>6,}  fav={r.get('favorite_model','')[:25]}")

        # ─── H. Claude Code (purpose=Agent) top users ───
        hr(f"H. Claude Code (purpose='Agent') top users ({args.days}d)")
        rows = conn.execute(
            """SELECT u.full_name AS name,
                      COUNT(*) AS requests,
                      ROUND(SUM(ue.cost_usd), 2) AS spend
               FROM usage_events ue
               JOIN users u    ON u.id = ue.user_id
               JOIN providers p ON p.id = ue.provider_id
               WHERE p.name = 'anthropic' AND ue.purpose = 'Agent'
                 AND ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.id ORDER BY spend DESC LIMIT 10""",
            (s_iso, e_iso),
        ).fetchall()
        for r in rows:
            print(f"  {r['name'][:25]:25s}  ${r['spend']:>7,.2f}  reqs={r['requests']:>6,}")

        # ─── I. Adoption segments (recomputed) ───
        hr("I. Git × AI segments (current)")
        from backend.services.git_correlation import get_git_ai_correlation
        devs = get_git_ai_correlation(period_days=args.days)
        seg: dict[str, int] = {}
        for d in devs:
            seg[d["segment"]] = seg.get(d["segment"], 0) + 1
        for k, n in sorted(seg.items(), key=lambda x: -x[1]):
            print(f"  {k:32s}  {n:>5}")

        # ─── J. Period totals — convenient summary ───
        hr("J. Summary KPIs (Last 30d)")
        kpi = conn.execute(
            """SELECT ROUND(SUM(ue.cost_usd), 2) AS spend,
                      SUM(ue.tokens_in)          AS tokens_in,
                      SUM(ue.tokens_out)         AS tokens_out,
                      COUNT(DISTINCT ue.user_id) AS users,
                      COUNT(*) AS events
               FROM usage_events ue
               WHERE ue.occurred_at BETWEEN ? AND ?""",
            (s_iso, e_iso),
        ).fetchone()
        print(f"  Total spend:    ${kpi['spend']:,.2f}")
        print(f"  Tokens in:      {kpi['tokens_in']:,}")
        print(f"  Tokens out:     {kpi['tokens_out']:,}")
        print(f"  Active users:   {kpi['users']}")
        print(f"  Events:         {kpi['events']:,}")
        if kpi["users"]:
            print(f"  Avg spend/user: ${kpi['spend']/kpi['users']:,.2f}")

    print("\n" + "=" * 60)
    print("  END OF DATA DUMP — paste this into chat")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
