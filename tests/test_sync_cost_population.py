"""Regression test: a fresh sync from an empty DB must produce non-zero
cost_usd for events whose model is in OPENAI_DEFAULT_PRICES.

Reproduces the bug where _sync_usage's prices_by_model cache was loaded
BEFORE _ensure_model created the very models we'd then look up — every
event ended up with cost_usd = 0.0.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


@pytest.fixture()
def empty_db(tmp_path, monkeypatch):
    """Empty schema, no seed data."""
    db = tmp_path / "test.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db))
    from data.db import init_schema
    init_schema(db)
    yield db


def _fake_get_factory(now_unix: int):
    """Returns a function with the same signature as OpenAIConnector._get."""
    def _fake_get(self, path, params):
        if path == "users":
            return {
                "data": [
                    {"id": "u_test", "email": "test@example.com", "name": "Test User", "role": "owner"},
                ],
                "has_more": False,
            }
        if path in ("admin_api_keys", "api_keys"):
            return {
                "data": [
                    {"id": "key_n8n", "name": "n8n_artem", "redacted_value": "sk-proj-...test",
                     "owner": {"id": "u_test"}, "created_at": "2026-01-01"},
                ],
                "has_more": False,
            }
        if path == "usage/completions":
            # 1 bucket, 1 result for gpt-4o-2024-08-06
            return {
                "data": [
                    {
                        "start_time": now_unix - 3600,
                        "results": [
                            {
                                "user_id": "u_test",
                                "model": "gpt-4o-2024-08-06",
                                "api_key_id": "key_n8n",
                                "input_tokens": 100_000,
                                "output_tokens": 10_000,
                                "input_cached_tokens": 0,
                                "num_model_requests": 50,
                            },
                            {
                                "user_id": "u_test",
                                "model": "gpt-4.1-mini-2025-04-14",
                                "api_key_id": "key_n8n",
                                "input_tokens": 500_000,
                                "output_tokens": 50_000,
                                "input_cached_tokens": 100_000,
                                "num_model_requests": 200,
                            },
                        ],
                    },
                ],
                "has_more": False,
            }
        if path == "costs":
            return {"data": [], "has_more": False}
        return {"data": [], "has_more": False}

    return _fake_get


def test_fresh_sync_produces_nonzero_cost(empty_db, monkeypatch):
    """The bug: prices_by_model was empty → cost_usd = 0 for every event."""
    from data.connectors.openai import OpenAIConnector
    from data.db import get_conn

    now_unix = int(datetime.now(timezone.utc).timestamp())
    monkeypatch.setattr(OpenAIConnector, "_get", _fake_get_factory(now_unix))

    c = OpenAIConnector(api_key="sk-admin-test", mock=False)
    report = c.sync(period_days=2)

    with get_conn() as conn:
        total = conn.execute(
            "SELECT ROUND(SUM(cost_usd), 4) AS total FROM usage_events"
        ).fetchone()["total"]

    assert total is not None
    assert total > 0, (
        "fresh sync must price events from OPENAI_DEFAULT_PRICES — "
        f"got total cost_usd = {total}"
    )

    # Sanity check: gpt-4o (100k input, 10k output) + gpt-4.1-mini (500k - 100k cached, 100k cached, 50k output)
    # gpt-4o:        100/1000 * 0.0025 + 10/1000 * 0.01                                  = 0.25 + 0.10 = 0.35
    # gpt-4.1-mini:  400/1000 * 0.0004 + 100/1000 * 0.0001 + 50/1000 * 0.0016            = 0.16 + 0.01 + 0.08 = 0.25
    # Expected ~ 0.60
    assert 0.50 < total < 0.70, f"unexpected total ${total} (expected ~$0.60)"


def test_existing_models_still_priced_after_backfill(empty_db, monkeypatch):
    """Backfill path: models exist without prices, sync must add prices then
    populate cost on usage events."""
    from data.connectors.openai import OpenAIConnector
    from data.db import get_conn

    # Pre-populate models without prices (simulates older sync runs)
    with get_conn() as conn:
        pid = conn.execute("INSERT INTO providers(name) VALUES('openai')").lastrowid
        conn.execute(
            "INSERT INTO models(provider_id, name, family) VALUES(?, 'gpt-4o-2024-08-06', 'gpt')",
            (pid,),
        )
        conn.commit()

    now_unix = int(datetime.now(timezone.utc).timestamp())
    monkeypatch.setattr(OpenAIConnector, "_get", _fake_get_factory(now_unix))

    c = OpenAIConnector(api_key="sk-admin-test", mock=False)
    c.sync(period_days=2)

    with get_conn() as conn:
        total = conn.execute(
            "SELECT ROUND(SUM(cost_usd), 4) AS total FROM usage_events"
        ).fetchone()["total"]
    assert total is not None and total > 0
