"""F-14 Cursor JSON loader tests — uses the real Cursor admin pull schema
with rollups.perUser + raw.spend.teamMemberSpend.
"""
from __future__ import annotations

import json
from pathlib import Path


def _minimal_cursor_doc() -> dict:
    return {
        "_meta": {
            "provider": "cursor",
            "version": "1.0",
            "rangeStart": "2026-05-01T00:00:00Z",
            "rangeEnd": "2026-05-07T23:59:59Z",
            "pulledAt": "2026-05-08T00:00:00Z",
        },
        "rollups": {
            "activeDevs": 2, "totalMembers": 2,
            "totalSpend": 5.0, "totalLines": 18000,
            "totalAccepts": 600, "totalAgent": 100,
            "perUser": {
                "u1@x": {"lines": 12000, "accepts": 400, "agent": 50},
                "u2@x": {"lines": 6000,  "accepts": 200, "agent": 50},
            },
        },
        "raw": {
            "members": {"teamMembers": [
                {"name": "User One",  "email": "u1@x", "id": "u1", "role": "member"},
                {"name": "User Two",  "email": "u2@x", "id": "u2", "role": "member"},
            ]},
            "usage": {"data": []},
            "spend": {"teamMemberSpend": [
                {"userId": "u1", "email": "u1@x", "name": "User One",
                 "spendCents": 100, "includedSpendCents": 200},
                {"userId": "u2", "email": "u2@x", "name": "User Two",
                 "spendCents": 50,  "includedSpendCents": 150},
            ]},
        },
    }


def _write(sources_dir: Path, name: str, body=None) -> Path:
    sources_dir.mkdir(parents=True, exist_ok=True)
    p = sources_dir / name
    p.write_text(json.dumps(body if body is not None else _minimal_cursor_doc()))
    return p


def test_fr_14_1_2_1_shape(tmp_path, monkeypatch):
    """Loader reads users + writes provider='cursor' events."""
    monkeypatch.setenv("HMND_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    from data.db import init_schema, get_conn
    init_schema()
    p = _write(tmp_path, "Cursor_20260507.json")

    import importlib
    from data.sources import cursor_json
    importlib.reload(cursor_json)
    r = cursor_json.load_cursor_json(p)
    assert r["users"] == 2
    assert r["inserted"] > 0

    with get_conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_events ue "
            "JOIN providers p ON p.id = ue.provider_id WHERE p.name='cursor'"
        ).fetchone()["n"]
    assert n > 0


def test_fr_14_1_2_2_json_over_csv_priority(tmp_path, monkeypatch):
    """cursor_analytics.load_user_leaderboard prefers JSON values over CSV."""
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))
    # CSV value
    (tmp_path / "User_Leaderboard_2026-04-30_2026-05-06.csv").write_text(
        "Email,Name,Agent Completions,Agent Lines,Tab Completions,Tab Lines,Ai Lines,Favorite Model\n"
        "u1@x,User One,1,1,0,0,1,gpt-5.5-medium\n"
    )
    # JSON value differs and must win
    _write(tmp_path, "Cursor_20260507.json")

    import importlib
    import backend.services.cursor_analytics as ca
    importlib.reload(ca)
    rows = ca.load_user_leaderboard()
    by_email = {r["email"]: r for r in rows}
    # JSON gave 12000 lines for u1, CSV gave 1
    assert by_email["u1@x"]["ai_lines"] == 12000


def test_loader_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("HMND_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    from data.db import init_schema, get_conn
    init_schema()
    p = _write(tmp_path, "Cursor_20260507.json")
    import importlib
    from data.sources import cursor_json
    importlib.reload(cursor_json)
    cursor_json.load_cursor_json(p)
    with get_conn() as conn:
        n1 = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_events ue "
            "JOIN providers p ON p.id = ue.provider_id WHERE p.name='cursor'"
        ).fetchone()["n"]
    cursor_json.load_cursor_json(p)
    with get_conn() as conn:
        n2 = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_events ue "
            "JOIN providers p ON p.id = ue.provider_id WHERE p.name='cursor'"
        ).fetchone()["n"]
    assert n1 == n2 and n1 > 0
