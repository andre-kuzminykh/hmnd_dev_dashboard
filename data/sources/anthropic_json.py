"""Anthropic_*.json loader — turns a vendor-side snapshot of Claude
spend / users / products / models into usage_events rows.

Schema in docs/SOURCES_SCHEMA.md. Idempotent: deletes events in the file's
period before inserting fresh ones.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from data.db import get_conn
from ._common import SourceFile, find_all, latest_match


_PATTERNS = ["Anthropic_*.json", "Anthropics_*.json"]


def find_anthropic_files() -> list[SourceFile]:
    return find_all(_PATTERNS)


def latest_anthropic_file() -> SourceFile | None:
    return latest_match(_PATTERNS)


# Product → purpose mapping (so the dashboard can split chat / claude_code
# the same way it does for cursor-derived events).
_PRODUCT_PURPOSE = {
    "chat": "Chat",
    "claude_code": "Agent",
    "cowork_other": "Other",
}


def _ensure_provider() -> int:
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO providers(name) VALUES('anthropic')")
        pid = conn.execute(
            "SELECT id FROM providers WHERE name='anthropic'"
        ).fetchone()["id"]
        conn.commit()
    return pid


def _ensure_model(name: str, provider_id: int) -> int:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO models(provider_id, name, family) VALUES(?, ?, ?)",
            (provider_id, name, name.split("-")[0] if name else "claude"),
        )
        mid = conn.execute(
            "SELECT id FROM models WHERE provider_id = ? AND name = ?",
            (provider_id, name),
        ).fetchone()["id"]
        conn.commit()
    return mid


def _ensure_user(email: str, full_name: str) -> int:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO users(email, full_name, monthly_limit_usd, is_active)
               VALUES(?, ?, 200, 1)""",
            (email, full_name or email.split("@")[0]),
        )
        uid = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
        conn.commit()
    return uid


def _ensure_api_key(external_id: str, name: str, provider_id: int, owner_id: int) -> int:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO api_keys(provider_id, external_id, name,
                                              redacted_value, owner_user_id, is_admin)
               VALUES(?, ?, ?, ?, ?, 0)""",
            (provider_id, external_id, name, f"sk-ant-json-…{external_id[-6:]}", owner_id),
        )
        kid = conn.execute(
            "SELECT id FROM api_keys WHERE provider_id=? AND external_id=?",
            (provider_id, external_id),
        ).fetchone()["id"]
        conn.commit()
    return kid


def load_anthropic_json(path: Path | str) -> dict[str, Any]:
    """Parse + load. Returns a small report (inserted, users, period_*)."""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))

    period_start = data.get("period_start")
    period_end = data.get("period_end")
    if not period_start or not period_end:
        return {"inserted": 0, "errors": ["missing period_start/period_end"], "path": str(p)}

    pid = _ensure_provider()

    # Wipe events in the file's period
    with get_conn() as conn:
        conn.execute(
            """DELETE FROM usage_events
               WHERE provider_id = ?
                 AND date(occurred_at) >= date(?) AND date(occurred_at) <= date(?)""",
            (pid, period_start, period_end),
        )
        conn.commit()

    # Register models so they show up in Models page and have prices.
    for m in data.get("models", []) or []:
        if m.get("name"):
            _ensure_model(m["name"], pid)

    users = data.get("users", []) or []
    if not users:
        return {"inserted": 0, "users": 0, "period_from": period_start,
                "period_to": period_end, "note": "no users in JSON"}

    inserted = 0
    start_dt = datetime.fromisoformat(period_start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(period_end).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )
    days = max((end_dt.date() - start_dt.date()).days + 1, 1)

    for u in users:
        email = u.get("email") or ""
        if not email:
            continue
        name = u.get("name") or email.split("@")[0]
        uid = _ensure_user(email, name)
        kid = _ensure_api_key(f"sk-ant-json-{email}", name, pid, uid)
        primary_model = u.get("primary_model") or "claude-opus-4-7"
        mid = _ensure_model(primary_model, pid)

        # Split into chat + cc events. Distribute evenly across the period.
        for product_key, purpose in _PRODUCT_PURPOSE.items():
            if product_key == "chat":
                reqs = int(u.get("chat_requests") or 0)
                spend = float(u.get("chat_spend_usd") or 0)
            elif product_key == "claude_code":
                reqs = int(u.get("cc_requests") or 0)
                spend = float(u.get("cc_spend_usd") or 0)
            else:
                reqs = int(u.get("cowork_requests") or 0)
                spend = float(u.get("cowork_spend_usd") or 0)
            if reqs <= 0:
                continue
            per_day_reqs = max(reqs // days, 0)
            remainder = reqs - per_day_reqs * days
            per_event_cost = round(spend / reqs, 6) if reqs else 0

            rows: list[tuple] = []
            for d in range(days):
                day_dt = start_dt + timedelta(days=d)
                n = per_day_reqs + (1 if d < remainder else 0)
                if n == 0:
                    continue
                # All events for the day at 12:00 UTC to keep things tidy;
                # individual second-precision isn't useful from a daily snapshot.
                ts = day_dt.replace(hour=12, minute=0, second=0).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                for _ in range(n):
                    # Token counts are unknown from JSON — use rough estimates
                    # so charts that show tokens aren't empty. Cost is correct.
                    tokens_in = 2500 if purpose == "Agent" else 800
                    tokens_out = 800 if purpose == "Agent" else 300
                    rows.append((
                        uid, pid, mid, kid, ts,
                        tokens_in, tokens_out, 0, per_event_cost,
                        0, 0, purpose,
                    ))
            if rows:
                with get_conn() as conn:
                    conn.executemany(
                        """INSERT INTO usage_events(
                            user_id, provider_id, model_id, api_key_id, occurred_at,
                            tokens_in, tokens_out, tokens_cached, cost_usd,
                            latency_ms, is_error, purpose
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        rows,
                    )
                    conn.commit()
                inserted += len(rows)

    return {
        "provider": "anthropic",
        "mode": "json",
        "source_file": p.name,
        "inserted": inserted,
        "users": len(users),
        "period_from": period_start,
        "period_to": period_end,
    }
