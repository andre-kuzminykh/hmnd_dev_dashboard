"""Full audit of every number in the CEO report (docs/report_updated.html)
against the live DB. For each metric: expected (from report), actual
(from DB), delta + OK/DRIFT verdict.

Usage on the VM:
    docker compose exec dashboard python -m scripts.audit_report_full
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta

from data.db import get_conn

OK = "OK   "
BAD = "DRIFT"
TOTAL_PASS = 0
TOTAL_FAIL = 0


def _check(label: str, expected, actual, tol_pct: float = 5.0,
           abs_tol: float = 0.5, comment: str = "") -> None:
    global TOTAL_PASS, TOTAL_FAIL
    if isinstance(expected, str) or isinstance(actual, str):
        is_match = str(expected).strip() == str(actual).strip()
        delta_s = ""
    else:
        exp_f = float(expected or 0)
        act_f = float(actual or 0)
        diff = act_f - exp_f
        if exp_f == 0:
            is_match = abs(diff) <= abs_tol
            delta_s = f"Δ={diff:+,.2f}"
        else:
            pct = abs(diff) / abs(exp_f) * 100
            is_match = pct <= tol_pct or abs(diff) <= abs_tol
            delta_s = f"Δ={diff:+,.2f} ({(diff/exp_f*100):+.1f}%)"

    if is_match:
        TOTAL_PASS += 1
        mark = OK
    else:
        TOTAL_FAIL += 1
        mark = BAD

    exp_str = (f"{float(expected):,.2f}" if isinstance(expected, (int, float))
               else str(expected))
    act_str = (f"{float(actual):,.2f}"   if isinstance(actual, (int, float))
               else str(actual))
    extra = f"  {comment}" if comment else ""
    print(f"  {mark}  {label:<58}  expected={exp_str:>14}  actual={act_str:>14}  {delta_s}{extra}")


def _section(title: str) -> None:
    line = "─" * 110
    print(f"\n{line}\n  {title}\n{line}")


def _last_30d_iso() -> tuple[str, str]:
    end = datetime.utcnow()
    start = end - timedelta(days=30)
    return (start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"))


# ─── 1. SNAPSHOT KPIs + §1.1 / §1.2 / §1.3 ────────────────────────────────

def audit_topline_30d() -> None:
    _section("§1.1 · TOTAL / TOOL MIX (last 30 days)")
    s_iso, e_iso = _last_30d_iso()
    with get_conn() as c:
        # Total spend
        total = float(c.execute(
            "SELECT ROUND(SUM(cost_usd),2) s FROM usage_events WHERE occurred_at BETWEEN ? AND ?",
            (s_iso, e_iso),
        ).fetchone()["s"] or 0)
        users = int(c.execute(
            "SELECT COUNT(DISTINCT user_id) n FROM usage_events WHERE occurred_at BETWEEN ? AND ?",
            (s_iso, e_iso),
        ).fetchone()["n"] or 0)

        def per_prov(name: str) -> tuple[float, int, int]:
            r = c.execute(
                """SELECT ROUND(SUM(ue.cost_usd),2) s,
                          COUNT(DISTINCT ue.user_id) u,
                          COUNT(*) c
                   FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
                   WHERE p.name=? AND ue.occurred_at BETWEEN ? AND ?""",
                (name, s_iso, e_iso),
            ).fetchone()
            return (float(r["s"] or 0), int(r["u"] or 0), int(r["c"] or 0))

        anth_s, anth_u, anth_c = per_prov("anthropic")
        oai_s,  oai_u,  oai_c  = per_prov("openai")
        cur_s,  cur_u,  cur_c  = per_prov("cursor")

    # Total spend / users
    _check("Total spend (30d, $)",          42149.00, total,           tol_pct=2)
    _check("Active humans (30d)",           151,      users,           tol_pct=5)

    # Tool mix dollars
    _check("Anthropic spend ($)",           31444.00, anth_s,          tol_pct=2)
    _check("Anthropic users",               125,      anth_u,          tol_pct=10)
    _check("Anthropic events",              9445,     anth_c,          tol_pct=10)
    _check("OpenAI spend ($)",              3111.00,  oai_s,           tol_pct=2)
    _check("OpenAI users",                  7,        oai_u,           tol_pct=20)
    _check("OpenAI events",                 60501,    oai_c,           tol_pct=5)
    _check("Cursor spend ($)",              7593.00,  cur_s,           tol_pct=2)
    _check("Cursor users",                  81,       cur_u,           tol_pct=10)

    # Tool mix percentages
    sum_v = anth_s + oai_s + cur_s or 1
    _check("Anthropic % of total",          74.6, round(anth_s / sum_v * 100, 1), tol_pct=2)
    _check("Cursor % of total",             18.0, round(cur_s  / sum_v * 100, 1), tol_pct=2)
    _check("OpenAI % of total",             7.4,  round(oai_s  / sum_v * 100, 1), tol_pct=2)

    # Per-engineer / per-commit derived
    _check("$ / engineer / mo (mean)",      279.13, round(total / max(users, 1), 2), tol_pct=5)

    # Anthropic per-purpose
    with get_conn() as c:
        for purpose, label, expected in [
            ("Agent",  "Anthropic Claude Code (Agent) ($)", 25810),
            ("Chat",   "Anthropic Chat ($)",                3197),
        ]:
            row = c.execute(
                """SELECT ROUND(SUM(ue.cost_usd),2) s
                   FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
                   WHERE p.name='anthropic' AND ue.purpose=? AND ue.occurred_at BETWEEN ? AND ?""",
                (purpose, s_iso, e_iso),
            ).fetchone()
            _check(label, expected, float(row["s"] or 0), tol_pct=3)
        # Cowork + Other = ще не "Chat" и не "Agent"
        row = c.execute(
            """SELECT ROUND(SUM(ue.cost_usd),2) s
               FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
               WHERE p.name='anthropic' AND ue.purpose NOT IN ('Agent','Chat')
                 AND ue.occurred_at BETWEEN ? AND ?""",
            (s_iso, e_iso),
        ).fetchone()
        _check("Anthropic Cowork+Other ($)", 2437, float(row["s"] or 0), tol_pct=3)


# ─── 2. §1.3 Concentration ────────────────────────────────────────────────

def audit_concentration() -> None:
    _section("§1.3 · CONCENTRATION (last 30 days)")
    s_iso, e_iso = _last_30d_iso()
    with get_conn() as c:
        rows = c.execute(
            """SELECT u.full_name n, ROUND(SUM(ue.cost_usd),2) s
               FROM usage_events ue JOIN users u ON u.id=ue.user_id
               WHERE ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.full_name HAVING s > 0 ORDER BY s DESC""",
            (s_iso, e_iso),
        ).fetchall()
    spends = [float(r["s"] or 0) for r in rows]
    total = sum(spends)
    top5  = sum(spends[:5])
    top10 = sum(spends[:10])
    top25 = sum(spends[:25])
    n_1k  = sum(1 for v in spends if v >= 1000)
    n_500 = sum(1 for v in spends if v >= 500)
    n_200 = sum(1 for v in spends if v >= 200)

    _check("Top-5 share (%)",   45.1, round(top5  / total * 100, 1), tol_pct=3)
    _check("Top-10 share (%)",  60.8, round(top10 / total * 100, 1), tol_pct=3)
    _check("Top-25 share (%)",  84.0, round(top25 / total * 100, 1), tol_pct=4)
    _check("Top-10 combined ($)", 25646, top10, tol_pct=3)
    _check("Users ≥ $1k/mo",    9,  n_1k,  tol_pct=15)
    _check("Users ≥ $500/mo",   14, n_500, tol_pct=30)
    _check("Users ≥ $200/mo (High spenders)", 37, n_200, tol_pct=15)


# ─── 3. §1.4 TOP 15 SPENDERS ─────────────────────────────────────────────

REPORT_TOP15 = [
    # (name_substring, expected_total)
    ("Atindra",      5432),
    ("Eugene Lyapustin", 5378),
    ("Richard",      3625),     # — could match "Richard Osterloh" too — handled below
    ("Sam Pfeiffer", 2367),
    ("Oleg Sinavski", 2229),
    ("Andy Park",    2227),
    ("Cody Griffin", 1319),
    ("Daksh Dhingra", 1155),
    ("Richard Osterloh", 1010),
    ("Artem",        904),
]


def audit_top_spenders() -> None:
    _section("§1.4 · TOP-10 SPENDERS (last 30 days)")
    s_iso, e_iso = _last_30d_iso()
    with get_conn() as c:
        rows = c.execute(
            """SELECT u.full_name n, ROUND(SUM(ue.cost_usd),2) s
               FROM usage_events ue JOIN users u ON u.id=ue.user_id
               WHERE ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.full_name HAVING s > 0 ORDER BY s DESC LIMIT 20""",
            (s_iso, e_iso),
        ).fetchall()
    db_top = {r["n"]: float(r["s"] or 0) for r in rows}

    print(f"  DB top-20 names: {list(db_top.keys())[:10]}\n")
    for name_sub, expected in REPORT_TOP15:
        # Exact name first, then substring fallback.
        actual = db_top.get(name_sub)
        if actual is None:
            # substring match; pick highest among matches that have NOT been
            # used as exact match by an earlier entry.
            cands = [(n, v) for n, v in db_top.items() if name_sub.lower() in n.lower()]
            if cands:
                actual = max(c[1] for c in cands)
        if actual is None:
            print(f"  ???  {name_sub:<24} not found in DB top-20")
            continue
        _check(name_sub, expected, actual, tol_pct=5)


# ─── 4. §2 ENGINEERING tab — segments + bug rates ────────────────────────

def audit_engineering() -> None:
    _section("§2 · ENGINEERING (git × AI, last 90 days)")
    # These rely on the same services the Engineering tab calls.
    try:
        from backend.services.git_correlation import (
            get_git_ai_correlation, get_team_ai_share,
        )
        from backend.services.git_quality import get_team_quality
    except Exception as exc:
        print(f"  (services not importable: {exc})")
        return
    period_days = 90
    devs = get_git_ai_correlation(period_days=period_days)
    if not devs:
        print("  (no git authors data — skipping)")
        return
    share = get_team_ai_share(period_days=period_days)

    n_humans = sum(1 for r in devs if not r.get("is_bot"))
    n_bots   = sum(1 for r in devs if r.get("is_bot"))
    _check("Tracked humans",  193, n_humans, tol_pct=5)
    _check("Tracked bots",    13,  n_bots,   tol_pct=5)
    _check("Team AI share (%)",        21.3, share["ai_share_pct"],   tol_pct=3)
    _check("Bot share (%)",            2.9,  share["bot_share_pct"],  tol_pct=3)
    _check("Human AI share (%)",       19.0, share["human_ai_share_pct"], tol_pct=3)

    # Segment counts
    seg_counts: dict[str, int] = {}
    for r in devs:
        seg_counts[r["segment"]] = seg_counts.get(r["segment"], 0) + 1
    _check("Segment HIGH_AI_HIGH_GIT",   19, seg_counts.get("HIGH_AI_SPEND_HIGH_GIT_OUTPUT", 0), tol_pct=5)
    _check("Segment LOW_AI_HIGH_GIT",    9,  seg_counts.get("LOW_AI_SPEND_HIGH_GIT_OUTPUT",  0), tol_pct=15)
    _check("Segment BOT_AUTOMATION",     13, seg_counts.get("BOT_AUTOMATION",                0), tol_pct=5)
    _check("Segment AI_ACTIVE_NO_GIT",   79, seg_counts.get("AI_ACTIVE_BUT_NO_GIT",          0), tol_pct=10)
    _check("Segment GIT_ACTIVE_NO_AI",   42, seg_counts.get("GIT_ACTIVE_BUT_NO_AI",          0), tol_pct=10)
    _check("Segment NORMAL",             43, seg_counts.get("NORMAL",                        0), tol_pct=10)

    # Code Quality
    tq = get_team_quality(period_days=period_days)
    _check("Commits (period)",   12100,  tq["commits"],             tol_pct=10)
    _check("Bug-fix rate (%)",   22.3,   tq.get("bug_rate_pct", 0), tol_pct=3)
    _check("Human bug rate (%)", 22.0,   tq.get("human_bug_rate_pct", 0), tol_pct=3)
    _check("Bot bug rate (%)",   26.8,   tq.get("bot_bug_rate_pct", 0),  tol_pct=3)


# ─── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"\n  REPORT AUDIT — utc {datetime.utcnow().isoformat()}\n")
    audit_topline_30d()
    audit_concentration()
    audit_top_spenders()
    audit_engineering()
    print(f"\n  {'═' * 110}")
    print(f"  SUMMARY:  {TOTAL_PASS} PASS  ·  {TOTAL_FAIL} DRIFT")
    print(f"  {'═' * 110}\n")
    return 0 if TOTAL_FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
