"""F-12 AI Tools Dashboard service.

Tool-centric roll-ups across Claude / ChatGPT / Cursor and a cross-provider
High Spenders view.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from data.db import get_conn
from backend.analytics import Filters, api_key_clause


# ---- Risk / flag classifiers (FR-12.1.3.2, FR-12.1.5.2) ----

def chatgpt_flag(spend: float) -> str:
    if spend >= 1000:
        return "High"
    if spend >= 500:
        return "Medium"
    if spend >= 200:
        return "Watch"
    return ""


def classify_risk(spend: float) -> str | None:
    if spend >= 1000:
        return "high"
    if spend >= 500:
        return "medium"
    if spend >= 200:
        return "low"
    return None


# ---- Freshness (FR-12.1.1.1, FR-12.1.1.3) ----

def get_provider_freshness() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with get_conn() as conn:
        # All known providers (from the providers table) so absent ones still appear.
        providers = [r["name"] for r in conn.execute("SELECT name FROM providers").fetchall()]
        for prov in ("openai", "anthropic", "cursor"):
            if prov not in providers:
                out[prov] = {"start_date": None, "end_date": None, "source": "absent"}
                continue
            row = conn.execute(
                """SELECT MIN(date(ue.occurred_at)) AS start_date,
                          MAX(date(ue.occurred_at)) AS end_date,
                          COUNT(*) AS n
                   FROM usage_events ue
                   JOIN providers p ON p.id = ue.provider_id
                   WHERE p.name = ?""",
                (prov,),
            ).fetchone()
            mock = conn.execute(
                """SELECT 1 FROM api_keys ak
                   JOIN providers p ON p.id = ak.provider_id
                   WHERE p.name = ?
                     AND (ak.external_id LIKE 'sk-ant-mock-%' OR ak.external_id LIKE 'sk-mock-%')
                   LIMIT 1""",
                (prov,),
            ).fetchone()
            real = conn.execute(
                """SELECT 1 FROM api_keys ak
                   JOIN providers p ON p.id = ak.provider_id
                   WHERE p.name = ?
                     AND ak.external_id NOT LIKE 'sk-ant-mock-%'
                     AND ak.external_id NOT LIKE 'sk-mock-%'
                   LIMIT 1""",
                (prov,),
            ).fetchone()
            if row and row["n"]:
                source = "mock" if (mock and not real) else ("real" if real else "real")
                # heuristic: events but no api_keys at all → assume real
                out[prov] = dict(start_date=row["start_date"], end_date=row["end_date"], source=source)
            else:
                out[prov] = {"start_date": None, "end_date": None, "source": "absent"}
    return out


# ---- Overview KPIs (FR-12.1.1.2) ----

def get_ai_tools_overview(period_days: int = 5) -> dict[str, Any]:
    end = datetime.utcnow()
    start = end - timedelta(days=period_days)
    s = start.strftime("%Y-%m-%d %H:%M:%S")
    e = end.strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        def _active_users(provider_name: str) -> int | None:
            row = conn.execute(
                """SELECT COUNT(DISTINCT ue.user_id) AS n FROM usage_events ue
                   JOIN providers p ON p.id = ue.provider_id
                   WHERE p.name = ? AND ue.occurred_at BETWEEN ? AND ?""",
                (provider_name, s, e),
            ).fetchone()
            return int(row["n"]) if row else 0

        out = {
            "claude_chat_users": _active_users("anthropic"),
            "claude_code_users": None,           # placeholder until Claude Code telemetry connected
            "chatgpt_active_users": _active_users("openai"),
            "cursor_active_devs": None,          # placeholder until Cursor connected
        }
    return out


# ---- Per-provider users (FR-12.1.2.1, FR-12.1.3.1) ----

def get_users_for_provider(provider: str, period_days: int = 30,
                           api_key_id: int | None = None) -> list[dict[str, Any]]:
    end = datetime.utcnow()
    start = end - timedelta(days=period_days)
    s = start.strftime("%Y-%m-%d %H:%M:%S")
    e = end.strftime("%Y-%m-%d %H:%M:%S")
    k_clause, k_params = api_key_clause(api_key_id, "ue")
    sql = f"""
        SELECT u.id, u.full_name AS user_name,
               COUNT(*)                          AS messages,
               ROUND(SUM(ue.cost_usd), 2)        AS cost,
               SUM(ue.tokens_in)                 AS tokens_in,
               SUM(ue.tokens_out)                AS tokens_out
        FROM usage_events ue
        JOIN users u ON u.id = ue.user_id
        JOIN providers p ON p.id = ue.provider_id
        WHERE p.name = ? AND ue.occurred_at BETWEEN ? AND ?
        {k_clause}
        GROUP BY u.id
        ORDER BY messages DESC
    """
    params = [provider, s, e] + k_params
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        out.append({
            "user_name": r["user_name"],
            "messages": int(r["messages"]),
            "cost": float(r["cost"] or 0),
            "tokens_in": int(r["tokens_in"] or 0),
            "tokens_out": int(r["tokens_out"] or 0),
            # placeholders until extra sources are connected
            "sessions": None,
            "lines_added": None,
            "commits": None,
        })
    return out


# ---- High Spenders (FR-12.1.5.*) ----

def get_high_spenders(period_days: int = 30, threshold_usd: float = 200,
                      api_key_id: int | None = None,
                      provider: str = "all",
                      organization: str = "all",
                      date_from: datetime | None = None,
                      date_to: datetime | None = None) -> list[dict[str, Any]]:
    """Top spenders, with optional provider / organization / explicit-date narrowing.

    F-19 / FR-19.1–4:
      - provider='all' (default) → cross-tool ranking (back-compat)
      - provider='anthropic' | 'openai' | 'cursor' → JOIN providers + WHERE p.name=?
      - organization='Artem' (etc.) → adds organization_id filter (OpenAI sub-orgs)
      - date_from + date_to set → use that window verbatim (overrides period_days)
    """
    # FR-19.4 — explicit dates win over period_days offset.
    if date_from is not None and date_to is not None:
        start, end = date_from, date_to
    else:
        end = datetime.utcnow()
        start = end - timedelta(days=period_days)
    s = start.strftime("%Y-%m-%d %H:%M:%S")
    e = end.strftime("%Y-%m-%d %H:%M:%S")

    k_clause, k_params = api_key_clause(api_key_id, "ue")

    # FR-19.2 — provider join + filter
    prov_join = ""
    prov_clause = ""
    prov_params: list = []
    if provider and provider != "all":
        prov_join = "JOIN providers p ON p.id = ue.provider_id"
        prov_clause = "AND p.name = ?"
        prov_params = [provider]

    # FR-19.3 — organization filter
    org_clause = ""
    org_params: list = []
    if organization and organization != "all":
        org_clause = ("AND ue.organization_id IN "
                      "(SELECT id FROM organizations WHERE label = ?)")
        org_params = [organization]

    sql = f"""
        SELECT u.id, u.full_name AS user_name,
               COUNT(*)                       AS messages,
               ROUND(SUM(ue.cost_usd), 2)     AS spend
        FROM usage_events ue
        JOIN users u ON u.id = ue.user_id
        {prov_join}
        WHERE ue.occurred_at BETWEEN ? AND ?
        {prov_clause}
        {org_clause}
        {k_clause}
        GROUP BY u.id
        HAVING spend >= ? AND spend > 0
        ORDER BY spend DESC
    """
    params = [s, e] + prov_params + org_params + k_params + [threshold_usd]
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        spend = float(r["spend"] or 0)
        msgs = int(r["messages"] or 0)
        dollar_per_msg = round(spend / msgs, 2) if msgs else None
        out.append({
            "user_name": r["user_name"],
            "messages": msgs,
            "spend": spend,
            "dollar_per_msg": dollar_per_msg,
            "risk": classify_risk(spend),
        })
    return out


# ---- Tool-specific breakdowns ----

def get_anthropic_spend_by_purpose(period_days: int = 30) -> list[dict[str, Any]]:
    """Anthropic spend split by `purpose` (Chat / Agent (= Claude Code) /
    Cowork / Chrome / Design / Other). Empty list if no events in window.
    Returns [{purpose, spend, requests, users}, ...] sorted by spend desc.
    """
    end = datetime.utcnow()
    start = end - timedelta(days=period_days)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ue.purpose AS purpose,
                      ROUND(SUM(ue.cost_usd), 2)        AS spend,
                      COUNT(*)                          AS requests,
                      COUNT(DISTINCT ue.user_id)        AS users
               FROM usage_events ue
               JOIN providers p ON p.id = ue.provider_id
               WHERE p.name = 'anthropic' AND ue.occurred_at BETWEEN ? AND ?
               GROUP BY ue.purpose
               ORDER BY spend DESC""",
            (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchall()
    return [dict(r) for r in rows]


def get_spend_by_model(provider: str, period_days: int = 30,
                       purpose: str | None = None) -> list[dict[str, Any]]:
    """Per-model spend (and request count) for a provider in the window.
    Optionally narrow to a single `purpose` (e.g. 'Agent' for Claude Code).
    """
    end = datetime.utcnow()
    start = end - timedelta(days=period_days)
    purpose_clause = " AND ue.purpose = ? " if purpose else ""
    purpose_params = [purpose] if purpose else []
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT m.name AS model,
                       ROUND(SUM(ue.cost_usd), 2) AS spend,
                       COUNT(*) AS requests,
                       COUNT(DISTINCT ue.user_id) AS users
                FROM usage_events ue
                JOIN providers p ON p.id = ue.provider_id
                JOIN models m   ON m.id = ue.model_id
                WHERE p.name = ? AND ue.occurred_at BETWEEN ? AND ?
                {purpose_clause}
                GROUP BY m.id
                ORDER BY spend DESC""",
            [provider, start.strftime("%Y-%m-%d %H:%M:%S"),
             end.strftime("%Y-%m-%d %H:%M:%S")] + purpose_params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_high_spenders_per_provider(period_days: int = 30) -> list[dict[str, Any]]:
    """Cross-tool spend per user with a per-provider breakdown — lets the
    UI show 'Andy Park: $9920 GPT + $3154 CC = $13074 total'.

    Returns one row per user_id with cost_openai, cost_anthropic, cost_cursor,
    cost_total, messages.
    """
    end = datetime.utcnow()
    start = end - timedelta(days=period_days)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT u.id, u.full_name AS user_name, u.email,
                      COUNT(*) AS messages,
                      ROUND(SUM(CASE WHEN p.name='openai'    THEN ue.cost_usd ELSE 0 END), 2) AS cost_openai,
                      ROUND(SUM(CASE WHEN p.name='anthropic' THEN ue.cost_usd ELSE 0 END), 2) AS cost_anthropic,
                      ROUND(SUM(CASE WHEN p.name='cursor'    THEN ue.cost_usd ELSE 0 END), 2) AS cost_cursor,
                      ROUND(SUM(ue.cost_usd), 2)              AS cost_total
               FROM usage_events ue
               JOIN users u    ON u.id = ue.user_id
               JOIN providers p ON p.id = ue.provider_id
               WHERE ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.id
               HAVING cost_total > 0
               ORDER BY cost_total DESC""",
            (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchall()
    return [dict(r) for r in rows]


def get_openai_top_models(period_days: int = 30) -> list[dict[str, Any]]:
    """ChatGPT / OpenAI per-model leaderboard by message count and spend."""
    return get_spend_by_model("openai", period_days=period_days)


def get_anthropic_model_spend_from_json() -> list[dict[str, Any]]:
    """Per-model Anthropic spend pulled DIRECTLY from the latest JSON dump's
    rollups.modelSpend field. We use this for the 'Spend by Model' card on
    the Claude Code tab — usage_events stores all Anthropic events under
    a 'claude-generic' placeholder model because raw.userCostByProduct
    records don't carry per-event model attribution. The rollup IS the
    authoritative per-model number.

    Returns [{model, spend, share}, ...] in USD, sorted by spend desc.
    Empty list when no JSON file is present.
    """
    try:
        from data.sources.anthropic_json import latest_anthropic_file
        import json as _json
    except Exception:
        return []
    f = latest_anthropic_file()
    if not f:
        return []
    try:
        doc = _json.loads(f.path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rollups = doc.get("rollups") or {}
    model_spend_cents = rollups.get("modelSpend") or {}
    total = sum(float(v or 0) for v in model_spend_cents.values()) or 1
    out = [
        {"model": name,
         "spend": round(float(v or 0) / 100.0, 2),
         "share": float(v or 0) / total * 100}
        for name, v in model_spend_cents.items()
    ]
    return sorted(out, key=lambda r: r["spend"], reverse=True)


def get_cursor_completion_split(period_days: int = 30) -> dict[str, int]:
    """Return {'agent': X, 'tab': Y, 'total': X+Y} aggregated across the
    Cursor leaderboard within `period_days` (best-effort: leaderboard
    rows carry the period that ended within the window).
    """
    # We import here to avoid circular imports between services.
    from backend.services.cursor_analytics import load_user_leaderboard
    rows = load_user_leaderboard()
    agent = sum(int(r.get("agent_completions") or 0) for r in rows)
    tab = sum(int(r.get("tab_completions") or 0) for r in rows)
    return {"agent": agent, "tab": tab, "total": agent + tab}
