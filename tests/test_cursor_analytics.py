"""Tests for the Cursor team analytics CSV loader."""
from __future__ import annotations

import textwrap
from pathlib import Path


def _write_fixtures(dir_path: Path) -> None:
    (dir_path / "User_Leaderboard_2026-04-30_2026-05-06.csv").write_text(textwrap.dedent("""\
        Email,Name,Agent Completions,Agent Lines,Tab Completions,Tab Lines,Ai Lines,Favorite Model
        olsi@x,Oleg,661,61067,0,0,61067,claude-opus-4-7-thinking-xhigh
        ssam@x,Saeid,1086,33399,5,14,33413,gpt-5.5-medium
        anba@x,Andrey,147,11358,0,0,11358,claude-opus-4-7-thinking-high
    """))
    (dir_path / "Team_DAU_Analytics_2026-04-30_2026-05-06.csv").write_text(textwrap.dedent("""\
        Date,Daily Active Users,Cli Dau,Bga Dau,Bugbot Dau
        2026-04-30,41,0,4,0
        2026-05-01,38,0,4,2
    """))
    (dir_path / "Contribution_Analytics_2026-04-30_2026-05-06.csv").write_text(textwrap.dedent("""\
        Date,Composer Total Suggested Diffs,Composer Total Accepted Diffs,Composer Total Green Lines Accepted,Composer Total Red Lines Accepted,Composer Total Green Lines Rejected,Composer Total Red Lines Rejected,Composer Total Green Lines Suggested,Composer Total Red Lines Suggested,Composer Total Lines Suggested,Composer Total Lines Accepted,Tabs Total Suggestions,Tabs Total Accepts,Tabs Total Rejects,Tabs Total Green Lines Accepted,Tabs Total Red Lines Accepted,Tabs Total Green Lines Rejected,Tabs Total Red Lines Rejected,Tabs Total Green Lines Suggested,Tabs Total Red Lines Suggested,Tabs Total Lines Suggested,Tabs Total Lines Accepted,Composer Total Rejected Diffs
        2026-04-30,655,644,24235,6022,56,0,575177,6022,581199,30257,1594,249,1192,362,190,1591,1172,2119,1507,3626,552,11
    """))
    (dir_path / "Analytics_Team_2026-04-30_2026-05-06.csv").write_text(textwrap.dedent("""\
        Date,Chats Chat,Chats Agent Requests,Ai Commits Total Commits,Ai Commits Ai Lines Added,Ai Commits Non Ai Lines Added,Bg Agent P Rs Opened,Bg Agent P Rs Merged,Models Time Series Data
        2026-04-30,0,964,153,29904,1749,4,2,"[{""model_breakdown"":{""claude-opus-4-7-thinking-xhigh"":{""requests"":130,""users"":11},""gpt-5.5-medium"":{""requests"":178,""users"":5}}}]"
    """))


def test_load_user_leaderboard(tmp_path, monkeypatch):
    _write_fixtures(tmp_path)
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    import importlib
    import backend.services.cursor_analytics as ca
    importlib.reload(ca)

    rows = ca.load_user_leaderboard()
    assert len(rows) == 3
    by_email = {r["email"]: r for r in rows}
    assert by_email["olsi@x"]["agent_lines"] == 61067
    assert by_email["olsi@x"]["favorite_model"].startswith("claude")
    # sorted by ai_lines desc
    assert rows[0]["email"] == "olsi@x"
    assert rows[-1]["email"] == "anba@x"
    # period extracted from filename
    assert rows[0]["period_start"] == "2026-04-30"
    assert rows[0]["period_end"] == "2026-05-06"


def test_claude_users_filter(tmp_path, monkeypatch):
    _write_fixtures(tmp_path)
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    import importlib
    import backend.services.cursor_analytics as ca
    importlib.reload(ca)

    rows = ca.claude_users()
    emails = {r["email"] for r in rows}
    # olsi & anba favorite Claude; ssam favorites GPT
    assert emails == {"olsi@x", "anba@x"}


def test_team_dau(tmp_path, monkeypatch):
    _write_fixtures(tmp_path)
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    import importlib
    import backend.services.cursor_analytics as ca
    importlib.reload(ca)

    rows = ca.load_team_dau()
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-04-30"
    assert rows[0]["dau"] == 41
    assert rows[0]["bga_dau"] == 4


def test_models_summary_aggregates_team_analytics(tmp_path, monkeypatch):
    _write_fixtures(tmp_path)
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    import importlib
    import backend.services.cursor_analytics as ca
    importlib.reload(ca)

    rows = ca.model_usage_summary()
    by_model = {r["model"]: r for r in rows}
    assert by_model["claude-opus-4-7-thinking-xhigh"]["requests"] == 130
    assert by_model["gpt-5.5-medium"]["requests"] == 178


def test_later_period_overrides_earlier(tmp_path, monkeypatch):
    """When two periods exist for the same user, later period wins."""
    (tmp_path / "User_Leaderboard_2026-04-23_2026-04-29.csv").write_text(
        "Email,Name,Agent Completions,Agent Lines,Tab Completions,Tab Lines,Ai Lines,Favorite Model\n"
        "olsi@x,Oleg,100,1000,0,0,1000,gpt-5.5-medium\n"
    )
    (tmp_path / "User_Leaderboard_2026-04-30_2026-05-06.csv").write_text(
        "Email,Name,Agent Completions,Agent Lines,Tab Completions,Tab Lines,Ai Lines,Favorite Model\n"
        "olsi@x,Oleg,500,5000,0,0,5000,claude-opus-4-7-thinking-xhigh\n"
    )
    monkeypatch.setenv("HMND_CURSOR_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    import importlib
    import backend.services.cursor_analytics as ca
    importlib.reload(ca)

    rows = ca.load_user_leaderboard()
    assert len(rows) == 1
    assert rows[0]["agent_lines"] == 5000  # later period wins
    assert rows[0]["favorite_model"].startswith("claude")
