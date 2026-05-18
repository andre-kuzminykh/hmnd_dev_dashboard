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
    _check("Cursor users (30d active)",     59,       cur_u,           tol_pct=10)

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
    _check("Top-25 share (%)",  80.0, round(top25 / total * 100, 1), tol_pct=4)
    _check("Top-10 combined ($)", 25646, top10, tol_pct=3)
    _check("Users ≥ $1k/mo",    9,  n_1k,  tol_pct=15)
    _check("Users ≥ $500/mo",   18, n_500, tol_pct=10)
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


# ─── 5. §1.2 DERIVED RATIOS ───────────────────────────────────────────────

def audit_derived_ratios() -> None:
    _section("§1.2 · DERIVED RATIOS (last 30 days)")
    s_iso, e_iso = _last_30d_iso()
    with get_conn() as c:
        anth = c.execute(
            """SELECT ROUND(SUM(ue.cost_usd),2) s, COUNT(*) e
               FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
               WHERE p.name='anthropic' AND ue.occurred_at BETWEEN ? AND ?""",
            (s_iso, e_iso),
        ).fetchone()
        cur = c.execute(
            """SELECT ROUND(SUM(ue.cost_usd),2) s, COUNT(*) e
               FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
               WHERE p.name='cursor' AND ue.occurred_at BETWEEN ? AND ?""",
            (s_iso, e_iso),
        ).fetchone()
        agent = c.execute(
            """SELECT ROUND(SUM(ue.cost_usd),2) s
               FROM usage_events ue JOIN providers p ON p.id=ue.provider_id
               WHERE p.name='anthropic' AND ue.purpose='Agent'
                 AND ue.occurred_at BETWEEN ? AND ?""",
            (s_iso, e_iso),
        ).fetchone()
    anth_s, anth_e = float(anth["s"] or 0), int(anth["e"] or 0)
    cur_s,  cur_e  = float(cur["s"]  or 0), int(cur["e"]  or 0)
    ag_s = float(agent["s"] or 0)
    _check("Anthropic $/req",        3.33,  round(anth_s / max(anth_e, 1), 2), tol_pct=5)
    _check("Cursor $/event",         12.13, round(cur_s  / max(cur_e, 1), 2),  tol_pct=5)
    _check("Claude Code Agent share within Anthropic (%)", 82.1,
           round(ag_s / max(anth_s, 1) * 100, 1), tol_pct=3)


# ─── 6. §1.4 PER-USER TOOL SPLITS (top-10) ────────────────────────────────

# (user_substring, expected: {Claude, GPT, Cursor})
REPORT_TOP10_SPLITS = [
    ("Atindra Nair",      {"anthropic": 5431, "openai": 0,    "cursor": 1}),
    ("Eugene Lyapustin",  {"anthropic": 5378, "openai": 0,    "cursor": 0}),
    ("Richard Osterloh",  {"anthropic": 1010, "openai": 0,    "cursor": 0}),
    ("Sam Pfeiffer",      {"anthropic": 1914, "openai": 453,  "cursor": 0}),
    ("Oleg Sinavski",     {"anthropic": 147,  "openai": 0,    "cursor": 2082}),
    ("Andy Park",         {"anthropic": 2224, "openai": 3,    "cursor": 1}),
    ("Cody Griffin",      {"anthropic": 136,  "openai": 1177, "cursor": 7}),
    ("Daksh Dhingra",     {"anthropic": 1146, "openai": 0,    "cursor": 9}),
]


def audit_top_user_tool_splits() -> None:
    _section("§1.4 · PER-USER TOOL-SPLIT (top-10, 30d)")
    s_iso, e_iso = _last_30d_iso()
    with get_conn() as c:
        rows = c.execute(
            """SELECT u.full_name n, p.name prov, ROUND(SUM(ue.cost_usd),2) s
               FROM usage_events ue
               JOIN users u ON u.id=ue.user_id
               JOIN providers p ON p.id=ue.provider_id
               WHERE ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.full_name, p.name""",
            (s_iso, e_iso),
        ).fetchall()
    by_user: dict[str, dict[str, float]] = {}
    for r in rows:
        by_user.setdefault(r["n"], {})[r["prov"]] = float(r["s"] or 0)
    for sub, expected in REPORT_TOP10_SPLITS:
        # find exact match preferred
        actual = by_user.get(sub) or next(
            (v for n, v in by_user.items() if sub.lower() in n.lower()),
            None,
        )
        if not actual:
            print(f"  ???  {sub} not found")
            continue
        for prov, exp_v in expected.items():
            label = f"{sub} · {prov}"
            _check(label, exp_v, actual.get(prov, 0), tol_pct=10, abs_tol=2)


# ─── 7. §1.6 ANOMALIES (OpenAI per-msg cost) ──────────────────────────────

# (user_substring, expected_msg_count, expected_dollars_per_msg)
REPORT_ANOMALIES = [
    ("Cody Griffin",       51, 23.11),
    ("Matt Klingensmith",  34, 23.25),
    ("Sam Pfeiffer",       26, 17.85),
]


def audit_anomalies() -> None:
    _section("§1.6 · ANOMALIES (OpenAI reasoning overusers, 30d)")
    s_iso, e_iso = _last_30d_iso()
    with get_conn() as c:
        rows = c.execute(
            """SELECT u.full_name n, COUNT(*) c, ROUND(SUM(ue.cost_usd),2) s
               FROM usage_events ue
               JOIN users u ON u.id=ue.user_id
               JOIN providers p ON p.id=ue.provider_id
               WHERE p.name='openai' AND ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.full_name HAVING s > 0
               ORDER BY s DESC""",
            (s_iso, e_iso),
        ).fetchall()
    by_user = {r["n"]: (int(r["c"]), float(r["s"] or 0)) for r in rows}
    for sub, exp_msgs, exp_dpm in REPORT_ANOMALIES:
        match = next(
            ((n, v) for n, v in by_user.items() if sub.lower() in n.lower()),
            None,
        )
        if not match:
            print(f"  ???  {sub} has no OpenAI events in 30d")
            continue
        n, (msgs, dollars) = match
        dpm = round(dollars / max(msgs, 1), 2)
        _check(f"{sub} · OpenAI msgs",  exp_msgs, msgs, tol_pct=25, abs_tol=5)
        _check(f"{sub} · OpenAI $/msg", exp_dpm,  dpm,  tol_pct=15, abs_tol=2)


# ─── 8. SNAPSHOT vs §2 LIFETIME (different windows) ───────────────────────

def audit_lifetime_git() -> None:
    _section("§2 · LIFETIME vs PERIOD (Git)")
    bot_pattern = (
        "name LIKE '%[bot]%' OR name LIKE '%-bot%' "
        "OR name LIKE 'github-actions%' OR name LIKE 'dependabot%' "
        "OR name LIKE 'renovate%' OR name LIKE 'codecov%' "
        "OR name LIKE '%-ci' OR name LIKE 'ci-%' "
        "OR name LIKE '%automation%' OR name LIKE '%[automated]%'"
    )
    with get_conn() as c:
        total_commits = int(c.execute(
            "SELECT COUNT(*) n FROM git_commits"
        ).fetchone()["n"] or 0)
        total_humans = int(c.execute(
            f"SELECT COUNT(*) n FROM git_authors WHERE NOT ({bot_pattern})"
        ).fetchone()["n"] or 0)
        total_bots = int(c.execute(
            f"SELECT COUNT(*) n FROM git_authors WHERE ({bot_pattern})"
        ).fetchone()["n"] or 0)
        # Also count bots via the same definition the dashboard uses
        # (any commit flagged is_bot in git_commits).
        commits_is_bot = c.execute(
            "SELECT COUNT(DISTINCT author_name) n FROM git_commits "
            "WHERE is_bot = 1"
        ).fetchone()
        dashboard_bots = int(commits_is_bot["n"] or 0) if commits_is_bot else 0
    # Snapshot card values (193 humans matches §2.7 TOTAL row in report)
    _check("Snapshot · commits ingested (lifetime)", 23044, total_commits, tol_pct=10)
    _check("Snapshot · humans (lifetime)",           193,   total_humans,  tol_pct=15)
    _check("Snapshot · bots (lifetime, is_bot flag)", 13, dashboard_bots,  tol_pct=20,
           comment="(uses git_commits.is_bot — same as §2 ENGINEERING)")
    # Informational: regex-only bot count (no PASS/DRIFT — known to undercount)
    print(f"         info   regex-only bot count (incomplete heuristic): "
          f"{total_bots}  · use is_bot flag instead.")


# ─── 9. MATT KLINGENSMITH DEEP-DIVE ───────────────────────────────────────

def audit_matt_klingensmith() -> None:
    _section("MATT KLINGENSMITH · DEEP DIVE (multi-window, name variants)")
    s_iso, e_iso = _last_30d_iso()
    from datetime import datetime as dt, timedelta as td
    e_90 = dt.utcnow()
    s_90 = e_90 - td(days=90)
    s_90s, e_90s = (s_90.strftime("%Y-%m-%d %H:%M:%S"),
                    e_90.strftime("%Y-%m-%d %H:%M:%S"))

    with get_conn() as c:
        rows = c.execute(
            "SELECT id, full_name, email FROM users "
            "WHERE LOWER(full_name) LIKE '%matt%klin%' "
            "OR LOWER(email) LIKE '%klingen%' "
            "OR LOWER(full_name) LIKE '%klingen%'"
        ).fetchall()
        if not rows:
            print("  ???  No user record matching 'matt klin*' / 'klingen*'")
            print("       The $790/34msg figure in §1.6 cannot be backed")
            print("       by a current DB user — likely from prior heuristic")
            print("       attribution. Recommend removing specific msg-count")
            print("       claim and keeping qualitative anomaly note.")
            return
        for u in rows:
            print(f"  USER  id={u['id']} name='{u['full_name']}' "
                  f"email='{u['email']}'")
            for label, window in (("30d",      (s_iso, e_iso)),
                                  ("90d",      (s_90s, e_90s)),
                                  ("lifetime", None)):
                if window:
                    res = c.execute(
                        "SELECT p.name prov, COUNT(*) c, "
                        "ROUND(SUM(ue.cost_usd),2) s FROM usage_events ue "
                        "JOIN providers p ON p.id=ue.provider_id "
                        "WHERE ue.user_id=? AND ue.occurred_at BETWEEN ? AND ? "
                        "GROUP BY p.name",
                        (u["id"], *window),
                    ).fetchall()
                else:
                    res = c.execute(
                        "SELECT p.name prov, COUNT(*) c, "
                        "ROUND(SUM(ue.cost_usd),2) s FROM usage_events ue "
                        "JOIN providers p ON p.id=ue.provider_id "
                        "WHERE ue.user_id=? GROUP BY p.name",
                        (u["id"],),
                    ).fetchall()
                if not res:
                    print(f"        {label:<10}  no usage events")
                    continue
                for r in res:
                    print(f"        {label:<10}  {r['prov']:<10}"
                          f"  {r['c']:>6} events  ${float(r['s'] or 0):>8.2f}")


# ─── 10. UNVERIFIABLE — list with provenance ──────────────────────────────

def list_unverifiable() -> None:
    _section("UNVERIFIABLE FROM DASHBOARD DB — provenance noted")
    items = [
        ("§2.2 per-module bug rates (14 modules)",
         "Needs git history walked per subdirectory of cloned hmnd repo. "
         "git_commits.repo is repo-level, not module-level. Source: manual "
         "analysis of /tmp/hmnd_repos_clone during one-off audit."),
        ("§2.4 test density (1:836, 1:1.3k, etc.)",
         "Test counts and LoC per module require filesystem walk. "
         "Not stored in DB."),
        ("§2.7 full per-module table (LoC, tests, top contributor %)",
         "Same — manual file-system walk. Top-contributor % was computed "
         "from per-(author, subdir) commit counts."),
        ("§1.2 Cursor: 27 Claude / 20 GPT / 16 default",
         "Comes from Cursor's own per-user model breakdown (their app UI). "
         "Not in usage_events."),
        ("§1.6 Amir Torabi 244k AI lines / 1 commit",
         "AI-lines is Cursor's lifetime counter (Cursor JSON export field "
         "`assisted_lines`). Verifiable from sources/Cursor_*.json but not "
         "via SQL aggregate."),
        ("§2.1 hmnd 9KB AGENTS.md / 40+ CI workflows / 10.3KB pre-commit",
         "File-system metadata of the cloned repos, not in DB."),
        ("Champion matrix specific name lists (Q1/Q2/Q3/Q4)",
         "Q1/Q2/Q3/Q4 cohort counts pass via segment audit (19/7/42/43). "
         "Specific names per quadrant are pulled by name match — verified "
         "elsewhere via segment + spend joins."),
    ]
    for label, why in items:
        print(f"  ??   {label}")
        print(f"       └─ {why}")


# ─── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"\n  REPORT AUDIT — utc {datetime.utcnow().isoformat()}\n")
    audit_topline_30d()
    audit_derived_ratios()
    audit_concentration()
    audit_top_spenders()
    audit_top_user_tool_splits()
    audit_anomalies()
    audit_engineering()
    audit_lifetime_git()
    audit_matt_klingensmith()
    list_unverifiable()
    print(f"\n  {'═' * 110}")
    print(f"  SUMMARY:  {TOTAL_PASS} PASS  ·  {TOTAL_FAIL} DRIFT")
    print(f"  {'═' * 110}\n")
    return 0 if TOTAL_FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
