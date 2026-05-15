"""Orchestrator вокруг коннекторов: дёргает sync, агрегирует daily_costs."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from backend.config import load_config
from data.connectors import AnthropicConnector, GitHubConnector, OpenAIConnector
from data.db import get_conn


def _ensure_organization(provider: str, label: str) -> int:
    """Get-or-create an organization row for (provider, label). Returns local id."""
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO providers(name) VALUES(?)", (provider,))
        pid = conn.execute(
            "SELECT id FROM providers WHERE name = ?", (provider,)
        ).fetchone()["id"]
        conn.execute(
            """INSERT OR IGNORE INTO organizations(provider_id, label)
               VALUES(?, ?)""",
            (pid, label),
        )
        row = conn.execute(
            "SELECT id FROM organizations WHERE provider_id = ? AND label = ?",
            (pid, label),
        ).fetchone()
        conn.commit()
    return row["id"]


def _sync_anthropic(cfg, period_days: int) -> dict[str, Any]:
    """Anthropic decision tree (most authoritative first):

    1. sources/Anthropic_*.json  → load JSON (FR-14.3.1.1)
    2. cursor leaderboard        → derive Claude usage from Cursor
    3. HMND_ANTHROPIC_MOCK=true  → synthetic random demo data
    4. real Admin API            → AnthropicConnector
    """
    # 1. JSON sources win
    from data.sources.anthropic_json import latest_anthropic_file, load_anthropic_json
    anthro_file = latest_anthropic_file()
    if anthro_file is not None:
        from data.anthropic_mock import purge_anthropic_mock
        purge_anthropic_mock()
        return load_anthropic_json(anthro_file.path)

    # 2. Cursor-derived
    from backend.services.cursor_analytics import claude_users as _cu
    cursor_rows = _cu()
    if cursor_rows:
        from data.anthropic_mock import purge_anthropic_mock
        from data.cursor_to_anthropic import derive_anthropic_from_cursor
        purge_anthropic_mock()
        return derive_anthropic_from_cursor()

    # 3. Mock
    if cfg.anthropic_mock:
        from data.anthropic_mock import synth_anthropic
        return {"provider": "anthropic", "mode": "mock", **synth_anthropic(period_days)}

    # 4. Real Admin API
    from data.anthropic_mock import purge_anthropic_mock
    purged = purge_anthropic_mock()
    c = AnthropicConnector(api_key=cfg.anthropic_key, mock=not cfg.anthropic_key)
    report = c.sync(period_days)
    report_dict = asdict(report)
    if any(v for v in purged.values()):
        report_dict["purged_mock"] = purged
    return report_dict


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
        if cfg.openai_orgs:
            # Multi-org sync: one OpenAIConnector per configured admin key.
            org_reports: list[dict[str, Any]] = []
            for org in cfg.openai_orgs:
                org_id = _ensure_organization(provider="openai", label=org.label)
                c = OpenAIConnector(
                    api_key=org.api_key, mock=False,
                    org_label=org.label, org_id=org_id,
                )
                r = asdict(c.sync(period_days))
                r["org_label"] = org.label
                org_reports.append(r)
            out["reports"]["openai"] = org_reports if len(org_reports) > 1 else org_reports[0]
        else:
            c = OpenAIConnector(api_key=cfg.openai_key, mock=not cfg.openai_key)
            out["reports"]["openai"] = asdict(c.sync(period_days))

    if "anthropic" in providers:
        out["reports"]["anthropic"] = _sync_anthropic(cfg, period_days)

    if "github" in providers and cfg.github_enabled:
        c = GitHubConnector(api_key=cfg.github_token, mock=not cfg.github_token)
        out["reports"]["github"] = asdict(c.sync(period_days))

    out["daily_costs_refreshed"] = _refresh_daily_costs(period_days)
    return out
