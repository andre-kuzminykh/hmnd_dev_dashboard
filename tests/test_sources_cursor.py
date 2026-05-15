"""F-14 Cursor JSON loader tests."""
from __future__ import annotations

import json
from pathlib import Path


SAMPLE = {
    "period_start": "2026-05-01",
    "period_end":   "2026-05-07",
    "summary": {"active_devs": 2, "total_completions": 600, "total_ai_lines": 18000},
    "models": [
        {"name": "claude-4.6-opus-high-thinking", "requests": 200, "users": 1},
        {"name": "gpt-5.3-codex", "requests": 100, "users": 1},
    ],
    "users": [
        {"email": "u1@x", "name": "User One",  "agent_completions": 400,
         "ai_lines": 12000, "favorite_model": "claude-4.6-opus-high-thinking"},
        {"email": "u2@x", "name": "User Two", "agent_completions": 200,
         "ai_lines": 6000,  "favorite_model": "gpt-5.3-codex"},
    ],
}


def _write(sources_dir: Path, name: str, body=SAMPLE) -> Path:
    sources_dir.mkdir(parents=True, exist_ok=True)
    p = sources_dir / name
    p.write_text(json.dumps(body))
    return p


def test_fr_14_1_2_1_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    _write(tmp_path, "Cursor_20260507.json")
    import importlib
    from data.sources import cursor_json
    importlib.reload(cursor_json)
    files = cursor_json.find_cursor_files()
    assert len(files) == 1
    doc = cursor_json.load_cursor_json(files[0].path)
    assert doc["period_start"] == "2026-05-01"
    assert len(doc["users"]) == 2
    # Every user has required leaderboard fields
    for u in doc["users"]:
        for k in ("email", "name", "agent_completions",
                  "tab_completions", "ai_lines", "favorite_model"):
            assert k in u


def test_fr_14_1_2_2_json_over_csv_priority(tmp_path, monkeypatch):
    """cursor_analytics.load_user_leaderboard should prefer JSON when both
    CSV and JSON describe the same email."""
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))
    # CSV with one number for u1
    (tmp_path / "User_Leaderboard_2026-04-30_2026-05-06.csv").write_text(
        "Email,Name,Agent Completions,Agent Lines,Tab Completions,Tab Lines,Ai Lines,Favorite Model\n"
        "u1@x,User One,1,1,0,0,1,gpt-5.5-medium\n"
    )
    # JSON has different number — must win
    _write(tmp_path, "Cursor_20260507.json")

    import importlib
    import backend.services.cursor_analytics as ca
    importlib.reload(ca)

    rows = ca.load_user_leaderboard()
    by_email = {r["email"]: r for r in rows}
    assert by_email["u1@x"]["ai_lines"] == 12000  # JSON value
    assert by_email["u1@x"]["favorite_model"].startswith("claude")
