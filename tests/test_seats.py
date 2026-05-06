"""F-03 Seats — тесты."""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.services.seats import (
    _recommendation, get_seats_summary, get_seats_table,
)


def test_fr_03_1_1_1_summary_keys(tmp_db):
    s = get_seats_summary()
    assert {"bought", "assigned", "active_30d", "inactive_paid", "potential_waste_usd"} == set(s)
    assert s["bought"] >= s["assigned"] >= s["active_30d"]
    assert s["inactive_paid"] >= 0


def test_fr_03_1_1_4_recommendation():
    now = datetime(2026, 5, 6, 12, 0, 0)
    assert _recommendation(None, now) == "revoke"
    assert _recommendation((now - timedelta(days=2)).isoformat(), now) == "keep"
    assert _recommendation((now - timedelta(days=20)).isoformat(), now) == "review"
    assert _recommendation((now - timedelta(days=40)).isoformat(), now) == "revoke"


def test_seats_table_has_all_fields(tmp_db):
    rows = get_seats_table()
    assert rows
    expected = {
        "id", "user_name", "seat_type", "provider", "assigned",
        "last_used_at", "monthly_cost_usd", "usage_30d", "recommendation",
    }
    assert expected.issubset(rows[0].keys())
