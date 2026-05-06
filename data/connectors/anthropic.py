"""Anthropic usage / costs connector (Admin API)."""
from __future__ import annotations

from datetime import date, timedelta

from .base import BaseConnector, SyncReport


class AnthropicConnector(BaseConnector):
    name = "anthropic"
    BASE = "https://api.anthropic.com/v1/organizations"

    def test_connection(self) -> bool:
        if self.mock:
            return True
        try:
            import requests

            r = requests.get(
                f"{self.BASE}/usage_report/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
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
        report.errors.append("real Anthropic sync not implemented yet")
        return report
