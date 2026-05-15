"""Cursor team analytics — CSV-backed loader.

User exports four files from Cursor's admin (kept at repo root):

    Analytics_Team_<from>_<to>.csv          team-wide daily stats incl. per-model JSON
    Contribution_Analytics_<from>_<to>.csv  composer + tabs daily diff stats
    Team_DAU_Analytics_<from>_<to>.csv      daily active users
    User_Leaderboard_<from>_<to>.csv        per-user totals over the period

Files are auto-discovered at every dashboard render (pattern + glob). The
period encoded in the filename becomes the canonical (from, to) for that
file's rows. When multiple snapshots exist (user uploads new files weekly),
the loader concatenates rows and keeps the most recent period per user/day.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent.parent
EXPORT_DIR = Path(os.environ.get("HMND_CURSOR_EXPORT_DIR", str(ROOT)))

_DATE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$")


@dataclass
class Period:
    start: date
    end: date

    @property
    def key(self) -> str:
        return f"{self.start.isoformat()}_{self.end.isoformat()}"


def _parse_period(filename: str) -> Period | None:
    m = _DATE_RE.search(filename)
    if not m:
        return None
    return Period(
        start=date.fromisoformat(m.group(1)),
        end=date.fromisoformat(m.group(2)),
    )


def _files(pattern: str) -> list[tuple[Period, Path]]:
    out: list[tuple[Period, Path]] = []
    for path in glob.glob(str(EXPORT_DIR / pattern)):
        p = _parse_period(path)
        if p:
            out.append((p, Path(path)))
    # Latest-period last so .extend() naturally lets the latest dominate
    # in deduping that follows.
    out.sort(key=lambda x: (x[0].end, x[0].start))
    return out


def _to_int(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _to_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# -------------------- public loaders --------------------


def load_user_leaderboard() -> list[dict[str, Any]]:
    """Combine all sources. Priority: JSON (sources/Cursor_*.json) > CSV.

    JSON overrides because vendors usually export it as the canonical
    weekly snapshot and CSVs can be stale. Within each source, later
    period overrides earlier per email.
    """
    by_email: dict[str, dict[str, Any]] = {}

    # 1. CSVs first (lowest priority, may be overwritten by JSON below).
    for period, path in _files("User_Leaderboard_*.csv"):
        with path.open() as f:
            for row in csv.DictReader(f):
                email = row.get("Email") or ""
                if not email:
                    continue
                by_email[email] = {
                    "email": email,
                    "name": row.get("Name") or email.split("@")[0],
                    "agent_completions": _to_int(row.get("Agent Completions")),
                    "agent_lines": _to_int(row.get("Agent Lines")),
                    "tab_completions": _to_int(row.get("Tab Completions")),
                    "tab_lines": _to_int(row.get("Tab Lines")),
                    "ai_lines": _to_int(row.get("Ai Lines")),
                    "favorite_model": (row.get("Favorite Model") or "").strip(),
                    "period_start": period.start.isoformat(),
                    "period_end": period.end.isoformat(),
                }

    # 2. JSON sources/Cursor_*.json — higher priority than CSV, override
    #    per email.
    try:
        from data.sources.cursor_json import find_cursor_files, load_cursor_json
        for sf in find_cursor_files():
            doc = load_cursor_json(sf.path)
            ps = doc.get("period_start") or ""
            pe = doc.get("period_end") or ""
            for u in doc.get("users", []):
                email = u.get("email") or ""
                if not email:
                    continue
                by_email[email] = {
                    "email": email,
                    "name": u.get("name") or email.split("@")[0],
                    "agent_completions": int(u.get("agent_completions") or 0),
                    "agent_lines": int(u.get("agent_lines") or 0),
                    "tab_completions": int(u.get("tab_completions") or 0),
                    "tab_lines": int(u.get("tab_lines") or 0),
                    "ai_lines": int(u.get("ai_lines") or 0),
                    "favorite_model": (u.get("favorite_model") or "").strip(),
                    "period_start": ps,
                    "period_end": pe,
                }
    except Exception:
        # Sources module / files absent — fall back to CSV-only behaviour.
        pass

    return sorted(by_email.values(), key=lambda r: r["ai_lines"], reverse=True)


def load_team_dau() -> list[dict[str, Any]]:
    """Concat Team_DAU_Analytics_*.csv. Dedupe by date (last period wins)."""
    by_day: dict[str, dict[str, Any]] = {}
    for period, path in _files("Team_DAU_Analytics_*.csv"):
        with path.open() as f:
            for row in csv.DictReader(f):
                d = row.get("Date") or ""
                if not d:
                    continue
                by_day[d] = {
                    "date": d,
                    "dau": _to_int(row.get("Daily Active Users")),
                    "cli_dau": _to_int(row.get("Cli Dau")),
                    "bga_dau": _to_int(row.get("Bga Dau")),
                    "bugbot_dau": _to_int(row.get("Bugbot Dau")),
                }
    return sorted(by_day.values(), key=lambda r: r["date"])


def load_contribution_daily() -> list[dict[str, Any]]:
    by_day: dict[str, dict[str, Any]] = {}
    for period, path in _files("Contribution_Analytics_*.csv"):
        with path.open() as f:
            for row in csv.DictReader(f):
                d = row.get("Date") or ""
                if not d:
                    continue
                by_day[d] = {
                    "date": d,
                    "composer_suggested": _to_int(row.get("Composer Total Suggested Diffs")),
                    "composer_accepted": _to_int(row.get("Composer Total Accepted Diffs")),
                    "composer_lines_accepted": _to_int(row.get("Composer Total Lines Accepted")),
                    "tabs_suggestions": _to_int(row.get("Tabs Total Suggestions")),
                    "tabs_accepts": _to_int(row.get("Tabs Total Accepts")),
                    "tabs_lines_accepted": _to_int(row.get("Tabs Total Lines Accepted")),
                }
    return sorted(by_day.values(), key=lambda r: r["date"])


def load_team_analytics() -> list[dict[str, Any]]:
    """Slim view of Analytics_Team_*.csv — columns we actually use plus the
    parsed models breakdown JSON.
    """
    by_day: dict[str, dict[str, Any]] = {}
    for period, path in _files("Analytics_Team_*.csv"):
        with path.open() as f:
            for row in csv.DictReader(f):
                d = row.get("Date") or ""
                if not d:
                    continue
                models_json = row.get("Models Time Series Data") or ""
                models = []
                try:
                    parsed = json.loads(models_json) if models_json else []
                    if parsed and isinstance(parsed, list):
                        breakdown = (parsed[0] or {}).get("model_breakdown") or {}
                        for name, stats in breakdown.items():
                            models.append({
                                "model": name,
                                "requests": _to_int((stats or {}).get("requests")),
                                "users": _to_int((stats or {}).get("users")),
                            })
                except Exception:
                    pass
                by_day[d] = {
                    "date": d,
                    "ai_commits_total": _to_int(row.get("Ai Commits Total Commits")),
                    "ai_lines_added": _to_int(row.get("Ai Commits Ai Lines Added")),
                    "non_ai_lines_added": _to_int(row.get("Ai Commits Non Ai Lines Added")),
                    "bg_agent_prs_opened": _to_int(row.get("Bg Agent P Rs Opened")),
                    "bg_agent_prs_merged": _to_int(row.get("Bg Agent P Rs Merged")),
                    "chats_chat": _to_int(row.get("Chats Chat")),
                    "chats_agent_requests": _to_int(row.get("Chats Agent Requests")),
                    "models": models,
                }
    return sorted(by_day.values(), key=lambda r: r["date"])


# -------------------- derived helpers --------------------


def claude_users() -> list[dict[str, Any]]:
    """Subset of leaderboard whose favorite_model contains 'claude'."""
    return [r for r in load_user_leaderboard() if "claude" in r["favorite_model"].lower()]


def model_usage_summary() -> list[dict[str, Any]]:
    """Aggregate model usage across all days in the loaded analytics."""
    totals: dict[str, dict[str, int]] = {}
    for day in load_team_analytics():
        for m in day.get("models", []):
            t = totals.setdefault(m["model"], {"requests": 0, "user_days": 0})
            t["requests"] += m["requests"]
            t["user_days"] += m["users"]
    out = [
        {"model": name, "requests": v["requests"], "user_days": v["user_days"]}
        for name, v in totals.items()
    ]
    return sorted(out, key=lambda r: r["requests"], reverse=True)
