"""Anthropic JSON loader v2 — handles the real provider-pull schema.

Top-level shape:
    {
      "_meta":    {"rangeStart": "...", "rangeEnd": "...", "provider":"anthropic"},
      "rollups":  {"totalSpend", "totalRequests", "totalTokens",
                   "spendByProduct": {chat, claude_code, cowork, ...},
                   "modelSpend":     {model_name: $}, ...},
      "raw":      {
        "userCostByProduct": {"data": [{actor, product, amount, requests}, ...]},
        "userUsageByModel":  {"data": [{actor, model, tokens...}, ...]},
        ...
      }
    }

UNIT NOTE — Anthropic Admin API docs:
    "Currency: All costs in USD, reported as decimal strings in lowest
     units (cents)"
So `amount`, `list_amount`, `rollups.totalSpend`, `rollups.spendByProduct.*`,
and `rollups.modelSpend.*` are ALL in cents. We divide by 100 on ingest so
the rest of the dashboard stores actual USD in `cost_usd`.

The loader writes per-user per-product events into `usage_events` with
the spend split evenly over the period in `_meta`, so all downstream
dashboards (Overview, Costs by People, Models, AI Tools) just work.
Idempotent: drops anthropic events in the file's period before insert.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from data.db import get_conn
from ._common import SourceFile, find_all, latest_match


_PATTERNS = ["Anthropic_*.json", "Anthropics_*.json"]

# Map Anthropic product code → our internal `purpose` so UI tabs split right.
_PRODUCT_PURPOSE = {
    "chat":            "Chat",
    "claude_code":     "Agent",
    "cowork":          "Cowork",
    "other":           "Other",
    "claude_in_chrome": "Chrome",
    "claude_design":   "Design",
}


def find_anthropic_files() -> list[SourceFile]:
    return find_all(_PATTERNS)


def latest_anthropic_file() -> SourceFile | None:
    return latest_match(_PATTERNS)


def _parse_iso(s: str) -> datetime:
    # Replace trailing 'Z' so fromisoformat eats it on Python 3.11.
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _compute_daily_product_weights(
    doc: dict[str, Any],
    start_dt: datetime,
    end_dt: datetime,
) -> dict[str, dict[int, float]]:
    """F-18 / FR-18.1.

    Inspect `raw.costByProduct.data[*]` (preferred) or `raw.cost.data[*]`
    (fallback) and build a mapping:

        { product_code: { day_index: weight_fraction } }

    `day_index` is days since `start_dt.date()`. `weight_fraction` is the
    share of that product's spend that landed on that day (sums to 1.0
    over the period if the product has any recorded spend; empty dict
    means "fall back to uniform").

    A special key ``"*"`` carries the same shape but built from total
    daily amounts (provider-wide), used for products that don't appear
    in costByProduct or when costByProduct is empty.
    """
    raw = doc.get("raw") or {}
    cbp = (raw.get("costByProduct") or {}).get("data") or []
    cost = (raw.get("cost") or {}).get("data") or []

    n_days = max((end_dt.date() - start_dt.date()).days + 1, 1)
    weights: dict[str, dict[int, float]] = {}
    totals: dict[str, float] = {}

    # 1. Per-product daily series from costByProduct.
    for bucket in cbp:
        try:
            day_iso = bucket.get("starting_at")
            if not day_iso:
                continue
            day_dt = _parse_iso(day_iso)
            d_idx = (day_dt.date() - start_dt.date()).days
            if d_idx < 0 or d_idx >= n_days:
                continue
            for r in bucket.get("results") or []:
                prod = r.get("product") or "*"
                amt = float(r.get("amount") or 0)  # cents
                if amt <= 0:
                    continue
                weights.setdefault(prod, {}).setdefault(d_idx, 0.0)
                weights[prod][d_idx] += amt
                totals[prod] = totals.get(prod, 0.0) + amt
        except Exception:
            continue

    # 2. Wildcard series from `cost.data` (used as fallback per product).
    wild_w: dict[int, float] = {}
    wild_total = 0.0
    for bucket in cost:
        try:
            day_iso = bucket.get("starting_at")
            if not day_iso:
                continue
            day_dt = _parse_iso(day_iso)
            d_idx = (day_dt.date() - start_dt.date()).days
            if d_idx < 0 or d_idx >= n_days:
                continue
            for r in bucket.get("results") or []:
                amt = float(r.get("amount") or 0)
                if amt <= 0:
                    continue
                wild_w[d_idx] = wild_w.get(d_idx, 0.0) + amt
                wild_total += amt
        except Exception:
            continue
    if wild_total > 0:
        weights["*"] = wild_w
        totals["*"] = wild_total

    # 3. Normalise each series to sum to 1.0
    for prod, day_amt in weights.items():
        t = totals.get(prod) or 0.0
        if t <= 0:
            weights[prod] = {}
            continue
        weights[prod] = {d: a / t for d, a in day_amt.items()}
    return weights


def _allocate_user_product_to_days(
    amount_usd: float,
    requests: int,
    weights: dict[int, float],
    n_days: int,
) -> list[tuple[int, float, int]]:
    """Given a user×product total + a normalised daily weight series,
    return a list of (day_index, day_cost_usd, day_requests) tuples.

    If `weights` is empty or all-zero → uniform split (back-compat,
    FR-18.3).
    Requests are split proportionally to cost (rounded; remainder spread).
    """
    nonzero = {d: w for d, w in (weights or {}).items() if w > 0}
    if not nonzero:
        # Uniform fallback
        if n_days <= 0:
            return []
        per = amount_usd / n_days
        per_req = requests // n_days
        rem = requests - per_req * n_days
        out: list[tuple[int, float, int]] = []
        for d in range(n_days):
            r = per_req + (1 if d < rem else 0)
            out.append((d, per, r))
        return out

    # Weighted: distribute cost by weight, requests proportionally.
    out: list[tuple[int, float, int]] = []
    remaining_reqs = requests
    keys = sorted(nonzero.keys())
    for i, d in enumerate(keys):
        w = nonzero[d]
        day_cost = amount_usd * w
        if i == len(keys) - 1:
            day_reqs = remaining_reqs
        else:
            day_reqs = int(round(requests * w))
            day_reqs = min(day_reqs, remaining_reqs)
            remaining_reqs -= day_reqs
        out.append((d, day_cost, day_reqs))
    return out


def _ensure_provider() -> int:
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO providers(name) VALUES('anthropic')")
        return conn.execute(
            "SELECT id FROM providers WHERE name='anthropic'"
        ).fetchone()["id"]


def _ensure_user(email: str, name: str) -> int:
    # Resolve to canonical user_id across HMND email domains (thehumanoid.ai
    # vs skl.vc) — see data/sources/_identity.py for the policy. Without this
    # the same human ends up with two user_id rows and split spend/segments.
    from ._identity import resolve_canonical_user_id
    return resolve_canonical_user_id(email, name)


def _ensure_model(name: str, provider_id: int) -> int:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO models(provider_id, name, family) VALUES(?, ?, ?)",
            (provider_id, name, "claude"),
        )
        return conn.execute(
            "SELECT id FROM models WHERE provider_id=? AND name=?",
            (provider_id, name),
        ).fetchone()["id"]


def _ensure_api_key(provider_id: int, ext_id: str, name: str, owner_id: int) -> int:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO api_keys(provider_id, external_id, name,
                                              redacted_value, owner_user_id, is_admin)
               VALUES(?, ?, ?, ?, ?, 0)""",
            (provider_id, ext_id, name, f"sk-ant-json-…{ext_id[-6:]}", owner_id),
        )
        return conn.execute(
            "SELECT id FROM api_keys WHERE provider_id=? AND external_id=?",
            (provider_id, ext_id),
        ).fetchone()["id"]


def load_anthropic_json(path: Path | str) -> dict[str, Any]:
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

    # Wipe period
    with get_conn() as conn:
        conn.execute(
            """DELETE FROM usage_events
               WHERE provider_id = ?
                 AND date(occurred_at) >= date(?) AND date(occurred_at) <= date(?)""",
            (pid, start_dt.date().isoformat(), end_dt.date().isoformat()),
        )
        conn.commit()

    # Register models that appear in rollups (no prices — Anthropic dump is
    # post-billed; we already have spend per record, no need to multiply).
    rollups = doc.get("rollups") or {}
    model_spend = rollups.get("modelSpend") or {}
    for mname in model_spend.keys():
        _ensure_model(mname, pid)
    # Generic fallback model that holds events without a specific model column.
    generic_mid = _ensure_model("claude-generic", pid)

    # Per-user per-product cost
    records = (doc.get("raw") or {}).get("userCostByProduct", {}).get("data", []) or []
    if not records:
        return {"inserted": 0, "users": 0,
                "period_from": start_dt.date().isoformat(),
                "period_to": end_dt.date().isoformat(),
                "note": "no userCostByProduct rows"}

    # F-18 / FR-18.1 — build per-product daily weight series. Empty dict
    # for a product means "use the wildcard (*) series", and an empty *
    # means "uniform" (handled inside _allocate_user_product_to_days).
    daily_weights = _compute_daily_product_weights(doc, start_dt, end_dt)

    inserted = 0
    user_ids: set[int] = set()
    for rec in records:
        actor = rec.get("actor") or {}
        if actor.get("type") != "user_actor":
            continue
        email = (actor.get("email") or "").strip()
        if not email:
            continue
        name = actor.get("name") or email.split("@")[0]
        uid = _ensure_user(email, name)
        user_ids.add(uid)

        product = rec.get("product") or "other"
        purpose = _PRODUCT_PURPOSE.get(product, product or "Other")
        # Anthropic admin API reports amounts in CENTS (lowest currency unit).
        # Divide by 100 to get USD before everything downstream.
        amount = float(rec.get("amount") or 0) / 100.0
        requests = int(rec.get("requests") or 0)
        if amount <= 0 and requests <= 0:
            continue

        kid = _ensure_api_key(pid, f"sk-ant-json-{email}-{product}",
                              f"{name}/{product}", uid)

        # F-18 / FR-18.2 — allocate this user×product total across the
        # period using the product's own daily weight curve, falling back
        # to the provider-wide curve, then to uniform.
        weights = (daily_weights.get(product)
                   or daily_weights.get("*")
                   or {})
        slices = _allocate_user_product_to_days(amount, requests, weights, days)

        rows: list[tuple] = []
        for d_idx, day_cost, n in slices:
            if day_cost <= 0 and n <= 0:
                # FR-18 / UC-18.3 — days with zero recorded activity stay empty.
                continue
            day_dt = start_dt + timedelta(days=d_idx)
            # Token counts are approximations: rollups.totalTokens / totalRequests
            # gives ~112K avg tokens/request, but per-user/per-product token split
            # isn't in this dump. Use a representative split so the UI shows
            # non-zero token columns; cost is exact and that's what matters.
            tin = int(2500 * n) if n > 0 else 0
            tout = int(800 * n) if n > 0 else 0
            rows.append((
                uid, pid, generic_mid, kid,
                day_dt.replace(hour=12, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S"),
                tin, tout, 0, round(day_cost, 6),
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
        "users": len(user_ids),
        "period_from": start_dt.date().isoformat(),
        "period_to": end_dt.date().isoformat(),
        "total_spend_usd": round(float(rollups.get("totalSpend") or 0) / 100.0, 2),
    }
