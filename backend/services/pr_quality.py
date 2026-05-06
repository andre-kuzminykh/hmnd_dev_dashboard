"""F-06 PR Quality."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from data.db import get_conn
from backend.analytics import Filters, safe_div


def risk_score(ai_pct: float, critical_files: int, review_comments: int, bug_count: int) -> float:
    """FR-06.1.1.1."""
    return round(
        (ai_pct / 100.0)
        * (1 + critical_files)
        * max(1, review_comments)
        * (1 + bug_count),
        2,
    )


def risk_badge(score: float) -> str:
    """FR-06.1.1.2."""
    if score >= 5.0:
        return "high"
    if score >= 2.0:
        return "medium"
    return "low"


def get_pr_quality(filters: Filters | None = None, repo: Optional[str] = None,
                   now: datetime | None = None) -> list[dict[str, Any]]:
    """FR-06.1.1.3."""
    f = filters or Filters()
    now = now or datetime.utcnow()
    start, end = f.date_range(now)

    where = ["pr.created_at BETWEEN ? AND ?"]
    params: list[Any] = [start.isoformat(sep=" "), end.isoformat(sep=" ")]
    if repo:
        where.append("r.name = ?")
        params.append(repo)
    where_sql = " AND ".join(where)

    sql = f"""
        SELECT
            pr.id, pr.number, pr.title, pr.state, pr.merged_at,
            r.name AS repo, u.full_name AS author,
            pr.additions, pr.deletions, pr.review_comments,
            pr.critical_files_changed, pr.bug_count, pr.rolled_back, pr.has_human_review,
            COALESCE((SELECT SUM(att.ai_lines) FROM ai_code_attribution att WHERE att.pr_id = pr.id), 0)    AS ai_lines,
            COALESCE((SELECT SUM(att.total_lines) FROM ai_code_attribution att WHERE att.pr_id = pr.id), 0) AS total_lines
        FROM pull_requests pr
        JOIN repositories r ON r.id = pr.repo_id
        LEFT JOIN users u ON u.id = pr.author_id
        WHERE {where_sql}
    """
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        ai_pct = safe_div(r["ai_lines"], r["total_lines"]) * 100 if r["total_lines"] else 0.0
        r["ai_code_pct"] = round(ai_pct, 1)
        r["risk_score"] = risk_score(
            r["ai_code_pct"],
            r["critical_files_changed"] or 0,
            r["review_comments"] or 0,
            r["bug_count"] or 0,
        )
        r["risk"] = risk_badge(r["risk_score"])
        r["has_human_review"] = bool(r["has_human_review"])
        r["rolled_back"] = bool(r["rolled_back"])
    rows.sort(key=lambda x: x["risk_score"], reverse=True)
    return rows
