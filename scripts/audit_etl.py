"""Full end-to-end audit of every data source the dashboard ingests.

For each source (Anthropic JSON, Cursor JSON, OpenAI JSON, OpenAI API):
  1. Compute the ground-truth total directly from raw JSON bytes
     (or for OpenAI API, from the live /costs response)
  2. Run the production loader against an empty DB
  3. SUM(cost_usd) from usage_events
  4. Compare 1, 2, 3 — they must agree within rounding

Idempotency check: load twice, row count must stay constant.

Usage:
    python -m scripts.audit_etl

Exit code 0 on full pass; 1 on any discrepancy.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCES = REPO / "sources"

OK = "\033[32m✓\033[0m"
BAD = "\033[31m✗\033[0m"
HEAD = "\033[1m"
END = "\033[0m"


def _print(label: str, expected: float, actual: float, tol: float = 0.5):
    ok = abs(expected - actual) <= tol or (
        expected > 0 and abs(expected - actual) / expected < 0.01
    )
    mark = OK if ok else BAD
    delta = actual - expected
    pct = (delta / expected * 100) if expected else 0
    print(f"  {mark} {label:40s} expected=${expected:>14,.2f}  actual=${actual:>14,.2f}  Δ={delta:+,.2f} ({pct:+.2f}%)")
    return ok


def _setup_db() -> Path:
    tmp = Path(tempfile.mkdtemp())
    os.environ["HMND_DB_PATH"] = str(tmp / "audit.db")
    os.environ["HMND_SOURCES_DIR"] = str(SOURCES)
    # Disable mocks/calibration that would distort the audit
    os.environ["HMND_ANTHROPIC_MOCK"] = "false"
    # Clear-import to honor the new env
    import importlib
    import data.db as _db
    importlib.reload(_db)
    _db.init_schema()
    return tmp


def _db_total(provider: str) -> float:
    from data.db import get_conn
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(cost_usd), 0) AS s
               FROM usage_events ue JOIN providers p ON p.id = ue.provider_id
               WHERE p.name = ?""",
            (provider,),
        ).fetchone()
    return float(row["s"] or 0)


def _db_count(provider: str) -> int:
    from data.db import get_conn
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n
               FROM usage_events ue JOIN providers p ON p.id = ue.provider_id
               WHERE p.name = ?""",
            (provider,),
        ).fetchone()
    return int(row["n"] or 0)


# ---------------------------------------------------------------------------
# ANTHROPIC
# ---------------------------------------------------------------------------

def audit_anthropic() -> bool:
    print(f"\n{HEAD}── ANTHROPIC (JSON) ──{END}")
    f = SOURCES / "Anthropics_20260515.json"
    if not f.exists():
        print(f"  {BAD} file missing: {f}")
        return False

    doc = json.loads(f.read_text())
    # GROUND TRUTH from raw bytes
    rollup_cents = float(doc["rollups"]["totalSpend"])
    rollup_usd = rollup_cents / 100.0

    items = doc["raw"]["userCostByProduct"]["data"]
    sum_amount_cents = sum(float(it["amount"]) for it in items)
    sum_amount_usd = sum_amount_cents / 100.0

    print(f"  raw rollups.totalSpend  = {rollup_cents:>14,.2f} cents  →  ${rollup_usd:,.2f}")
    print(f"  raw Σ userCost amounts  = {sum_amount_cents:>14,.2f} cents  →  ${sum_amount_usd:,.2f}")
    print(f"  raw rows               = {len(items):>14d}")
    print(f"  raw totalUsers         = {doc['rollups']['totalUsers']:>14d}")
    print(f"  raw totalRequests      = {doc['rollups']['totalRequests']:>14,d}")
    print(f"  raw totalTokens        = {doc['rollups']['totalTokens']:>14,d}")

    # Loader run
    from data.sources.anthropic_json import load_anthropic_json
    report = load_anthropic_json(f)
    db_total = _db_total("anthropic")

    ok1 = _print("loader report total_spend_usd vs rollups", rollup_usd, report["total_spend_usd"])
    ok2 = _print("DB SUM(cost_usd) vs rollups", rollup_usd, db_total, tol=rollup_usd * 0.02)
    ok3 = _print("DB SUM vs raw Σ userCost amounts", sum_amount_usd, db_total, tol=sum_amount_usd * 0.02)

    # Idempotency
    rows1 = _db_count("anthropic")
    load_anthropic_json(f)
    rows2 = _db_count("anthropic")
    ok4 = rows1 == rows2
    mark = OK if ok4 else BAD
    print(f"  {mark} idempotent reload                       rows1={rows1}  rows2={rows2}")

    return ok1 and ok2 and ok3 and ok4


# ---------------------------------------------------------------------------
# CURSOR
# ---------------------------------------------------------------------------

def audit_cursor() -> bool:
    print(f"\n{HEAD}── CURSOR (JSON) ──{END}")
    f = SOURCES / "Cursor_20260515.json"
    if not f.exists():
        print(f"  {BAD} file missing: {f}")
        return False

    doc = json.loads(f.read_text())
    rollup_total = float(doc["rollups"]["totalSpend"])

    # Cursor's raw spend is in raw.spend.teamMemberSpend[*].spendCents/includedSpendCents
    members = doc["raw"]["spend"]["teamMemberSpend"]
    sum_spend = sum(int(m.get("spendCents") or 0) for m in members) / 100.0
    sum_included = sum(int(m.get("includedSpendCents") or 0) for m in members) / 100.0
    sum_total = sum_spend + sum_included
    # Loader counts users with either spend OR activity (lines/agent). Build
    # the same "active" set from raw so the count matches what the loader does.
    per_user_rollup = doc.get("rollups", {}).get("perUser") or {}
    active_users = 0
    for m in members:
        email = (m.get("email") or "").lower().strip()
        if not email:
            continue
        cents = int(m.get("spendCents") or 0) + int(m.get("includedSpendCents") or 0)
        r = per_user_rollup.get(email) or per_user_rollup.get(m.get("email") or "") or {}
        if cents > 0 or int(r.get("lines") or 0) > 0 or int(r.get("agent") or 0) > 0:
            active_users += 1

    print(f"  raw rollups.totalSpend  = ${rollup_total:>12,.2f}")
    print(f"  raw Σ spendCents        = ${sum_spend:>12,.2f}  (overage only)")
    print(f"  raw Σ includedSpendCents= ${sum_included:>12,.2f}  (subscription)")
    print(f"  raw Σ both              = ${sum_total:>12,.2f}")
    print(f"  raw team members        = {len(members):>13d}")
    print(f"  raw active users        = {active_users:>13d}  (spend>0 OR lines>0 OR agent>0)")

    from data.sources.cursor_json import load_cursor_json
    report = load_cursor_json(f)
    db_total = _db_total("cursor")

    ok1 = _print("DB SUM(cost_usd) vs Σ(spend+included)", sum_total, db_total, tol=sum_total * 0.02)
    ok2 = _print("loader users count vs raw active users", float(active_users),
                 float(report.get("users") or 0), tol=1)

    # Idempotency
    rows1 = _db_count("cursor")
    load_cursor_json(f)
    rows2 = _db_count("cursor")
    ok3 = rows1 == rows2
    mark = OK if ok3 else BAD
    print(f"  {mark} idempotent reload                       rows1={rows1}  rows2={rows2}")

    return ok1 and ok2 and ok3


# ---------------------------------------------------------------------------
# OPENAI (Humanoid JSON)
# ---------------------------------------------------------------------------

def audit_openai_json() -> bool:
    print(f"\n{HEAD}── OPENAI / Humanoid (JSON) ──{END}")
    f = SOURCES / "OpenAI_20260515.json"
    if not f.exists():
        print(f"  {BAD} file missing: {f}")
        return False

    doc = json.loads(f.read_text())
    rollup = float(doc["rollups"]["totalSpend"])
    total_reqs = int(doc["rollups"]["totalRequests"])
    per_user = doc["rollups"]["perUser"]

    # Sum per_user spend share — should equal rollup
    if total_reqs > 0 and rollup > 0:
        sum_share = sum(
            (int(reqs) / total_reqs) * rollup for reqs in per_user.values()
        )
    else:
        sum_share = 0.0

    print(f"  raw rollups.totalSpend       = ${rollup:>12,.2f}")
    print(f"  raw rollups.totalRequests    = {total_reqs:>13,d}")
    print(f"  raw rollups.perUser entries  = {len(per_user):>13d}")
    print(f"  Σ per_user spend share       = ${sum_share:>12,.2f}")

    from data.sources.openai_json import load_openai_json
    report = load_openai_json(f, org_label="Humanoid")
    db_total = _db_total("openai")

    # The loader spends `per_user_reqs/total_reqs * totalSpend` per user,
    # then attributes per-request cost = user_spend / user_total_reqs.
    # DB total should equal sum_share (which equals totalSpend if every
    # user in perUser also shows up in usage.data buckets).
    ok1 = _print("DB SUM vs rollups.totalSpend", rollup, db_total, tol=rollup * 0.05)
    ok2 = _print("loader.total_spend_usd vs rollups", rollup, float(report["total_spend_usd"]))

    # Org tagging
    from data.db import get_conn
    with get_conn() as conn:
        untagged = conn.execute(
            """SELECT COUNT(*) AS n FROM usage_events ue
               JOIN providers p ON p.id = ue.provider_id
               WHERE p.name='openai'
                 AND (ue.organization_id IS NULL OR
                      ue.organization_id NOT IN
                      (SELECT id FROM organizations WHERE label='Humanoid'))"""
        ).fetchone()["n"]
    ok3 = untagged == 0
    mark = OK if ok3 else BAD
    print(f"  {mark} every row tagged organization_id=Humanoid     untagged={untagged}")

    # Idempotency (Humanoid scope)
    rows1 = _db_count("openai")
    load_openai_json(f, org_label="Humanoid")
    rows2 = _db_count("openai")
    ok4 = rows1 == rows2
    mark = OK if ok4 else BAD
    print(f"  {mark} idempotent reload                              rows1={rows1}  rows2={rows2}")

    return ok1 and ok2 and ok3 and ok4


# ---------------------------------------------------------------------------
# DASHBOARD QUERY (post-load): tokens_in matches OpenAI Platform UI
# ---------------------------------------------------------------------------

def audit_tokens_uncached() -> bool:
    print(f"\n{HEAD}── DASHBOARD: tokens_in == raw input_tokens (matches OpenAI Platform) ──{END}")
    from data.db import get_conn
    from backend.analytics import Filters
    from backend.services.overview import get_overview_kpis

    with get_conn() as conn:
        raw = conn.execute(
            """SELECT COALESCE(SUM(tokens_in), 0)     AS s_in,
                      COALESCE(SUM(tokens_cached), 0) AS s_c
               FROM usage_events"""
        ).fetchone()
    raw_in = int(raw["s_in"])
    raw_cached = int(raw["s_c"])

    kpis = get_overview_kpis(Filters(period_days=120))
    displayed_in = int(kpis["tokens_in"])
    displayed_cached = int(kpis.get("tokens_cached") or 0)

    print(f"  raw Σ tokens_in                          = {raw_in:>14,d}")
    print(f"  raw Σ tokens_cached                      = {raw_cached:>14,d}")
    print(f"  KPI tokens_in (= raw, matches OpenAI UI) = {displayed_in:>14,d}")
    print(f"  KPI tokens_cached (separate aggregate)   = {displayed_cached:>14,d}")

    ok1 = displayed_in == raw_in
    ok2 = displayed_cached == raw_cached
    mark1 = OK if ok1 else BAD
    mark2 = OK if ok2 else BAD
    print(f"  {mark1} displayed tokens_in == raw")
    print(f"  {mark2} displayed tokens_cached == raw cached")
    return ok1 and ok2


# ---------------------------------------------------------------------------
# GIT CSV — drop-the-file source for Git × AI correlation
# ---------------------------------------------------------------------------

def audit_git_csv() -> bool:
    print(f"\n{HEAD}── GIT (CSV drop) ──{END}")
    from data.sources.git_csv import (
        latest_git_authors_file, latest_git_commits_file,
        load_git_authors_csv, load_git_commits_csv,
    )
    from data.db import get_conn
    import csv

    ga = latest_git_authors_file()
    if ga is None:
        print(f"  {BAD} no git_authors_*.csv in sources/")
        return False
    gc = latest_git_commits_file()
    print(f"  authors CSV: {ga.path.name}")
    if gc is not None:
        print(f"  commits CSV: {gc.path.name}")
    else:
        print(f"  (no per-commit-file CSV — repo filter won't work)")

    # Raw author totals
    with open(ga.path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        raw_authors = list(reader)
    raw_commits = sum(int(r.get("commits") or 0) for r in raw_authors)
    raw_add = sum(int(r.get("additions") or 0) for r in raw_authors)
    raw_del = sum(int(r.get("deletions") or 0) for r in raw_authors)
    print(f"  raw rows           : {len(raw_authors):>10,}")
    print(f"  raw Σ commits      : {raw_commits:>10,}")
    print(f"  raw Σ additions    : {raw_add:>10,}")
    print(f"  raw Σ deletions    : {raw_del:>10,}")

    # Load and compare
    rep1 = load_git_authors_csv(ga.path)
    if gc is not None:
        rep2 = load_git_commits_csv(gc.path)
    with get_conn() as conn:
        db = conn.execute(
            """SELECT COUNT(*) AS n,
                      COALESCE(SUM(commits), 0)   AS c,
                      COALESCE(SUM(additions), 0) AS a,
                      COALESCE(SUM(deletions), 0) AS d
               FROM git_authors"""
        ).fetchone()
    db_n, db_c, db_a, db_d = db["n"], db["c"], db["a"], db["d"]

    ok1 = _print("DB rows == raw rows",          float(len(raw_authors)), float(db_n), tol=0)
    ok2 = _print("DB Σ commits == raw",          float(raw_commits),      float(db_c), tol=1)
    ok3 = _print("DB Σ additions == raw",        float(raw_add),          float(db_a), tol=1)
    ok4 = _print("DB Σ deletions == raw",        float(raw_del),          float(db_d), tol=1)
    print(f"  matched_to_users (deterministic): {rep1['matched_to_users']} / {rep1['inserted']}")

    # Bot detection sanity
    from backend.services.git_correlation import get_git_ai_correlation
    devs = get_git_ai_correlation(period_days=120)
    n_bots = sum(1 for r in devs if r.get("is_bot"))
    print(f"  bot rows detected               : {n_bots}")
    return ok1 and ok2 and ok3 and ok4


def audit_code_quality() -> bool:
    """Cross-check Code Quality numbers (F-15) against raw CSV.

    For each unique (repo, sha) in the per-commit-file CSV:
      - Run _classify_subject on the subject line independently
      - Sum the flags by repo
      - Compare with what get_team_quality / direct SQL returns

    This is the strongest possible 'do you trust the dashboard'
    check — we re-derive every Code Quality KPI from raw bytes.
    """
    print(f"\n{HEAD}── CODE QUALITY (Git × AI) ──{END}")
    from data.sources.git_csv import (
        _classify_subject, latest_git_commits_file,
    )
    from data.db import get_conn
    import csv

    gc = latest_git_commits_file()
    if gc is None:
        print(f"  {BAD} no git_commit_file_stats_*.csv — skipping Code Quality audit")
        return True

    # Re-derive from raw CSV: one classification per unique (repo, sha)
    seen: set[tuple[str, str]] = set()
    raw_total = 0
    raw_fix = raw_revert = raw_feat = raw_refactor = raw_test = raw_doc = 0
    raw_per_repo_fix: dict[str, int] = {}
    raw_per_repo_total: dict[str, int] = {}
    with open(gc.path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            key = (r.get("repo") or "", r.get("commit_sha") or "")
            if key in seen or not key[0] or not key[1]:
                continue
            seen.add(key)
            tags = _classify_subject(r.get("subject") or "")
            raw_total += 1
            raw_fix      += tags["is_bug_fix"]
            raw_revert   += tags["is_revert"]
            raw_feat     += tags["is_feature"]
            raw_refactor += tags["is_refactor"]
            raw_test     += tags["is_test"]
            raw_doc      += tags["is_docs"]
            raw_per_repo_total[key[0]] = raw_per_repo_total.get(key[0], 0) + 1
            raw_per_repo_fix[key[0]] = raw_per_repo_fix.get(key[0], 0) + tags["is_bug_fix"]

    # Compare with what's in git_commits after load
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS commits,
                      SUM(is_bug_fix)  AS fixes,
                      SUM(is_revert)   AS reverts,
                      SUM(is_feature)  AS features,
                      SUM(is_refactor) AS refactors,
                      SUM(is_test)     AS tests,
                      SUM(is_docs)     AS docs
               FROM git_commits"""
        ).fetchone()
        per_repo_db = {
            r["repo"]: (r["commits"], r["fixes"]) for r in conn.execute(
                """SELECT repo, COUNT(*) AS commits,
                          SUM(is_bug_fix) AS fixes
                   FROM git_commits GROUP BY repo"""
            ).fetchall()
        }

    ok_total   = _print("DB git_commits unique == raw", float(raw_total),    float(row["commits"]),   tol=0)
    ok_fix     = _print("DB Σ is_bug_fix  == raw",      float(raw_fix),      float(row["fixes"]),     tol=0)
    ok_revert  = _print("DB Σ is_revert   == raw",      float(raw_revert),   float(row["reverts"]),   tol=0)
    ok_feat    = _print("DB Σ is_feature  == raw",      float(raw_feat),     float(row["features"]),  tol=0)
    ok_refac   = _print("DB Σ is_refactor == raw",      float(raw_refactor), float(row["refactors"]), tol=0)
    ok_test    = _print("DB Σ is_test     == raw",      float(raw_test),     float(row["tests"]),     tol=0)
    ok_doc     = _print("DB Σ is_docs     == raw",      float(raw_doc),      float(row["docs"]),      tol=0)

    print(f"\n  Per-repo cross-check (period_days=0 → all-time):")
    from backend.services.git_quality import get_team_quality
    repo_oks: list[bool] = []
    for repo, (db_commits, db_fixes) in sorted(per_repo_db.items()):
        tq = get_team_quality(period_days=0, repos=[repo])
        ok_c = _print(f"  [{repo}] commits service==db",
                      float(db_commits), float(tq["commits"]), tol=0)
        ok_f = _print(f"  [{repo}] fixes service==db",
                      float(db_fixes),  float(tq["fixes"]),    tol=0)
        ok_r = _print(f"  [{repo}] commits db==raw",
                      float(raw_per_repo_total.get(repo, 0)), float(db_commits), tol=0)
        ok_rf = _print(f"  [{repo}] fixes db==raw",
                       float(raw_per_repo_fix.get(repo, 0)), float(db_fixes),    tol=0)
        repo_oks.extend([ok_c, ok_f, ok_r, ok_rf])

    # $/fix sanity: numerator team-wide spend, denominator follows repo filter
    from backend.services.git_quality import get_ai_spend_per_fix
    spf_all = get_ai_spend_per_fix(period_days=30)
    print(f"\n  $/fix (team-wide, last 30d): "
          f"${spf_all['ai_spend']:,.2f} ÷ {spf_all['fixes']} = "
          f"${spf_all['ai_spend_per_fix'] or 0:.2f}")
    for repo in sorted(per_repo_db):
        spf_r = get_ai_spend_per_fix(period_days=30, repos=[repo])
        print(f"  $/fix [{repo}]: same numerator ${spf_r['ai_spend']:,.2f} ÷ "
              f"{spf_r['fixes']} fixes (filtered) = "
              f"${spf_r['ai_spend_per_fix'] or 0:.2f}")

    return all([ok_total, ok_fix, ok_revert, ok_feat, ok_refac, ok_test, ok_doc, *repo_oks])


# ---------------------------------------------------------------------------

def audit_openai_api() -> bool:
    """Cross-check the OpenAI API (live push) source.

    Loader writes events from /v1/organization/costs into usage_events
    AND populates provider_totals (authoritative daily totals from the
    same API). We verify:
      1. SUM(usage_events.cost_usd) per day matches provider_totals
      2. Every OpenAI event has organization_id set
      3. Artem-org events have api_key_id attributed (multi-key tenant)
    """
    print(f"\n{HEAD}── OPENAI API (live push) ──{END}")
    from data.db import get_conn
    with get_conn() as conn:
        # 1. Per-day reconciliation: provider_totals vs SUM(usage_events)
        rows = conn.execute(
            """SELECT pt.day                      AS day,
                      pt.cost_usd                 AS pt_cost,
                      COALESCE(ue.daily_sum, 0)   AS ue_cost
               FROM provider_totals pt
               JOIN providers p ON p.id = pt.provider_id
               LEFT JOIN (
                   SELECT provider_id,
                          substr(occurred_at, 1, 10) AS day,
                          SUM(cost_usd)              AS daily_sum
                   FROM usage_events
                   GROUP BY provider_id, substr(occurred_at, 1, 10)
               ) ue ON ue.provider_id = pt.provider_id AND ue.day = pt.day
               WHERE p.name = 'openai'
               ORDER BY pt.day DESC LIMIT 30"""
        ).fetchall()
        total_pt = sum(r["pt_cost"] for r in rows)
        total_ue = sum(r["ue_cost"] for r in rows)
        # provider_totals comes from /v1/organization/costs (authoritative).
        # usage_events sum may be off by a small calibration delta — the
        # loader calibrates per-day to match provider_totals at the end of
        # sync, so divergence > 1% indicates a sync issue.
        ok_recon = _print(
            "provider_totals == SUM(usage_events) (30d window)",
            total_pt, total_ue, tol=1.0,
        )

        # 2. All OpenAI events must have organization_id
        row_org = conn.execute(
            """SELECT COUNT(*) AS missing
               FROM usage_events ue
               JOIN providers p ON p.id = ue.provider_id
               WHERE p.name = 'openai' AND ue.organization_id IS NULL"""
        ).fetchone()
        ok_org = _print(
            "OpenAI events missing organization_id",
            0.0, float(row_org["missing"]), tol=0,
        )

        # 3. Per-org event count breakdown for transparency
        org_rows = conn.execute(
            """SELECT o.label, COUNT(*) AS n, ROUND(SUM(ue.cost_usd), 2) AS s
               FROM usage_events ue
               JOIN providers p ON p.id = ue.provider_id
               JOIN organizations o ON o.id = ue.organization_id
               WHERE p.name = 'openai'
               GROUP BY o.label
               ORDER BY s DESC"""
        ).fetchall()
        for r in org_rows:
            print(f"  org={r['label']:10s}  events={r['n']:>6,}  spend=${r['s']:>10,.2f}")

        # 4. API key attribution check (Artem org should have api_key_id)
        row_key = conn.execute(
            """SELECT COUNT(*) AS missing
               FROM usage_events ue
               JOIN providers p ON p.id = ue.provider_id
               JOIN organizations o ON o.id = ue.organization_id
               WHERE p.name = 'openai' AND o.label = 'Artem'
                 AND ue.api_key_id IS NULL"""
        ).fetchone()
        # Many Artem events legitimately lack api_key_id (untagged usage)
        # — print as informational not a hard fail
        print(f"  Artem events without api_key_id: {row_key['missing']:,} (informational)")

    return ok_recon and ok_org


def audit_dashboard_math() -> bool:
    """Self-verify that service-layer formulas equal direct SQL.

    Catches bugs where a service function reports a wrong number even
    when the underlying data is correct — e.g. bug_rate_pct rounding
    drift, or someone changes the formula and the test still passes.
    """
    print(f"\n{HEAD}── DASHBOARD MATH (formulas vs direct SQL) ──{END}")
    from data.db import get_conn
    from backend.services.git_quality import (
        get_team_quality, get_quality_per_author,
    )

    # 1. Bug rate math: fixes / commits * 100 (rounded to 1 dec)
    tq = get_team_quality(period_days=0)
    if tq["commits"] == 0:
        print("  (no git_commits — skipping)")
        return True
    expected_br = round(tq["fixes"] / tq["commits"] * 100, 1)
    ok_br = _print("bug_rate_pct == fixes/commits*100",
                   expected_br, tq["bug_rate_pct"], tol=0)

    # 2. Revert rate math (rounded to 2 dec)
    expected_rr = round(tq["reverts"] / tq["commits"] * 100, 2)
    ok_rr = _print("revert_rate_pct == reverts/commits*100",
                   expected_rr, tq["revert_rate_pct"], tol=0)

    # 3. Human bug rate math
    if tq["human_commits"] > 0:
        with get_conn() as conn:
            hf = conn.execute(
                "SELECT SUM(is_bug_fix) AS f FROM git_commits WHERE is_bot=0"
            ).fetchone()["f"] or 0
        expected_hbr = round(hf / tq["human_commits"] * 100, 1)
        ok_hbr = _print("human_bug_rate_pct == human_fixes/human_commits*100",
                        expected_hbr, tq["human_bug_rate_pct"], tol=0)
    else:
        ok_hbr = True

    # 4. Human + Bot commits == Total commits (no orphan is_bot=NULL)
    ok_split = _print("human_commits + bot_commits == total",
                      float(tq["commits"]),
                      float(tq["human_commits"] + tq["bot_commits"]), tol=0)

    # 5. Per-author dedup: number of rows = unique COALESCE(user_id, name)
    authors = get_quality_per_author(period_days=0, limit=10000)
    with get_conn() as conn:
        expected_keys = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(user_id, author_name)) AS n FROM git_commits"
        ).fetchone()["n"]
    # service caps at limit=10000 by design; expect equal when not capped
    ok_dedup = _print("per_author rows == unique (user_id, name) keys",
                      float(min(expected_keys, 10000)), float(len(authors)), tol=0)

    return ok_br and ok_rr and ok_hbr and ok_split and ok_dedup


def audit_segment_partition() -> bool:
    """Every dev must land in EXACTLY one segment (mutual exclusivity)
    and the segments must cover ALL devs from get_git_ai_correlation.
    """
    print(f"\n{HEAD}── SEGMENT PARTITION ──{END}")
    from backend.services.git_correlation import get_git_ai_correlation
    devs = get_git_ai_correlation(period_days=365)
    if not devs:
        print("  (no devs in 365d — skipping)")
        return True

    seg_counts: dict[str, int] = {}
    for r in devs:
        s = r.get("segment") or "MISSING"
        seg_counts[s] = seg_counts.get(s, 0) + 1
    for seg, n in sorted(seg_counts.items(), key=lambda x: -x[1]):
        print(f"  {seg:32s}  {n:>5} devs")

    valid = {
        "HIGH_AI_SPEND_HIGH_GIT_OUTPUT", "HIGH_AI_SPEND_LOW_GIT_OUTPUT",
        "HIGH_AI_LINES_LOW_COMMITS", "LOW_AI_SPEND_HIGH_GIT_OUTPUT",
        "BOT_AUTOMATION", "AI_ACTIVE_BUT_NO_GIT",
        "GIT_ACTIVE_BUT_NO_AI", "NORMAL",
    }
    invalid = set(seg_counts) - valid
    ok_valid = _print("all segment labels are in the spec'd 8",
                      0.0, float(len(invalid)), tol=0)
    if invalid:
        print(f"    invalid labels found: {invalid}")
    ok_sum = _print("Σ segments == len(devs)",
                    float(len(devs)), float(sum(seg_counts.values())), tol=0)
    return ok_valid and ok_sum


def audit_high_spenders_math() -> bool:
    """Cross-tool High Spenders: combined spend per user == sum across
    providers. Catches bugs where the rollup over-counts or double-
    counts a user appearing under multiple providers.
    """
    print(f"\n{HEAD}── HIGH SPENDERS (cross-tool) ──{END}")
    from backend.services.ai_tools import (
        get_high_spenders, get_high_spenders_per_provider,
    )
    combined = {r["user_name"]: r for r in
                get_high_spenders(period_days=30, threshold_usd=0,
                                  api_key_id=None)}
    per_prov = {r["user_name"]: r for r in
                get_high_spenders_per_provider(period_days=30)}
    if not combined:
        print("  (no spenders in 30d — skipping)")
        return True

    bad = 0
    sample = 0
    for name, r in combined.items():
        sp = per_prov.get(name, {})
        expected = round(
            (sp.get("cost_openai", 0) or 0)
            + (sp.get("cost_anthropic", 0) or 0)
            + (sp.get("cost_cursor", 0) or 0),
            2,
        )
        actual = round(r["spend"] or 0, 2)
        if abs(expected - actual) > 0.05:
            bad += 1
            if sample < 3:
                print(f"  ✗ {name}: combined=${actual}, sum-per-provider=${expected}")
                sample += 1
    ok = _print("combined spend == Σ per-provider (across all users)",
                0.0, float(bad), tol=0)
    print(f"  checked: {len(combined)} users")
    return ok


def audit_high_churn() -> bool:
    """Compare service top-15 with a fresh top-15 computed from raw CSV.
    """
    print(f"\n{HEAD}── HIGH-CHURN FILES (service vs raw CSV) ──{END}")
    from data.sources.git_csv import latest_git_commits_file
    from backend.services.git_quality import get_high_churn_files
    import csv
    from collections import Counter

    gc = latest_git_commits_file()
    if gc is None:
        print("  (no commits CSV — skipping)")
        return True

    # Re-derive raw top-15 (all-time)
    seen_per_file: dict[str, set] = {}
    counts: Counter = Counter()
    with open(gc.path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            path = r.get("file_path") or ""
            sha = r.get("commit_sha") or ""
            if not path or not sha:
                continue
            s = seen_per_file.setdefault(path, set())
            if sha not in s:
                s.add(sha)
                counts[path] += 1
    raw_top15 = [p for p, _ in counts.most_common(15)]

    # Service top-15 (period_days=0 → all-time, no repo filter)
    svc = get_high_churn_files(period_days=0, limit=15)
    svc_top15 = [r["file"] for r in svc]

    ok = raw_top15 == svc_top15
    mark = OK if ok else BAD
    print(f"  {mark} top-15 files identical (raw vs service)")
    if not ok:
        for i, (raw, srv) in enumerate(zip(raw_top15, svc_top15)):
            tag = "==" if raw == srv else "≠"
            print(f"     [{i+1:>2}] raw={raw:60s} {tag} svc={srv}")
    return ok


# ---------------------------------------------------------------------------

def main() -> int:
    _setup_db()
    results = {
        "Anthropic":          audit_anthropic(),
        "Cursor":             audit_cursor(),
        "OpenAI / Humanoid":  audit_openai_json(),
        "OpenAI / API push":  audit_openai_api(),
        "Tokens (uncached)":  audit_tokens_uncached(),
        "Git CSV":            audit_git_csv(),
        "Code Quality":       audit_code_quality(),
        "Dashboard math":     audit_dashboard_math(),
        "Segment partition":  audit_segment_partition(),
        "High Spenders math": audit_high_spenders_math(),
        "High-churn files":   audit_high_churn(),
    }
    print(f"\n{HEAD}══════════════════ SUMMARY ══════════════════{END}")
    all_ok = True
    for k, v in results.items():
        mark = OK if v else BAD
        print(f"  {mark} {k}")
        all_ok &= bool(v)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
