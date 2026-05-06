"""F-05 Repositories."""
from __future__ import annotations

from backend.services.repos import _risk, get_repos_overview
from backend.analytics import Filters


def test_fr_05_1_1_3_risk():
    assert _risk(70, True) == "high"
    assert _risk(70, False) == "medium"
    assert _risk(45, False) == "medium"
    assert _risk(20, True) == "low"
    assert _risk(20, False) == "low"


def test_repos_overview_shape(tmp_db):
    rows = get_repos_overview(Filters(period_days=14))
    assert rows
    expected = {"repo", "is_critical", "commits", "prs", "lines_added",
                "ai_lines", "ai_code_pct", "risk"}
    assert expected.issubset(rows[0].keys())
    for r in rows:
        assert r["risk"] in {"low", "medium", "high"}
