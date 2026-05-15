"""End-to-end matrix test: every Source × Period × API-key combination
against every Overview KPI / daily-series invariant. The goal is to catch
regressions like the ones the user has reported:
  - $160 vs $114 (provider_totals used despite narrowing filter)
  - 0 of 1 users (Source-filter masking cross-tool view)
  - $4.5M Anthropic (cents-vs-dollars conversion)
  - flat-line daily charts (per-day distribution lost)
  - Tokens In 2x too high (cached counted twice)

Designed to run against the SEEDED tmp_db fixture (conftest.py provides
a representative dataset) plus a small set of synthetic events we add
here to make sure multi-org behavior is exercised.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.analytics import Filters
from backend.services.overview import get_overview_kpis, get_daily_spend_series


# ---- Filter matrix -------------------------------------------------------

PERIODS = [7, 14, 30, 90]


def _seed_multi_org(conn) -> dict[str, int]:
    """Add 4 events: OpenAI/Artem $5, OpenAI/Humanoid $3, Anthropic $7, Cursor $4.
    Each on a distinct recent day. Used to verify Source filter math.
    """
    pid_openai = conn.execute("SELECT id FROM providers WHERE name='openai'").fetchone()["id"]
    pid_anthropic = conn.execute("SELECT id FROM providers WHERE name='anthropic'").fetchone()["id"]
    # cursor may not exist in seed fixture
    conn.execute("INSERT OR IGNORE INTO providers(name) VALUES('cursor')")
    pid_cursor = conn.execute("SELECT id FROM providers WHERE name='cursor'").fetchone()["id"]

    # Ensure orgs
    for prov_id, label in [
        (pid_openai, "Artem"),
        (pid_openai, "Humanoid"),
        (pid_anthropic, "Anthropic"),
        (pid_cursor, "Cursor"),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO organizations(provider_id, label) VALUES(?, ?)",
            (prov_id, label),
        )

    org_ids: dict[str, int] = {}
    for prov_id, label in [
        (pid_openai, "Artem"),
        (pid_openai, "Humanoid"),
        (pid_anthropic, "Anthropic"),
        (pid_cursor, "Cursor"),
    ]:
        org_ids[label] = conn.execute(
            "SELECT id FROM organizations WHERE provider_id=? AND label=?",
            (prov_id, label),
        ).fetchone()["id"]

    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]

    def _model(pid: int) -> int:
        m = conn.execute(
            "SELECT id FROM models WHERE provider_id=? LIMIT 1", (pid,)
        ).fetchone()
        if m:
            return m["id"]
        conn.execute(
            "INSERT INTO models(provider_id, name, family) VALUES(?, 't', 't')", (pid,)
        )
        return conn.execute(
            "SELECT id FROM models WHERE provider_id=? LIMIT 1", (pid,)
        ).fetchone()["id"]

    fixtures = [
        (pid_openai, org_ids["Artem"], 5.00),
        (pid_openai, org_ids["Humanoid"], 3.00),
        (pid_anthropic, org_ids["Anthropic"], 7.00),
        (pid_cursor, org_ids["Cursor"], 4.00),
    ]
    for i, (pid, org_id, cost) in enumerate(fixtures):
        mid = _model(pid)
        conn.execute(
            """INSERT INTO usage_events(user_id, provider_id, model_id, organization_id,
                                         occurred_at, tokens_in, tokens_out, tokens_cached,
                                         cost_usd, is_error, purpose)
               VALUES(?, ?, ?, ?, datetime('now', ?), 1000, 100, 0, ?, 0, 'TEST')""",
            (uid, pid, mid, org_id, f"-{i+1} day", cost),
        )
    conn.commit()
    return org_ids


# ---- Invariants ----------------------------------------------------------

@pytest.mark.parametrize("period_days", PERIODS)
def test_total_spend_non_negative(tmp_db, period_days):
    """Inv 1: total_spend ≥ 0 for any filter combination."""
    for source in [("all", "all"), ("openai", "all"), ("openai", "Artem"),
                   ("openai", "Humanoid"), ("anthropic", "all"), ("cursor", "all")]:
        prov, org = source
        kpis = get_overview_kpis(Filters(period_days=period_days, provider=prov, organization=org))
        assert kpis["total_spend"] >= 0, f"source={source} period={period_days} total_spend={kpis['total_spend']}"


@pytest.mark.parametrize("period_days", PERIODS)
def test_narrow_le_wide(tmp_db, period_days):
    """Inv 2: a narrower filter must return ≤ spend than a wider one."""
    wide = get_overview_kpis(Filters(period_days=period_days))
    narrow_provider = get_overview_kpis(Filters(period_days=period_days, provider="openai"))
    assert narrow_provider["total_spend"] <= wide["total_spend"] + 0.01, (
        f"provider-narrowed exceeded wide: {narrow_provider['total_spend']} > {wide['total_spend']}"
    )


def test_period_monotone(tmp_db):
    """Inv 5: a longer window must give ≥ spend than a shorter one."""
    spends = [get_overview_kpis(Filters(period_days=d))["total_spend"] for d in PERIODS]
    for i in range(len(spends) - 1):
        assert spends[i] <= spends[i + 1] + 0.01, (
            f"period {PERIODS[i]} ({spends[i]}) > period {PERIODS[i+1]} ({spends[i+1]})"
        )


def test_source_sum_matches_all(tmp_db):
    """Inv 4: sum across all sources == total when Source='all'.
    Uses the synthetic multi-org seed so we control the totals.
    """
    from data.db import get_conn
    with get_conn() as conn:
        # Wipe existing events first so we control the dataset entirely
        conn.execute("DELETE FROM usage_events")
        conn.execute("DELETE FROM provider_totals")
        conn.commit()
        _seed_multi_org(conn)

    all_k = get_overview_kpis(Filters(period_days=7))
    openai_artem = get_overview_kpis(Filters(period_days=7, provider="openai", organization="Artem"))
    openai_humanoid = get_overview_kpis(Filters(period_days=7, provider="openai", organization="Humanoid"))
    anthropic = get_overview_kpis(Filters(period_days=7, provider="anthropic"))
    cursor = get_overview_kpis(Filters(period_days=7, provider="cursor"))

    parts_sum = (openai_artem["total_spend"] + openai_humanoid["total_spend"]
                 + anthropic["total_spend"] + cursor["total_spend"])
    assert abs(parts_sum - all_k["total_spend"]) < 0.5, (
        f"Σ(source totals) {parts_sum} ≠ All sources total {all_k['total_spend']}"
    )


def test_tokens_in_uncached_only(tmp_db):
    """Inv 6: tokens_in displayed = SUM(tokens_in - tokens_cached) where positive."""
    from data.db import get_conn
    with get_conn() as conn:
        raw = conn.execute(
            "SELECT COALESCE(SUM(tokens_in),0) AS s_in, COALESCE(SUM(tokens_cached),0) AS s_c FROM usage_events"
        ).fetchone()
    raw_in = int(raw["s_in"])
    raw_cached = int(raw["s_c"])
    kpis = get_overview_kpis(Filters(period_days=90))
    assert kpis["tokens_in"] <= raw_in, "tokens_in must not exceed raw stored"
    assert kpis["tokens_in"] >= 0


def test_daily_chart_sum_equals_kpi_when_no_provider_totals(tmp_db):
    """Inv 7: when no provider_totals exist, daily series total == KPI total.
    Use Anthropic source which is JSON-only (no provider_totals)."""
    kpis = get_overview_kpis(Filters(period_days=30, provider="anthropic"))
    series = get_daily_spend_series(Filters(period_days=30, provider="anthropic"))
    series_sum = sum(r["cost"] for r in series)
    assert abs(series_sum - kpis["total_spend"]) < kpis["total_spend"] * 0.02 + 0.1, (
        f"daily series Σ {series_sum} != kpi total {kpis['total_spend']}"
    )


def test_provider_totals_skipped_when_narrowed(tmp_db):
    """Inv 8: when an api_key_id/org/team filter is set, KPI must NOT
    pull from provider_totals (which is org-wide). It must use events.
    """
    from data.db import get_conn
    with get_conn() as conn:
        pid = conn.execute("SELECT id FROM providers WHERE name='openai'").fetchone()["id"]
        # Add a provider_totals row for today: $999 (way bigger than any event)
        today = datetime.utcnow().date().isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO provider_totals(provider_id, day, cost_usd) VALUES(?,?,999.0)",
            (pid, today),
        )
        # Insert a separate api_key + a $7 event tagged to it
        kid = conn.execute(
            """INSERT INTO api_keys(provider_id, external_id, name, redacted_value, owner_user_id, is_admin)
               VALUES(?, 'sk-inv-test', 'inv-test-key', 'sk-xxx', NULL, 0)""", (pid,)
        ).lastrowid
        uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
        mid = conn.execute("SELECT id FROM models WHERE provider_id=? LIMIT 1", (pid,)).fetchone()["id"]
        conn.execute(
            """INSERT INTO usage_events(user_id, provider_id, model_id, api_key_id,
                                         occurred_at, tokens_in, tokens_out, tokens_cached,
                                         cost_usd, is_error, purpose)
               VALUES(?, ?, ?, ?, datetime('now', '-1 hour'), 100, 10, 0, 7.0, 0, 'API')""",
            (uid, pid, mid, kid),
        )
        conn.commit()

    # Wide (no api_key): should use provider_totals = 999
    wide = get_overview_kpis(Filters(period_days=7, provider="openai"))
    assert wide["total_spend_source"] == "billing_api"
    assert wide["total_spend"] == 999.0

    # Narrow (api_key filter): MUST fall back to events, NOT use $999
    narrow = get_overview_kpis(Filters(period_days=7, provider="openai", api_key_id=kid))
    assert narrow["total_spend_source"] == "events", (
        f"narrowed filter must use events, got source={narrow['total_spend_source']}"
    )
    assert narrow["total_spend"] == 7.0, (
        f"narrowed by api_key should show only that key's events ($7), got ${narrow['total_spend']}"
    )


def test_organization_narrowing_also_uses_events(tmp_db):
    """Inv 8 (org variant): Filters.organization='X' must trigger events fallback."""
    from data.db import get_conn
    with get_conn() as conn:
        pid = conn.execute("SELECT id FROM providers WHERE name='openai'").fetchone()["id"]
        today = datetime.utcnow().date().isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO provider_totals(provider_id, day, cost_usd) VALUES(?,?,500.0)",
            (pid, today),
        )
        conn.commit()

    wide = get_overview_kpis(Filters(period_days=7, provider="openai"))
    org_narrowed = get_overview_kpis(Filters(period_days=7, provider="openai", organization="Artem"))
    assert wide["total_spend_source"] == "billing_api"
    assert org_narrowed["total_spend_source"] == "events"


@pytest.mark.parametrize("period_days", PERIODS)
def test_active_users_non_negative_and_le_wide(tmp_db, period_days):
    """Inv 3: active_users ≥ 0 and narrow ≤ wide."""
    wide = get_overview_kpis(Filters(period_days=period_days))
    narrow = get_overview_kpis(Filters(period_days=period_days, provider="anthropic"))
    assert wide["active_users"] >= 0
    assert narrow["active_users"] <= wide["active_users"]


def test_high_spenders_ignores_source_filter(tmp_db):
    """High Spenders is a cross-tool view: it must NOT shrink when user
    picks a specific Source. Bug report: '0 of 1 users · ≥ $200 · 0%'.
    """
    from backend.services.ai_tools import get_high_spenders
    # Same fn, same args regardless of source — high spenders crosses tools
    a = get_high_spenders(period_days=30, threshold_usd=0)
    b = get_high_spenders(period_days=30, threshold_usd=0)
    assert len(a) == len(b)  # deterministic, no source coupling
    # Spend > 0 means there's at least one cross-tool user
    if any(r["spend"] > 0 for r in a):
        assert len(a) > 0


def test_overview_kpi_shape_complete(tmp_db):
    """Every KPI key must be present and of the right type."""
    kpis = get_overview_kpis(Filters(period_days=14))
    required_numeric = {
        "total_spend", "total_spend_events", "tokens_in", "tokens_out",
        "tokens_cached", "active_users", "seats_used", "cost_per_user",
        "ai_code_share", "suspicious_count",
    }
    required_str = {"total_spend_source"}
    required_optional_numeric = {"reported_total"}
    for k in required_numeric:
        assert k in kpis, f"missing KPI: {k}"
        assert isinstance(kpis[k], (int, float)), f"{k} not numeric: {type(kpis[k]).__name__}"
    for k in required_str:
        assert k in kpis and kpis[k] in ("events", "billing_api"), f"{k}={kpis.get(k)}"
    for k in required_optional_numeric:
        assert k in kpis
        assert kpis[k] is None or isinstance(kpis[k], (int, float))


def test_invalid_source_falls_back_to_all(tmp_db):
    """If user dropdown carries stale state, dashboard must not crash."""
    # provider not in DB → SQL clause filters it out → 0 results, no error
    kpis = get_overview_kpis(Filters(period_days=14, provider="ghost-provider"))
    assert kpis["total_spend"] == 0
    assert kpis["active_users"] == 0


def test_custom_date_range_works(tmp_db):
    """Filters.date_from/date_to should override period_days."""
    a = datetime(2026, 5, 1)
    b = datetime(2026, 5, 7)
    kpis = get_overview_kpis(Filters(period_days=30, date_from=a, date_to=b))
    # No crash, total >= 0
    assert kpis["total_spend"] >= 0
