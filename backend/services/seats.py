"""F-03 Seats & Licenses."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from data.db import get_conn


def _recommendation(last_used: str | None, days_now: datetime | None = None) -> str:
    """FR-03.1.1.4."""
    if not last_used:
        return "revoke"
    now = days_now or datetime.utcnow()
    last = datetime.fromisoformat(last_used)
    age = (now - last).days
    if age >= 30:
        return "revoke"
    if age >= 14:
        return "review"
    return "keep"


def get_seats_summary(now: datetime | None = None) -> dict[str, Any]:
    """FR-03.1.1.1."""
    now = now or datetime.utcnow()
    threshold = (now - timedelta(days=30)).isoformat(sep=" ")

    with get_conn() as conn:
        bought = conn.execute("SELECT COUNT(*) AS n FROM seats").fetchone()["n"]
        assigned = conn.execute(
            "SELECT COUNT(*) AS n FROM seats WHERE assigned = 1"
        ).fetchone()["n"]
        active = conn.execute(
            """SELECT COUNT(DISTINCT s.user_id) AS n
               FROM seats s
               JOIN usage_events ue ON ue.user_id = s.user_id
               WHERE s.assigned = 1 AND ue.occurred_at >= ?""",
            (threshold,),
        ).fetchone()["n"]
        # FR-03.1.1.2 — inactive paid seats
        inactive_paid = conn.execute(
            """SELECT COUNT(*) AS n FROM seats
               WHERE assigned = 1
                 AND (last_used_at IS NULL OR last_used_at < ?)""",
            (threshold,),
        ).fetchone()["n"]
        avg_cost = conn.execute(
            "SELECT COALESCE(AVG(monthly_cost_usd), 0) AS c FROM seats"
        ).fetchone()["c"]

    return {
        "bought": int(bought),
        "assigned": int(assigned),
        "active_30d": int(active),
        "inactive_paid": int(inactive_paid),
        "potential_waste_usd": round(inactive_paid * (avg_cost or 0), 2),
    }


def get_seats_table(now: datetime | None = None) -> list[dict[str, Any]]:
    """FR-03.1.1.3."""
    sql = """
        SELECT s.id, u.full_name AS user_name, s.seat_type, p.name AS provider,
               s.assigned, s.assigned_at, s.last_used_at, s.monthly_cost_usd,
               (
                   SELECT COALESCE(SUM(ue.cost_usd), 0)
                   FROM usage_events ue
                   WHERE ue.user_id = s.user_id
                     AND ue.provider_id = s.provider_id
                     AND ue.occurred_at >= datetime('now', '-30 days')
               ) AS usage_30d
        FROM seats s
        LEFT JOIN users u ON u.id = s.user_id
        JOIN providers p ON p.id = s.provider_id
        ORDER BY s.assigned DESC, s.last_used_at ASC
    """
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql).fetchall()]
    for r in rows:
        r["recommendation"] = _recommendation(r["last_used_at"], now)
        r["assigned"] = bool(r["assigned"])
    return rows
