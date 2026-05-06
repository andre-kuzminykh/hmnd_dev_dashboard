"""Calibration test: after _calibrate_to_reported, the daily sum of
usage_events.cost_usd for that provider exactly matches provider_totals.

Catches regressions in the calibration math (per-day proportional scale).
"""
from __future__ import annotations

from datetime import datetime, timezone


def _setup_data(conn, provider_name="openai"):
    """Insert a provider, model, two users with raw cost_usd values that
    don't match the reported total (computed = $10, reported = $30 → 3x scale).
    Returns (provider_id, day_iso).
    """
    pid = conn.execute("INSERT INTO providers(name) VALUES(?)", (provider_name,)).lastrowid
    mid = conn.execute(
        "INSERT INTO models(provider_id, name, family) VALUES(?, 'gpt-test', 'gpt')",
        (pid,),
    ).lastrowid
    u1 = conn.execute(
        "INSERT INTO users(email, full_name, role, monthly_limit_usd, is_active) "
        "VALUES('a@x', 'A', 'user', 200, 1)"
    ).lastrowid
    u2 = conn.execute(
        "INSERT INTO users(email, full_name, role, monthly_limit_usd, is_active) "
        "VALUES('b@x', 'B', 'user', 200, 1)"
    ).lastrowid
    day = "2026-05-06"
    ts = f"{day} 12:00:00"
    # Two events: $4 and $6 → computed $10
    conn.execute(
        """INSERT INTO usage_events(user_id, provider_id, model_id, occurred_at,
                                    tokens_in, tokens_out, tokens_cached, cost_usd,
                                    is_error, purpose)
           VALUES(?,?,?,?,?,?,?,?,0,'API')""",
        (u1, pid, mid, ts, 1000, 500, 0, 4.0),
    )
    conn.execute(
        """INSERT INTO usage_events(user_id, provider_id, model_id, occurred_at,
                                    tokens_in, tokens_out, tokens_cached, cost_usd,
                                    is_error, purpose)
           VALUES(?,?,?,?,?,?,?,?,0,'API')""",
        (u2, pid, mid, ts, 2000, 1000, 0, 6.0),
    )
    # Provider says $30 for the same day
    conn.execute(
        "INSERT INTO provider_totals(provider_id, day, cost_usd) VALUES(?,?,?)",
        (pid, day, 30.0),
    )
    conn.commit()
    return pid, day


def test_calibrate_matches_provider_total(tmp_path, monkeypatch):
    """After _calibrate_to_reported, sum of usage_events for the day equals
    provider_totals.cost_usd."""
    from data.db import get_conn, init_schema
    db = tmp_path / "test.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db))
    init_schema(db)
    with get_conn() as conn:
        pid, day = _setup_data(conn)

    from data.connectors.openai import OpenAIConnector
    from data.connectors.base import SyncReport
    from datetime import date as _date
    c = OpenAIConnector(api_key="sk-admin-test", mock=False)
    report = SyncReport(provider="openai", period_from=_date(2026, 5, 1), period_to=_date(2026, 5, 7))
    c._calibrate_to_reported(
        datetime(2026, 5, 1, tzinfo=timezone.utc),
        datetime(2026, 5, 7, tzinfo=timezone.utc),
        pid,
        report,
    )

    with get_conn() as conn:
        total = conn.execute(
            "SELECT ROUND(SUM(cost_usd), 4) AS t FROM usage_events WHERE provider_id = ? AND date(occurred_at) = ?",
            (pid, day),
        ).fetchone()["t"]
    assert abs(total - 30.0) < 0.01, f"calibrated total {total}, expected 30.0"


def test_calibrate_preserves_user_proportions(tmp_path, monkeypatch):
    """Calibration scales every event by the same factor so per-user shares
    stay correct (user A had 40% of computed cost, must still have 40% after)."""
    from data.db import get_conn, init_schema
    db = tmp_path / "test.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db))
    init_schema(db)
    with get_conn() as conn:
        pid, day = _setup_data(conn)

    from data.connectors.openai import OpenAIConnector
    from data.connectors.base import SyncReport
    from datetime import date as _date
    c = OpenAIConnector(api_key="sk-admin-test", mock=False)
    report = SyncReport(provider="openai", period_from=_date(2026, 5, 1), period_to=_date(2026, 5, 7))
    c._calibrate_to_reported(
        datetime(2026, 5, 1, tzinfo=timezone.utc),
        datetime(2026, 5, 7, tzinfo=timezone.utc),
        pid,
        report,
    )

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT u.email, ROUND(SUM(ue.cost_usd), 4) AS s "
            "FROM usage_events ue JOIN users u ON u.id = ue.user_id "
            "WHERE ue.provider_id = ? GROUP BY u.id",
            (pid,),
        ).fetchall()
    by_email = {r["email"]: r["s"] for r in rows}
    # Original 40/60 split must hold: A=40% of $30 = $12, B=60% of $30 = $18
    assert abs(by_email["a@x"] - 12.0) < 0.01
    assert abs(by_email["b@x"] - 18.0) < 0.01


def test_calibrate_skips_when_reported_zero(tmp_path, monkeypatch):
    """If provider_totals.cost_usd is 0 for a day, leave usage_events unchanged
    (otherwise we'd zero out everything from a transient API hiccup)."""
    from data.db import get_conn, init_schema
    db = tmp_path / "test.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db))
    init_schema(db)
    with get_conn() as conn:
        pid, day = _setup_data(conn)
        conn.execute(
            "UPDATE provider_totals SET cost_usd = 0 WHERE provider_id = ?",
            (pid,),
        )
        conn.commit()

    from data.connectors.openai import OpenAIConnector
    from data.connectors.base import SyncReport
    from datetime import date as _date
    c = OpenAIConnector(api_key="sk-admin-test", mock=False)
    report = SyncReport(provider="openai", period_from=_date(2026, 5, 1), period_to=_date(2026, 5, 7))
    c._calibrate_to_reported(
        datetime(2026, 5, 1, tzinfo=timezone.utc),
        datetime(2026, 5, 7, tzinfo=timezone.utc),
        pid,
        report,
    )

    with get_conn() as conn:
        total = conn.execute(
            "SELECT SUM(cost_usd) AS t FROM usage_events WHERE provider_id = ?",
            (pid,),
        ).fetchone()["t"]
    # untouched original
    assert abs(total - 10.0) < 0.01
