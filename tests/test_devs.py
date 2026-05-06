"""F-04 Developer usage."""
from __future__ import annotations

from backend.analytics import Filters
from backend.services.developers import get_developer_usage


def test_fr_04_1_1_2_ai_code_pct(tmp_db):
    rows = get_developer_usage(Filters(period_days=14))
    assert rows
    for r in rows:
        if r["total_lines"] == 0:
            assert r["ai_code_pct"] is None
        else:
            assert 0 <= r["ai_code_pct"] <= 100
