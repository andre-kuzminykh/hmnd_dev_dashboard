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


import re as _re

# Subject-classification patterns. Each commit's subject (first line of
# message) is scanned against all of them; multiple flags can fire.
_RE_FIX     = _re.compile(r"\b(fix|fixes|fixed|bug|bugfix|hotfix|patch)\b|^fix[:\(!]", _re.I)
_RE_REVERT  = _re.compile(r"^revert\b|\brevert[:\s\"\']", _re.I)
_RE_FEATURE = _re.compile(r"^feat\b|^feature\b|\badd(ed|s)?\b\s", _re.I)
_RE_REFACTOR= _re.compile(r"^refactor\b|\brefactor(ing|ed)?\b|^style\b|^perf\b|^chore\b", _re.I)
_RE_TEST    = _re.compile(r"^test\b|\btest(s|ing)?\b", _re.I)
_RE_DOCS    = _re.compile(r"^docs?\b|\b(documentation|readme)\b", _re.I)


def _classify_subject(subject: str) -> dict[str, int]:
    """Return {flag: 0|1} dict for one commit subject."""
    s = (subject or "").strip()
    return {
        "is_bug_fix":  1 if _RE_FIX.search(s)     else 0,
        "is_revert":   1 if _RE_REVERT.search(s)  else 0,
        "is_feature":  1 if _RE_FEATURE.search(s) else 0,
        "is_refactor": 1 if _RE_REFACTOR.search(s) else 0,
        "is_test":     1 if _RE_TEST.search(s)    else 0,
        "is_docs":     1 if _RE_DOCS.search(s)    else 0,
    }


def load_git_commits_csv(path: Path | str) -> dict[str, Any]:
    """Build per-(author, repo) rollup AND per-commit details from the
    granular per-commit-file CSV (`analysis/git_commit_file_stats.csv`
    from the user's script).

    Two writes per call:
      - git_author_repo_stats (author × repo aggregate)
      - git_commits           (one row per unique (repo, sha) with
                               subject-classification flags for the
                               Code Quality analytics tab)

    Columns expected in CSV (header):
        repo, commit_sha, author_name, author_email, author_date,
        committer_name, committer_email, committer_date, subject,
        file_path, additions, deletions, is_binary
    """
    p = Path(path)
    # In-memory aggregates: per (author, repo) AND per commit.
    bag: dict[tuple[str, str], dict[str, Any]] = {}
    commits: dict[tuple[str, str], dict[str, Any]] = {}  # (repo, sha) → details

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
            subject = (r.get("subject") or "").strip()
            try:
                add = int(r.get("additions") or 0)
                del_ = int(r.get("deletions") or 0)
            except ValueError:
                continue

            # Per-commit aggregate (one row per unique repo+sha)
            ckey = (repo, sha)
            c = commits.get(ckey)
            if c is None:
                c = {
                    "repo": repo, "sha": sha, "author_name": name,
                    "author_email": email, "author_date": date,
                    "subject": subject, "additions": 0, "deletions": 0,
                    "files_changed": 0,
                }
                commits[ckey] = c
            c["additions"] += add
            c["deletions"] += del_
            c["files_changed"] += 1

            # Per-(author, repo) aggregate
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
    # Build a per-name → user_id cache so we resolve each author once.
    with get_conn() as conn:
        conn.execute("DELETE FROM git_author_repo_stats")
        conn.execute("DELETE FROM git_commits")
        name_to_user: dict[str, int | None] = {}
        for (name, repo), s in bag.items():
            emails = sorted(s["emails"])
            user_id = _match_user_id(conn, name, emails)
            name_to_user[name] = user_id
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
        # Per-commit insert with subject classification + bot flag
        try:
            from backend.services.git_correlation import _is_bot_author
        except Exception:
            def _is_bot_author(_n):  # type: ignore[misc]
                return False
        commits_written = 0
        for c in commits.values():
            tags = _classify_subject(c["subject"])
            uid = name_to_user.get(c["author_name"])
            is_bot = 1 if _is_bot_author(c["author_name"]) else 0
            conn.execute(
                """INSERT INTO git_commits(
                       repo, sha, author_name, author_email, author_date,
                       subject, additions, deletions, files_changed,
                       is_bug_fix, is_revert, is_feature, is_refactor,
                       is_test, is_docs, user_id, is_bot)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?)""",
                (c["repo"], c["sha"], c["author_name"], c["author_email"],
                 c["author_date"], c["subject"], c["additions"],
                 c["deletions"], c["files_changed"],
                 tags["is_bug_fix"], tags["is_revert"], tags["is_feature"],
                 tags["is_refactor"], tags["is_test"], tags["is_docs"],
                 uid, is_bot),
            )
            commits_written += 1
        conn.commit()
    return {
        "provider": "github",
        "mode": "csv_commits",
        "source_file": p.name,
        "inserted": inserted,
        "matched_to_users": matched,
        "unique_authors": len({n for n, _ in bag}),
        "unique_repos": len({r for _, r in bag}),
        "commits_written": commits_written,
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
