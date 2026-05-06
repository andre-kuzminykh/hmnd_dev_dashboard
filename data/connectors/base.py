from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class SyncReport:
    provider: str
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    period_from: date | None = None
    period_to: date | None = None


class BaseConnector:
    """Контракт коннектора, FR-09.1.1.1."""

    name: str = "base"

    def __init__(self, api_key: str | None = None, mock: bool = True):
        self.api_key = api_key
        # FR-09.1.1.2: при отсутствии ключа коннектор НЕ хранит его никуда и работает в mock-режиме.
        self.mock = mock or not api_key

    def test_connection(self) -> bool:
        if self.mock:
            return True
        raise NotImplementedError

    def sync(self, period_days: int = 7) -> SyncReport:
        raise NotImplementedError
