"""Typed dataclasses mirroring DB rows. Используются на границе data ↔ backend."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    id: int
    email: str
    full_name: str
    team_id: Optional[int]
    role: Optional[str]
    monthly_limit_usd: float
    is_active: bool
    created_at: datetime


@dataclass
class Team:
    id: int
    name: str
    monthly_budget_usd: float


@dataclass
class UsageEvent:
    id: int
    user_id: int
    provider_id: int
    model_id: int
    occurred_at: datetime
    tokens_in: int
    tokens_out: int
    tokens_cached: int
    cost_usd: float
    latency_ms: Optional[int]
    is_error: bool
    purpose: Optional[str]


@dataclass
class Seat:
    id: int
    user_id: Optional[int]
    provider_id: int
    seat_type: str
    assigned: bool
    monthly_cost_usd: float
    assigned_at: Optional[datetime]
    last_used_at: Optional[datetime]


@dataclass
class PullRequest:
    id: int
    repo_id: int
    number: int
    title: Optional[str]
    author_id: Optional[int]
    created_at: datetime
    merged_at: Optional[datetime]
    state: str
    additions: int
    deletions: int
    review_comments: int
    critical_files_changed: int
    bug_count: int
    rolled_back: bool
    has_human_review: bool
