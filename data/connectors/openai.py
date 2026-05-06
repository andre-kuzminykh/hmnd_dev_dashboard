"""OpenAI Admin API connector — Usage + Costs + Users."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from .base import BaseConnector, SyncReport, to_float, to_int
from data.db import get_conn


# Hard-coded $/1K-token prices for the most common OpenAI models.
# Used to compute cost_usd per usage event when the org's costs endpoint
# can't be group_by-ed at user_id level.
# Format: model_name -> (input_per_1k, output_per_1k, cache_read_per_1k)
OPENAI_DEFAULT_PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-4o":                  (0.0025,   0.01,    0.00125),
    "gpt-4o-mini":             (0.00015,  0.0006,  0.000075),
    "gpt-4o-realtime-preview": (0.005,    0.02,    0.0025),
    "gpt-4-turbo":             (0.01,     0.03,    0.0),
    "gpt-4":                   (0.03,     0.06,    0.0),
    "gpt-3.5-turbo":           (0.0005,   0.0015,  0.0),
    "gpt-5":                   (0.005,    0.015,   0.0025),
    "gpt-5.1":                 (0.005,    0.015,   0.0025),
    "gpt-5.1-mini":            (0.0008,   0.0024,  0.0004),
    "o1":                      (0.015,    0.06,    0.0075),
    "o1-mini":                 (0.003,    0.012,   0.0015),
    "o1-preview":              (0.015,    0.06,    0.0075),
    "o3":                      (0.002,    0.008,   0.001),
    "o3-mini":                 (0.0011,   0.0044,  0.00055),
    "o4-mini":                 (0.0011,   0.0044,  0.00055),
    "text-embedding-3-small":  (0.00002,  0.0,     0.0),
    "text-embedding-3-large":  (0.00013,  0.0,     0.0),
    "text-embedding-ada-002":  (0.0001,   0.0,     0.0),
}


def _model_price_lookup(name: str) -> tuple[float, float, float] | None:
    """Find prices for `name` (exact) or its base (e.g. 'gpt-4o-2024-08-06' → 'gpt-4o').

    Returns None when no match is found — caller should default to 0.
    """
    if not name:
        return None
    if name in OPENAI_DEFAULT_PRICES:
        return OPENAI_DEFAULT_PRICES[name]
    # Try longest-prefix match (handles versioned models like gpt-4o-2024-08-06)
    for base in sorted(OPENAI_DEFAULT_PRICES.keys(), key=len, reverse=True):
        if name.startswith(base):
            return OPENAI_DEFAULT_PRICES[base]
    return None


class OpenAIConnector(BaseConnector):
    name = "openai"
    BASE = "https://api.openai.com/v1/organization"

    # ---- helpers ----
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any]) -> dict | None:
        import requests

        try:
            r = requests.get(
                f"{self.BASE}/{path}", headers=self._headers(), params=params, timeout=30
            )
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:
            return None

    def test_connection(self) -> bool:
        if self.mock:
            return True
        data = self._get("users", {"limit": 1})
        return data is not None

    # ---- main sync ----
    def sync(self, period_days: int = 7) -> SyncReport:
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=period_days)
        report = SyncReport(provider=self.name, period_from=start_dt.date(), period_to=end_dt.date())
        if self.mock:
            report.skipped = 1
            return report

        users_by_id = self._sync_users(report)
        provider_id, model_ids = self._ensure_provider_and_models(report)
        # Backfill default prices for models created by previous sync runs
        self._backfill_prices(provider_id)
        keys_by_external = self._sync_api_keys(provider_id, users_by_id, report)
        self._sync_usage(start_dt, end_dt, users_by_id, provider_id, model_ids, keys_by_external, report)
        # Org-level totals from /costs endpoint are kept as a sanity log only;
        # per-event cost_usd is now computed from model prices in _sync_usage,
        # which gives accurate per-user attribution that the costs endpoint
        # cannot provide (it does not support group_by=user_id).
        self._sync_costs_report_only(start_dt, end_dt, report)
        return report

    # ---- api keys ----
    def _sync_api_keys(
        self, provider_id: int, users_by_id: dict[str, int], report: SyncReport
    ) -> dict[str, int]:
        """`/v1/organization/admin_api_keys` (admin keys) и `/v1/organization/api_keys`.

        Возвращает mapping external_id → local id.
        """
        keys_by_external: dict[str, int] = {}
        for endpoint, is_admin in (("admin_api_keys", 1), ("api_keys", 0)):
            after = None
            while True:
                params = {"limit": 100}
                if after:
                    params["after"] = after
                data = self._get(endpoint, params)
                if data is None:
                    # endpoint может быть недоступен в зависимости от прав
                    break
                items = data.get("data", []) if isinstance(data, dict) else []
                for k in items:
                    ext = k.get("id") or k.get("key_id")
                    if not ext:
                        continue
                    name = k.get("name") or "(unnamed)"
                    redacted = k.get("redacted_value") or k.get("redacted_key") or ""
                    owner_ext = (k.get("owner") or {}).get("id") if isinstance(k.get("owner"), dict) else None
                    owner_local = users_by_id.get(owner_ext) if owner_ext else None
                    created_at = k.get("created_at")
                    last_used = k.get("last_used_at")
                    with get_conn() as conn:
                        row = conn.execute(
                            "SELECT id FROM api_keys WHERE provider_id=? AND external_id=?",
                            (provider_id, ext),
                        ).fetchone()
                        if row:
                            kid = row["id"]
                            conn.execute(
                                """UPDATE api_keys SET name=?, redacted_value=?, owner_user_id=?,
                                                       is_admin=?, last_used_at=? WHERE id=?""",
                                (name, redacted, owner_local, is_admin, last_used, kid),
                            )
                        else:
                            kid = conn.execute(
                                """INSERT INTO api_keys(provider_id, external_id, name, redacted_value,
                                                        owner_user_id, is_admin, created_at, last_used_at)
                                   VALUES(?,?,?,?,?,?,?,?)""",
                                (provider_id, ext, name, redacted, owner_local, is_admin, created_at, last_used),
                            ).lastrowid
                            report.inserted += 1
                        conn.commit()
                    keys_by_external[ext] = kid
                if not data.get("has_more"):
                    break
                after = data.get("last_id")
        return keys_by_external

    # ---- pieces ----
    def _ensure_provider_and_models(self, report: SyncReport) -> tuple[int, dict[str, int]]:
        with get_conn() as conn:
            row = conn.execute("SELECT id FROM providers WHERE name = 'openai'").fetchone()
            if row:
                provider_id = row["id"]
            else:
                cur = conn.execute("INSERT INTO providers(name) VALUES('openai')")
                provider_id = cur.lastrowid
            rows = conn.execute(
                "SELECT id, name FROM models WHERE provider_id = ?", (provider_id,)
            ).fetchall()
            conn.commit()
        return provider_id, {r["name"]: r["id"] for r in rows}

    def _ensure_model(self, name: str, provider_id: int, model_ids: dict[str, int]) -> int:
        if name in model_ids:
            return model_ids[name]
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO models(provider_id, name, family) VALUES(?,?,?)",
                (provider_id, name, name.split("-")[0]),
            )
            mid = cur.lastrowid
            price = _model_price_lookup(name)
            if price:
                conn.execute(
                    """INSERT INTO model_prices(model_id, valid_from,
                                                input_per_1k, output_per_1k, cache_read_per_1k)
                       VALUES(?, '2026-01-01', ?, ?, ?)""",
                    (mid, *price),
                )
            conn.commit()
        model_ids[name] = mid
        return mid

    def _backfill_prices(self, provider_id: int) -> int:
        """For OpenAI models that exist without a price row, insert defaults."""
        inserted = 0
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT m.id, m.name FROM models m
                   LEFT JOIN model_prices mp ON mp.model_id = m.id
                   WHERE m.provider_id = ? AND mp.id IS NULL""",
                (provider_id,),
            ).fetchall()
            for r in rows:
                price = _model_price_lookup(r["name"])
                if not price:
                    continue
                conn.execute(
                    """INSERT INTO model_prices(model_id, valid_from,
                                                input_per_1k, output_per_1k, cache_read_per_1k)
                       VALUES(?, '2026-01-01', ?, ?, ?)""",
                    (r["id"], *price),
                )
                inserted += 1
            conn.commit()
        return inserted

    def _price_cache(self, provider_id: int) -> dict[int, tuple[float, float, float]]:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT model_id, input_per_1k, output_per_1k, cache_read_per_1k
                   FROM model_prices mp
                   JOIN models m ON m.id = mp.model_id
                   WHERE m.provider_id = ?""",
                (provider_id,),
            ).fetchall()
        return {
            r["model_id"]: (r["input_per_1k"], r["output_per_1k"], r["cache_read_per_1k"])
            for r in rows
        }

    def _sync_users(self, report: SyncReport) -> dict[str, int]:
        """`/v1/organization/users` → upsert по email."""
        users_by_id: dict[str, int] = {}
        after = None
        while True:
            params = {"limit": 100}
            if after:
                params["after"] = after
            data = self._get("users", params)
            if data is None:
                report.errors.append("users endpoint failed")
                break
            items = data.get("data", []) if isinstance(data, dict) else []
            for u in items:
                email = u.get("email") or f"{u.get('id','unknown')}@openai"
                full_name = u.get("name") or email
                role = u.get("role")
                with get_conn() as conn:
                    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
                    if row:
                        uid = row["id"]
                    else:
                        cur = conn.execute(
                            """INSERT INTO users(email, full_name, role, monthly_limit_usd, is_active)
                               VALUES(?,?,?,?,1)""",
                            (email, full_name, role, 200),
                        )
                        uid = cur.lastrowid
                        report.inserted += 1
                    conn.commit()
                users_by_id[u.get("id", "")] = uid
            if not data.get("has_more"):
                break
            after = data.get("last_id")
        return users_by_id

    def _sync_usage(
        self,
        start_dt: datetime,
        end_dt: datetime,
        users_by_id: dict[str, int],
        provider_id: int,
        model_ids: dict[str, int],
        keys_by_external: dict[str, int],
        report: SyncReport,
    ) -> None:
        """`/usage/completions` группируем по user_id и model, bucket = 1d.

        Идемпотентность: перед загрузкой удаляем уже существующие события
        OpenAI в окне, чтобы повторный sync не дублировал записи.
        Tokens равномерно делим между requests'ами одного bucket'а — это даёт
        нормальные `COUNT(*)` в models breakdown и аккуратные суммы в KPI.
        """
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM usage_events WHERE provider_id = ? AND occurred_at BETWEEN ? AND ?",
                (
                    provider_id,
                    start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            conn.commit()

        params: dict[str, Any] = {
            "start_time": int(start_dt.timestamp()),
            "end_time": int(end_dt.timestamp()),
            "bucket_width": "1d",
            "group_by": "user_id,model,api_key_id",
            "limit": 31,
        }
        # Preload prices once per sync (one query, then in-memory lookup).
        prices_by_model = self._price_cache(provider_id)
        page = None
        while True:
            if page:
                params["page"] = page
            data = self._get("usage/completions", params)
            if data is None:
                report.errors.append("usage/completions failed")
                return
            for bucket in data.get("data", []):
                ts = bucket.get("start_time")
                if not ts:
                    continue
                bucket_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                with get_conn() as conn:
                    rows: list[tuple] = []
                    for r in bucket.get("results", []):
                        user_ext = r.get("user_id")
                        user_id = users_by_id.get(user_ext)
                        if not user_id:
                            continue
                        model_name = r.get("model") or "unknown"
                        model_id = self._ensure_model(model_name, provider_id, model_ids)
                        tokens_in = to_int(r.get("input_tokens"))
                        tokens_out = to_int(r.get("output_tokens"))
                        tokens_cached = to_int(r.get("input_cached_tokens"))
                        requests_n = max(to_int(r.get("num_model_requests"), default=1), 1)
                        per_in = tokens_in // requests_n
                        per_out = tokens_out // requests_n
                        per_cached = tokens_cached // requests_n
                        # Compute cost per event using model prices.
                        p_in, p_out, p_cache = prices_by_model.get(model_id, (0.0, 0.0, 0.0))
                        billed_in = max(per_in - per_cached, 0)
                        per_cost = round(
                            billed_in / 1000.0 * p_in
                            + per_cached / 1000.0 * p_cache
                            + per_out / 1000.0 * p_out,
                            6,
                        )
                        ts_str = bucket_dt.strftime("%Y-%m-%d %H:%M:%S")
                        api_key_ext = r.get("api_key_id")
                        api_key_id = keys_by_external.get(api_key_ext) if api_key_ext else None
                        for _ in range(requests_n):
                            rows.append((
                                user_id, provider_id, model_id, api_key_id, ts_str,
                                per_in, per_out, per_cached, per_cost, 0, "API",
                            ))
                    if rows:
                        conn.executemany(
                            """INSERT INTO usage_events(
                                user_id, provider_id, model_id, api_key_id, occurred_at,
                                tokens_in, tokens_out, tokens_cached, cost_usd,
                                is_error, purpose
                            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            rows,
                        )
                        report.inserted += len(rows)
                    conn.commit()
            if not data.get("has_more"):
                break
            page = data.get("next_page")

    def _sync_costs_report_only(
        self, start_dt: datetime, end_dt: datetime, report: SyncReport
    ) -> None:
        """Pull org total from /costs and stash it on the report for cross-check.
        Does NOT write to daily_costs — those are aggregated from usage_events.
        """
        params: dict[str, Any] = {
            "start_time": int(start_dt.timestamp()),
            "end_time": int(end_dt.timestamp()),
            "bucket_width": "1d",
            "limit": 31,
        }
        page = None
        total = 0.0
        while True:
            if page:
                params["page"] = page
            data = self._get("costs", params)
            if data is None:
                report.errors.append("costs endpoint failed (cross-check skipped)")
                return
            for bucket in data.get("data", []):
                for r in bucket.get("results", []):
                    total += to_float((r.get("amount") or {}).get("value"))
            if not data.get("has_more"):
                break
            page = data.get("next_page")
        report.errors.append(f"openai_reported_total_usd={round(total, 2)}")

    def _sync_costs_legacy(
        self, start_dt: datetime, end_dt: datetime, provider_id: int, report: SyncReport
    ) -> None:
        """`/costs` → daily_costs (на уровне организации)."""
        params: dict[str, Any] = {
            "start_time": int(start_dt.timestamp()),
            "end_time": int(end_dt.timestamp()),
            "bucket_width": "1d",
            "limit": 31,
        }
        page = None
        while True:
            if page:
                params["page"] = page
            data = self._get("costs", params)
            if data is None:
                report.errors.append("costs failed")
                return
            for bucket in data.get("data", []):
                ts = bucket.get("start_time")
                day = (
                    datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
                    if ts
                    else None
                )
                if not day:
                    continue
                cost = 0.0
                for r in bucket.get("results", []):
                    cost += to_float((r.get("amount") or {}).get("value"))
                # пишем в daily_costs на «организационного» юзера id=NULL не позволит схема,
                # поэтому маппим на первого юзера из users_by_id; либо обновим existing rows.
                with get_conn() as conn:
                    row = conn.execute(
                        "SELECT id FROM users ORDER BY id LIMIT 1"
                    ).fetchone()
                    if not row:
                        continue
                    conn.execute(
                        """INSERT INTO daily_costs(user_id, provider_id, day,
                                                   cost_usd, tokens_in, tokens_out, requests)
                           VALUES(?,?,?,?,0,0,0)
                           ON CONFLICT(user_id, provider_id, day)
                           DO UPDATE SET cost_usd = excluded.cost_usd""",
                        (row["id"], provider_id, day, round(cost, 4)),
                    )
                    conn.commit()
                    report.updated += 1
            if not data.get("has_more"):
                break
            page = data.get("next_page")
