"""Common helpers for all analytical services: period / provider / team / api-key filters."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class Filters:
    period_days: int = 30
    provider: str = "all"                # 'all' | 'openai' | 'anthropic' | 'cursor' | ...
    team: str = "all"                    # 'all' | team name (legacy: backend/frontend/...)
    organization: str = "all"            # 'all' | org label (Artem, Humanoid, ...)
    repo: Optional[str] = None
    user_id: Optional[int] = None
    # F-13 — explicit date range overrides period_days when both are set.
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    # F-13 — drill-downs.
    api_key_id: Optional[int] = None
    project_id: Optional[int] = None

    def previous_period(self) -> "Filters":
        return Filters(
            period_days=self.period_days,
            provider=self.provider,
            team=self.team,
            organization=self.organization,
            repo=self.repo,
            user_id=self.user_id,
            date_from=self.date_from,
            date_to=self.date_to,
            api_key_id=self.api_key_id,
            project_id=self.project_id,
        )

    def date_range(self, now: datetime | None = None) -> tuple[datetime, datetime]:
        """FR-13.1.1.2 — explicit dates win over period_days."""
        now = now or datetime.utcnow()
        if self.date_from and self.date_to:
            start = self.date_from.replace(hour=0, minute=0, second=0, microsecond=0)
            end = self.date_to.replace(hour=23, minute=59, second=59, microsecond=0)
            return start, end
        start = (now - timedelta(days=self.period_days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return start, now

    def previous_range(self, now: datetime | None = None) -> tuple[datetime, datetime]:
        now = now or datetime.utcnow()
        if self.date_from and self.date_to:
            span = (self.date_to - self.date_from).days + 1
            prev_end = self.date_from - timedelta(seconds=1)
            prev_start = prev_end - timedelta(days=span)
            return prev_start, prev_end
        prev_end = (now - timedelta(days=self.period_days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        prev_start = prev_end - timedelta(days=self.period_days)
        return prev_start, prev_end


def preset_range(label: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """FR-13.1.2.* — return (start, end) for a named preset."""
    now = now or datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=0)
    if label == "Today":
        return today, end_of_today
    if label == "Yesterday":
        y = today - timedelta(days=1)
        return y, y.replace(hour=23, minute=59, second=59)
    if label == "Week to date":
        # Monday-anchored ISO week
        start = today - timedelta(days=today.weekday())
        return start, end_of_today
    if label == "Month to date":
        return today.replace(day=1), end_of_today
    if label == "Last 7 days":
        return today - timedelta(days=7), end_of_today
    if label == "Last 14 days":
        return today - timedelta(days=14), end_of_today
    if label == "Last 30 days":
        return today - timedelta(days=30), end_of_today
    if label == "Last 90 days":
        return today - timedelta(days=90), end_of_today
    raise ValueError(f"unknown preset: {label}")


def provider_clause(provider: str, alias: str = "p") -> tuple[str, list]:
    if provider == "all":
        return "", []
    return f" AND {alias}.name = ? ", [provider]


def team_clause(team: str, alias: str = "t") -> tuple[str, list]:
    if team == "all":
        return "", []
    return f" AND {alias}.name = ? ", [team]


def api_key_clause(api_key_id: int | None, alias: str = "ue") -> tuple[str, list]:
    """FR-13.2.1.1."""
    if not api_key_id:
        return "", []
    return f" AND {alias}.api_key_id = ? ", [api_key_id]


def org_clause(org_label: str, alias: str = "ue") -> tuple[str, list]:
    """Filter usage_events (or users) rows by organization label. Matches via
    a subquery against organizations.label so callers don't need to JOIN.

    `alias` is the usage_events (or users) table alias whose
    `organization_id` column we filter on.
    """
    if not org_label or org_label == "all":
        return "", []
    return (
        f" AND {alias}.organization_id IN "
        f"(SELECT id FROM organizations WHERE label = ?) ",
        [org_label],
    )


def safe_div(a: float, b: float, default: float | None = 0.0):
    if not b:
        return default
    return a / b


def pct_delta(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0 if current == 0 else 100.0
    return round((current - previous) / previous * 100, 1)
