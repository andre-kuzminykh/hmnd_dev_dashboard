"""Snapshot every metric the dashboard displays as plain text — so you can
read it end-to-end without opening Streamlit.

Run on the VM with the production DB:
    docker compose exec dashboard python -m scripts.snapshot_dashboard

Sections covered (1:1 with what the dashboard shows):
  - Source freshness (per provider+org)
  - Overview KPIs across the 4 main Source filters
  - AI Tools — Spend Breakdown, per-tool cards, Top Spenders
  - Claude Users tab: KPIs + Claude Products Breakdown
  - Claude Code tab: KPIs + Top Spenders + Model Share (from rollup)
  - ChatGPT tab: KPIs + Top Models + Spend Metrics
  - Cursor tab: KPIs + Top devs (lines/completions)
  - Models tab: model landscape (top 20)
  - High Spenders: cross-tool ranking with per-tool split
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

from backend.analytics import Filters
from backend.services.overview import (
    get_daily_spend_series, get_overview_kpis, get_source_freshness,
)
from backend.services.ai_tools import (
    get_anthropic_model_spend_from_json,
    get_anthropic_spend_by_purpose,
    get_high_spenders,
    get_high_spenders_per_provider,
    get_openai_top_models,
    get_spend_by_model,
    get_users_for_provider,
)
from backend.services.cursor_analytics import (
    claude_users, load_user_leaderboard, model_usage_summary,
)
from data.db import get_conn

PERIOD_DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 30


def _fmt_money(v: float) -> str:
    return f"${v:,.2f}" if v < 100 else f"${v:,.0f}"


def _fmt_int(v: int) -> str:
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v/1000:.1f}k"
    return str(int(v))


def _print_section(title: str) -> None:
    print(f"\n\033[1m── {title} ──\033[0m")


# ---------------------------------------------------------------------------

print(f"\033[1mDASHBOARD SNAPSHOT — last {PERIOD_DAYS} days @ {datetime.utcnow().isoformat()}Z\033[0m")

_print_section("Source freshness")
for s in get_source_freshness():
    age = "live" if s["is_live"] else f"{s['days_old']}d old"
    org = f" · {s['org_label']}" if s["org_label"] else ""
    print(f"  {s['provider']}{org}  {age}  last={s['last_day']}  events={s['events']:,}")


_print_section(f"Overview KPIs (Last {PERIOD_DAYS} days)")
print(f"  {'Source':<22} {'Total Spend':>12} {'Tokens In':>14} {'Tokens Out':>14} {'Users':>6}")
print("  " + "─" * 70)
for prov, org in [("all", "all"), ("openai", "Artem"), ("openai", "Humanoid"),
                   ("anthropic", "all"), ("cursor", "all")]:
    k = get_overview_kpis(Filters(period_days=PERIOD_DAYS, provider=prov, organization=org))
    label = f"{prov}/{org}"
    print(f"  {label:<22} {_fmt_money(k['total_spend']):>12} "
          f"{_fmt_int(k['tokens_in']):>14} {_fmt_int(k['tokens_out']):>14} "
          f"{k['active_users']:>6}")


_print_section("AI Tools — Spend Breakdown")
s_iso = (datetime.utcnow() - __import__('datetime').timedelta(days=PERIOD_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
e_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
with get_conn() as conn:
    for prov in ("anthropic", "openai", "cursor"):
        row = conn.execute(
            """SELECT COALESCE(SUM(ue.cost_usd), 0) AS s, COUNT(DISTINCT ue.user_id) AS u, COUNT(*) AS c
               FROM usage_events ue JOIN providers p ON p.id = ue.provider_id
               WHERE p.name = ? AND ue.occurred_at BETWEEN ? AND ?""",
            (prov, s_iso, e_iso),
        ).fetchone()
        print(f"  {prov:<10}  spend={_fmt_money(float(row['s'])):>12}  "
              f"users={row['u']:>4}  events={row['c']:>7,}")


_print_section("Claude Users tab")
cu = claude_users()
print(f"  Claude-favoring devs: {len(cu)}")
all_leaders = load_user_leaderboard()
total_ai = sum(int(r['ai_lines'] or 0) for r in cu)
print(f"  Total AI lines (Cursor leaderboard, claude-fav users): {_fmt_int(total_ai)}")
print()
print("  Claude Products Breakdown (Anthropic spend split by purpose):")
for p in get_anthropic_spend_by_purpose(period_days=PERIOD_DAYS):
    print(f"    {p['purpose']:<14}  spend={_fmt_money(p['spend']):>12}  "
          f"users={p['users']:>4}  reqs={p['requests']:>6,}")


_print_section("Claude Code tab")
cc_users = [r for r in get_users_for_provider("anthropic", period_days=PERIOD_DAYS)]
# CC-specific via raw SQL since get_users_for_provider doesn't filter by purpose
with get_conn() as conn:
    cc = conn.execute(
        """SELECT u.full_name AS name, ROUND(SUM(ue.cost_usd), 2) AS spend, COUNT(*) AS reqs
           FROM usage_events ue
           JOIN users u ON u.id = ue.user_id
           JOIN providers p ON p.id = ue.provider_id
           WHERE p.name = 'anthropic' AND ue.purpose = 'Agent'
             AND ue.occurred_at BETWEEN ? AND ?
           GROUP BY u.id
           ORDER BY spend DESC""",
        (s_iso, e_iso),
    ).fetchall()
cc_rows = [dict(r) for r in cc]
cc_total = sum(r['spend'] or 0 for r in cc_rows)
print(f"  CC users: {len(cc_rows)}, total CC spend: {_fmt_money(cc_total)}")
for r in cc_rows[:5]:
    print(f"    {r['name']:<24}  {_fmt_money(r['spend'] or 0):>10}  reqs={r['reqs']}")
print()
print("  Spend by Model (from rollups.modelSpend in JSON):")
for m in get_anthropic_model_spend_from_json()[:6]:
    print(f"    {m['model']:<40}  spend={_fmt_money(m['spend']):>12}  share={m['share']:5.1f}%")


_print_section("ChatGPT tab")
gpt_users = get_users_for_provider("openai", period_days=PERIOD_DAYS)
total_msgs = sum(r['messages'] for r in gpt_users)
total_spend = sum(r['cost'] for r in gpt_users)
high = [r for r in gpt_users if r['cost'] >= 200]
print(f"  Users: {len(gpt_users)}, messages: {_fmt_int(total_msgs)}, "
      f"spend: {_fmt_money(total_spend)}, high (≥$200): {len(high)}")
print("  Top users by messages:")
for r in sorted(gpt_users, key=lambda x: x['messages'], reverse=True)[:5]:
    print(f"    {r['user_name']:<24}  msgs={_fmt_int(r['messages']):>8}  spend={_fmt_money(r['cost']):>10}")
print()
print("  Top models by request count:")
for m in get_openai_top_models(period_days=PERIOD_DAYS)[:5]:
    print(f"    {m['model']:<32}  reqs={_fmt_int(m['requests']):>8}  spend={_fmt_money(m['spend']):>10}")


_print_section("Cursor tab")
leaders = load_user_leaderboard()
total_completions = sum(int(r.get('agent_completions') or 0) + int(r.get('tab_completions') or 0)
                         for r in leaders)
total_ai_lines = sum(int(r.get('ai_lines') or 0) for r in leaders)
prefer_claude = sum(1 for r in leaders if 'claude' in r['favorite_model'].lower())
prefer_gpt = sum(1 for r in leaders if r['favorite_model'].lower().startswith('gpt'))
print(f"  Active devs: {len(leaders)}, completions: {_fmt_int(total_completions)}, "
      f"AI lines: {_fmt_int(total_ai_lines)}")
print(f"  Prefer Claude: {prefer_claude}    Prefer GPT: {prefer_gpt}")
print("  Top devs by AI lines:")
for r in sorted(leaders, key=lambda x: int(x.get('ai_lines') or 0), reverse=True)[:5]:
    print(f"    {r['name']:<24}  lines={_fmt_int(int(r.get('ai_lines') or 0)):>8}  "
          f"fav={r.get('favorite_model','')[:30]}")
print()
print("  Top Cursor models (request count):")
for m in model_usage_summary()[:5]:
    print(f"    {m['model']:<40}  reqs={m['requests']:>6,}")


_print_section("Models tab — full landscape")
from backend.services.models_svc import get_models_breakdown
mb = get_models_breakdown(Filters(period_days=PERIOD_DAYS))
print(f"  {'Provider':<10} {'Model':<40} {'Spend':>12} {'Requests':>10}")
for r in mb[:15]:
    print(f"  {r['provider']:<10} {r['model']:<40} "
          f"{_fmt_money(r['cost'] or 0):>12} {(r.get('requests') or 0):>10,}")


_print_section("High Spenders (cross-tool, top 10)")
per_prov = {r["user_name"]: r for r in get_high_spenders_per_provider(period_days=PERIOD_DAYS)}
for r in get_high_spenders(period_days=PERIOD_DAYS, threshold_usd=0)[:10]:
    splits = []
    pp = per_prov.get(r["user_name"])
    if pp:
        if (pp.get("cost_openai") or 0) > 0:
            splits.append(f"GPT {_fmt_money(pp['cost_openai'])}")
        if (pp.get("cost_anthropic") or 0) > 0:
            splits.append(f"CC {_fmt_money(pp['cost_anthropic'])}")
        if (pp.get("cost_cursor") or 0) > 0:
            splits.append(f"Cursor {_fmt_money(pp['cost_cursor'])}")
    split_str = (" = " + " + ".join(splits)) if len(splits) > 1 else ""
    print(f"  {r['user_name']:<24}  {_fmt_money(r['spend']):>10}  "
          f"msgs={r['messages']:>6}{split_str}")

print("\n\033[1m── END SNAPSHOT ──\033[0m")
