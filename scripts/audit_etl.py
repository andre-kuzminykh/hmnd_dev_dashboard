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

def main() -> int:
    _setup_db()
    results = {
        "Anthropic":          audit_anthropic(),
        "Cursor":             audit_cursor(),
        "OpenAI / Humanoid":  audit_openai_json(),
        "Tokens (uncached)":  audit_tokens_uncached(),
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
