"""F-01 Executive Overview — тесты по ID требований."""
from __future__ import annotations

import time
from datetime import datetime

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


def test_total_spend_uses_billing_api_when_available(tmp_db):
    """When provider_totals has rows (= we synced /costs from the billing API),
    the Total Spend KPI must reflect that, NOT the SUM of usage_events. The
    /usage endpoint is incomplete (missing audio, batch, some buckets), so
    summing events undersees by 20-40%. /costs is the source of truth.
    """
    from data.db import get_conn
    with get_conn() as conn:
        pid = conn.execute("SELECT id FROM providers WHERE name='openai'").fetchone()["id"]
        uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
        mid = conn.execute(
            "SELECT id FROM models WHERE provider_id = ? LIMIT 1", (pid,)
        ).fetchone()["id"]
        # Wipe existing OpenAI data so the assertion isn't muddied by fixture noise.
        today = datetime.utcnow().date().isoformat()
        conn.execute("DELETE FROM usage_events WHERE provider_id = ?", (pid,))
        conn.execute("DELETE FROM provider_totals WHERE provider_id = ?", (pid,))
        # usage_events: $50 (undersees actual billing)
        conn.execute(
            """INSERT INTO usage_events(user_id, provider_id, model_id,
                                         occurred_at, tokens_in, tokens_out,
                                         tokens_cached, cost_usd, is_error, purpose)
               VALUES(?, ?, ?, datetime('now', '-1 day'), 1000, 100, 0, 50.0, 0, 'API')""",
            (uid, pid, mid),
        )
        # provider_totals: $100 (authoritative)
        conn.execute(
            """INSERT INTO provider_totals(provider_id, day, cost_usd)
               VALUES(?, ?, 100.0)""",
            (pid, today),
        )
        conn.commit()

    kpis = get_overview_kpis(Filters(period_days=7, provider="openai"))
    assert kpis["total_spend"] == 100.0, (
        f"Total Spend should reflect /costs ($100), got ${kpis['total_spend']}"
    )
    assert kpis["total_spend_events"] == 50.0, (
        f"events-derived figure must be exposed for transparency, got ${kpis['total_spend_events']}"
    )
    assert kpis["reported_total"] == 100.0


def test_tokens_in_subtracts_cached(tmp_db):
    """Tokens In KPI must show UNCACHED input only, so the number matches
    the OpenAI Platform billing UI (which shows uncached only). Stored
    tokens_in includes cached, so the SQL aggregate subtracts tokens_cached.
    """
    from data.db import get_conn
    with get_conn() as conn:
        pid = conn.execute("SELECT id FROM providers WHERE name='openai'").fetchone()["id"]
        uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
        mid = conn.execute(
            "SELECT id FROM models WHERE provider_id = ? LIMIT 1", (pid,)
        ).fetchone()["id"]
        # Insert 1 event with tokens_in=100 incl. tokens_cached=70 → display = 30.
        conn.execute(
            """INSERT INTO usage_events(user_id, provider_id, model_id, occurred_at,
                                         tokens_in, tokens_out, tokens_cached, cost_usd,
                                         is_error, purpose)
               VALUES(?, ?, ?, datetime('now', '-1 day'), 100, 50, 70, 0.5, 0, 'API')""",
            (uid, pid, mid),
        )
        conn.commit()

    kpis = get_overview_kpis(Filters(period_days=7, provider="openai"))
    # The KPI exposes the cached portion separately, and tokens_in must be
    # strictly smaller than raw SUM(tokens_in) because we subtract cached.
    assert kpis["tokens_cached"] >= 70
    with get_conn() as conn:
        raw_in = conn.execute(
            """SELECT COALESCE(SUM(tokens_in), 0) AS s
               FROM usage_events ue JOIN providers p ON p.id = ue.provider_id
               WHERE p.name = 'openai' AND ue.occurred_at >= datetime('now', '-7 days')"""
        ).fetchone()["s"]
    # Display value must equal raw minus cached (clamped at zero per row to
    # defend against any individual event where cached > input).
    assert kpis["tokens_in"] < raw_in
    assert kpis["tokens_in"] >= 0
    # Drop in tokens_in across the new row must equal exactly 100-70=30, even
    # if other fixture rows already existed (they're stable).
    # Re-running with the row deleted should bump tokens_in by 30 less.
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM usage_events WHERE tokens_in=100 AND tokens_cached=70"
        )
        conn.commit()
    kpis2 = get_overview_kpis(Filters(period_days=7, provider="openai"))
    assert kpis["tokens_in"] - kpis2["tokens_in"] == 30


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
