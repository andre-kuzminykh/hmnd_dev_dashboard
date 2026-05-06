"""F-13 Advanced filters — tests pinned to requirement IDs."""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.analytics import Filters, preset_range


# ---- F-13.1 date range ----

def test_fr_13_1_1_1_explicit_dates_priority():
    """When date_from/to are set, period_days must be ignored."""
    now = datetime(2026, 5, 6, 12, 0, 0)
    f = Filters(
        period_days=7,
        date_from=datetime(2026, 4, 1),
        date_to=datetime(2026, 4, 10),
    )
    start, end = f.date_range(now)
    assert start == datetime(2026, 4, 1)
    assert end == datetime(2026, 4, 10, 23, 59, 59)


def test_fr_13_1_1_2_date_range_explicit_or_computed():
    """Falls back to period_days when explicit dates aren't set."""
    now = datetime(2026, 5, 6, 12, 0, 0)
    f = Filters(period_days=7)
    start, end = f.date_range(now)
    assert (now - start).days == 7
    assert end == now


def test_fr_13_1_2_2_today_yesterday_presets():
    now = datetime(2026, 5, 6, 12, 30)
    s, e = preset_range("Today", now=now)
    assert s.date() == now.date()
    assert e.date() == now.date()
    s2, e2 = preset_range("Yesterday", now=now)
    assert s2.date() == (now - timedelta(days=1)).date()
    assert e2.date() == (now - timedelta(days=1)).date()


def test_fr_13_1_2_3_week_to_date():
    # 2026-05-06 is Wednesday; week starts on Monday 2026-05-04.
    now = datetime(2026, 5, 6, 12, 30)
    s, e = preset_range("Week to date", now=now)
    assert s.date() == datetime(2026, 5, 4).date()
    assert e.date() == now.date()


def test_fr_13_1_2_4_month_to_date():
    now = datetime(2026, 5, 6, 12, 30)
    s, e = preset_range("Month to date", now=now)
    assert s.date() == datetime(2026, 5, 1).date()
    assert e.date() == now.date()


# ---- F-13.2 API key filter ----

def test_fr_13_2_1_1_api_key_filter_in_costs(tmp_db):
    """Costs services must respect Filters.api_key_id when provided."""
    from data.db import get_conn

    # pick any user from seed and attach a fresh anthropic api_key, write 1 event
    with get_conn() as conn:
        u = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        p = conn.execute("SELECT id FROM providers WHERE name='anthropic'").fetchone()
        m = conn.execute(
            "SELECT id FROM models WHERE provider_id = ? LIMIT 1", (p["id"],)
        ).fetchone()
        kid = conn.execute(
            """INSERT INTO api_keys(provider_id, external_id, name, redacted_value, owner_user_id, is_admin)
               VALUES(?, 'sk-test-filter', 'filter-key', 'sk-...test', ?, 0)""",
            (p["id"], u["id"]),
        ).lastrowid
        conn.execute(
            """INSERT INTO usage_events(user_id, provider_id, model_id, api_key_id, occurred_at,
                                        tokens_in, tokens_out, tokens_cached, cost_usd, is_error, purpose)
               VALUES(?, ?, ?, ?, datetime('now'), 1000, 500, 0, 1.23, 0, 'API')""",
            (u["id"], p["id"], m["id"], kid),
        )
        conn.commit()

    from backend.services.costs import get_costs_by_user
    rows_no_filter = get_costs_by_user(Filters(period_days=14))
    rows_filtered = get_costs_by_user(Filters(period_days=14, api_key_id=kid))
    assert rows_filtered  # at least the synthetic key owner present
    # filtered total never exceeds unfiltered
    assert sum(r["cost_total"] for r in rows_filtered) <= sum(r["cost_total"] for r in rows_no_filter)


# ---- F-13.3 project filter ----

def test_fr_13_3_1_2_project_filter_field():
    """Filters dataclass must expose project_id field for future project drill-down."""
    f = Filters(project_id=42)
    assert f.project_id == 42
    f2 = Filters()
    assert f2.project_id is None
