"""F-01 Executive Overview — тесты по ID требований."""
from __future__ import annotations

import time

from backend.analytics import Filters
from backend.services.overview import get_overview_kpis


REQUIRED_KEYS = {
    "total_spend", "tokens_in", "tokens_out", "active_users",
    "seats_used", "cost_per_user", "ai_code_share", "suspicious_count",
}


def test_fr_01_1_1_1_kpi_keys(tmp_db):
    kpis = get_overview_kpis(Filters(period_days=14))
    assert REQUIRED_KEYS.issubset(kpis.keys())
    for k in REQUIRED_KEYS:
        assert isinstance(kpis[k], (int, float))


def test_fr_01_1_1_2_zero_users(tmp_db, monkeypatch):
    """cost_per_user не должен делиться на ноль."""
    from backend.services import overview as ov

    def _empty(*_a, **_kw):
        return {"total_spend": 0, "tokens_in": 0, "tokens_out": 0, "active_users": 0}

    monkeypatch.setattr(ov, "_kpis_in_window", _empty)
    monkeypatch.setattr(ov, "_seats_used", lambda *_a, **_kw: 0)
    monkeypatch.setattr(ov, "_ai_code_share", lambda *_a, **_kw: 0.0)
    monkeypatch.setattr(ov, "_suspicious_count", lambda *_a, **_kw: 0)

    kpis = ov.get_overview_kpis(Filters(period_days=7))
    assert kpis["cost_per_user"] == 0.0


def test_fr_01_1_1_3_delta_calc(tmp_db):
    kpis = get_overview_kpis(Filters(period_days=7))
    # delta_pct присутствует для всех числовых KPI
    for k in ["total_spend", "tokens_in", "tokens_out", "active_users", "cost_per_user", "ai_code_share"]:
        assert f"{k}_delta" in kpis
        assert isinstance(kpis[f"{k}_delta"], (int, float))


def test_nfr_01_1_1_1_perf(tmp_db):
    """KPI-расчёт по 14d seed-данных должен быть быстрым."""
    start = time.perf_counter()
    get_overview_kpis(Filters(period_days=14))
    elapsed = time.perf_counter() - start
    assert elapsed < 0.8, f"KPI took {elapsed:.3f}s — too slow"


def test_fr_01_1_2_1_provider_filter(tmp_db):
    all_k = get_overview_kpis(Filters(period_days=14, provider="all"))
    only_o = get_overview_kpis(Filters(period_days=14, provider="openai"))
    only_a = get_overview_kpis(Filters(period_days=14, provider="anthropic"))
    assert only_o["total_spend"] <= all_k["total_spend"] + 1e-6
    assert only_a["total_spend"] <= all_k["total_spend"] + 1e-6
    # сумма по двум провайдерам ≈ all (не строго ==, но близко)
    assert abs(only_o["total_spend"] + only_a["total_spend"] - all_k["total_spend"]) < 0.5


def test_fr_01_1_2_2_team_filter(tmp_db):
    all_k = get_overview_kpis(Filters(period_days=14, team="all"))
    backend = get_overview_kpis(Filters(period_days=14, team="Backend"))
    assert backend["total_spend"] <= all_k["total_spend"] + 1e-6
    assert backend["active_users"] <= all_k["active_users"]
