"""Cursor_*.json loader — JSON version of the CSV exports we already
support. When both are present, JSON wins (newer, structured).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._common import SourceFile, find_all, latest_match


_PATTERNS = ["Cursor_*.json"]


def find_cursor_files() -> list[SourceFile]:
    return find_all(_PATTERNS)


def latest_cursor_file() -> SourceFile | None:
    return latest_match(_PATTERNS)


def load_cursor_json(path: Path | str) -> dict[str, Any]:
    """Parse a Cursor_YYYYMMDD.json into normalised dict that the existing
    cursor_analytics module can also serve.

    Returns:
        {
          "period_start", "period_end",
          "users": [{email, name, agent_completions, tab_completions,
                     ai_lines, favorite_model, ...}],
          "models": [...],
          "summary": {...}
        }
    """
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, Any] = {
        "period_start": data.get("period_start"),
        "period_end":   data.get("period_end"),
        "users":  list(data.get("users") or []),
        "models": list(data.get("models") or []),
        "summary": dict(data.get("summary") or {}),
        "source_file": p.name,
    }
    # Normalise field names: leaderboard uses these on the CSV/CSV-loader.
    for u in out["users"]:
        u.setdefault("agent_completions", 0)
        u.setdefault("tab_completions", 0)
        u.setdefault("agent_lines", 0)
        u.setdefault("tab_lines", 0)
        u.setdefault("ai_lines", 0)
        u.setdefault("favorite_model", "")
    return out
