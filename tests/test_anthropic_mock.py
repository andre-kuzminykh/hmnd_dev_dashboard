"""Tests for synthetic Anthropic data generator."""
from __future__ import annotations


def test_synth_anthropic_inserts_when_users_present(tmp_db):
    from data.anthropic_mock import synth_anthropic

    result = synth_anthropic(period_days=7)
    assert result["inserted"] > 0
    assert result["daily_costs"] > 0


def test_synth_anthropic_idempotent(tmp_db):
    """Re-run должен не задвоить — DELETE-then-INSERT в окне."""
    from data.anthropic_mock import synth_anthropic
    from data.db import get_conn

    synth_anthropic(period_days=5)
    with get_conn() as conn:
        n1 = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_events ue "
            "JOIN providers p ON p.id = ue.provider_id WHERE p.name='anthropic'"
        ).fetchone()["n"]

    synth_anthropic(period_days=5)
    with get_conn() as conn:
        n2 = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_events ue "
            "JOIN providers p ON p.id = ue.provider_id WHERE p.name='anthropic'"
        ).fetchone()["n"]
    assert n2 == n1


def test_synth_anthropic_skips_on_empty_db(tmp_path, monkeypatch):
    """Если в БД нет юзеров — мок ничего не делает."""
    db = tmp_path / "empty.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db))
    from data.db import init_schema
    init_schema()

    from data.anthropic_mock import synth_anthropic
    result = synth_anthropic(period_days=3)
    assert result["inserted"] == 0
    assert result.get("skipped") == 1
