"""F-07 Models."""
from __future__ import annotations

from backend.services.models_svc import get_models_breakdown
from backend.analytics import Filters


def test_fr_07_1_1_2_error_rate(tmp_db):
    rows = get_models_breakdown(Filters(period_days=14))
    assert rows
    for r in rows:
        if r["requests"] == 0:
            assert r["error_rate"] is None
        else:
            assert 0 <= r["error_rate"] <= 100


def test_models_sorted_desc(tmp_db):
    rows = get_models_breakdown(Filters(period_days=14))
    costs = [r["cost"] for r in rows]
    assert costs == sorted(costs, reverse=True)


def test_main_users_top_3(tmp_db):
    rows = get_models_breakdown(Filters(period_days=14))
    for r in rows:
        assert len(r["main_users"]) <= 3
