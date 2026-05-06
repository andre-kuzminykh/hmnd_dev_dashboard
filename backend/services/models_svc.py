"""F-07 Models breakdown."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from data.db import get_conn
from backend.analytics import Filters, api_key_clause, safe_div


def get_models_breakdown(filters: Filters | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    """FR-07.1.1.1, FR-07.1.1.2."""
    f = filters or Filters()
    now = now or datetime.utcnow()
    start, end = f.date_range(now)
    k_clause, k_params = api_key_clause(f.api_key_id, "ue")

    sql = f"""
        SELECT m.id AS model_id,
               m.name AS model,
               p.name AS provider,
               COUNT(*)              AS requests,
               SUM(ue.tokens_in + ue.tokens_out) AS tokens,
               ROUND(SUM(ue.cost_usd), 2) AS cost,
               ROUND(AVG(ue.latency_ms), 0)  AS avg_latency,
               SUM(CASE WHEN ue.is_error THEN 1 ELSE 0 END) AS errors
        FROM usage_events ue
        JOIN models m ON m.id = ue.model_id
        JOIN providers p ON p.id = ue.provider_id
        WHERE ue.occurred_at BETWEEN ? AND ?
        {k_clause}
        GROUP BY m.id
        ORDER BY cost DESC
    """
    params = [start.isoformat(sep=" "), end.isoformat(sep=" ")] + k_params
    top_users_sql = f"""
        SELECT u.full_name AS user_name, ROUND(SUM(ue.cost_usd), 2) AS cost
        FROM usage_events ue
        JOIN users u ON u.id = ue.user_id
        WHERE ue.model_id = ? AND ue.occurred_at BETWEEN ? AND ?
        {k_clause}
        GROUP BY u.id
        ORDER BY cost DESC
        LIMIT 3
    """
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        for r in rows:
            top_params = [r["model_id"], start.isoformat(sep=" "), end.isoformat(sep=" ")] + k_params
            top = conn.execute(top_users_sql, top_params).fetchall()
            r["main_users"] = [t["user_name"] for t in top]
            r["error_rate"] = (
                round(safe_div(r["errors"], r["requests"]) * 100, 2)
                if r["requests"]
                else None
            )
    return rows
