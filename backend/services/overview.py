"""F-01 Executive Overview — KPI и временные ряды."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from data.db import get_conn
from backend.analytics import (
    Filters, api_key_clause, org_clause, pct_delta, provider_clause, safe_div, team_clause,
)


def _kpis_in_window(conn, start: datetime, end: datetime, f: Filters) -> dict[str, Any]:
    p_clause, p_params = provider_clause(f.provider, "p")
    t_clause, t_params = team_clause(f.team, "t")
    o_clause, o_params = org_clause(f.organization, "ue")
    k_clause, k_params = api_key_clause(f.api_key_id, "ue")

    # FR-01.1.1.1 — основной набор метрик.
    # tokens_in is stored as the raw 'input_tokens' value from each provider
    # API. For OpenAI that field already includes cached input tokens and is
    # the same number Platform UI displays as 'Total tokens' / 'input tokens'
    # — so we show it as-is to match the billing UI. tokens_cached is kept
    # as a separate aggregate so we can break it out if needed.
    sql = f"""
        SELECT
            COALESCE(SUM(ue.cost_usd), 0)        AS total_spend,
            COALESCE(SUM(ue.tokens_in), 0)       AS tokens_in,
            COALESCE(SUM(ue.tokens_out), 0)      AS tokens_out,
            COALESCE(SUM(COALESCE(ue.tokens_cached, 0)), 0)  AS tokens_cached,
            COALESCE(COUNT(DISTINCT ue.user_id), 0) AS active_users
        FROM usage_events ue
        JOIN users u    ON u.id = ue.user_id
        LEFT JOIN teams t ON t.id = u.team_id
        JOIN providers p ON p.id = ue.provider_id
        WHERE ue.occurred_at BETWEEN ? AND ?
        {p_clause}
        {t_clause}
        {o_clause}
        {k_clause}
    """
    params = (
        [start.isoformat(sep=" "), end.isoformat(sep=" ")]
        + p_params + t_params + o_params + k_params
    )
    row = conn.execute(sql, params).fetchone()
    return dict(row)


def _seats_used(conn, f: Filters) -> int:
    p_clause, p_params = provider_clause(f.provider, "p")
    sql = f"""
        SELECT COUNT(*) AS seats_used
        FROM seats s
        JOIN providers p ON p.id = s.provider_id
        WHERE s.assigned = 1 {p_clause}
    """
    return conn.execute(sql, p_params).fetchone()["seats_used"]


def _ai_code_share(conn, start: datetime, end: datetime) -> float:
    """ai_code_pct по всем PR в окне."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(att.ai_lines),0) AS ai_lines,
               COALESCE(SUM(att.total_lines),0) AS total_lines
        FROM ai_code_attribution att
        LEFT JOIN pull_requests pr ON pr.id = att.pr_id
        WHERE COALESCE(pr.merged_at, att.detected_at) BETWEEN ? AND ?
        """,
        (start.isoformat(sep=" "), end.isoformat(sep=" ")),
    ).fetchone()
    pct = safe_div(row["ai_lines"], row["total_lines"], default=0.0) * 100
    return round(pct, 1)


def _suspicious_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM alerts WHERE status='new'"
    ).fetchone()["n"]


def _provider_reported_total(conn, start: datetime, end: datetime, provider: str) -> float | None:
    """Authoritative org-level spend reported by the provider's billing API.
    Pulled by the sync into provider_totals; None when no rows exist yet."""
    if provider == "all":
        sql = (
            "SELECT COALESCE(SUM(pt.cost_usd), 0) AS total FROM provider_totals pt "
            "WHERE pt.day BETWEEN ? AND ?"
        )
        params = [start.date().isoformat(), end.date().isoformat()]
    else:
        sql = (
            "SELECT COALESCE(SUM(pt.cost_usd), 0) AS total FROM provider_totals pt "
            "JOIN providers p ON p.id = pt.provider_id "
            "WHERE p.name = ? AND pt.day BETWEEN ? AND ?"
        )
        params = [provider, start.date().isoformat(), end.date().isoformat()]
    row = conn.execute(sql, params).fetchone()
    if row and row["total"] is not None:
        # Only return when at least one provider_totals row exists for the period.
        check = conn.execute(
            "SELECT COUNT(*) AS n FROM provider_totals WHERE day BETWEEN ? AND ?",
            (start.date().isoformat(), end.date().isoformat()),
        ).fetchone()
        if check and check["n"]:
            return float(row["total"])
    return None


def get_source_freshness() -> list[dict[str, Any]]:
    """Per-source data-freshness summary: when did each provider last log
    a usage event. Used to show 'last data May 13' / 'live (today)' chips
    so the user doesn't think a sparse 'Today' view is a bug — it just
    reflects which sources actually have data for today.
    """
    raw: list[dict[str, Any]] = []
    today = datetime.utcnow().date()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT p.name AS provider,
                      COALESCE(o.label, '') AS org_label,
                      MAX(date(ue.occurred_at)) AS last_day,
                      MIN(date(ue.occurred_at)) AS first_day,
                      COUNT(*) AS events
               FROM usage_events ue
               JOIN providers p ON p.id = ue.provider_id
               LEFT JOIN organizations o ON o.id = ue.organization_id
               GROUP BY p.id, o.id
               ORDER BY p.name, o.label"""
        ).fetchall()
    for r in rows:
        if not r["last_day"]:
            continue
        last = datetime.fromisoformat(r["last_day"]).date()
        days_old = (today - last).days
        raw.append({
            "provider": r["provider"],
            "org_label": r["org_label"] or "",
            "first_day": r["first_day"],
            "last_day": r["last_day"],
            "days_old": days_old,
            "events": int(r["events"] or 0),
            "is_live": days_old <= 1,
        })

    # Hide untagged residual rows for providers that also have at least one
    # properly-tagged row — those are legacy events from before org tagging
    # was wired in. Showing them as 'OpenAI · 10d stale · last 2026-05-05'
    # looks like a phantom source to the user.
    providers_with_orgs = {r["provider"] for r in raw if r["org_label"]}
    return [
        r for r in raw
        if r["org_label"] or r["provider"] not in providers_with_orgs
    ]


def get_overview_kpis(filters: Filters | None = None, now: datetime | None = None) -> dict[str, Any]:
    """FR-01.1.1.1, FR-01.1.1.2, FR-01.1.1.3.

    Возвращает dict со значениями текущего периода и `_delta` для каждого числового KPI.
    """
    f = filters or Filters()
    now = now or datetime.utcnow()
    start, end = f.date_range(now)
    prev_start, prev_end = f.previous_range(now)

    with get_conn() as conn:
        cur = _kpis_in_window(conn, start, end, f)
        prev = _kpis_in_window(conn, prev_start, prev_end, f)
        seats_used = _seats_used(conn, f)
        ai_share = _ai_code_share(conn, start, end)
        ai_share_prev = _ai_code_share(conn, prev_start, prev_end)
        suspicious = _suspicious_count(conn)
        reported_total = _provider_reported_total(conn, start, end, f.provider)
        reported_total_prev = _provider_reported_total(conn, prev_start, prev_end, f.provider)

    # provider_totals is stored at the (provider, day) grain — no
    # organization_id, no api_key_id, no team. So it only matches the user's
    # filter when those narrower filters aren't active. Otherwise we'd show an
    # org-wide total against a user-narrowed events breakdown.
    # Additionally, only OpenAI populates provider_totals today (via /costs
    # admin API). Anthropic and Cursor are JSON-only and have no rows there.
    # So 'All sources' must use events-sum — otherwise the headline collapses
    # to JUST the OpenAI portion (the $537 vs $25k bug).
    narrowed = bool(
        f.api_key_id
        or (f.organization and f.organization != "all")
        or (f.team and f.team != "all")
    )
    use_billing_api = (
        reported_total is not None and reported_total > 0
        and not narrowed
        and (f.provider or "all") != "all"
    )
    if use_billing_api:
        total_spend = reported_total
        total_spend_prev = reported_total_prev if reported_total_prev is not None else prev["total_spend"]
        spend_source = "billing_api"
    else:
        total_spend = cur["total_spend"]
        total_spend_prev = prev["total_spend"]
        spend_source = "events"

    cost_per_user = safe_div(total_spend, cur["active_users"], default=0.0)
    cost_per_user_prev = safe_div(total_spend_prev, prev["active_users"], default=0.0)

    out = {
        "total_spend": round(total_spend, 2),
        "total_spend_events": round(cur["total_spend"], 2),  # for transparency
        "total_spend_source": spend_source,                  # 'billing_api' or 'events'
        "tokens_in": int(cur["tokens_in"]),
        "tokens_out": int(cur["tokens_out"]),
        "tokens_cached": int(cur.get("tokens_cached") or 0),
        "active_users": int(cur["active_users"]),
        "seats_used": int(seats_used),
        "cost_per_user": round(cost_per_user, 2),
        "ai_code_share": ai_share,
        "suspicious_count": int(suspicious),
        # F-13.x — authoritative org total reported by the provider's billing API.
        # None when sync hasn't populated provider_totals yet.
        "reported_total": round(reported_total, 2) if reported_total is not None else None,
        # deltas (FR-01.1.1.3)
        "total_spend_delta": pct_delta(total_spend, total_spend_prev),
        "tokens_in_delta": pct_delta(cur["tokens_in"], prev["tokens_in"]),
        "tokens_out_delta": pct_delta(cur["tokens_out"], prev["tokens_out"]),
        "active_users_delta": pct_delta(cur["active_users"], prev["active_users"]),
        "seats_used_delta": 0.0,  # snapshot, прошлого окна нет
        "cost_per_user_delta": pct_delta(cost_per_user, cost_per_user_prev),
        "ai_code_share_delta": pct_delta(ai_share, ai_share_prev),
        "suspicious_count_delta": 0.0,
    }
    return out


def get_daily_spend_series(filters: Filters | None = None, now: datetime | None = None) -> list[dict]:
    """Time series для линейного графика на Overview.

    For providers that populate provider_totals (currently OpenAI via /costs),
    we use those daily totals — they're authoritative and match the provider's
    billing UI. For providers that don't (Anthropic JSON, Cursor JSON), we
    sum usage_events as before.
    """
    f = filters or Filters()
    now = now or datetime.utcnow()
    start, end = f.date_range(now)

    # provider_totals can only stand in for events when no narrower filter is
    # active — see _kpis_in_window for the same guard. Plus: skip when the
    # filter is 'All sources' because provider_totals is sparse (only OpenAI
    # populates it today) and would silently undercount Anthropic + Cursor.
    narrowed = bool(
        f.api_key_id
        or (f.organization and f.organization != "all")
        or (f.team and f.team != "all")
    )
    use_billing_api = not narrowed and (f.provider or "all") != "all"

    with get_conn() as conn:
        # 1) Daily authoritative numbers from provider_totals (e.g. OpenAI /costs).
        pt_rows = []
        if use_billing_api:
            pt_rows = conn.execute(
                """SELECT pt.day, p.name AS provider, pt.cost_usd AS cost
                   FROM provider_totals pt
                   JOIN providers p ON p.id = pt.provider_id
                   WHERE pt.day BETWEEN ? AND ?""",
                (start.date().isoformat(), end.date().isoformat()),
            ).fetchall()
        providers_with_totals = {r["provider"] for r in pt_rows}

        # 2) Daily events-summed for providers that don't have totals (JSON sources).
        p_clause, p_params = provider_clause(f.provider, "p")
        t_clause, t_params = team_clause(f.team, "t")
        o_clause, o_params = org_clause(f.organization, "ue")
        k_clause, k_params = api_key_clause(f.api_key_id, "ue")
        ev_rows = conn.execute(
            f"""SELECT date(ue.occurred_at) AS day,
                       p.name AS provider,
                       ROUND(SUM(ue.cost_usd), 2) AS cost
                FROM usage_events ue
                JOIN users u ON u.id = ue.user_id
                LEFT JOIN teams t ON t.id = u.team_id
                JOIN providers p ON p.id = ue.provider_id
                WHERE ue.occurred_at BETWEEN ? AND ?
                {p_clause}
                {t_clause}
                {o_clause}
                {k_clause}
                GROUP BY day, provider
                ORDER BY day""",
            [start.isoformat(sep=" "), end.isoformat(sep=" ")]
            + p_params + t_params + o_params + k_params,
        ).fetchall()

    # Compose: provider_totals win per (provider, day); fallback to events.
    out: dict[tuple[str, str], dict] = {}
    for r in ev_rows:
        prov = r["provider"]
        # Skip events for providers that have authoritative provider_totals —
        # we'll use those instead to avoid mixing two different signals.
        if prov in providers_with_totals:
            continue
        out[(r["day"], prov)] = {"day": r["day"], "provider": prov, "cost": r["cost"]}
    for r in pt_rows:
        prov = r["provider"]
        # Honor the provider filter on the totals path too.
        if f.provider != "all" and prov != f.provider:
            continue
        out[(r["day"], prov)] = {"day": r["day"], "provider": prov, "cost": round(float(r["cost"] or 0), 2)}

    return sorted(out.values(), key=lambda x: (x["day"], x["provider"]))
