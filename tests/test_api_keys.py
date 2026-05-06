"""F-11 API Keys tests."""
from __future__ import annotations

from backend.analytics import Filters
from backend.services.api_keys import get_api_keys_breakdown, get_orphan_usage


def test_api_keys_breakdown_returns_empty_when_no_keys(tmp_db):
    rows = get_api_keys_breakdown(Filters(period_days=14))
    # seed не создаёт api_keys, поэтому пусто
    assert isinstance(rows, list)
    assert rows == []


def test_orphan_usage_counts_keyless_events(tmp_db):
    """Все seed-события без api_key_id — должны быть 'orphan'."""
    o = get_orphan_usage(Filters(period_days=14))
    assert o["requests"] > 0
    assert o["cost"] >= 0


def test_anthropic_mock_creates_api_keys(tmp_db):
    """Mock-режим должен создать ключ на каждого юзера и привязать события."""
    from data.anthropic_mock import synth_anthropic
    from data.db import get_conn

    synth_anthropic(period_days=5)
    with get_conn() as conn:
        n_keys = conn.execute(
            "SELECT COUNT(*) AS n FROM api_keys ak "
            "JOIN providers p ON p.id = ak.provider_id WHERE p.name='anthropic'"
        ).fetchone()["n"]
        n_events_with_key = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_events ue "
            "JOIN providers p ON p.id = ue.provider_id "
            "WHERE p.name='anthropic' AND ue.api_key_id IS NOT NULL"
        ).fetchone()["n"]
    assert n_keys > 0
    assert n_events_with_key > 0
