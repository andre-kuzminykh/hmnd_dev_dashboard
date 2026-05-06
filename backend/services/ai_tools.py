"""F-12 AI Tools Dashboard service.

Tool-centric roll-ups across Claude / ChatGPT / Cursor and a cross-provider
High Spenders view.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from data.db import get_conn


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

def get_users_for_provider(provider: str, period_days: int = 30) -> list[dict[str, Any]]:
    end = datetime.utcnow()
    start = end - timedelta(days=period_days)
    s = start.strftime("%Y-%m-%d %H:%M:%S")
    e = end.strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT u.id, u.full_name AS user_name,
                      COUNT(*)                          AS messages,
                      ROUND(SUM(ue.cost_usd), 2)        AS cost,
                      SUM(ue.tokens_in)                 AS tokens_in,
                      SUM(ue.tokens_out)                AS tokens_out
               FROM usage_events ue
               JOIN users u ON u.id = ue.user_id
               JOIN providers p ON p.id = ue.provider_id
               WHERE p.name = ? AND ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.id
               ORDER BY messages DESC""",
            (provider, s, e),
        ).fetchall()
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

def get_high_spenders(period_days: int = 30, threshold_usd: float = 200) -> list[dict[str, Any]]:
    end = datetime.utcnow()
    start = end - timedelta(days=period_days)
    s = start.strftime("%Y-%m-%d %H:%M:%S")
    e = end.strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT u.id, u.full_name AS user_name,
                      COUNT(*)                       AS messages,
                      ROUND(SUM(ue.cost_usd), 2)     AS spend
               FROM usage_events ue
               JOIN users u ON u.id = ue.user_id
               WHERE ue.occurred_at BETWEEN ? AND ?
               GROUP BY u.id
               HAVING spend >= ?
               ORDER BY spend DESC""",
            (s, e, threshold_usd),
        ).fetchall()
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
