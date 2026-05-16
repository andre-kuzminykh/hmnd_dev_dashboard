"""Synthesise Anthropic usage events from Cursor team CSV exports.

Why: we don't have an Anthropic Admin API key. The user explicitly said
"use only the CSVs for Claude". Cursor's User_Leaderboard gives us per-user
agent + tab completion counts and lines for the period; we estimate
tokens-per-call and apply public Claude pricing to produce a believable
usage_events stream that the rest of the dashboard (Overview, Costs by
People, Models, AI Tools) renders normally.

Estimates are conservative defaults — override with env vars if you want
to tune them:
    HMND_ANTHROPIC_AGENT_INPUT_PER_CALL  (default 3000)
    HMND_ANTHROPIC_AGENT_OUTPUT_PER_CALL (default 1000)
    HMND_ANTHROPIC_AGENT_CACHED_RATIO    (default 0.3)
    HMND_ANTHROPIC_TAB_INPUT_PER_CALL    (default 500)
    HMND_ANTHROPIC_TAB_OUTPUT_PER_CALL   (default 30)
"""
from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.services.cursor_analytics import claude_users
from data.db import get_conn


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Public Claude pricing per 1K tokens (input, output, cached_input).
CLAUDE_PRICES: dict[str, tuple[float, float, float]] = {
    "claude-opus-4-7":   (0.015, 0.075, 0.0015),
    "claude-opus":       (0.015, 0.075, 0.0015),
    "claude-sonnet-4-6": (0.003, 0.015, 0.0003),
    "claude-sonnet":     (0.003, 0.015, 0.0003),
    "claude-haiku-4-5":  (0.0008, 0.004, 0.00008),
    "claude-haiku":      (0.0008, 0.004, 0.00008),
}


def _price_for_model(model_name: str) -> tuple[float, float, float]:
    name = (model_name or "").lower()
    # Longest-prefix match on known Claude families
    for base in sorted(CLAUDE_PRICES.keys(), key=len, reverse=True):
        if base in name:
            return CLAUDE_PRICES[base]
    return CLAUDE_PRICES["claude-opus-4-7"]


def _model_family(model_name: str) -> str:
    n = (model_name or "").lower()
    if "haiku" in n:
        return "claude-4-haiku"
    if "sonnet" in n:
        return "claude-4-sonnet"
    return "claude-4-opus"


def derive_anthropic_from_cursor() -> dict[str, Any]:
    """Generate Anthropic usage events from Cursor leaderboard.

    Idempotent: deletes existing Anthropic events in the leaderboard's period
    before inserting fresh rows.
    Returns a small report (inserted, users, period_*) for the sync log.
    """
    leaders = claude_users()
    if not leaders:
        return {"inserted": 0, "users": 0, "note": "no Claude users in Cursor exports"}

    # Period — from filename of the leaderboard CSV.
    period_start = datetime.fromisoformat(leaders[0]["period_start"]).replace(tzinfo=timezone.utc)
    period_end = datetime.fromisoformat(leaders[0]["period_end"]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )
    days = max((period_end.date() - period_start.date()).days + 1, 1)

    agent_in = int(_f("HMND_ANTHROPIC_AGENT_INPUT_PER_CALL", 3000))
    agent_out = int(_f("HMND_ANTHROPIC_AGENT_OUTPUT_PER_CALL", 1000))
    agent_cached_ratio = _f("HMND_ANTHROPIC_AGENT_CACHED_RATIO", 0.3)
    tab_in = int(_f("HMND_ANTHROPIC_TAB_INPUT_PER_CALL", 500))
    tab_out = int(_f("HMND_ANTHROPIC_TAB_OUTPUT_PER_CALL", 30))

    rng = random.Random(42)

    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO providers(name) VALUES('anthropic')")
        pid = conn.execute("SELECT id FROM providers WHERE name='anthropic'").fetchone()["id"]
        # Wipe period
        conn.execute(
            """DELETE FROM usage_events
               WHERE provider_id = ?
                 AND date(occurred_at) >= date(?) AND date(occurred_at) <= date(?)""",
            (pid, period_start.date().isoformat(), period_end.date().isoformat()),
        )
        conn.commit()

    inserted = 0
    for leader in leaders:
        favorite_model = leader["favorite_model"] or "claude-opus-4-7"
        p_in, p_out, p_cache = _price_for_model(favorite_model)

        with get_conn() as conn:
            # Upsert user (lowercase email — see audit_user_dedup rationale)
            email_lc = (leader["email"] or "").strip().lower()
            conn.execute(
                """INSERT OR IGNORE INTO users(email, full_name, monthly_limit_usd, is_active)
                   VALUES(?, ?, 200, 1)""",
                (email_lc, leader["name"]),
            )
            uid = conn.execute(
                "SELECT id FROM users WHERE email = ?", (email_lc,)
            ).fetchone()["id"]

            # Upsert model
            conn.execute(
                "INSERT OR IGNORE INTO models(provider_id, name, family) VALUES(?,?,?)",
                (pid, favorite_model, _model_family(favorite_model)),
            )
            mid = conn.execute(
                "SELECT id FROM models WHERE provider_id = ? AND name = ?",
                (pid, favorite_model),
            ).fetchone()["id"]
            # Price
            conn.execute(
                """INSERT OR IGNORE INTO model_prices(
                        model_id, valid_from, input_per_1k, output_per_1k, cache_read_per_1k)
                   VALUES(?, '2026-01-01', ?, ?, ?)""",
                (mid, p_in, p_out, p_cache),
            )

            # Synthetic api_key per user (so the API key drill-down still works)
            ext = f"sk-ant-cursor-{leader['email']}"
            conn.execute(
                """INSERT OR IGNORE INTO api_keys(provider_id, external_id, name,
                                                   redacted_value, owner_user_id, is_admin)
                   VALUES(?, ?, ?, ?, ?, 0)""",
                (pid, ext, leader["name"], f"sk-ant-…{ext[-6:]}", uid),
            )
            kid = conn.execute(
                "SELECT id FROM api_keys WHERE provider_id = ? AND external_id = ?",
                (pid, ext),
            ).fetchone()["id"]
            conn.commit()

        # Distribute completions across the period.
        ag_total = max(int(leader.get("agent_completions") or 0), 0)
        tb_total = max(int(leader.get("tab_completions") or 0), 0)
        ag_per = ag_total // days
        tb_per = tb_total // days
        ag_rem = ag_total - ag_per * days
        tb_rem = tb_total - tb_per * days

        all_rows: list[tuple] = []
        for d in range(days):
            day_dt = period_start + timedelta(days=d)
            n_agent = ag_per + (1 if d < ag_rem else 0)
            n_tab = tb_per + (1 if d < tb_rem else 0)

            for _ in range(n_agent):
                jitter_in = rng.randint(-int(agent_in * 0.3), int(agent_in * 0.5))
                jitter_out = rng.randint(-int(agent_out * 0.3), int(agent_out * 0.5))
                tokens_in = max(agent_in + jitter_in, 100)
                tokens_out = max(agent_out + jitter_out, 50)
                tokens_cached = int(tokens_in * agent_cached_ratio * rng.uniform(0.5, 1.5))
                tokens_cached = min(tokens_cached, tokens_in)
                billed_in = max(tokens_in - tokens_cached, 0)
                cost = round(
                    billed_in / 1000.0 * p_in
                    + tokens_cached / 1000.0 * p_cache
                    + tokens_out / 1000.0 * p_out,
                    6,
                )
                ts = day_dt.replace(hour=rng.randint(8, 22), minute=rng.randint(0, 59),
                                    second=rng.randint(0, 59))
                all_rows.append((
                    uid, pid, mid, kid, ts.strftime("%Y-%m-%d %H:%M:%S"),
                    tokens_in, tokens_out, tokens_cached, cost,
                    rng.randint(500, 4500), 0, "Agent",
                ))

            for _ in range(n_tab):
                tokens_in = max(tab_in + rng.randint(-100, 200), 50)
                tokens_out = max(tab_out + rng.randint(-10, 30), 5)
                cost = round(
                    tokens_in / 1000.0 * p_in
                    + tokens_out / 1000.0 * p_out,
                    6,
                )
                ts = day_dt.replace(hour=rng.randint(8, 22), minute=rng.randint(0, 59),
                                    second=rng.randint(0, 59))
                all_rows.append((
                    uid, pid, mid, kid, ts.strftime("%Y-%m-%d %H:%M:%S"),
                    tokens_in, tokens_out, 0, cost,
                    rng.randint(100, 800), 0, "Tab",
                ))

        if all_rows:
            with get_conn() as conn:
                conn.executemany(
                    """INSERT INTO usage_events(
                        user_id, provider_id, model_id, api_key_id, occurred_at,
                        tokens_in, tokens_out, tokens_cached, cost_usd,
                        latency_ms, is_error, purpose
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    all_rows,
                )
                conn.commit()
            inserted += len(all_rows)

    return {
        "provider": "anthropic",
        "mode": "cursor-derived",
        "inserted": inserted,
        "users": len(leaders),
        "period_from": period_start.date().isoformat(),
        "period_to": period_end.date().isoformat(),
    }
