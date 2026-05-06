"""F-04 Developer AI Usage."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from data.db import get_conn
from backend.analytics import Filters, safe_div, team_clause


def get_developer_usage(filters: Filters | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    """FR-04.1.1.1, FR-04.1.1.2."""
    f = filters or Filters()
    now = now or datetime.utcnow()
    start, end = f.date_range(now)
    t_clause, t_params = team_clause(f.team, "t")
    # When an api_key drill-down is active, only the AI usage subqueries are
    # filtered. Repos / PRs / attribution come from GitHub data and are not
    # tied to API keys.
    key_filter_sql = ""
    key_filter_params: list[Any] = []
    if f.api_key_id:
        key_filter_sql = " AND ue.api_key_id = ? "
        key_filter_params = [f.api_key_id]

    sql = f"""
        SELECT
            u.id AS user_id,
            u.full_name AS user_name,
            COALESCE(t.name, '—') AS team,
            (SELECT COUNT(*) FROM usage_events ue
             WHERE ue.user_id = u.id AND ue.occurred_at BETWEEN ? AND ?
             {key_filter_sql}) AS ai_requests,
            (SELECT COALESCE(SUM(ue.tokens_in + ue.tokens_out), 0)
             FROM usage_events ue WHERE ue.user_id = u.id AND ue.occurred_at BETWEEN ? AND ?
             {key_filter_sql}) AS tokens,
            (SELECT COALESCE(SUM(ue.cost_usd), 0)
             FROM usage_events ue WHERE ue.user_id = u.id AND ue.occurred_at BETWEEN ? AND ?
             {key_filter_sql}) AS cost,
            (SELECT COUNT(DISTINCT c.repo_id) FROM commits c
             WHERE c.author_id = u.id AND c.authored_at BETWEEN ? AND ?) AS repos_touched,
            (SELECT COUNT(*) FROM pull_requests pr
             WHERE pr.author_id = u.id AND pr.created_at BETWEEN ? AND ?) AS prs,
            (SELECT COALESCE(SUM(att.ai_lines), 0) FROM ai_code_attribution att
             WHERE att.user_id = u.id AND att.detected_at BETWEEN ? AND ?) AS ai_lines,
            (SELECT COALESCE(SUM(att.total_lines), 0) FROM ai_code_attribution att
             WHERE att.user_id = u.id AND att.detected_at BETWEEN ? AND ?) AS total_lines,
            (SELECT COALESCE(SUM(pr.review_comments), 0) FROM pull_requests pr
             WHERE pr.author_id = u.id AND pr.created_at BETWEEN ? AND ?) AS review_issues
        FROM users u
        LEFT JOIN teams t ON t.id = u.team_id
        WHERE 1 = 1 {t_clause}
        ORDER BY cost DESC
    """
    s = start.isoformat(sep=" ")
    e = end.isoformat(sep=" ")
    # 3 usage_events subqueries (with optional api_key clause) + 5 GitHub subqueries.
    params: list[Any] = []
    for _ in range(3):
        params += [s, e] + key_filter_params
    for _ in range(5):
        params += [s, e]
    params += t_params
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        # FR-04.1.1.2 — ai_code_pct, None если total_lines=0
        if r["total_lines"]:
            r["ai_code_pct"] = round(safe_div(r["ai_lines"], r["total_lines"]) * 100, 1)
        else:
            r["ai_code_pct"] = None
        r["cost"] = round(r["cost"] or 0, 2)
    return rows
