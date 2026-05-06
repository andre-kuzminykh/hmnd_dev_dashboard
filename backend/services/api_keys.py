"""F-11 API Keys breakdown — spend / tokens grouped by API key."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from data.db import get_conn
from backend.analytics import Filters


def get_api_keys_breakdown(filters: Filters | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    f = filters or Filters()
    now = now or datetime.utcnow()
    start, end = f.date_range(now)

    sql = """
        SELECT
            ak.id          AS key_id,
            ak.external_id AS external_id,
            COALESCE(ak.name, '(unnamed)') AS name,
            COALESCE(ak.redacted_value, '') AS redacted,
            ak.is_admin    AS is_admin,
            p.name         AS provider,
            COALESCE(u.full_name, '—') AS owner,
            COUNT(ue.id)                                AS requests,
            COALESCE(SUM(ue.tokens_in), 0)              AS tokens_in,
            COALESCE(SUM(ue.tokens_out), 0)             AS tokens_out,
            ROUND(COALESCE(SUM(ue.cost_usd), 0), 2)     AS cost,
            MAX(ue.occurred_at)                         AS last_used
        FROM api_keys ak
        JOIN providers p ON p.id = ak.provider_id
        LEFT JOIN users u ON u.id = ak.owner_user_id
        LEFT JOIN usage_events ue
               ON ue.api_key_id = ak.id
              AND ue.occurred_at BETWEEN ? AND ?
        GROUP BY ak.id
        ORDER BY cost DESC, requests DESC
    """
    s = start.strftime("%Y-%m-%d %H:%M:%S")
    e = end.strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, (s, e)).fetchall()]
    return rows


def get_orphan_usage(filters: Filters | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Usage events без api_key_id — например, cookies-based ChatGPT, не API."""
    f = filters or Filters()
    now = now or datetime.utcnow()
    start, end = f.date_range(now)
    s = start.strftime("%Y-%m-%d %H:%M:%S")
    e = end.strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS requests,
                      COALESCE(SUM(tokens_in), 0)  AS tokens_in,
                      COALESCE(SUM(tokens_out), 0) AS tokens_out,
                      ROUND(COALESCE(SUM(cost_usd), 0), 2) AS cost
               FROM usage_events
               WHERE api_key_id IS NULL
                 AND occurred_at BETWEEN ? AND ?""",
            (s, e),
        ).fetchone()
    return dict(row) if row else {"requests": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0}
