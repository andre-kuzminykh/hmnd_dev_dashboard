"""F-19 — Top Spenders & Usage Summary respect Source + Date filters.

Tests per SPEC.md §F-19:
  T-SVC-19.1  provider='all' → cross-tool ranking matches SUM(cost_usd) per user
  T-SVC-19.2  provider='anthropic' → only Anthropic rows; users w/ 0 anthropic excluded
  T-SVC-19.3  provider='openai' + organization='Artem' → both filters compose
  T-SVC-19.4  date_from/date_to override period_days
  T-SVC-19.5  Back-compat — no-kwargs call still returns cross-tool ranking
"""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.services.ai_tools import get_high_spenders


def _window_iso(period_days: int = 365):
    end = datetime.utcnow()
    start = end - timedelta(days=period_days)
    return (start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"))


def _all_spend_by_user(period_days: int = 365) -> dict:
    """Helper — SUM(cost_usd) GROUP BY user in the same window the service
    uses. Must mirror the service-side WHERE clause exactly (no extra JOIN)."""
    from data.db import get_conn
    s, e = _window_iso(period_days)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT u.full_name AS name, ROUND(SUM(ue.cost_usd), 2) AS s "
            "FROM usage_events ue JOIN users u ON u.id = ue.user_id "
            "WHERE ue.occurred_at BETWEEN ? AND ? "
            "GROUP BY u.id "
            "HAVING s > 0",
            (s, e),
        ).fetchall()
    return {r["name"]: r["s"] for r in rows}


def _spend_by_user_for_provider(provider, period_days: int = 365) -> dict:
    from data.db import get_conn
    s, e = _window_iso(period_days)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT u.full_name AS name, ROUND(SUM(ue.cost_usd), 2) AS s "
            "FROM usage_events ue "
            "JOIN users u ON u.id = ue.user_id "
            "JOIN providers p ON p.id = ue.provider_id "
            "WHERE p.name = ? AND ue.occurred_at BETWEEN ? AND ? "
            "GROUP BY u.id "
            "HAVING s > 0",
            (provider, s, e),
        ).fetchall()
    return {r["name"]: r["s"] for r in rows}


# ──────────────────────────────────────────────────────────────────────
# T-SVC-19.1 — provider='all' regression
# ──────────────────────────────────────────────────────────────────────

def test_t_svc_19_1_provider_all_matches_cross_tool_sum(tmp_db):
    """provider='all' must reproduce the pre-F-19 cross-tool ranking."""
    rows = get_high_spenders(period_days=365, threshold_usd=0, provider="all")
    assert rows
    by_name = {r["user_name"]: r["spend"] for r in rows}
    truth = _all_spend_by_user(period_days=365)
    # Every name returned must match cross-tool truth
    for name, spend in by_name.items():
        # Rounding can drift by a few cents because the service does
        # ROUND() on the per-user SUM while truth does the same; allow tol.
        assert abs(spend - truth[name]) < 0.05, (name, spend, truth[name])


# ──────────────────────────────────────────────────────────────────────
# T-SVC-19.2 — provider='anthropic'
# ──────────────────────────────────────────────────────────────────────

def test_t_svc_19_2_provider_anthropic_narrows_and_excludes_zero(tmp_db):
    """provider='anthropic' returns only Anthropic spend; users with $0
    Anthropic are excluded by HAVING."""
    rows = get_high_spenders(period_days=365, threshold_usd=0, provider="anthropic")
    truth = _spend_by_user_for_provider("anthropic", period_days=365)
    assert rows, "no Anthropic spenders found — fixture likely empty"
    for r in rows:
        assert r["user_name"] in truth, f"unexpected user {r['user_name']}"
        assert abs(r["spend"] - truth[r["user_name"]]) < 0.05
        assert r["spend"] > 0, f"zero-spend row leaked through: {r}"
    # Users with $0 Anthropic must NOT appear
    returned_names = {r["user_name"] for r in rows}
    cross = _all_spend_by_user(period_days=365)
    pure_non_anthropic = {n for n, s in cross.items()
                          if s > 0 and truth.get(n, 0) == 0}
    assert returned_names.isdisjoint(pure_non_anthropic), (
        f"users with $0 anthropic leaked: {returned_names & pure_non_anthropic}"
    )


# ──────────────────────────────────────────────────────────────────────
# T-SVC-19.3 — provider + organization composition
# ──────────────────────────────────────────────────────────────────────

def test_t_svc_19_3_provider_openai_plus_organization(tmp_db):
    """OpenAI scope + Artem organization narrows further."""
    rows_all_openai = get_high_spenders(period_days=365, threshold_usd=0,
                                        provider="openai")
    rows_artem = get_high_spenders(period_days=365, threshold_usd=0,
                                   provider="openai", organization="Artem")
    # Artem subset must be ≤ full OpenAI scope.
    sum_artem = sum(r["spend"] for r in rows_artem)
    sum_all_openai = sum(r["spend"] for r in rows_all_openai)
    assert sum_artem <= sum_all_openai + 0.01


# ──────────────────────────────────────────────────────────────────────
# T-SVC-19.4 — date window override
# ──────────────────────────────────────────────────────────────────────

def test_t_svc_19_4_date_from_date_to_overrides_period_days(tmp_db):
    """When date_from/date_to are passed, window is verbatim (no period_days offset)."""
    # Pick a 2-day window in the middle of the 14-day fixture.
    from data.db import get_conn
    with get_conn() as conn:
        meta = conn.execute(
            "SELECT MIN(occurred_at) AS lo, MAX(occurred_at) AS hi FROM usage_events"
        ).fetchone()
    lo = datetime.fromisoformat(meta["lo"])
    hi = datetime.fromisoformat(meta["hi"])
    mid = lo + (hi - lo) / 2
    window_from = mid - timedelta(days=1)
    window_to = mid + timedelta(days=1)

    rows = get_high_spenders(
        period_days=999,            # ignored when date_from/date_to set
        threshold_usd=0,
        date_from=window_from,
        date_to=window_to,
    )
    # All returned spend must be within the window in DB.
    with get_conn() as conn:
        truth = conn.execute(
            "SELECT u.full_name AS n, ROUND(SUM(ue.cost_usd),2) AS s "
            "FROM usage_events ue JOIN users u ON u.id=ue.user_id "
            "WHERE ue.occurred_at BETWEEN ? AND ? "
            "GROUP BY u.id",
            (window_from.strftime("%Y-%m-%d %H:%M:%S"),
             window_to.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchall()
    truth_map = {r["n"]: r["s"] for r in truth}
    for r in rows:
        assert abs(r["spend"] - truth_map[r["user_name"]]) < 0.01


# ──────────────────────────────────────────────────────────────────────
# T-SVC-19.5 — back-compat
# ──────────────────────────────────────────────────────────────────────

def test_t_svc_19_5_no_kwargs_back_compat(tmp_db):
    """Caller without provider/org kwargs (alerts.py, snapshot_dashboard.py)
    keeps the original cross-tool behaviour."""
    rows_no_kwargs = get_high_spenders(period_days=365, threshold_usd=0)
    rows_all = get_high_spenders(period_days=365, threshold_usd=0, provider="all")
    assert {r["user_name"]: r["spend"] for r in rows_no_kwargs} == \
           {r["user_name"]: r["spend"] for r in rows_all}
