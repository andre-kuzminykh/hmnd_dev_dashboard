"""Management insights: concentration risk, idle paid seats, per-developer ROI.

Powers the Insights section on the dashboard with the metrics most useful
for management decisions: where is money concentrated, which paid seats
are wasted, and what's the AI ROI per developer.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Optional

from data.db import get_conn


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ---- Top-N concentration risk ----

def get_top_n_concentration(
    top_n: int = 5,
    period_days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return top N spenders and their cumulative share of total spend.

    Output:
        {
            "top_n": [{user_id, user_name, email, spend_usd}, ...],
            "top_n_spend": float,
            "total_spend": float,
            "concentration_pct": float,        # top_n / total * 100
            "total_users": int,
            "period_from": ISO date, "period_to": ISO date,
        }
    """
    now = now or datetime.utcnow()
    start = (now - timedelta(days=period_days)).strftime("%Y-%m-%d %H:%M:%S")
    end = now.strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        all_rows = conn.execute(
            """SELECT u.id AS user_id, u.full_name AS user_name, u.email,
                      ROUND(SUM(ue.cost_usd), 2) AS spend_usd
               FROM usage_events ue
               JOIN users u ON u.id = ue.user_id
               WHERE ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.id
               ORDER BY spend_usd DESC""",
            (start, end),
        ).fetchall()

    spenders = [dict(r) for r in all_rows if (r["spend_usd"] or 0) > 0]
    total = sum(s["spend_usd"] for s in spenders)
    top = spenders[:top_n]
    top_spend = sum(s["spend_usd"] for s in top)
    concentration = (top_spend / total * 100) if total > 0 else 0.0

    return {
        "top_n": top,
        "top_n_spend": round(top_spend, 2),
        "total_spend": round(total, 2),
        "concentration_pct": round(concentration, 1),
        "total_users": len(spenders),
        "period_from": start[:10],
        "period_to": end[:10],
    }


def concentration_risk_label(pct: float) -> str:
    """Categorical risk for the headline: <30 low, 30–60 medium, >60 high."""
    if pct >= 60:
        return "high"
    if pct >= 30:
        return "medium"
    return "low"


# ---- Idle paid seats ----

def get_idle_paid_seats(
    threshold_days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Seats that are paid + assigned but show no activity in the window.

    Output:
        {
            "rows": [{seat_id, user_name, seat_type, provider, monthly_cost_usd,
                      last_used_at, days_idle, recommendation}, ...],
            "idle_count": int,
            "wasted_monthly_usd": float,
            "wasted_annual_usd": float,
            "threshold_days": int,
        }
    """
    now = now or datetime.utcnow()
    cutoff = (now - timedelta(days=threshold_days)).isoformat(sep=" ")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT s.id AS seat_id,
                      COALESCE(u.full_name, '(unassigned)') AS user_name,
                      u.email,
                      s.seat_type,
                      p.name AS provider,
                      s.monthly_cost_usd,
                      s.last_used_at,
                      s.assigned
               FROM seats s
               JOIN providers p ON p.id = s.provider_id
               LEFT JOIN users u ON u.id = s.user_id
               WHERE s.assigned = 1
                 AND (s.last_used_at IS NULL OR s.last_used_at < ?)
               ORDER BY s.last_used_at ASC NULLS FIRST""",
            (cutoff,),
        ).fetchall()

    idle = []
    wasted = 0.0
    for r in rows:
        d = dict(r)
        last_used = d.get("last_used_at")
        if last_used:
            try:
                last_dt = datetime.fromisoformat(last_used)
                days_idle = (now - last_dt).days
            except ValueError:
                days_idle = threshold_days
        else:
            days_idle = 9999
        d["days_idle"] = days_idle
        cost = float(d.get("monthly_cost_usd") or 0)
        wasted += cost
        d["recommendation"] = "revoke" if days_idle >= threshold_days else "review"
        idle.append(d)

    return {
        "rows": idle,
        "idle_count": len(idle),
        "wasted_monthly_usd": round(wasted, 2),
        "wasted_annual_usd": round(wasted * 12, 2),
        "threshold_days": threshold_days,
    }


# ---- Per-developer ROI ----

def get_developer_roi(
    dev_rate_usd_per_hour: float | None = None,
    lines_per_hour: float | None = None,
    period_days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """For each Cursor developer (we have their AI lines from the leaderboard),
    estimate value_saved = ai_lines / lines_per_hour * dev_rate.
    Combine with their AI spend (cursor synth + OpenAI/Anthropic if matched
    by email) → ROI ratio.

    Rates default to typical assumptions, override with env:
        HMND_DEV_RATE_USD_PER_HOUR (default 80)
        HMND_LINES_PER_HOUR        (default 50)
    """
    rate = dev_rate_usd_per_hour if dev_rate_usd_per_hour is not None else _env_float(
        "HMND_DEV_RATE_USD_PER_HOUR", 80.0
    )
    lph = lines_per_hour if lines_per_hour is not None else _env_float(
        "HMND_LINES_PER_HOUR", 50.0
    )
    now = now or datetime.utcnow()
    start = (now - timedelta(days=period_days)).strftime("%Y-%m-%d %H:%M:%S")
    end = now.strftime("%Y-%m-%d %H:%M:%S")

    # Pull AI-line totals from Cursor leaderboard (CSV-backed).
    try:
        from backend.services.cursor_analytics import load_user_leaderboard
        leaders = load_user_leaderboard()
    except Exception:
        leaders = []

    # Spend by user email (matched via users table).
    with get_conn() as conn:
        spend_rows = conn.execute(
            """SELECT u.email, ROUND(SUM(ue.cost_usd), 2) AS spend_usd
               FROM usage_events ue
               JOIN users u ON u.id = ue.user_id
               WHERE ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.email""",
            (start, end),
        ).fetchall()
    spend_by_email = {r["email"]: r["spend_usd"] or 0 for r in spend_rows}

    out: list[dict[str, Any]] = []
    for ld in leaders:
        email = ld.get("email") or ""
        ai_lines = int(ld.get("ai_lines") or 0)
        spend = float(spend_by_email.get(email, 0.0))
        hours_saved = ai_lines / lph if lph > 0 else 0
        value_saved = hours_saved * rate
        # ROI multiple: value vs cost. Cap to avoid div-by-zero blowup.
        if spend > 0:
            roi_multiple = round(value_saved / spend, 1)
        else:
            roi_multiple = None    # no spend tracked yet → can't compute
        out.append({
            "email": email,
            "name": ld.get("name") or email.split("@")[0],
            "ai_lines": ai_lines,
            "spend_usd": round(spend, 2),
            "hours_saved": round(hours_saved, 1),
            "value_saved_usd": round(value_saved, 2),
            "roi_multiple": roi_multiple,
            "favorite_model": ld.get("favorite_model") or "",
        })
    # Sort by value_saved desc so top performers float up.
    out.sort(key=lambda r: r["value_saved_usd"], reverse=True)

    total_lines = sum(r["ai_lines"] for r in out)
    total_spend = sum(r["spend_usd"] for r in out)
    total_value = sum(r["value_saved_usd"] for r in out)
    team_roi = round(total_value / total_spend, 1) if total_spend > 0 else None

    return {
        "rows": out,
        "team": {
            "total_developers": len(out),
            "total_ai_lines": total_lines,
            "total_spend_usd": round(total_spend, 2),
            "total_hours_saved": round(total_value / rate, 1) if rate > 0 else 0,
            "total_value_saved_usd": round(total_value, 2),
            "team_roi_multiple": team_roi,
        },
        "assumptions": {
            "dev_rate_usd_per_hour": rate,
            "lines_per_hour": lph,
        },
    }
