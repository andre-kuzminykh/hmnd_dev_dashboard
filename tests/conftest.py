"""Каждый тест работает в изолированной БД через env HMND_DB_PATH."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db))
    from data.seed import seed  # noqa: WPS433  — поздний импорт, чтобы env подхватился

    seed(db, days=14)
    yield db
