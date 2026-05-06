"""Общие хелперы для всех сервисов: фильтры периода, провайдера, команды."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class Filters:
    period_days: int = 30
    provider: str = "all"      # 'all' | 'openai' | 'anthropic'
    team: str = "all"          # 'all' | team name
    repo: Optional[str] = None
    user_id: Optional[int] = None

    def previous_period(self) -> "Filters":
        return Filters(
            period_days=self.period_days,
            provider=self.provider,
            team=self.team,
            repo=self.repo,
            user_id=self.user_id,
        )

    def date_range(self, now: datetime | None = None) -> tuple[datetime, datetime]:
        now = now or datetime.utcnow()
        start = (now - timedelta(days=self.period_days)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now

    def previous_range(self, now: datetime | None = None) -> tuple[datetime, datetime]:
        now = now or datetime.utcnow()
        prev_end = (now - timedelta(days=self.period_days)).replace(hour=0, minute=0, second=0, microsecond=0)
        prev_start = prev_end - timedelta(days=self.period_days)
        return prev_start, prev_end


def provider_clause(provider: str, alias: str = "p") -> tuple[str, list]:
    if provider == "all":
        return "", []
    return f" AND {alias}.name = ? ", [provider]


def team_clause(team: str, alias: str = "t") -> tuple[str, list]:
    if team == "all":
        return "", []
    return f" AND {alias}.name = ? ", [team]


def safe_div(a: float, b: float, default: float | None = 0.0):
    if not b:
        return default
    return a / b


def pct_delta(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0 if current == 0 else 100.0
    return round((current - previous) / previous * 100, 1)
