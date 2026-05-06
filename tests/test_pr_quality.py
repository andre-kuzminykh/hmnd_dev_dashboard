"""F-06 PR Quality."""
from __future__ import annotations

from backend.services.pr_quality import risk_badge, risk_score, get_pr_quality
from backend.analytics import Filters


def test_fr_06_1_1_1_risk_score_formula():
    # AI%=80 => 0.8; critical=3 => *4; review=2 => *2; bug=1 => *2 → 0.8 * 4 * 2 * 2 = 12.8
    assert risk_score(80, 3, 2, 1) == 12.8
    # пограничные значения
    assert risk_score(0, 0, 0, 0) == 0.0
    # review_comments=0 умножается на max(1, ...) = 1
    assert risk_score(50, 0, 0, 0) == 0.5


def test_fr_06_1_1_2_risk_badge():
    assert risk_badge(5.0) == "high"
    assert risk_badge(7.0) == "high"
    assert risk_badge(3.0) == "medium"
    assert risk_badge(1.0) == "low"


def test_fr_06_1_1_3_pr_quality_sorted_desc(tmp_db):
    rows = get_pr_quality(Filters(period_days=14))
    if rows:
        scores = [r["risk_score"] for r in rows]
        assert scores == sorted(scores, reverse=True)
