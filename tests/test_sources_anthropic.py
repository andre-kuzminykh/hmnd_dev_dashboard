"""F-14 Anthropic JSON loader tests — uses the real `_meta/rollups/raw`
schema produced by the provider pull script.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def _minimal_anthropic_doc(range_start="2026-05-01T00:00:00Z",
                           range_end="2026-05-07T23:59:59Z",
                           total_spend=100.0,
                           user_records=None) -> dict:
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
            "totalSpend": total_spend,
            "totalRequests": 200,
            "totalTokens": 1_000_000,
            "spendByProduct": {"chat": 30.0, "claude_code": 70.0},
            "modelSpend": {"claude-opus-4-7": 70.0, "claude-sonnet-4-6": 30.0},
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
                        "amount": "70.0", "requests": 150,
                    },
                    {
                        "product": "chat",
                        "actor": {"type": "user_actor",
                                  "user_id": "user_b",
                                  "email": "b@x",
                                  "name": "Bob"},
                        "amount": "30.0", "requests": 50,
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
        # 30 chat + 70 cc = 100
        assert abs(total - 100.0) < 1.0


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
