"""OpenAI usage / costs connector.

В реальном развёртывании дергает https://api.openai.com/v1/organization/usage
(usage_buckets) и https://api.openai.com/v1/organization/costs.
"""
from __future__ import annotations

from datetime import date, timedelta

from .base import BaseConnector, SyncReport


class OpenAIConnector(BaseConnector):
    name = "openai"
    BASE = "https://api.openai.com/v1/organization"

    def test_connection(self) -> bool:
        if self.mock:
            return True
        try:
            import requests

            r = requests.get(
                f"{self.BASE}/users",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            return r.status_code in (200, 401)
        except Exception:
            return False

    def sync(self, period_days: int = 7) -> SyncReport:
        end = date.today()
        start = end - timedelta(days=period_days)
        report = SyncReport(provider=self.name, period_from=start, period_to=end)
        if self.mock:
            report.skipped = 1
            return report
        # реальный sync — задел на будущее: пагинация по usage_buckets и upsert в usage_events
        report.errors.append("real OpenAI sync not implemented yet")
        return report
