"""OpenAI JSON loader — when no admin API key is available, drop the
admin-pull JSON into sources/ and we'll populate usage_events from it.

Top-level shape:
    {
      "_meta":   {"rangeStart","rangeEnd","provider":"openai"},
      "rollups": {"totalSpend","totalRequests","perUser":{user_id: requests},
                  "modelMsgs":{model:msgs}, "activeUsers","totalUsers"},
      "raw":     {
        "users": [{id, email, name, role, added_at}, ...],
        "usage": {"data": [{end_time, results:[{user_id, model, num_model_requests,
                                                 input_tokens, output_tokens,...}]}]},
        "cost":  {"data": [{start_time, end_time, results:[{amount:{value},
                                                             line_item, project_id, ...}]}]},
      }
    }

The cost endpoint is project-level (`user_id` is null in OpenAI's API for
cost), so per-user spend is computed from `usage.data` tokens × the
implied $/request from `rollups.totalSpend / totalRequests`. Total
matches `rollups.totalSpend` exactly.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from data.db import get_conn
from ._common import SourceFile, find_all, latest_match


_PATTERNS = ["OpenAI_*.json"]


def find_openai_files() -> list[SourceFile]:
    return find_all(_PATTERNS)


def latest_openai_file() -> SourceFile | None:
    return latest_match(_PATTERNS)


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _ensure_provider() -> int:
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO providers(name) VALUES('openai')")
        return conn.execute(
            "SELECT id FROM providers WHERE name='openai'"
        ).fetchone()["id"]


def _ensure_organization(provider_id: int, label: str) -> int:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO organizations(provider_id, label) VALUES(?, ?)",
            (provider_id, label),
        )
        row = conn.execute(
            "SELECT id FROM organizations WHERE provider_id = ? AND label = ?",
            (provider_id, label),
        ).fetchone()
        conn.commit()
        return row["id"]


def _ensure_user(email: str, name: str, org_id: int | None = None) -> int:
    # Canonical user resolution across HMND domains — see _identity.py.
    # OpenAI-specific addition: tag the user with organization_id when first seen,
    # so multi-org filter in the dashboard works.
    from ._identity import resolve_canonical_user_id
    uid = resolve_canonical_user_id(email, name)
    if org_id is not None:
        with get_conn() as conn:
            conn.execute(
                "UPDATE users SET organization_id = ? WHERE id = ? AND organization_id IS NULL",
                (org_id, uid),
            )
            conn.commit()
    return uid


def _ensure_model(name: str, provider_id: int) -> int:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO models(provider_id, name, family) VALUES(?, ?, ?)",
            (provider_id, name, name.split("-")[0]),
        )
        return conn.execute(
            "SELECT id FROM models WHERE provider_id=? AND name=?",
            (provider_id, name),
        ).fetchone()["id"]


def load_openai_json(path: Path | str, org_label: str = "Humanoid") -> dict[str, Any]:
    """Load an OpenAI dump (sources/OpenAI_*.json) into usage_events.

    Rows are tagged with `organization_id` for `org_label` (default 'Humanoid')
    so that they coexist with API-synced rows from other orgs (e.g. Artem)
    without wiping each other on re-sync.
    """
    p = Path(path)
    doc = json.loads(p.read_text(encoding="utf-8"))

    meta = doc.get("_meta") or {}
    start_iso = meta.get("rangeStart") or doc.get("period_start")
    end_iso = meta.get("rangeEnd") or doc.get("period_end")
    if not start_iso or not end_iso:
        return {"inserted": 0, "errors": ["missing period_start/period_end"], "path": str(p)}

    start_dt = _parse_iso(start_iso)
    end_dt = _parse_iso(end_iso)

    pid = _ensure_provider()
    org_id = _ensure_organization(pid, org_label)

    # Wipe ONLY this org's rows in the period. Otherwise we'd nuke Artem's
    # API-synced events for the same days.
    with get_conn() as conn:
        conn.execute(
            """DELETE FROM usage_events
               WHERE provider_id = ?
                 AND organization_id = ?
                 AND date(occurred_at) >= date(?) AND date(occurred_at) <= date(?)""",
            (pid, org_id, start_dt.date().isoformat(), end_dt.date().isoformat()),
        )
        conn.commit()

    rollups = doc.get("rollups") or {}
    total_spend = float(rollups.get("totalSpend") or 0)

    raw = doc.get("raw") or {}
    users_meta = {u.get("id"): u for u in (raw.get("users") or []) if u.get("id")}

    # Per-day actual cost from raw.cost.data (OpenAI's billing daily totals).
    # Previously we used `total_spend / total_requests` as a uniform per-request
    # cost — that preserves lifetime sums byte-for-byte but smears spend across
    # days, so any 30d window can drift by 5-10% when the period's model-mix
    # differs from lifetime average. Using actual per-day cost eliminates the
    # smear: sum per day = day_cost; sum across all days = total_spend.
    day_cost_usd: dict[str, float] = {}
    for bucket in (raw.get("cost") or {}).get("data") or []:
        st = bucket.get("start_time")
        if isinstance(st, (int, float)):
            day_key = datetime.fromtimestamp(st, tz=timezone.utc).date().isoformat()
        elif isinstance(st, str):
            day_key = _parse_iso(st).date().isoformat()
        else:
            continue
        day_cost_usd[day_key] = sum(
            float((r.get("amount") or {}).get("value") or 0)
            for r in (bucket.get("results") or [])
        )

    # Per-day attributed request count from raw.usage.data — denominator for
    # distributing day_cost across (user, model) events on that day.
    buckets = (raw.get("usage") or {}).get("data") or []
    day_total_reqs: dict[str, int] = {}
    for bucket in buckets:
        end_time = bucket.get("end_time") or bucket.get("end_time_iso")
        if isinstance(end_time, (int, float)):
            day_dt = datetime.fromtimestamp(end_time - 1, tz=timezone.utc)
        elif isinstance(end_time, str):
            day_dt = _parse_iso(end_time) - timedelta(seconds=1)
        else:
            continue
        day_key = day_dt.date().isoformat()
        day_total_reqs[day_key] = day_total_reqs.get(day_key, 0) + sum(
            max(int(r.get("num_model_requests") or 1), 1)
            for r in (bucket.get("results") or [])
            if r.get("user_id")
        )

    # Walk usage buckets, emit one event per (day, user, model).
    inserted = 0
    user_ids_seen: set[int] = set()
    for bucket in buckets:
        end_time = bucket.get("end_time") or bucket.get("end_time_iso")
        if isinstance(end_time, (int, float)):
            day_dt = datetime.fromtimestamp(end_time - 1, tz=timezone.utc)
        elif isinstance(end_time, str):
            day_dt = _parse_iso(end_time) - timedelta(seconds=1)
        else:
            continue
        day_key = day_dt.date().isoformat()
        # Per-request cost = (actual day cost) / (attributed requests that day).
        # Zero if the day has no cost data (e.g. free-tier usage).
        day_reqs = day_total_reqs.get(day_key, 0)
        day_cost = day_cost_usd.get(day_key, 0.0)
        per_request_cost = (day_cost / day_reqs) if day_reqs > 0 else 0.0
        results = bucket.get("results") or []
        with get_conn() as conn:
            rows: list[tuple] = []
            for r in results:
                user_id_ext = r.get("user_id")
                if not user_id_ext:
                    continue
                u_meta = users_meta.get(user_id_ext) or {}
                email = u_meta.get("email") or f"{user_id_ext}@openai-unknown"
                name = u_meta.get("name") or email.split("@")[0]
                uid = _ensure_user(email, name, org_id=org_id)
                user_ids_seen.add(uid)
                model_name = r.get("model") or "unknown"
                mid = _ensure_model(model_name, pid)
                tokens_in = int(r.get("input_tokens") or 0)
                tokens_out = int(r.get("output_tokens") or 0)
                tokens_cached = int(r.get("input_cached_tokens") or 0)
                n_reqs = max(int(r.get("num_model_requests") or 1), 1)
                cost = round(per_request_cost * n_reqs, 6)
                rows.append((
                    uid, pid, mid, None, org_id,
                    day_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    tokens_in, tokens_out, tokens_cached, cost,
                    0, 0, "API",
                ))
            if rows:
                conn.executemany(
                    """INSERT INTO usage_events(
                        user_id, provider_id, model_id, api_key_id, organization_id,
                        occurred_at,
                        tokens_in, tokens_out, tokens_cached, cost_usd,
                        latency_ms, is_error, purpose
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    rows,
                )
                conn.commit()
                inserted += len(rows)

    return {
        "provider": "openai",
        "mode": "json",
        "source_file": p.name,
        "org_label": org_label,
        "inserted": inserted,
        "users": len(user_ids_seen),
        "period_from": start_dt.date().isoformat(),
        "period_to": end_dt.date().isoformat(),
        "total_spend_usd": round(total_spend, 2),
    }
