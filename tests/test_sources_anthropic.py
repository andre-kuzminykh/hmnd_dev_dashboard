"""F-14 Anthropic JSON loader tests — uses the real `_meta/rollups/raw`
schema produced by the provider pull script.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def _minimal_anthropic_doc(range_start="2026-05-01T00:00:00Z",
                           range_end="2026-05-07T23:59:59Z",
                           total_spend_cents=10000.0,
                           user_records=None) -> dict:
    """Builds a fixture matching the real Anthropic Admin API shape:
    every amount/spend value is in CENTS (lowest currency unit).
    Default totalSpend = 10000 cents = $100 USD.
    """
    return {
        "_meta": {
            "provider": "anthropic",
            "version": "1.0",
            "rangeStart": range_start,
            "rangeEnd": range_end,
            "pulledAt": "2026-05-08T00:00:00Z",
        },
        "rollups": {
            "provider": "anthropic",
            "totalUsers": 2,
            "totalSpend": total_spend_cents,
            "totalRequests": 200,
            "totalTokens": 1_000_000,
            "spendByProduct": {"chat": 3000.0, "claude_code": 7000.0},
            "modelSpend": {"claude-opus-4-7": 7000.0, "claude-sonnet-4-6": 3000.0},
        },
        "raw": {
            "users": [],
            "userCostByProduct": {
                "data": user_records or [
                    {
                        "product": "claude_code",
                        "actor": {"type": "user_actor",
                                  "user_id": "user_a",
                                  "email": "a@x",
                                  "name": "Alice"},
                        "amount": "7000.0", "requests": 150,  # 7000 cents = $70
                    },
                    {
                        "product": "chat",
                        "actor": {"type": "user_actor",
                                  "user_id": "user_b",
                                  "email": "b@x",
                                  "name": "Bob"},
                        "amount": "3000.0", "requests": 50,   # 3000 cents = $30
                    },
                ],
            },
        },
    }


def _write(sources_dir: Path, name: str, body: dict | None = None) -> Path:
    sources_dir.mkdir(parents=True, exist_ok=True)
    p = sources_dir / name
    p.write_text(json.dumps(body if body is not None else _minimal_anthropic_doc()))
    return p


def test_fr_14_1_1_4_filename_pattern(tmp_path, monkeypatch):
    """Loader discovers both Anthropic_*.json and the typo Anthropics_*.json."""
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    _write(tmp_path, "Anthropic_20260507.json")
    _write(tmp_path, "Anthropics_20260514.json")

    import importlib
    from data.sources import anthropic_json, _common
    importlib.reload(_common)
    importlib.reload(anthropic_json)

    files = anthropic_json.find_anthropic_files()
    names = sorted(f.path.name for f in files)
    assert names == ["Anthropic_20260507.json", "Anthropics_20260514.json"]
    latest = anthropic_json.latest_anthropic_file()
    assert latest.path.name == "Anthropics_20260514.json"


def test_fr_14_1_1_1_schema_required_keys(tmp_path, monkeypatch):
    """Missing _meta.rangeStart → loader records error, doesn't crash."""
    monkeypatch.setenv("HMND_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    from data.db import init_schema
    init_schema()

    bad = _minimal_anthropic_doc()
    del bad["_meta"]["rangeStart"]
    p = _write(tmp_path, "Anthropic_20260507.json", bad)
    import importlib
    from data.sources import anthropic_json
    importlib.reload(anthropic_json)
    report = anthropic_json.load_anthropic_json(p)
    assert report["inserted"] == 0
    assert any("period" in e for e in report.get("errors", []))


def test_fr_14_1_1_2_idempotent(tmp_path, monkeypatch):
    """Loading the same file twice must yield identical row counts."""
    monkeypatch.setenv("HMND_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    from data.db import init_schema, get_conn
    init_schema()

    p = _write(tmp_path, "Anthropic_20260507.json")
    import importlib
    from data.sources import anthropic_json
    importlib.reload(anthropic_json)

    anthropic_json.load_anthropic_json(p)
    with get_conn() as conn:
        n1 = conn.execute("SELECT COUNT(*) AS n FROM usage_events").fetchone()["n"]
    anthropic_json.load_anthropic_json(p)
    with get_conn() as conn:
        n2 = conn.execute("SELECT COUNT(*) AS n FROM usage_events").fetchone()["n"]
    assert n1 == n2 and n1 > 0


def test_fr_14_1_1_3_latest_file_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    _write(tmp_path, "Anthropic_20260501.json")
    _write(tmp_path, "Anthropic_20260514.json")
    _write(tmp_path, "Anthropic_20260507.json")
    import importlib
    from data.sources import anthropic_json
    importlib.reload(anthropic_json)
    latest = anthropic_json.latest_anthropic_file()
    assert latest.path.name == "Anthropic_20260514.json"
    assert latest.date_in_name == date(2026, 5, 14)


def test_loaded_events_have_cost_and_purpose(tmp_path, monkeypatch):
    """Loaded events split by product into the correct purposes."""
    monkeypatch.setenv("HMND_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    from data.db import init_schema, get_conn
    init_schema()
    p = _write(tmp_path, "Anthropic_20260507.json")
    import importlib
    from data.sources import anthropic_json
    importlib.reload(anthropic_json)
    anthropic_json.load_anthropic_json(p)

    with get_conn() as conn:
        purposes = {r["purpose"] for r in conn.execute(
            "SELECT DISTINCT purpose FROM usage_events"
        ).fetchall()}
        assert "Chat" in purposes
        assert "Agent" in purposes
        total = conn.execute(
            "SELECT ROUND(SUM(cost_usd), 2) AS s FROM usage_events"
        ).fetchone()["s"]
        # 3000 chat + 7000 cc = 10000 cents = $100 USD after /100
        assert abs(total - 100.0) < 1.0


def test_amount_is_converted_from_cents_to_usd(tmp_path, monkeypatch):
    """Anthropic Admin API returns USD amounts in LOWEST UNIT (cents). The
    loader must divide by 100 — otherwise totals are 100x inflated (which is
    what produced the bogus $4.5M reading on Humanoid's dashboard).

    Doc reference:
        https://platform.claude.com/docs/en/build-with-claude/usage-cost-api
        > "Currency: All costs in USD, reported as decimal strings in lowest
        >  units (cents)"
    """
    monkeypatch.setenv("HMND_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    from data.db import init_schema, get_conn
    init_schema()

    # Single user record with a known amount: 4500000 cents = $45,000 USD
    doc = _minimal_anthropic_doc(
        total_spend_cents=4_500_000.0,
        user_records=[{
            "product": "claude_code",
            "actor": {"type": "user_actor", "user_id": "u1",
                      "email": "u1@x", "name": "U1"},
            "amount": "4500000.0", "requests": 100,
        }],
    )
    p = _write(tmp_path, "Anthropic_20260507.json", doc)
    import importlib
    from data.sources import anthropic_json
    importlib.reload(anthropic_json)
    report = anthropic_json.load_anthropic_json(p)

    # Loader's reported total must also be in USD (not cents)
    assert report["total_spend_usd"] == 45000.0, report

    # DB sum must be $45,000 — NOT 4,500,000
    with get_conn() as conn:
        total = conn.execute(
            "SELECT ROUND(SUM(cost_usd), 2) AS s FROM usage_events"
        ).fetchone()["s"]
    assert abs(total - 45000.0) < 1.0, f"DB total {total} (expected ~$45,000)"


def test_fr_14_3_1_1_json_wins_over_cursor_derived(tmp_path, monkeypatch):
    """When sources/Anthropic_*.json is present, sync uses it and skips
    the cursor-derived path."""
    monkeypatch.setenv("HMND_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEYS", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from data.db import init_schema
    init_schema()
    _write(tmp_path, "Anthropic_20260507.json")
    (tmp_path / "User_Leaderboard_2026-04-30_2026-05-06.csv").write_text(
        "Email,Name,Agent Completions,Agent Lines,Tab Completions,Tab Lines,Ai Lines,Favorite Model\n"
        "c@x,Carol,500,5000,0,0,5000,claude-opus-4-7\n"
    )

    import importlib
    import backend.config as cfg; importlib.reload(cfg)
    import backend.services.cursor_analytics as ca; importlib.reload(ca)
    from data.sources import anthropic_json; importlib.reload(anthropic_json)
    from backend.services import sync as sync_mod; importlib.reload(sync_mod)

    out = sync_mod.run_sync(period_days=7)
    rpt = out["reports"]["anthropic"]
    assert rpt.get("mode") == "json", rpt
