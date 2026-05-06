"""Orchestrator вокруг коннекторов: дёргает sync, агрегирует daily_costs."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from backend.config import load_config
from data.connectors import AnthropicConnector, GitHubConnector, OpenAIConnector
from data.db import get_conn


def _refresh_daily_costs(period_days: int) -> int:
    """Wipe daily_costs in the period and re-aggregate from usage_events.

    Idempotent regardless of how many times sync runs: every event that
    survived in usage_events contributes once to daily_costs.
    """
    cutoff = (datetime.utcnow() - timedelta(days=period_days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        conn.execute("DELETE FROM daily_costs WHERE day >= ?", (cutoff,))
        cur = conn.execute(
            """INSERT INTO daily_costs(user_id, provider_id, day,
                                       cost_usd, tokens_in, tokens_out, requests)
               SELECT user_id, provider_id, date(occurred_at) AS day,
                      ROUND(SUM(cost_usd), 4),
                      SUM(tokens_in), SUM(tokens_out), COUNT(*)
               FROM usage_events
               WHERE date(occurred_at) >= ?
               GROUP BY user_id, provider_id, day""",
            (cutoff,),
        )
        rows = cur.rowcount
        conn.commit()
    return rows


def run_sync(period_days: int = 7, providers: tuple[str, ...] = ("openai", "anthropic", "github")) -> dict[str, Any]:
    cfg = load_config()
    out: dict[str, Any] = {"reports": {}}

    if "openai" in providers:
        c = OpenAIConnector(api_key=cfg.openai_key, mock=not cfg.openai_key)
        out["reports"]["openai"] = asdict(c.sync(period_days))

    if "anthropic" in providers:
        if cfg.anthropic_mock:
            from data.anthropic_mock import synth_anthropic

            out["reports"]["anthropic"] = {
                "provider": "anthropic",
                "mode": "mock",
                **synth_anthropic(period_days),
            }
        else:
            # Mock-режим выключен — почистим любые остатки синтетики, чтобы дашборд
            # показывал только реальные данные.
            from data.anthropic_mock import purge_anthropic_mock

            purged = purge_anthropic_mock()
            c = AnthropicConnector(api_key=cfg.anthropic_key, mock=not cfg.anthropic_key)
            report = c.sync(period_days)
            report_dict = asdict(report)
            if any(v for v in purged.values()):
                report_dict["purged_mock"] = purged
            out["reports"]["anthropic"] = report_dict

    if "github" in providers and cfg.github_enabled:
        c = GitHubConnector(api_key=cfg.github_token, mock=not cfg.github_token)
        out["reports"]["github"] = asdict(c.sync(period_days))

    out["daily_costs_refreshed"] = _refresh_daily_costs(period_days)
    return out
