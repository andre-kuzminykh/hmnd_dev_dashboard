"""Tests for management insights service."""
from __future__ import annotations

from datetime import datetime, timedelta


def test_concentration_basic(tmp_db):
    from backend.services.insights import get_top_n_concentration, concentration_risk_label
    out = get_top_n_concentration(top_n=5, period_days=14)
    assert "top_n" in out and "concentration_pct" in out
    # Cumulative top-5 spend <= total spend (within rounding tolerance)
    assert out["top_n_spend"] <= out["total_spend"] + 0.5
    # Each entry must have these fields
    if out["top_n"]:
        for row in out["top_n"]:
            assert {"user_id", "user_name", "email", "spend_usd"}.issubset(row.keys())


def test_concentration_risk_labels():
    from backend.services.insights import concentration_risk_label
    assert concentration_risk_label(80) == "high"
    assert concentration_risk_label(60) == "high"
    assert concentration_risk_label(45) == "medium"
    assert concentration_risk_label(30) == "medium"
    assert concentration_risk_label(15) == "low"
    assert concentration_risk_label(0) == "low"


def test_concentration_top_n_bound(tmp_db):
    """Top-N must never return more rows than N."""
    from backend.services.insights import get_top_n_concentration
    out = get_top_n_concentration(top_n=3, period_days=30)
    assert len(out["top_n"]) <= 3


def test_idle_seats_shape(tmp_db):
    from backend.services.insights import get_idle_paid_seats
    out = get_idle_paid_seats(threshold_days=30)
    assert "idle_count" in out
    assert "wasted_monthly_usd" in out
    assert "wasted_annual_usd" in out
    assert out["wasted_annual_usd"] == round(out["wasted_monthly_usd"] * 12, 2)


def test_idle_seats_detects_stale(tmp_db):
    """A seat used 60 days ago must be flagged when threshold is 30."""
    from data.db import get_conn
    from backend.services.insights import get_idle_paid_seats

    with get_conn() as conn:
        # find any assigned seat and pin its last_used_at 60 days back
        seat = conn.execute(
            "SELECT id FROM seats WHERE assigned = 1 LIMIT 1"
        ).fetchone()
        if not seat:
            return  # fixture has no seats — skip
        old = (datetime.utcnow() - timedelta(days=60)).isoformat()
        conn.execute(
            "UPDATE seats SET last_used_at = ? WHERE id = ?",
            (old, seat["id"]),
        )
        conn.commit()

    out = get_idle_paid_seats(threshold_days=30)
    assert out["idle_count"] >= 1
    # Every reported row has days_idle >= threshold
    for r in out["rows"]:
        assert r["days_idle"] >= 30 or r["last_used_at"] in (None, "")


def test_dev_roi_shape(tmp_db, monkeypatch):
    """ROI shape when there's no Cursor data → empty rows but team totals 0."""
    from backend.services.insights import get_developer_roi
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", "/tmp/empty_for_roi_test")
    out = get_developer_roi(dev_rate_usd_per_hour=100, lines_per_hour=50, period_days=14)
    assert "rows" in out and "team" in out
    assert "assumptions" in out
    assert out["assumptions"]["dev_rate_usd_per_hour"] == 100
    assert out["assumptions"]["lines_per_hour"] == 50


def test_dev_roi_math(tmp_path, monkeypatch):
    """With known leaderboard + spend, verify the formula:
       hours = lines / lph
       value = hours * rate
       roi = value / spend
    """
    # Stand up an empty DB so we don't get noise from the seed fixture.
    db = tmp_path / "test.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db))
    from data.db import init_schema, get_conn
    init_schema()

    # Cursor CSV mock
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))
    (tmp_path / "User_Leaderboard_2026-04-30_2026-05-06.csv").write_text(
        "Email,Name,Agent Completions,Agent Lines,Tab Completions,Tab Lines,Ai Lines,Favorite Model\n"
        "u1@x,User One,100,4000,0,0,4000,claude-opus-4-7\n"
    )

    # User in DB with spend = $100
    with get_conn() as conn:
        pid = conn.execute("INSERT INTO providers(name) VALUES('openai')").lastrowid
        uid = conn.execute(
            "INSERT INTO users(email, full_name, monthly_limit_usd, is_active) "
            "VALUES('u1@x', 'User One', 200, 1)"
        ).lastrowid
        mid = conn.execute(
            "INSERT INTO models(provider_id, name, family) VALUES(?, 'm', 'm')", (pid,)
        ).lastrowid
        ts = (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO usage_events(user_id, provider_id, model_id, occurred_at, "
            "tokens_in, tokens_out, tokens_cached, cost_usd, is_error, purpose) "
            "VALUES(?, ?, ?, ?, 1000, 100, 0, 100.0, 0, 'API')",
            (uid, pid, mid, ts),
        )
        conn.commit()

    # Force reload cursor_analytics so it picks up the new env
    import importlib
    import backend.services.cursor_analytics as ca; importlib.reload(ca)
    import backend.services.insights as ins; importlib.reload(ins)

    out = ins.get_developer_roi(dev_rate_usd_per_hour=100, lines_per_hour=50, period_days=14)
    assert len(out["rows"]) == 1
    r = out["rows"][0]
    # 4000 lines / 50 LOC/h = 80 hours → 80 * $100 = $8000 value
    assert r["hours_saved"] == 80.0
    assert r["value_saved_usd"] == 8000.0
    # $8000 saved / $100 spend = 80x ROI
    assert r["roi_multiple"] == 80.0
