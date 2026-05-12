"""SQLite connection + schema bootstrap."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _resolve_db_path(override: Path | str | None = None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("HMND_DB_PATH")
    return Path(env) if env else ROOT / "data" / "hmnd.db"


# Публичный атрибут — динамически читает env (важно для тестов с monkeypatch).
class _LazyPath:
    def __fspath__(self) -> str:
        return str(_resolve_db_path())

    def __str__(self) -> str:
        return str(_resolve_db_path())

    def __getattr__(self, item):
        return getattr(_resolve_db_path(), item)

    @property
    def name(self) -> str:
        return _resolve_db_path().name

    def exists(self) -> bool:
        return _resolve_db_path().exists()


DB_PATH = _LazyPath()


def get_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_schema(db_path: Path | str | None = None) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_conn(db_path) as conn:
        conn.executescript(sql)
        # idempotent migrations for older DBs
        _ensure_column(conn, "usage_events", "api_key_id", "INTEGER")
        _ensure_column(conn, "usage_events", "organization_id", "INTEGER")
        _ensure_column(conn, "api_keys", "organization_id", "INTEGER")
        _ensure_column(conn, "users", "organization_id", "INTEGER")
        _ensure_column(conn, "daily_costs", "organization_id", "INTEGER")
        _ensure_column(conn, "provider_totals", "organization_id", "INTEGER")
        conn.commit()


@contextmanager
def transaction(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = get_conn(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
