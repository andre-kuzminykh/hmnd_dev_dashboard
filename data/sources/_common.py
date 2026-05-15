"""Shared discovery + parsing helpers for JSON source loaders."""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# Sources are looked up here in order; first hit per pattern wins by date.
def sources_dirs() -> list[Path]:
    """When HMND_SOURCES_DIR is set, ONLY that dir is searched (useful in
    tests). Otherwise scan the canonical locations in priority order.
    """
    env = os.environ.get("HMND_SOURCES_DIR")
    if env:
        p = Path(env)
        return [p] if p.exists() else []
    out: list[Path] = [ROOT / "sources", Path("/app/sources")]
    return [p for p in out if p.exists()]


# Accept dates as YYYYMMDD or YYYY-MM-DD anywhere in the filename suffix.
_DATE_RE = re.compile(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})(?:\.json)$")


@dataclass
class SourceFile:
    path: Path
    date_in_name: date

    def __lt__(self, other: "SourceFile") -> bool:
        return self.date_in_name < other.date_in_name


def _glob_with_dates(pattern: str) -> list[SourceFile]:
    """Return matched files sorted by date in filename, latest last."""
    found: list[SourceFile] = []
    for d in sources_dirs():
        for path in glob.glob(str(d / pattern)):
            m = _DATE_RE.search(path)
            if not m:
                continue
            try:
                dt = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            found.append(SourceFile(Path(path), dt))
    found.sort()
    return found


def latest_match(patterns: list[str]) -> SourceFile | None:
    """Across the given filename patterns, return the file with the most
    recent date encoded in the name. Returns None when nothing matches."""
    candidates: list[SourceFile] = []
    for p in patterns:
        candidates.extend(_glob_with_dates(p))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1]


def find_all(patterns: list[str]) -> list[SourceFile]:
    """Every match, sorted oldest-first. For tests / inspection."""
    out: list[SourceFile] = []
    for p in patterns:
        out.extend(_glob_with_dates(p))
    out.sort()
    return out
