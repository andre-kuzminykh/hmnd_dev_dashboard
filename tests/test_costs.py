"""F-02 Costs by People — тесты по ID требований."""
from __future__ import annotations

from backend.analytics import Filters
from backend.services.costs import detect_spend_spikes, get_costs_by_user


def test_fr_02_1_1_1_user_costs_shape(tmp_db):
    rows = get_costs_by_user(Filters(period_days=14))
    assert rows
    sample = rows[0]
    expected = {
        "user_id", "user_name", "team", "cost_openai", "cost_anthropic",
        "tokens_in", "tokens_out", "models", "last_activity", "limit_status",
    }
    assert expected.issubset(sample.keys())
    # sorted desc по сумме
    totals = [r["cost_openai"] + r["cost_anthropic"] for r in rows]
    assert totals == sorted(totals, reverse=True)


def test_fr_02_1_1_2_limit_status(tmp_db):
    from backend.services.costs import _limit_status

    assert _limit_status(0, 100) == "ok"
    assert _limit_status(50, 100) == "ok"
    assert _limit_status(80, 100) == "warn"
    assert _limit_status(99, 100) == "warn"
    assert _limit_status(101, 100) == "breach"
    # пограничные
    assert _limit_status(0, 0) == "ok"


def test_fr_02_1_2_1_spike_detection(tmp_db):
    """Seed создаёт спайк у Ivan — должен быть детектирован."""
    spikes = detect_spend_spikes()
    assert spikes, "spike on Ivan must be detected"
    # все спайки имеют ratio > 3 либо avg=0
    for s in spikes:
        assert s["today_cost"] > 20
        assert (s["ratio"] >= 3.0) or (s["avg_cost"] == 0.0)
