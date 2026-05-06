"""OpenAI Admin API connector — Usage + Costs + Users."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from .base import BaseConnector, SyncReport, to_float, to_int
from data.db import get_conn


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
        keys_by_external = self._sync_api_keys(provider_id, users_by_id, report)
        self._sync_usage(start_dt, end_dt, users_by_id, provider_id, model_ids, keys_by_external, report)
        self._sync_costs(start_dt, end_dt, provider_id, report)
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
            conn.commit()
        model_ids[name] = mid
        return mid

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
                        ts_str = bucket_dt.strftime("%Y-%m-%d %H:%M:%S")
                        api_key_ext = r.get("api_key_id")
                        api_key_id = keys_by_external.get(api_key_ext) if api_key_ext else None
                        for _ in range(requests_n):
                            rows.append((
                                user_id, provider_id, model_id, api_key_id, ts_str,
                                per_in, per_out, per_cached, 0.0, 0, "API",
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

    def _sync_costs(
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
