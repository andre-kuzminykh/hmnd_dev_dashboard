"""F-02 Costs by People."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from data.db import get_conn
from backend.analytics import Filters, api_key_clause, provider_clause, team_clause


def _limit_status(cost: float, limit: float) -> str:
    """FR-02.1.1.2."""
    if not limit or limit <= 0:
        return "ok"
    if cost >= limit:
        return "breach"
    if cost >= 0.8 * limit:
        return "warn"
    return "ok"


def get_costs_by_user(filters: Filters | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    """FR-02.1.1.1."""
    f = filters or Filters()
    now = now or datetime.utcnow()
    start, end = f.date_range(now)
    p_clause, p_params = provider_clause(f.provider, "p")
    t_clause, t_params = team_clause(f.team, "t")
    k_clause, k_params = api_key_clause(f.api_key_id, "ue")

    sql = f"""
        SELECT
            u.id        AS user_id,
            u.full_name AS user_name,
            COALESCE(t.name, '—') AS team,
            u.monthly_limit_usd   AS monthly_limit,
            ROUND(SUM(CASE WHEN p.name='openai'    THEN ue.cost_usd ELSE 0 END), 2) AS cost_openai,
            ROUND(SUM(CASE WHEN p.name='anthropic' THEN ue.cost_usd ELSE 0 END), 2) AS cost_anthropic,
            SUM(ue.tokens_in)  AS tokens_in,
            SUM(ue.tokens_out) AS tokens_out,
            GROUP_CONCAT(DISTINCT m.name) AS models,
            MAX(ue.occurred_at) AS last_activity
        FROM usage_events ue
        JOIN users u    ON u.id = ue.user_id
        LEFT JOIN teams t ON t.id = u.team_id
        JOIN providers p ON p.id = ue.provider_id
        JOIN models m ON m.id = ue.model_id
        WHERE ue.occurred_at BETWEEN ? AND ?
        {p_clause}
        {t_clause}
        {k_clause}
        GROUP BY u.id
        ORDER BY (cost_openai + cost_anthropic) DESC
    """
    params = [start.isoformat(sep=" "), end.isoformat(sep=" ")] + p_params + t_params + k_params
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    out = []
    for r in rows:
        total = (r["cost_openai"] or 0) + (r["cost_anthropic"] or 0)
        r["cost_total"] = round(total, 2)
        r["models"] = r["models"].split(",") if r["models"] else []
        r["limit_status"] = _limit_status(total, r["monthly_limit"])
        out.append(r)
    return out


def detect_spend_spikes(now: datetime | None = None) -> list[dict[str, Any]]:
    """FR-02.1.2.1, NFR-02.1.2.1 — работаем по daily_costs."""
    now = now or datetime.utcnow()
    today = now.date().isoformat()
    horizon_start = (now - timedelta(days=30)).date().isoformat()

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT user_id,
                   SUM(CASE WHEN day = ? THEN cost_usd ELSE 0 END) AS today_cost,
                   AVG(CASE WHEN day < ? THEN cost_usd END)        AS avg_cost
            FROM daily_costs
            WHERE day >= ?
            GROUP BY user_id
            """,
            (today, today, horizon_start),
        ).fetchall()
    spikes = []
    for r in rows:
        today_cost = r["today_cost"] or 0
        avg_cost = r["avg_cost"] or 0
        if today_cost > 20 and (avg_cost == 0 or today_cost > 3 * avg_cost):
            spikes.append(
                {
                    "user_id": r["user_id"],
                    "today_cost": round(today_cost, 2),
                    "avg_cost": round(avg_cost, 2),
                    "ratio": round(today_cost / max(avg_cost, 0.01), 2),
                }
            )
    return spikes


def heatmap_user_day(filters: Filters | None = None, now: datetime | None = None) -> list[dict]:
    """Возвращает сетку user × day для heatmap (FR-02.1.1.4 input)."""
    f = filters or Filters()
    now = now or datetime.utcnow()
    start, end = f.date_range(now)
    sql = """
        SELECT u.full_name AS user_name,
               date(ue.occurred_at) AS day,
               SUM(ue.tokens_in + ue.tokens_out) AS tokens
        FROM usage_events ue
        JOIN users u ON u.id = ue.user_id
        WHERE ue.occurred_at BETWEEN ? AND ?
        GROUP BY u.id, day
    """
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, (start.isoformat(sep=" "), end.isoformat(sep=" "))).fetchall()]
