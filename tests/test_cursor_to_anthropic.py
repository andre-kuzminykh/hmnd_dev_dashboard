"""Tests for the Cursor→Anthropic event generator."""
from __future__ import annotations

import textwrap
from pathlib import Path


def _write_leaderboard(dir_path: Path, period: str = "2026-04-30_2026-05-06") -> None:
    """Write a tiny leaderboard CSV with two Claude users + one GPT user."""
    (dir_path / f"User_Leaderboard_{period}.csv").write_text(textwrap.dedent("""\
        Email,Name,Agent Completions,Agent Lines,Tab Completions,Tab Lines,Ai Lines,Favorite Model
        olsi@x,Oleg,140,7000,0,0,7000,claude-opus-4-7-thinking-xhigh
        anba@x,Andrey,28,1400,0,0,1400,claude-opus-4-7-thinking-high
        ssam@x,Saeid,200,8000,0,0,8000,gpt-5.5-medium
    """))


def test_generator_produces_anthropic_events(tmp_path, monkeypatch):
    monkeypatch.setenv("HMND_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))
    _write_leaderboard(tmp_path)

    from data.db import init_schema
    init_schema()

    # cursor_analytics is imported lazily by the generator to honour env vars
    import importlib
    import backend.services.cursor_analytics as ca
    importlib.reload(ca)
    import data.cursor_to_anthropic as gen
    importlib.reload(gen)

    report = gen.derive_anthropic_from_cursor()
    assert report["users"] == 2  # only Claude favorites
    assert report["inserted"] >= 168  # 140 + 28 agent events spread over 7 days

    from data.db import get_conn
    with get_conn() as conn:
        # Provider exists
        prov = conn.execute("SELECT id FROM providers WHERE name='anthropic'").fetchone()
        assert prov
        # Cost > 0
        total = conn.execute(
            "SELECT ROUND(SUM(cost_usd), 4) AS s FROM usage_events WHERE provider_id = ?",
            (prov["id"],),
        ).fetchone()["s"]
        assert total > 0
        # Two Claude users have synthetic api_keys
        keys = conn.execute(
            "SELECT name FROM api_keys WHERE provider_id = ? ORDER BY name", (prov["id"],),
        ).fetchall()
        names = [k["name"] for k in keys]
        assert "Oleg" in names and "Andrey" in names
        # No api_key for the GPT-favorite user
        assert "Saeid" not in names


def test_generator_idempotent(tmp_path, monkeypatch):
    """Re-running should DELETE the period and re-INSERT — total stays the same."""
    monkeypatch.setenv("HMND_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))
    _write_leaderboard(tmp_path)

    from data.db import init_schema, get_conn
    init_schema()
    import importlib
    import backend.services.cursor_analytics as ca; importlib.reload(ca)
    import data.cursor_to_anthropic as gen; importlib.reload(gen)

    gen.derive_anthropic_from_cursor()
    with get_conn() as conn:
        n1 = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_events ue "
            "JOIN providers p ON p.id = ue.provider_id WHERE p.name='anthropic'"
        ).fetchone()["n"]

    gen.derive_anthropic_from_cursor()
    with get_conn() as conn:
        n2 = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_events ue "
            "JOIN providers p ON p.id = ue.provider_id WHERE p.name='anthropic'"
        ).fetchone()["n"]
    assert n2 == n1, f"second run produced {n2}, first {n1}"


def test_generator_empty_when_no_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("HMND_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))  # empty dir
    from data.db import init_schema
    init_schema()
    import importlib
    import backend.services.cursor_analytics as ca; importlib.reload(ca)
    import data.cursor_to_anthropic as gen; importlib.reload(gen)

    report = gen.derive_anthropic_from_cursor()
    assert report["users"] == 0
    assert report["inserted"] == 0
