"""F-12 AI Tools Dashboard — tests pinned to requirement IDs."""
from __future__ import annotations

from backend.services.ai_tools import (
    classify_risk,
    get_ai_tools_overview,
    get_high_spenders,
    get_provider_freshness,
    get_users_for_provider,
)


def test_fr_12_1_1_1_freshness(tmp_db):
    f = get_provider_freshness()
    # seed создаёт OpenAI и Anthropic события без api_keys
    assert "openai" in f and "anthropic" in f
    for provider, info in f.items():
        assert {"start_date", "end_date", "source"}.issubset(info.keys())
        assert info["source"] in {"real", "mock", "absent"}


def test_fr_12_1_1_2_overview_keys(tmp_db):
    out = get_ai_tools_overview(period_days=14)
    expected = {"claude_chat_users", "claude_code_users", "chatgpt_active_users", "cursor_active_devs"}
    assert expected.issubset(out.keys())


def test_fr_12_1_1_3_source_mock(tmp_db):
    """После synth_anthropic source должен стать 'mock'."""
    from data.anthropic_mock import synth_anthropic
    synth_anthropic(period_days=3)
    f = get_provider_freshness()
    assert f["anthropic"]["source"] == "mock"


def test_fr_12_1_2_1_users_shape(tmp_db):
    rows = get_users_for_provider("anthropic", period_days=14)
    assert rows
    expected = {"user_name", "messages", "sessions", "lines_added", "commits", "cost"}
    assert expected.issubset(rows[0].keys())
    # пока нет Claude Code telemetry — sessions/lines/commits = None
    for r in rows:
        assert r["sessions"] is None
        assert r["lines_added"] is None
        assert r["commits"] is None


def test_fr_12_1_3_2_chatgpt_flag():
    """Flag-классификация для ChatGPT users по spend."""
    from backend.services.ai_tools import chatgpt_flag
    assert chatgpt_flag(1500) == "High"
    assert chatgpt_flag(700) == "Medium"
    assert chatgpt_flag(250) == "Watch"
    assert chatgpt_flag(50) == ""
    assert chatgpt_flag(0) == ""


def test_fr_12_1_5_1_high_spenders_sort(tmp_db):
    rows = get_high_spenders(period_days=30, threshold_usd=0)
    assert rows
    spends = [r["spend"] for r in rows]
    assert spends == sorted(spends, reverse=True)


def test_fr_12_1_5_2_risk_classification():
    assert classify_risk(2000) == "high"
    assert classify_risk(1000) == "high"
    assert classify_risk(700) == "medium"
    assert classify_risk(500) == "medium"
    assert classify_risk(250) == "low"
    assert classify_risk(199) is None
    assert classify_risk(0) is None


def test_fr_12_1_5_3_dollar_per_msg(tmp_db):
    rows = get_high_spenders(period_days=30, threshold_usd=0)
    for r in rows:
        if r["messages"] == 0:
            assert r["dollar_per_msg"] is None
        else:
            assert r["dollar_per_msg"] is not None
            # round to 2 decimal places, allow rounding tolerance
            assert abs(r["dollar_per_msg"] - r["spend"] / r["messages"]) < 0.01
