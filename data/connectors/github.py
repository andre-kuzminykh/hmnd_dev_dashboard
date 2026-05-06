"""GitHub repositories connector — commits, PRs, AI attribution."""
from __future__ import annotations

import re
from datetime import date, timedelta

from .base import BaseConnector, SyncReport

AI_MARKER = re.compile(r"AI-assisted:\s*yes", re.IGNORECASE)
AGENT_TRAILER = re.compile(
    r"Co-authored-by:\s*(claude|copilot|cursor|codex)", re.IGNORECASE
)


class GitHubConnector(BaseConnector):
    name = "github"
    BASE = "https://api.github.com"

    def test_connection(self) -> bool:
        if self.mock:
            return True
        try:
            import requests

            r = requests.get(
                f"{self.BASE}/user",
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
        report.errors.append("real GitHub sync not implemented yet")
        return report

    @staticmethod
    def detect_ai_source(commit_message: str) -> tuple[str | None, float]:
        """FR-05.1.1.2 — порядок доверия источников AI-attribution."""
        if AI_MARKER.search(commit_message or ""):
            return "commit_message_marker", 0.95
        if AGENT_TRAILER.search(commit_message or ""):
            return "agent_metadata", 0.85
        return None, 0.0
