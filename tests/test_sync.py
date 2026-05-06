"""Tests for sync orchestrator (mock mode)."""
from __future__ import annotations


def test_run_sync_mock_no_keys(tmp_db, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("HMND_GITHUB_ENABLED", raising=False)

    from importlib import reload
    import backend.config as cfgmod
    reload(cfgmod)
    from backend.services import sync as sync_mod
    reload(sync_mod)

    out = sync_mod.run_sync(period_days=3)
    assert "openai" in out["reports"]
    assert "anthropic" in out["reports"]
    # github пропущен, так как HMND_GITHUB_ENABLED не установлен
    assert "github" not in out["reports"]
    # mock мод => skipped >= 1
    assert out["reports"]["openai"]["skipped"] >= 1
    assert out["reports"]["anthropic"]["skipped"] >= 1


def test_refresh_daily_costs_aggregates(tmp_db):
    from backend.services.sync import _refresh_daily_costs
    n = _refresh_daily_costs(period_days=14)
    assert n >= 0
