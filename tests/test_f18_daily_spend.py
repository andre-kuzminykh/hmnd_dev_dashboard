"""F-18 — Real per-day spend curves for Anthropic and Cursor.

Verifies that the dashboard "Spend over time" line gets actual daily
variance instead of `amount/days` flat spread.

Tests follow the SPEC §F-18 traceability:
  T-DATA-18.1  Anthropic: daily weights from raw.costByProduct.data
  T-DATA-18.2  Anthropic: per-user-per-product TOTAL is preserved
  T-DATA-18.3  Anthropic: zero-amount day → zero cost_usd in that day
  T-DATA-18.4  Anthropic: missing daily series → falls back to uniform
  T-DATA-18.5  Cursor: weights from acceptedLinesAdded
  T-DATA-18.6  Cursor: per-user TOTAL is preserved
  T-DATA-18.7  Cursor: zero-activity user → falls back to uniform
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import date


# ─────────────────────────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _two_day_anthropic_doc_daily(amount_day1_cents: float = 1000.0,
                                  amount_day2_cents: float = 9000.0):
    """2-day window. One user 'Alice' / one product 'claude_code'.
    Source-of-truth daily curve: day1 = $10, day2 = $90 (cents → /100).
    `userCostByProduct` total: $100.
    """
    return {
        "_meta": {
            "provider": "anthropic", "version": "1.0",
            "rangeStart": "2026-05-01T00:00:00Z",
            "rangeEnd":   "2026-05-02T23:59:59Z",
            "pulledAt":   "2026-05-03T00:00:00Z",
        },
        "rollups": {
            "provider": "anthropic", "totalUsers": 1,
            "totalSpend": amount_day1_cents + amount_day2_cents,
            "totalRequests": 200, "totalTokens": 10000,
            "spendByProduct": {"claude_code": amount_day1_cents + amount_day2_cents},
            "modelSpend": {"claude-opus-4-7": amount_day1_cents + amount_day2_cents},
        },
        "raw": {
            "users": [],
            # NEW: daily series the loader should weight against.
            "costByProduct": {"data": [
                {
                    "starting_at": "2026-05-01T00:00:00Z",
                    "ending_at":   "2026-05-02T00:00:00Z",
                    "results": [{"product": "claude_code",
                                 "amount": str(amount_day1_cents),
                                 "requests": 20}],
                },
                {
                    "starting_at": "2026-05-02T00:00:00Z",
                    "ending_at":   "2026-05-03T00:00:00Z",
                    "results": [{"product": "claude_code",
                                 "amount": str(amount_day2_cents),
                                 "requests": 180}],
                },
            ]},
            "userCostByProduct": {"data": [
                {
                    "product": "claude_code",
                    "actor": {"type": "user_actor", "user_id": "user_a",
                              "email": "alice@x", "name": "Alice"},
                    "amount": str(amount_day1_cents + amount_day2_cents),
                    "requests": 200,
                },
            ]},
        },
    }


def _two_day_anthropic_doc_no_daily():
    """Back-compat fixture: NO costByProduct/cost daily series. Loader must
    fall back to uniform split."""
    return {
        "_meta": {
            "provider": "anthropic", "version": "1.0",
            "rangeStart": "2026-05-01T00:00:00Z",
            "rangeEnd":   "2026-05-02T23:59:59Z",
            "pulledAt":   "2026-05-03T00:00:00Z",
        },
        "rollups": {
            "provider": "anthropic", "totalUsers": 1, "totalSpend": 10000.0,
            "totalRequests": 200, "totalTokens": 10000,
            "spendByProduct": {"claude_code": 10000.0},
            "modelSpend": {"claude-opus-4-7": 10000.0},
        },
        "raw": {
            "users": [],
            "userCostByProduct": {"data": [
                {
                    "product": "claude_code",
                    "actor": {"type": "user_actor", "user_id": "user_a",
                              "email": "alice@x", "name": "Alice"},
                    "amount": "10000.0", "requests": 200,
                },
            ]},
        },
    }


def _two_day_cursor_doc_daily(u1_lines_day1: int = 100, u1_lines_day2: int = 900):
    """2-day window. User u1@x: 100 lines day1, 900 lines day2.
    Spend $1.00 total (50 + 50 cents). Daily weighting should send 10% / 90%.
    """
    return {
        "_meta": {
            "provider": "cursor", "version": "1.0",
            "rangeStart": "2026-05-01T00:00:00Z",
            "rangeEnd":   "2026-05-02T23:59:59Z",
            "pulledAt":   "2026-05-03T00:00:00Z",
        },
        "rollups": {
            "activeDevs": 1, "totalMembers": 1, "totalSpend": 1.0,
            "totalLines": u1_lines_day1 + u1_lines_day2,
            "totalAccepts": u1_lines_day1 + u1_lines_day2,
            "totalAgent": 0,
            "perUser": {"u1@x": {"lines": u1_lines_day1 + u1_lines_day2,
                                  "accepts": u1_lines_day1 + u1_lines_day2,
                                  "agent": 0}},
        },
        "raw": {
            "members": {"teamMembers": [
                {"name": "User One", "email": "u1@x", "id": "u1", "role": "member"},
            ]},
            # NEW: per-day per-user activity rows.
            "usage": {"data": [
                {"date": 0, "day": "2026-05-01", "userId": "u1", "email": "u1@x",
                 "isActive": True, "totalLinesAdded": u1_lines_day1,
                 "totalLinesDeleted": 0, "acceptedLinesAdded": u1_lines_day1,
                 "agentChatTotalRequests": 0},
                {"date": 0, "day": "2026-05-02", "userId": "u1", "email": "u1@x",
                 "isActive": True, "totalLinesAdded": u1_lines_day2,
                 "totalLinesDeleted": 0, "acceptedLinesAdded": u1_lines_day2,
                 "agentChatTotalRequests": 0},
            ]},
            "spend": {"teamMemberSpend": [
                {"userId": "u1", "email": "u1@x", "name": "User One",
                 "spendCents": 50, "includedSpendCents": 50},
            ]},
        },
    }


def _two_day_cursor_doc_no_activity():
    """User has spend but no daily activity rows → uniform fallback expected."""
    return {
        "_meta": {
            "provider": "cursor", "version": "1.0",
            "rangeStart": "2026-05-01T00:00:00Z",
            "rangeEnd":   "2026-05-02T23:59:59Z",
            "pulledAt":   "2026-05-03T00:00:00Z",
        },
        "rollups": {
            "activeDevs": 0, "totalMembers": 1, "totalSpend": 1.0,
            "totalLines": 0, "totalAccepts": 0, "totalAgent": 0,
            "perUser": {"u1@x": {"lines": 0, "accepts": 0, "agent": 0}},
        },
        "raw": {
            "members": {"teamMembers": [
                {"name": "User One", "email": "u1@x", "id": "u1", "role": "member"},
            ]},
            "usage": {"data": []},  # no daily activity
            "spend": {"teamMemberSpend": [
                {"userId": "u1", "email": "u1@x", "name": "User One",
                 "spendCents": 100, "includedSpendCents": 0},
            ]},
        },
    }


def _write(sources_dir: Path, name: str, body: dict) -> Path:
    sources_dir.mkdir(parents=True, exist_ok=True)
    p = sources_dir / name
    p.write_text(json.dumps(body))
    return p


# ─────────────────────────────────────────────────────────────────────────────
# T-DATA-18 · Anthropic per-day weighting
# ─────────────────────────────────────────────────────────────────────────────

def test_t_data_18_1_anthropic_daily_weighting(tmp_path, monkeypatch):
    """T-DATA-18.1 — Two days, $10 and $90 in source daily curve, one user
    with $100 total → loader should write ~$10 on day 1, ~$90 on day 2."""
    from data.db import get_conn, init_schema
    from data.sources import anthropic_json

    db_path = tmp_path / "t.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db_path))
    init_schema()

    p = _write(tmp_path / "src", "Anthropic_20260503.json",
               _two_day_anthropic_doc_daily(1000.0, 9000.0))
    res = anthropic_json.load_anthropic_json(p)
    assert res["inserted"] > 0, res

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT date(occurred_at) AS d, ROUND(SUM(cost_usd),2) AS c
               FROM usage_events GROUP BY d ORDER BY d"""
        ).fetchall()
    by_day = {r["d"]: r["c"] for r in rows}
    assert by_day.get("2026-05-01") == 10.00, by_day
    assert by_day.get("2026-05-02") == 90.00, by_day


def test_t_data_18_2_anthropic_user_total_preserved(tmp_path, monkeypatch):
    """T-DATA-18.2 — Per-user total after load equals source amount."""
    from data.db import get_conn, init_schema
    from data.sources import anthropic_json

    db_path = tmp_path / "t.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db_path))
    init_schema()

    p = _write(tmp_path / "src", "Anthropic_20260503.json",
               _two_day_anthropic_doc_daily(1234.0, 8766.0))
    anthropic_json.load_anthropic_json(p)

    with get_conn() as conn:
        total = conn.execute(
            "SELECT ROUND(SUM(cost_usd), 2) AS t FROM usage_events"
        ).fetchone()["t"]
    # Source userCostByProduct = $100 (1234+8766=10000 cents)
    assert abs(total - 100.00) < 0.01, total


def test_t_data_18_3_anthropic_zero_day_zero_cost(tmp_path, monkeypatch):
    """T-DATA-18.3 — Day with $0 in daily curve gets $0 in DB."""
    from data.db import get_conn, init_schema
    from data.sources import anthropic_json

    db_path = tmp_path / "t.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db_path))
    init_schema()

    # Day 1 = $0, day 2 = $100 — all spend should land on day 2.
    p = _write(tmp_path / "src", "Anthropic_20260503.json",
               _two_day_anthropic_doc_daily(0.0, 10000.0))
    anthropic_json.load_anthropic_json(p)

    with get_conn() as conn:
        d1 = conn.execute(
            "SELECT ROUND(COALESCE(SUM(cost_usd),0),2) AS c FROM usage_events "
            "WHERE date(occurred_at)='2026-05-01'"
        ).fetchone()["c"]
        d2 = conn.execute(
            "SELECT ROUND(COALESCE(SUM(cost_usd),0),2) AS c FROM usage_events "
            "WHERE date(occurred_at)='2026-05-02'"
        ).fetchone()["c"]
    assert d1 == 0.00, f"day 1 should be $0, got {d1}"
    assert d2 == 100.00, f"day 2 should be $100, got {d2}"


def test_t_data_18_4_anthropic_no_daily_series_uniform_fallback(tmp_path, monkeypatch):
    """T-DATA-18.4 — When the daily curve is missing entirely, fall back to
    even split (back-compat) and still preserve total."""
    from data.db import get_conn, init_schema
    from data.sources import anthropic_json

    db_path = tmp_path / "t.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db_path))
    init_schema()

    p = _write(tmp_path / "src", "Anthropic_20260503.json",
               _two_day_anthropic_doc_no_daily())
    res = anthropic_json.load_anthropic_json(p)
    assert res["inserted"] > 0, res

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT date(occurred_at) AS d, ROUND(SUM(cost_usd),2) AS c
               FROM usage_events GROUP BY d ORDER BY d"""
        ).fetchall()
    by_day = {r["d"]: r["c"] for r in rows}
    # Even split across 2 days: $100 / 2 = $50 each
    assert by_day.get("2026-05-01") == 50.00, by_day
    assert by_day.get("2026-05-02") == 50.00, by_day


# ─────────────────────────────────────────────────────────────────────────────
# T-DATA-18 · Cursor per-day weighting
# ─────────────────────────────────────────────────────────────────────────────

def test_t_data_18_5_cursor_daily_weighting(tmp_path, monkeypatch):
    """T-DATA-18.5 — Cursor: user with 100 lines day1, 900 day2 → spend
    distributes 10% / 90%."""
    from data.db import get_conn, init_schema
    from data.sources import cursor_json

    db_path = tmp_path / "t.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db_path))
    init_schema()

    p = _write(tmp_path / "src", "Cursor_20260503.json",
               _two_day_cursor_doc_daily(100, 900))
    cursor_json.load_cursor_json(p)

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT date(occurred_at) AS d, ROUND(SUM(cost_usd),4) AS c
               FROM usage_events GROUP BY d ORDER BY d"""
        ).fetchall()
    by_day = {r["d"]: r["c"] for r in rows}
    # Total spend = ($0.50 + $0.50) = $1.00. Weights 10/90 → $0.10 / $0.90.
    assert abs(by_day.get("2026-05-01", 0) - 0.10) < 0.01, by_day
    assert abs(by_day.get("2026-05-02", 0) - 0.90) < 0.01, by_day


def test_t_data_18_6_cursor_user_total_preserved(tmp_path, monkeypatch):
    """T-DATA-18.6 — Cursor: per-user total matches spend.teamMemberSpend."""
    from data.db import get_conn, init_schema
    from data.sources import cursor_json

    db_path = tmp_path / "t.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db_path))
    init_schema()

    p = _write(tmp_path / "src", "Cursor_20260503.json",
               _two_day_cursor_doc_daily(123, 877))
    cursor_json.load_cursor_json(p)

    with get_conn() as conn:
        total = conn.execute(
            "SELECT ROUND(SUM(cost_usd), 2) AS t FROM usage_events"
        ).fetchone()["t"]
    # 50 + 50 cents = $1.00
    assert abs(total - 1.00) < 0.01, total


def test_t_data_18_7_cursor_no_activity_uniform_fallback(tmp_path, monkeypatch):
    """T-DATA-18.7 — Cursor: user with spend but no daily activity rows
    falls back to uniform split (so spend is still attributed)."""
    from data.db import get_conn, init_schema
    from data.sources import cursor_json

    db_path = tmp_path / "t.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db_path))
    init_schema()

    p = _write(tmp_path / "src", "Cursor_20260503.json",
               _two_day_cursor_doc_no_activity())
    cursor_json.load_cursor_json(p)

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT date(occurred_at) AS d, ROUND(SUM(cost_usd),2) AS c
               FROM usage_events GROUP BY d ORDER BY d"""
        ).fetchall()
    by_day = {r["d"]: r["c"] for r in rows}
    # Even split: $1.00 / 2 = $0.50 each
    assert abs(by_day.get("2026-05-01", 0) - 0.50) < 0.01, by_day
    assert abs(by_day.get("2026-05-02", 0) - 0.50) < 0.01, by_day
