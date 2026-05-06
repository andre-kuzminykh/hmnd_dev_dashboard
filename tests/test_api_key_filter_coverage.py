"""Coverage test: every analytical service must honour Filters.api_key_id.

Failing this test means somewhere in a service we forgot to add
api_key_clause(...) — the API key dropdown silently does nothing on the
corresponding page.

Strategy: build a tiny fixture (1 user, 2 distinct api_keys both with usage
events for the same model on the same day, different costs) and verify
that filtering by each api_key returns DIFFERENT results.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from backend.analytics import Filters
from data.db import get_conn


@pytest.fixture()
def two_keys(tmp_db) -> tuple[int, int, int]:
    """Returns (user_id, key_a_id, key_b_id) with distinct usage events."""
    with get_conn() as conn:
        user_id = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
        provider_id = conn.execute(
            "SELECT id FROM providers WHERE name = 'openai'"
        ).fetchone()["id"]
        model_id = conn.execute(
            "SELECT id FROM models WHERE provider_id = ? LIMIT 1", (provider_id,)
        ).fetchone()["id"]
        key_a = conn.execute(
            """INSERT INTO api_keys(provider_id, external_id, name, redacted_value,
                                    owner_user_id, is_admin)
               VALUES(?, 'key_A', 'KEY_A', 'sk-...A', ?, 0)""",
            (provider_id, user_id),
        ).lastrowid
        key_b = conn.execute(
            """INSERT INTO api_keys(provider_id, external_id, name, redacted_value,
                                    owner_user_id, is_admin)
               VALUES(?, 'key_B', 'KEY_B', 'sk-...B', ?, 0)""",
            (provider_id, user_id),
        ).lastrowid
        # Tag distinct usage on each key. Different days so daily_costs has
        # a clean per-key footprint.
        conn.executemany(
            """INSERT INTO usage_events(user_id, provider_id, model_id, api_key_id,
                                         occurred_at, tokens_in, tokens_out, tokens_cached,
                                         cost_usd, latency_ms, is_error, purpose)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (user_id, provider_id, model_id, key_a,
                 datetime.utcnow().strftime("%Y-%m-%d 10:00:00"),
                 5000, 1000, 0, 7.50, 100, 0, "API"),
                (user_id, provider_id, model_id, key_b,
                 datetime.utcnow().strftime("%Y-%m-%d 11:00:00"),
                 1000, 200, 0, 1.25, 80, 0, "API"),
            ],
        )
        conn.commit()
    return user_id, key_a, key_b


def _filters_for(key_id: int | None, days: int = 14) -> Filters:
    return Filters(period_days=days, api_key_id=key_id)


def _spend_for(rows: list[dict[str, Any]], key_field: str = "cost_total") -> float:
    return sum(r[key_field] for r in rows)


# ---- F-01 Overview ----

def test_overview_kpis_filter_by_api_key(two_keys):
    from backend.services.overview import get_overview_kpis
    _, a, b = two_keys
    only_a = get_overview_kpis(_filters_for(a))
    only_b = get_overview_kpis(_filters_for(b))
    no_filter = get_overview_kpis(_filters_for(None))
    assert only_a["total_spend"] != only_b["total_spend"], (
        "Overview total_spend doesn't change when api_key_id filter switches — "
        "_kpis_in_window is missing api_key_clause"
    )
    assert only_a["total_spend"] + only_b["total_spend"] <= no_filter["total_spend"] + 1e-3


def test_overview_daily_series_filter_by_api_key(two_keys):
    from backend.services.overview import get_daily_spend_series
    _, a, b = two_keys
    only_a = sum(r["cost"] for r in get_daily_spend_series(_filters_for(a)))
    only_b = sum(r["cost"] for r in get_daily_spend_series(_filters_for(b)))
    assert only_a != only_b


# ---- F-02 Costs by People ----

def test_costs_by_user_filter_by_api_key(two_keys):
    from backend.services.costs import get_costs_by_user
    _, a, b = two_keys
    only_a = _spend_for(get_costs_by_user(_filters_for(a)))
    only_b = _spend_for(get_costs_by_user(_filters_for(b)))
    assert only_a != only_b


# ---- F-04 Developer Usage ----

def test_developer_usage_filter_by_api_key(two_keys):
    from backend.services.developers import get_developer_usage
    _, a, b = two_keys
    cost_a = sum(r["cost"] for r in get_developer_usage(_filters_for(a)))
    cost_b = sum(r["cost"] for r in get_developer_usage(_filters_for(b)))
    assert cost_a != cost_b


# ---- F-07 Models ----

def test_models_breakdown_filter_by_api_key(two_keys):
    from backend.services.models_svc import get_models_breakdown
    _, a, b = two_keys
    cost_a = sum(r["cost"] for r in get_models_breakdown(_filters_for(a)))
    cost_b = sum(r["cost"] for r in get_models_breakdown(_filters_for(b)))
    assert cost_a != cost_b


# ---- F-12 AI Tools ----

def test_ai_tools_users_for_provider_filter_by_api_key(two_keys):
    from backend.services.ai_tools import get_users_for_provider
    _, a, b = two_keys
    cost_a = sum(r["cost"] for r in get_users_for_provider("openai", api_key_id=a))
    cost_b = sum(r["cost"] for r in get_users_for_provider("openai", api_key_id=b))
    assert cost_a != cost_b


def test_ai_tools_high_spenders_filter_by_api_key(two_keys):
    from backend.services.ai_tools import get_high_spenders
    _, a, b = two_keys
    spend_a = sum(r["spend"] for r in get_high_spenders(threshold_usd=0, api_key_id=a))
    spend_b = sum(r["spend"] for r in get_high_spenders(threshold_usd=0, api_key_id=b))
    assert spend_a != spend_b
