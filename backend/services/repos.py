"""F-05 Repositories & AI Code %."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from data.db import get_conn
from backend.analytics import Filters, safe_div


def _risk(ai_pct: float, is_critical: bool) -> str:
    """FR-05.1.1.3."""
    if is_critical and ai_pct > 60:
        return "high"
    if ai_pct > 40:
        return "medium"
    return "low"


def get_repos_overview(filters: Filters | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    """FR-05.1.1.1."""
    f = filters or Filters()
    now = now or datetime.utcnow()
    start, end = f.date_range(now)
    s, e = start.isoformat(sep=" "), end.isoformat(sep=" ")

    sql = """
        SELECT
            r.id AS repo_id,
            r.name AS repo,
            r.is_critical,
            (SELECT COUNT(*) FROM commits c
             WHERE c.repo_id = r.id AND c.authored_at BETWEEN ? AND ?) AS commits,
            (SELECT COUNT(*) FROM pull_requests pr
             WHERE pr.repo_id = r.id AND pr.created_at BETWEEN ? AND ?) AS prs,
            (SELECT COALESCE(SUM(c.additions),0) FROM commits c
             WHERE c.repo_id = r.id AND c.authored_at BETWEEN ? AND ?) AS lines_added,
            (SELECT COALESCE(SUM(att.ai_lines),0) FROM ai_code_attribution att
             WHERE att.repo_id = r.id AND att.detected_at BETWEEN ? AND ?) AS ai_lines,
            (SELECT COALESCE(SUM(att.total_lines),0) FROM ai_code_attribution att
             WHERE att.repo_id = r.id AND att.detected_at BETWEEN ? AND ?) AS attrib_total
        FROM repositories r
        ORDER BY r.is_critical DESC, r.name
    """
    params = [s, e] * 5
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        attrib_total = r["attrib_total"] or 0
        r["ai_code_pct"] = round(safe_div(r["ai_lines"], attrib_total) * 100, 1) if attrib_total else 0.0
        r["risk"] = _risk(r["ai_code_pct"], bool(r["is_critical"]))
    return rows
