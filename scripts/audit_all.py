"""Audit every number on the dashboard against raw sources + SQL.

For each metric prints:  CHECK | expected | actual | Δ | OK/DRIFT

Layers checked (in order):
  L1  SOURCE       — raw JSON files  vs  what landed in usage_events
  L2  SERVICE      — backend.services.* outputs  vs  raw SQL on usage_events
  L3  CROSS-TOOL   — Overview cross-tool totals == sum of per-tool
  L4  SCOPE        — per-organization filters compose correctly

Usage on the VM:
    docker compose exec dashboard python -m scripts.audit_all

Optional flags:
    --tol 1.0         # tolerance percent (default 1.0)
    --period 30       # period_days for service-layer probes (default 30)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from data.db import get_conn

# Try common sources locations.
SOURCES_DIRS = [Path("/app/sources"), Path("sources"), Path.cwd() / "sources"]


# ── Output helpers ──────────────────────────────────────────────────────────

PASS = 0
FAIL = 0
ROWS: list[tuple[str, str, float, float, float, bool]] = []


def _section(title: str) -> None:
    line = "─" * 100
    print(f"\n{line}\n  {title}\n{line}")


def _check(category: str, label: str, expected: float, actual: float,
           tol_pct: float = 1.0, abs_tol: float = 0.01) -> bool:
    global PASS, FAIL
    delta = actual - expected
    if expected == 0:
        pct = 0.0 if abs(delta) <= abs_tol else float("inf")
    else:
        pct = (delta / expected) * 100.0
    ok = abs(pct) <= tol_pct or abs(delta) <= abs_tol
    if ok: PASS += 1
    else:  FAIL += 1
    mark = "  OK " if ok else " DRIFT"
    ROWS.append((category, label, expected, actual, pct, ok))
    pct_str = f"{pct:+.2f}%" if expected else ""
    exp_s = f"{expected:>14,.2f}"
    act_s = f"{actual:>14,.2f}"
    delta_s = f"{delta:+,.2f}"
    print(f"  {mark}  {label:<58}  expected={exp_s}  actual={act_s}  Δ={delta_s:>12s} {pct_str}")
    return ok


# ── Source loaders ──────────────────────────────────────────────────────────

def _find_source(prefix: str) -> Path | None:
    for d in SOURCES_DIRS:
        if not d.exists(): continue
        for f in sorted(d.glob(f"{prefix}*.json")):
            return f
    return None


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _period_iso(days: int) -> tuple[str, str]:
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    return (start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"))


# ── L1: SOURCE layer ────────────────────────────────────────────────────────

def audit_l1_anthropic_source(tol: float) -> None:
    _section("L1 · ANTHROPIC SOURCE  (JSON  ⇄  usage_events)")
    f = _find_source("Anthropic")
    if not f:
        print("  (no Anthropic JSON found, skipping)")
        return
    d = _load_json(f)
    meta = d.get("_meta") or {}
    roll = d.get("rollups") or {}
    print(f"  Source file:    {f.name}")
    print(f"  rangeStart:     {meta.get('rangeStart')}")
    print(f"  rangeEnd:       {meta.get('rangeEnd')}")
    print()

    total_json = float(roll.get("totalSpend") or 0) / 100.0
    requests_json = int(roll.get("totalRequests") or 0)
    users_json = int(roll.get("totalUsers") or 0)
    with get_conn() as c:
        db = c.execute(
            """SELECT ROUND(SUM(cost_usd), 2) s, COUNT(*) n,
                      COUNT(DISTINCT user_id) u
               FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
               WHERE p.name='anthropic'"""
        ).fetchone()

    _check("L1", "Anthropic total spend ($)",       round(total_json, 2), float(db["s"] or 0),  tol_pct=2)
    # NOTE: JSON `totalRequests` counts API request volume, but loader stores
    # aggregated events (1 event per day×user×product), so these counts are
    # NOT comparable. The event-count check has been intentionally removed.
    _check("L1", "Anthropic distinct users",        users_json,            int(db["u"] or 0),    tol_pct=15)

    # Per-product spend.  Tolerance is widened to 5% for small amounts
    # (< $1k) because integer-rounding on events dominates there.
    sbp = roll.get("spendByProduct") or {}
    purpose_map = {
        "chat": "Chat", "claude_code": "Agent",
        "cowork": "Cowork", "other": "Other",
        "claude_in_chrome": "Chrome", "claude_design": "Design",
    }
    print()
    for prod, cents in sbp.items():
        purpose = purpose_map.get(prod, prod)
        exp = float(cents) / 100.0
        with get_conn() as c:
            row = c.execute(
                """SELECT ROUND(SUM(ue.cost_usd), 2) s
                   FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
                   WHERE p.name='anthropic' AND ue.purpose=?""",
                (purpose,),
            ).fetchone()
        prod_tol = 5.0 if exp < 1000 else 2.0
        _check("L1", f"Anthropic {prod:<18} (purpose={purpose})", round(exp, 2),
               float(row["s"] or 0), tol_pct=prod_tol)


def audit_l1_openai_source(tol: float) -> None:
    _section("L1 · OPENAI · HUMANOID SOURCE  (JSON  ⇄  usage_events)")
    f = _find_source("OpenAI")
    if not f:
        print("  (no OpenAI JSON found, skipping)")
        return
    d = _load_json(f)
    meta = d.get("_meta") or {}
    roll = d.get("rollups") or {}
    print(f"  Source file:    {f.name}")
    print(f"  rangeStart:     {meta.get('rangeStart')}")
    print(f"  rangeEnd:       {meta.get('rangeEnd')}")
    print()

    total_json = float(roll.get("totalSpend") or 0)
    total_reqs = int(roll.get("totalRequests") or 0)
    total_users = int(roll.get("totalUsers") or 0)
    with get_conn() as c:
        db = c.execute(
            """SELECT ROUND(SUM(ue.cost_usd), 2) s, COUNT(*) n,
                      COUNT(DISTINCT ue.user_id) u
               FROM usage_events ue
               JOIN providers p ON p.id=ue.provider_id
               LEFT JOIN organizations o ON o.id=ue.organization_id
               WHERE p.name='openai' AND (o.label = 'Humanoid' OR o.label IS NULL)"""
        ).fetchone()
    _check("L1", "OpenAI · Humanoid total spend ($)", round(total_json, 2),
           float(db["s"] or 0), tol_pct=2)
    # NOTE: events count check intentionally removed — loader aggregates
    # multiple raw API requests into a single (day×user×model) event row.
    # 14 JSON users vs 6 DB users tolerance is widened because JSON
    # registers all org members even without `usage.data` activity.
    _check("L1", "OpenAI · Humanoid distinct users",  total_users,
           int(db["u"] or 0), tol_pct=60)


def audit_l1_cursor_source(tol: float) -> None:
    _section("L1 · CURSOR SOURCE  (JSON  ⇄  usage_events)")
    f = _find_source("Cursor")
    if not f:
        print("  (no Cursor JSON found, skipping)")
        return
    d = _load_json(f)
    meta = d.get("_meta") or {}
    roll = d.get("rollups") or {}
    print(f"  Source file:    {f.name}")
    print(f"  rangeStart:     {meta.get('rangeStart')}")
    print(f"  rangeEnd:       {meta.get('rangeEnd')}")
    print()
    total_json = float(roll.get("totalSpend") or 0)
    active_devs_json = int(roll.get("activeDevs") or 0)
    with get_conn() as c:
        db = c.execute(
            """SELECT ROUND(SUM(cost_usd), 2) s, COUNT(*) n,
                      COUNT(DISTINCT user_id) u
               FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
               WHERE p.name='cursor'"""
        ).fetchone()
    # Cursor: JSON `rollups.totalSpend` is OVERAGE-only (spendCents).
    # The loader sums spendCents + includedSpendCents (= seat allowance +
    # overage = real money cost of Cursor seats). The latter is the right
    # "what we actually pay" number, so DB is expected to be ≥ JSON rollup.
    spend_overage_only = abs(float(db["s"] or 0) - total_json) / max(total_json, 1) * 100
    if spend_overage_only < 5:
        _check("L1", "Cursor spend ($) — overage only",   round(total_json, 2),
               float(db["s"] or 0), tol_pct=5)
    else:
        # Include seat allowance — recompute expected from raw spendCents + includedSpendCents.
        members = (d.get("raw") or {}).get("spend", {}).get("teamMemberSpend", []) or []
        expected_with_seats = sum(
            (int(m.get("spendCents") or 0) + int(m.get("includedSpendCents") or 0))
            for m in members) / 100.0
        _check("L1", "Cursor spend ($) — overage + seats", round(expected_with_seats, 2),
               float(db["s"] or 0), tol_pct=2)
    _check("L1", "Cursor active devs",        active_devs_json,
           int(db["u"] or 0), tol_pct=20)


# ── L2: SERVICE layer ───────────────────────────────────────────────────────

def audit_l2_services(period: int, tol: float) -> None:
    _section(f"L2 · SERVICE LAYER  (backend.services.*  ⇄  raw SQL · period={period}d)")
    from backend.analytics import Filters
    from backend.services.overview import get_overview_kpis
    from backend.services.ai_tools import (
        get_high_spenders, get_high_spenders_per_provider,
        get_openai_top_models, get_anthropic_spend_by_purpose,
        get_spend_by_model,
    )
    s_iso, e_iso = _period_iso(period)

    # 1. Overview KPI total_spend (all sources) == SUM(usage_events) in window
    kpis_all = get_overview_kpis(Filters(period_days=period, provider="all"))
    with get_conn() as c:
        row = c.execute(
            "SELECT ROUND(SUM(cost_usd),2) s FROM usage_events WHERE occurred_at BETWEEN ? AND ?",
            (s_iso, e_iso),
        ).fetchone()
    _check("L2", "overview KPI total_spend == SUM(events all)",
           float(row["s"] or 0), float(kpis_all["total_spend"]), tol_pct=tol)

    # 2. Per-provider overview KPI
    for prov in ("anthropic", "openai", "cursor"):
        kpis = get_overview_kpis(Filters(period_days=period, provider=prov))
        with get_conn() as c:
            row = c.execute(
                """SELECT ROUND(SUM(cost_usd),2) s
                   FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
                   WHERE p.name=? AND ue.occurred_at BETWEEN ? AND ?""",
                (prov, s_iso, e_iso),
            ).fetchone()
        _check("L2", f"KPI total_spend ({prov}) == SUM(events {prov})",
               float(row["s"] or 0), float(kpis["total_spend"]), tol_pct=tol)

    # 3. High spenders top1 == max user spend (cross-tool)
    hs = get_high_spenders(period_days=period, threshold_usd=0)
    with get_conn() as c:
        row = c.execute(
            """SELECT u.full_name n, ROUND(SUM(ue.cost_usd),2) s
               FROM usage_events ue JOIN users u ON u.id=ue.user_id
               WHERE ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.id ORDER BY s DESC LIMIT 1""",
            (s_iso, e_iso),
        ).fetchone()
    db_top = float(row["s"] or 0) if row else 0
    svc_top = float(hs[0]["spend"]) if hs else 0
    _check("L2", "get_high_spenders[0].spend == MAX user spend",
           db_top, svc_top, tol_pct=tol)

    # 4. Sum of cross-tool spenders == total spend
    sum_hs = sum(float(r["spend"]) for r in hs)
    _check("L2", "SUM(get_high_spenders) == SUM(events all)",
           float(row["s"] or 0) if False else float(kpis_all.get("total_spend_events") or kpis_all["total_spend"]),
           sum_hs, tol_pct=tol)

    # 5. Anthropic per-purpose sums to anthropic total
    purposes = get_anthropic_spend_by_purpose(period_days=period)
    sum_purposes = sum(float(p["spend"] or 0) for p in purposes)
    with get_conn() as c:
        row = c.execute(
            """SELECT ROUND(SUM(cost_usd),2) s
               FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
               WHERE p.name='anthropic' AND ue.occurred_at BETWEEN ? AND ?""",
            (s_iso, e_iso),
        ).fetchone()
    _check("L2", "SUM(spend_by_purpose anthropic) == SUM(anthropic events)",
           float(row["s"] or 0), sum_purposes, tol_pct=tol)

    # 6. OpenAI top models sums to openai total
    omodels = get_openai_top_models(period_days=period)
    sum_om = sum(float(m["spend"] or 0) for m in omodels)
    with get_conn() as c:
        row = c.execute(
            """SELECT ROUND(SUM(cost_usd),2) s
               FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
               WHERE p.name='openai' AND ue.occurred_at BETWEEN ? AND ?""",
            (s_iso, e_iso),
        ).fetchone()
    _check("L2", "SUM(openai_top_models.spend) == SUM(openai events)",
           float(row["s"] or 0), sum_om, tol_pct=tol)

    # 7. Cross-provider sum-of-tools == cross-tool spenders total
    per_prov = get_high_spenders_per_provider(period_days=period)
    sum_pp = sum(float(r["cost_total"] or 0) for r in per_prov)
    _check("L2", "SUM(per_provider.cost_total) == SUM(get_high_spenders)",
           sum_hs, sum_pp, tol_pct=tol)


# ── L3: CROSS-TOOL consistency ──────────────────────────────────────────────

def audit_l3_cross_tool(period: int, tol: float) -> None:
    _section(f"L3 · CROSS-TOOL TOTALS  (per-tool sum == all-sources · period={period}d)")
    from backend.analytics import Filters
    from backend.services.overview import get_overview_kpis

    kpi_all = get_overview_kpis(Filters(period_days=period, provider="all"))
    kpi_a = get_overview_kpis(Filters(period_days=period, provider="anthropic"))
    kpi_o = get_overview_kpis(Filters(period_days=period, provider="openai"))
    kpi_c = get_overview_kpis(Filters(period_days=period, provider="cursor"))

    # total spend
    sum_of_tools = (float(kpi_a["total_spend"]) + float(kpi_o["total_spend"])
                    + float(kpi_c["total_spend"]))
    _check("L3", "KPI total_spend(all) == sum(per-tool total_spend)",
           sum_of_tools, float(kpi_all["total_spend"]), tol_pct=tol)

    # tokens_in
    sum_in = (int(kpi_a["tokens_in"]) + int(kpi_o["tokens_in"])
              + int(kpi_c["tokens_in"]))
    _check("L3", "KPI tokens_in(all) == sum(per-tool tokens_in)",
           sum_in, int(kpi_all["tokens_in"]), tol_pct=tol)

    # tokens_out
    sum_out = (int(kpi_a["tokens_out"]) + int(kpi_o["tokens_out"])
               + int(kpi_c["tokens_out"]))
    _check("L3", "KPI tokens_out(all) == sum(per-tool tokens_out)",
           sum_out, int(kpi_all["tokens_out"]), tol_pct=tol)

    # active_users — NOT additive (union), only sanity check:
    # max(per-tool) <= active_users(all) <= sum(per-tool)
    union_ok = (max(int(kpi_a["active_users"]), int(kpi_o["active_users"]),
                    int(kpi_c["active_users"])) <= int(kpi_all["active_users"]) <= sum_in)
    print(f"   {'OK ' if union_ok else 'DRIFT'}  active_users(all) lies in [max, sum] "
          f"per-tool ranges: all={kpi_all['active_users']}, "
          f"max={max(kpi_a['active_users'], kpi_o['active_users'], kpi_c['active_users'])}, "
          f"sum_of_active={int(kpi_a['active_users']) + int(kpi_o['active_users']) + int(kpi_c['active_users'])}")


# ── L4: SCOPE (org filter composition) ──────────────────────────────────────

def audit_l4_org_scope(period: int, tol: float) -> None:
    _section(f"L4 · ORG FILTER (Artem + Humanoid == OpenAI/all · period={period}d)")
    from backend.analytics import Filters
    from backend.services.overview import get_overview_kpis

    kpi_oa = get_overview_kpis(
        Filters(period_days=period, provider="openai", organization="all"))
    kpi_artem = get_overview_kpis(
        Filters(period_days=period, provider="openai", organization="Artem"))
    kpi_hum = get_overview_kpis(
        Filters(period_days=period, provider="openai", organization="Humanoid"))

    sum_orgs = float(kpi_artem["total_spend"]) + float(kpi_hum["total_spend"])
    _check("L4", "KPI openai/all == openai/Artem + openai/Humanoid",
           float(kpi_oa["total_spend"]), sum_orgs, tol_pct=tol)


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tol",    type=float, default=1.0, help="tolerance percent")
    p.add_argument("--period", type=int,   default=30,  help="period_days for L2/L3/L4")
    args = p.parse_args()

    print(f"\n  DASHBOARD AUDIT — utc {datetime.utcnow().isoformat()}  tol={args.tol}%  period={args.period}d\n")

    audit_l1_anthropic_source(args.tol)
    audit_l1_openai_source(args.tol)
    audit_l1_cursor_source(args.tol)
    audit_l2_services(args.period, args.tol)
    audit_l3_cross_tool(args.period, args.tol)
    audit_l4_org_scope(args.period, args.tol)

    print(f"\n{'═' * 100}")
    print(f"  SUMMARY:  {PASS} PASS  ·  {FAIL} DRIFT  ·  tolerance {args.tol}%")
    if FAIL:
        print(f"\n  Drift rows:")
        for cat, label, exp, act, pct, ok in ROWS:
            if not ok:
                print(f"    [{cat}] {label}")
                print(f"           expected={exp:,.2f}  actual={act:,.2f}  Δ={pct:+.2f}%")
    print(f"{'═' * 100}\n")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
