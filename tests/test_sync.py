"""Tests for sync orchestrator (mock mode)."""
from __future__ import annotations


def test_run_sync_mock_no_keys(tmp_db, monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("HMND_GITHUB_ENABLED", raising=False)
    # Point cursor exports + sources at an empty dir so we fall through to
    # the mock path (otherwise the orchestrator picks up real files at repo root).
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))

    from importlib import reload
    import backend.config as cfgmod
    reload(cfgmod)
    import backend.services.cursor_analytics as ca
    reload(ca)
    from backend.services import sync as sync_mod
    reload(sync_mod)

    out = sync_mod.run_sync(period_days=3)
    assert "openai" in out["reports"]
    assert "anthropic" in out["reports"]
    # github пропущен, так как HMND_GITHUB_ENABLED не установлен
    assert "github" not in out["reports"]
    # OpenAI without admin key → skipped (mock mode)
    assert out["reports"]["openai"]["skipped"] >= 1
    # Anthropic without admin key AND without cursor data falls through to
    # AnthropicConnector mock — which sets skipped.
    assert out["reports"]["anthropic"].get("skipped", 0) >= 1


def test_refresh_daily_costs_aggregates(tmp_db):
    from backend.services.sync import _refresh_daily_costs
    n = _refresh_daily_costs(period_days=14)
    assert n >= 0


def _anthropic_week_doc(range_start, range_end, email, name, amount_cents, requests):
    """Minimal Anthropic v2 dump (amounts in CENTS) covering one week."""
    return {
        "_meta": {"provider": "anthropic", "version": "1.0",
                  "rangeStart": range_start, "rangeEnd": range_end,
                  "pulledAt": range_end},
        "rollups": {"provider": "anthropic", "totalSpend": float(amount_cents),
                    "totalRequests": requests, "totalTokens": 1_000_000,
                    "modelSpend": {"claude-opus-4-7": float(amount_cents)}},
        "raw": {"users": [], "userCostByProduct": {"data": [
            {"product": "claude_code",
             "actor": {"type": "user_actor", "user_id": email, "email": email, "name": name},
             "amount": str(amount_cents), "requests": requests},
        ]}},
    }


def test_incremental_weekly_anthropic_json_accumulates(tmp_path, monkeypatch):
    """Dropping a week-only Anthropic JSON next to an older one keeps BOTH:
    sync now loads every provider file oldest-first, and each loader DELETEs
    only its own `_meta` period — so non-overlapping weeks coexist (history is
    not lost) and re-running sync is idempotent. Regression for the
    incremental weekly-export workflow."""
    import json
    from importlib import reload

    monkeypatch.setenv("HMND_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path / "sources"))
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path / "empty"))
    for k in ("OPENAI_API_KEY", "OPENAI_API_KEYS", "ANTHROPIC_API_KEY", "GITHUB_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("HMND_GITHUB_ENABLED", raising=False)
    src = tmp_path / "sources"
    src.mkdir(parents=True)

    # Week 1 = $70, Week 2 = $50, periods do not overlap.
    (src / "Anthropic_20260507.json").write_text(json.dumps(
        _anthropic_week_doc("2026-05-01T00:00:00Z", "2026-05-07T23:59:59Z",
                            "a@x", "Alice", 7000, 70)))
    (src / "Anthropic_20260514.json").write_text(json.dumps(
        _anthropic_week_doc("2026-05-08T00:00:00Z", "2026-05-14T23:59:59Z",
                            "a@x", "Alice", 5000, 50)))

    import backend.config as cfg; reload(cfg)
    import backend.services.cursor_analytics as ca; reload(ca)
    from data.sources import _common, anthropic_json
    reload(_common); reload(anthropic_json)
    from backend.services import sync as sync_mod; reload(sync_mod)
    from data.db import init_schema, get_conn
    init_schema()

    out = sync_mod.run_sync(period_days=400, providers=("anthropic",))

    # >1 file → report is a list (single file stays a dict; see test above).
    rpt = out["reports"]["anthropic"]
    assert isinstance(rpt, list) and len(rpt) == 2, rpt
    assert all(r.get("mode") == "json" for r in rpt), rpt

    def spend_between(conn, a, b):
        return conn.execute(
            "SELECT COUNT(*) c, ROUND(COALESCE(SUM(cost_usd),0),2) s FROM usage_events ue "
            "JOIN providers p ON p.id=ue.provider_id WHERE p.name='anthropic' "
            "AND date(occurred_at)>=? AND date(occurred_at)<=?", (a, b)).fetchone()

    with get_conn() as conn:
        w1 = spend_between(conn, "2026-05-01", "2026-05-07")
        w2 = spend_between(conn, "2026-05-08", "2026-05-14")
        total = conn.execute("SELECT COUNT(*) c, ROUND(SUM(cost_usd),2) s FROM usage_events").fetchone()

    assert w1["c"] > 0, "week 1 history was lost when week 2 was added"
    assert w2["c"] > 0, "week 2 was not loaded"
    assert abs(w1["s"] - 70.0) < 0.5 and abs(w2["s"] - 50.0) < 0.5, (w1["s"], w2["s"])
    assert abs(total["s"] - 120.0) < 0.5, total["s"]

    # Idempotent: a second sync re-DELETEs+re-INSERTs each period, no growth.
    sync_mod.run_sync(period_days=400, providers=("anthropic",))
    with get_conn() as conn:
        total2 = conn.execute("SELECT COUNT(*) c, ROUND(SUM(cost_usd),2) s FROM usage_events").fetchone()
    assert (total2["c"], total2["s"]) == (total["c"], total["s"]), (dict(total), dict(total2))
