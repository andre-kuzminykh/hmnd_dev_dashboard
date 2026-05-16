"""Cursor JSON loader v2 — handles the real Cursor admin pull.

Top-level shape:
    {
      "_meta":   {"rangeStart","rangeEnd","provider":"cursor"},
      "rollups": {"activeDevs","totalMembers","totalSpend","totalLines",
                  "totalAccepts","totalAgent",
                  "perUser": {email: {lines, accepts, agent}}},
      "raw":     {
        "members": {"teamMembers": [{name, email, id, role, isRemoved}]},
        "usage":   {"data": [{date, day, email, totalLines..., accepted...}]},
        "spend":   {"teamMemberSpend": [{userId, email, spendCents,
                                         includedSpendCents, monthlyLimitDollars}]},
      }
    }

Cursor IDE is paid via a team subscription, not per-token billing, so the
spend stored per user reflects what they consumed against their seat
allowance. We write `provider='cursor'` events with cost_usd from
spendCents and lines/accepts/agent counters from `rollups.perUser`.
Idempotent: drops cursor events in the file's period before insert.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from data.db import get_conn
from ._common import SourceFile, find_all, latest_match


_PATTERNS = ["Cursor_*.json"]


def find_cursor_files() -> list[SourceFile]:
    return find_all(_PATTERNS)


def latest_cursor_file() -> SourceFile | None:
    return latest_match(_PATTERNS)


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _ensure_provider() -> int:
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO providers(name) VALUES('cursor')")
        return conn.execute(
            "SELECT id FROM providers WHERE name='cursor'"
        ).fetchone()["id"]


def _ensure_user(email: str, name: str) -> int:
    # Lowercase email to dodge case-sensitive UNIQUE constraint dupes.
    email = (email or "").strip().lower()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO users(email, full_name, monthly_limit_usd, is_active)
               VALUES(?, ?, 200, 1)""",
            (email, name or email.split("@")[0]),
        )
        uid = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
        if name:
            conn.execute("UPDATE users SET full_name=? WHERE id=?", (name, uid))
        conn.commit()
        return uid


def _ensure_model(name: str, provider_id: int) -> int:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO models(provider_id, name, family) VALUES(?, ?, ?)",
            (provider_id, name, "cursor"),
        )
        return conn.execute(
            "SELECT id FROM models WHERE provider_id=? AND name=?",
            (provider_id, name),
        ).fetchone()["id"]


def parse_cursor_json(path: Path | str) -> dict[str, Any]:
    """Read the Cursor JSON dump and return a flat leaderboard-style document
    that cursor_analytics.load_user_leaderboard can merge with CSV rows.

    Output shape:
        {
          "period_start": ISO,
          "period_end":   ISO,
          "users": [
              {email, name, agent_completions, tab_completions,
               agent_lines, tab_lines, ai_lines, favorite_model,
               spend_usd},
              ...
          ],
          "models":  [{name, requests, users}, ...],
          "summary": rollups dict,
        }
    """
    p = Path(path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    meta = doc.get("_meta") or {}
    rollups = doc.get("rollups") or {}
    raw = doc.get("raw") or {}
    per_user_rollup = rollups.get("perUser") or {}
    members = (raw.get("members") or {}).get("teamMembers") or []
    members_by_email = {(m.get("email") or "").lower(): m for m in members if m.get("email")}
    spend_rows = (raw.get("spend") or {}).get("teamMemberSpend") or []
    spend_by_email = {
        (sr.get("email") or "").lower():
            (int(sr.get("spendCents") or 0) + int(sr.get("includedSpendCents") or 0)) / 100.0
        for sr in spend_rows
    }
    # Derive per-user favorite_model by aggregating raw.usage.data[*].mostUsedModel
    # — Cursor's members.teamMembers entries don't carry favoriteModel, but the
    # daily usage rows do (one mostUsedModel per (user, day)). The mode across
    # days IS the user's favorite model.
    from collections import Counter
    daily_usage = (raw.get("usage") or {}).get("data") or []
    fav_counter: dict[str, Counter] = {}
    for row in daily_usage:
        email = (row.get("email") or "").lower().strip()
        model = (row.get("mostUsedModel") or "").strip()
        if not email or not model:
            continue
        fav_counter.setdefault(email, Counter())[model] += 1
    favorite_by_email: dict[str, str] = {
        email: ctr.most_common(1)[0][0] for email, ctr in fav_counter.items()
    }

    users_out: list[dict[str, Any]] = []
    seen = set()
    # Build the union of users we know about (rollup + members + usage rows).
    emails = (
        set(per_user_rollup.keys())
        | set(members_by_email.keys())
        | set(favorite_by_email.keys())
    )
    for email_raw in emails:
        email = (email_raw or "").lower().strip()
        if not email or email in seen:
            continue
        seen.add(email)
        m = members_by_email.get(email, {})
        roll = per_user_rollup.get(email_raw) or per_user_rollup.get(email) or {}
        users_out.append({
            "email": email,
            "name": m.get("name") or email.split("@")[0],
            "agent_completions": int(roll.get("agent") or 0),
            "tab_completions":   max(int(roll.get("accepts") or 0)
                                    - int(roll.get("agent") or 0), 0),
            "agent_lines":       int(roll.get("lines") or 0),
            "tab_lines":         0,
            "ai_lines":          int(roll.get("lines") or 0),
            # Favorite model preference: explicit per-member field (legacy
            # CSV path) → aggregated mostUsedModel from daily usage → empty.
            "favorite_model":    m.get("favoriteModel") or favorite_by_email.get(email, ""),
            "spend_usd":         round(spend_by_email.get(email, 0.0), 2),
        })
    users_out.sort(key=lambda r: r["ai_lines"], reverse=True)
    return {
        "period_start": meta.get("rangeStart") or doc.get("period_start"),
        "period_end":   meta.get("rangeEnd")   or doc.get("period_end"),
        "users":   users_out,
        "models":  [],   # Cursor dump doesn't include model breakdown at team level
        "summary": rollups,
        "source_file": p.name,
    }


def load_cursor_json(path: Path | str) -> dict[str, Any]:
    """Parse + INSERT usage_events. Idempotent (DELETE-then-INSERT)."""
    p = Path(path)
    doc = json.loads(p.read_text(encoding="utf-8"))

    meta = doc.get("_meta") or {}
    start_iso = meta.get("rangeStart") or doc.get("period_start")
    end_iso = meta.get("rangeEnd") or doc.get("period_end")
    if not start_iso or not end_iso:
        return {"inserted": 0, "errors": ["missing period_start/period_end"], "path": str(p)}

    start_dt = _parse_iso(start_iso)
    end_dt = _parse_iso(end_iso)
    days = max((end_dt.date() - start_dt.date()).days + 1, 1)

    pid = _ensure_provider()
    cursor_generic_mid = _ensure_model("cursor-team", pid)

    # Wipe period
    with get_conn() as conn:
        conn.execute(
            """DELETE FROM usage_events
               WHERE provider_id = ?
                 AND date(occurred_at) >= date(?) AND date(occurred_at) <= date(?)""",
            (pid, start_dt.date().isoformat(), end_dt.date().isoformat()),
        )
        conn.commit()

    rollups = doc.get("rollups") or {}
    per_user_rollup = rollups.get("perUser") or {}
    members = ((doc.get("raw") or {}).get("members") or {}).get("teamMembers") or []
    spend_rows = ((doc.get("raw") or {}).get("spend") or {}).get("teamMemberSpend") or []
    members_by_email = {(m.get("email") or "").lower(): m for m in members if m.get("email")}

    inserted = 0
    user_ids_seen: set[int] = set()
    for sr in spend_rows:
        email = (sr.get("email") or "").lower().strip()
        if not email:
            continue
        spend_cents = int(sr.get("spendCents") or 0)
        included_cents = int(sr.get("includedSpendCents") or 0)
        total_cents = spend_cents + included_cents
        # No cost AND no rollup → skip user
        rollup = per_user_rollup.get(email) or per_user_rollup.get(sr.get("email") or "") or {}
        lines = int(rollup.get("lines") or 0)
        accepts = int(rollup.get("accepts") or 0)
        agent = int(rollup.get("agent") or 0)
        if total_cents <= 0 and lines == 0 and agent == 0:
            continue

        name = (sr.get("name") or members_by_email.get(email, {}).get("name")
                or email.split("@")[0])
        uid = _ensure_user(email, name)
        user_ids_seen.add(uid)

        # One row per day with the day's slice of activity.
        per_day_lines = lines // days
        rem_lines = lines - per_day_lines * days
        per_day_agent = agent // days
        rem_agent = agent - per_day_agent * days
        # Spend is the user's monthly allowance + overage in cents — split evenly.
        per_day_cost = (total_cents / 100.0) / days

        rows: list[tuple] = []
        for d in range(days):
            day_dt = start_dt + timedelta(days=d)
            day_lines = per_day_lines + (1 if d < rem_lines else 0)
            day_agent = per_day_agent + (1 if d < rem_agent else 0)
            # Token estimate: 1 line ≈ 20 tokens (very rough). UI shows it as
            # "tokens_out" so the developer-by-AI-output panels aren't empty.
            tokens_out_est = day_lines * 20
            rows.append((
                uid, pid, cursor_generic_mid, None,  # no api_key
                day_dt.replace(hour=12, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S"),
                tokens_out_est * 5, tokens_out_est, 0,  # tokens_in ~5x out
                round(per_day_cost, 6),
                0, 0, "Cursor",
            ))
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
        "provider": "cursor",
        "mode": "json",
        "source_file": p.name,
        "inserted": inserted,
        "users": len(user_ids_seen),
        "period_from": start_dt.date().isoformat(),
        "period_to": end_dt.date().isoformat(),
        "total_spend_usd": round(float(rollups.get("totalSpend") or 0), 2),
        "active_devs": rollups.get("activeDevs"),
    }
