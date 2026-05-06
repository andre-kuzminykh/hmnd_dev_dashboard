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


def test_purge_anthropic_mock_clears_synthetic_data(tmp_db):
    """purge() удаляет ключи sk-ant-mock-* и связанные usage_events."""
    from data.anthropic_mock import purge_anthropic_mock, synth_anthropic
    from data.db import get_conn

    synth_anthropic(period_days=5)
    with get_conn() as conn:
        keys_before = conn.execute(
            "SELECT COUNT(*) AS n FROM api_keys WHERE external_id LIKE 'sk-ant-mock-%'"
        ).fetchone()["n"]
    assert keys_before > 0

    deleted = purge_anthropic_mock()
    assert deleted["keys"] == keys_before
    assert deleted["events"] > 0

    with get_conn() as conn:
        keys_after = conn.execute(
            "SELECT COUNT(*) AS n FROM api_keys WHERE external_id LIKE 'sk-ant-mock-%'"
        ).fetchone()["n"]
        events_with_mock_key = conn.execute(
            """SELECT COUNT(*) AS n FROM usage_events ue
               WHERE ue.api_key_id IS NOT NULL AND ue.api_key_id IN (
                   SELECT id FROM api_keys WHERE external_id LIKE 'sk-ant-mock-%'
               )"""
        ).fetchone()["n"]
    assert keys_after == 0
    assert events_with_mock_key == 0


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
