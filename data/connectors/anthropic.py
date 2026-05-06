"""Anthropic Admin API connector.

Anthropic's Admin API (`/v1/organizations/usage_report/messages`,
`/v1/organizations/cost_report`) требует **Admin** ключ. Обычный
`sk-ant-api03-...` ключ его дёрнуть не сможет — запрос вернёт 401/403,
и мы остановимся с понятным сообщением.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from .base import BaseConnector, SyncReport
from data.db import get_conn


class AnthropicConnector(BaseConnector):
    name = "anthropic"
    BASE = "https://api.anthropic.com/v1/organizations"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any]) -> tuple[int, dict | None]:
        import requests

        try:
            r = requests.get(
                f"{self.BASE}/{path}", headers=self._headers(), params=params, timeout=30
            )
            return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else None)
        except Exception:
            return 0, None

    def test_connection(self) -> bool:
        if self.mock:
            return True
        code, _ = self._get("usage_report/messages", {"limit": 1})
        return code == 200

    def sync(self, period_days: int = 7) -> SyncReport:
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=period_days)
        report = SyncReport(provider=self.name, period_from=start_dt.date(), period_to=end_dt.date())
        if self.mock:
            report.skipped = 1
            return report

        # Admin-only — graceful если ключ не админский
        code, data = self._get(
            "usage_report/messages",
            {
                "starting_at": start_dt.isoformat().replace("+00:00", "Z"),
                "ending_at": end_dt.isoformat().replace("+00:00", "Z"),
                "bucket_width": "1d",
                "limit": 31,
            },
        )
        if code in (401, 403):
            report.errors.append(
                "Anthropic admin key required (current key has no access to /organizations/usage_report)."
            )
            return report
        if code != 200 or data is None:
            report.errors.append(f"Anthropic usage_report HTTP {code}")
            return report

        provider_id, model_ids = self._ensure_provider_and_models()
        with get_conn() as conn:
            row = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        org_user_id = row["id"] if row else None
        if not org_user_id:
            report.errors.append("no users in DB to attribute Anthropic usage to")
            return report

        for bucket in data.get("data", []):
            day = (bucket.get("starting_at") or "")[:10]
            if not day:
                continue
            for r in bucket.get("results", []):
                model_name = r.get("model") or "unknown"
                model_id = self._ensure_model(model_name, provider_id, model_ids)
                tokens_in = r.get("input_tokens", 0) + r.get("cache_creation_input_tokens", 0)
                tokens_out = r.get("output_tokens", 0)
                tokens_cached = r.get("cache_read_input_tokens", 0)
                with get_conn() as conn:
                    conn.execute(
                        """INSERT INTO usage_events(
                            user_id, provider_id, model_id, occurred_at,
                            tokens_in, tokens_out, tokens_cached, cost_usd, is_error, purpose
                        ) VALUES(?,?,?,?,?,?,?,?,0,'API')""",
                        (
                            org_user_id,
                            provider_id,
                            model_id,
                            f"{day} 00:00:00",
                            tokens_in,
                            tokens_out,
                            tokens_cached,
                            0.0,
                        ),
                    )
                    conn.commit()
                    report.inserted += 1

        # cost_report
        code, data = self._get(
            "cost_report",
            {
                "starting_at": start_dt.isoformat().replace("+00:00", "Z"),
                "ending_at": end_dt.isoformat().replace("+00:00", "Z"),
                "bucket_width": "1d",
            },
        )
        if code == 200 and data:
            for bucket in data.get("data", []):
                day = (bucket.get("starting_at") or "")[:10]
                cost = sum((r.get("amount") or {}).get("value", 0) for r in bucket.get("results", []))
                if not day:
                    continue
                with get_conn() as conn:
                    conn.execute(
                        """INSERT INTO daily_costs(user_id, provider_id, day,
                                                   cost_usd, tokens_in, tokens_out, requests)
                           VALUES(?,?,?,?,0,0,0)
                           ON CONFLICT(user_id, provider_id, day)
                           DO UPDATE SET cost_usd = excluded.cost_usd""",
                        (org_user_id, provider_id, day, round(cost, 4)),
                    )
                    conn.commit()
                    report.updated += 1
        return report

    def _ensure_provider_and_models(self) -> tuple[int, dict[str, int]]:
        with get_conn() as conn:
            row = conn.execute("SELECT id FROM providers WHERE name='anthropic'").fetchone()
            if row:
                pid = row["id"]
            else:
                pid = conn.execute("INSERT INTO providers(name) VALUES('anthropic')").lastrowid
            rows = conn.execute("SELECT id, name FROM models WHERE provider_id = ?", (pid,)).fetchall()
            conn.commit()
        return pid, {r["name"]: r["id"] for r in rows}

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
