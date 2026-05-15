"""Git-authors CSV loader.

Reads `sources/git_authors*.csv` produced by the user's
`analysis/git_authors.csv` script (one row per author with totals across
all three Humanoid repos) and upserts into the `git_authors` table.

Schema expected (header row required):
    git_author_name, git_author_emails, repos, commits,
    additions, deletions, net_lines, first_commit, last_commit

Idempotent: rewrites all rows on each call (table is treated as a
snapshot, not append-log).
"""
from __future__ import annotations

import csv
import glob
import os
from pathlib import Path
from typing import Any

from data.db import get_conn
from ._common import SourceFile, find_all, latest_match


_PATTERNS = ["git_authors_*.csv", "git_authors.csv"]
_COMMIT_PATTERNS = ["git_commit_file_stats_*.csv", "git_commit_file_stats.csv"]


def find_git_authors_files() -> list[SourceFile]:
    """All `git_authors*.csv` files (and bare `git_authors.csv`) in
    HMND_SOURCES_DIR / repo root.
    """
    return find_all(_PATTERNS)


def latest_git_authors_file() -> SourceFile | None:
    return latest_match(_PATTERNS)


def latest_git_commits_file() -> SourceFile | None:
    """Path to the granular per-commit-file CSV (from the user's
    `analysis/git_commit_file_stats.csv` extraction script).
    Used to build per-(author, repo) rollup for the Devs tab repo filter.
    """
    return latest_match(_COMMIT_PATTERNS)


def _match_user_id(conn, name: str, emails: list[str]) -> int | None:
    """Try to find a canonical user_id for a git author.

    Strategy (in order):
      1. Exact email match against users.email (case-insensitive)
      2. Exact full_name match (case-insensitive)
      3. Local-part-of-email match (before '@') against users.email
         local-part, in case domain differs (skl.vc vs thehumanoid.ai).
    Returns None if no match — these become 'git-only contributors'.
    """
    for email in emails:
        e = (email or "").strip().lower()
        if not e:
            continue
        row = conn.execute(
            "SELECT id FROM users WHERE LOWER(email) = ?", (e,)
        ).fetchone()
        if row:
            return row["id"]
    if name:
        row = conn.execute(
            "SELECT id FROM users WHERE LOWER(full_name) = ?", (name.lower(),)
        ).fetchone()
        if row:
            return row["id"]
    # local-part fallback
    for email in emails:
        local = (email or "").split("@", 1)[0].strip().lower()
        if not local:
            continue
        row = conn.execute(
            "SELECT id FROM users WHERE LOWER(email) LIKE ?", (f"{local}@%",)
        ).fetchone()
        if row:
            return row["id"]
    return None


def load_git_authors_csv(path: Path | str) -> dict[str, Any]:
    """Replace the git_authors table contents with the rows in `path`."""
    p = Path(path)
    rows: list[dict[str, str]] = []
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        return {"inserted": 0, "errors": ["empty csv"], "path": str(p)}

    inserted = 0
    matched = 0
    with get_conn() as conn:
        conn.execute("DELETE FROM git_authors")
        for r in rows:
            name = (r.get("git_author_name") or "").strip()
            if not name:
                continue
            emails_raw = (r.get("git_author_emails") or "").strip()
            emails = [e.strip().lower() for e in emails_raw.split(";") if e.strip()]
            repos = (r.get("repos") or "").strip()
            commits = int(r.get("commits") or 0)
            additions = int(r.get("additions") or 0)
            deletions = int(r.get("deletions") or 0)
            first_commit = (r.get("first_commit") or "").strip() or None
            last_commit = (r.get("last_commit") or "").strip() or None
            user_id = _match_user_id(conn, name, emails)
            if user_id is not None:
                matched += 1
            conn.execute(
                """INSERT INTO git_authors(
                       name, emails, repos, commits, additions, deletions,
                       first_commit, last_commit, user_id)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, ";".join(emails), repos, commits, additions, deletions,
                 first_commit, last_commit, user_id),
            )
            inserted += 1
        conn.commit()

    return {
        "provider": "github",
        "mode": "csv",
        "source_file": p.name,
        "inserted": inserted,
        "matched_to_users": matched,
        "unmatched": inserted - matched,
    }


def load_git_commits_csv(path: Path | str) -> dict[str, Any]:
    """Build per-(author, repo) rollup from the granular per-commit-file
    CSV (`analysis/git_commit_file_stats.csv` from the user's script).

    Columns expected (header):
        repo, commit_sha, author_name, author_email, author_date,
        committer_name, committer_email, committer_date, subject,
        file_path, additions, deletions, is_binary
    """
    p = Path(path)
    # In-memory aggregate: {(name, repo) -> stats}
    bag: dict[tuple[str, str], dict[str, Any]] = {}
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = (r.get("author_name") or "").strip()
            repo = (r.get("repo") or "").strip()
            if not name or not repo:
                continue
            email = (r.get("author_email") or "").strip().lower()
            sha = r.get("commit_sha") or ""
            date = r.get("author_date") or ""
            try:
                add = int(r.get("additions") or 0)
                del_ = int(r.get("deletions") or 0)
            except ValueError:
                continue
            key = (name, repo)
            s = bag.setdefault(key, {
                "shas": set(), "emails": set(), "add": 0, "del": 0,
                "first": None, "last": None,
            })
            s["shas"].add(sha)
            if email:
                s["emails"].add(email)
            s["add"] += add
            s["del"] += del_
            if date:
                if s["first"] is None or date < s["first"]:
                    s["first"] = date
                if s["last"] is None or date > s["last"]:
                    s["last"] = date

    inserted = 0
    matched = 0
    with get_conn() as conn:
        conn.execute("DELETE FROM git_author_repo_stats")
        for (name, repo), s in bag.items():
            emails = sorted(s["emails"])
            user_id = _match_user_id(conn, name, emails)
            if user_id is not None:
                matched += 1
            conn.execute(
                """INSERT INTO git_author_repo_stats(
                       name, repo, commits, additions, deletions,
                       first_commit, last_commit, user_id)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, repo, len(s["shas"]), s["add"], s["del"],
                 s["first"], s["last"], user_id),
            )
            inserted += 1
        conn.commit()
    return {
        "provider": "github",
        "mode": "csv_commits",
        "source_file": p.name,
        "inserted": inserted,
        "matched_to_users": matched,
        "unique_authors": len({n for n, _ in bag}),
        "unique_repos": len({r for _, r in bag}),
    }


def list_known_repos() -> list[str]:
    """All distinct repos seen in git_author_repo_stats (for the UI filter)."""
    try:
        with get_conn() as conn:
            return [r["repo"] for r in conn.execute(
                "SELECT DISTINCT repo FROM git_author_repo_stats ORDER BY repo"
            ).fetchall()]
    except Exception:
        return []
