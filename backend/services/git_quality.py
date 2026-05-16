"""Code-quality analytics from git commit messages × AI usage signals.

We classify commits at load time (data/sources/git_csv.py) into:
  is_bug_fix · is_revert · is_feature · is_refactor · is_test · is_docs

This service rolls them up into per-author / team / repo / bot-vs-human
metrics the dashboard's 'Code Quality (Git × AI)' tab visualises.

Honest scope: the classification is REGEX-on-subject. Won't catch
'sneaky' bug fixes that don't say so, won't tell you the SEVERITY of a
bug. It's a directional signal, not ground truth.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from data.db import get_conn


def _safe_div(a: float, b: float) -> float | None:
    if not b:
        return None
    return round(a / b, 4)


def _date_filter_sql(period_days: int) -> tuple[str, list]:
    if period_days <= 0 or period_days > 9999:
        return "", []
    cutoff = (datetime.utcnow() - timedelta(days=period_days)).date().isoformat()
    # author_date in commits CSV is ISO-8601 with time / zone — substr extracts
    # the bare date and compares as text (lex order = chrono).
    return " AND substr(c.author_date, 1, 10) >= ? ", [cutoff]


def get_team_quality(period_days: int = 90,
                     repos: list[str] | None = None) -> dict[str, Any]:
    """Team-wide commit-tag totals + bug / revert / refactor rates.

    Period filter compares against `author_date` (the original author
    time). Pass period_days=0 to disable the time filter.
    """
    where, params = _date_filter_sql(period_days)
    repo_clause = ""
    if repos:
        repo_clause = f" AND c.repo IN ({','.join('?'*len(repos))}) "
        params = params + list(repos)
    sql = f"""
        SELECT
            COUNT(*)               AS commits,
            SUM(c.is_bug_fix)      AS fixes,
            SUM(c.is_revert)       AS reverts,
            SUM(c.is_feature)      AS features,
            SUM(c.is_refactor)     AS refactors,
            SUM(c.is_test)         AS tests,
            SUM(c.is_docs)         AS docs,
            SUM(c.is_bot)          AS bot_commits,
            SUM(CASE WHEN c.is_bot = 0 THEN 1 ELSE 0 END) AS human_commits,
            SUM(CASE WHEN c.is_bot = 0 AND c.is_bug_fix = 1 THEN 1 ELSE 0 END)
                                   AS human_fixes,
            SUM(CASE WHEN c.is_bot = 1 AND c.is_bug_fix = 1 THEN 1 ELSE 0 END)
                                   AS bot_fixes,
            SUM(c.additions)       AS additions,
            SUM(c.deletions)       AS deletions
        FROM git_commits c
        WHERE 1=1
          {where}
          {repo_clause}
    """
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    if not row or not row["commits"]:
        return {
            "commits": 0, "fixes": 0, "reverts": 0, "features": 0,
            "refactors": 0, "tests": 0, "docs": 0, "bot_commits": 0,
            "human_commits": 0, "bug_rate_pct": None,
            "revert_rate_pct": None, "human_bug_rate_pct": None,
            "bot_bug_rate_pct": None, "additions": 0, "deletions": 0,
        }
    commits = row["commits"]
    fixes = row["fixes"] or 0
    reverts = row["reverts"] or 0
    human = row["human_commits"] or 0
    bot = row["bot_commits"] or 0
    human_fixes = row["human_fixes"] or 0
    bot_fixes = row["bot_fixes"] or 0
    return {
        "commits": commits,
        "fixes": fixes,
        "reverts": reverts,
        "features": row["features"] or 0,
        "refactors": row["refactors"] or 0,
        "tests": row["tests"] or 0,
        "docs": row["docs"] or 0,
        "bot_commits": bot,
        "human_commits": human,
        "additions": row["additions"] or 0,
        "deletions": row["deletions"] or 0,
        "bug_rate_pct":
            round(fixes / commits * 100, 1) if commits else None,
        "revert_rate_pct":
            round(reverts / commits * 100, 2) if commits else None,
        "human_bug_rate_pct":
            round(human_fixes / human * 100, 1) if human else None,
        "bot_bug_rate_pct":
            round(bot_fixes / bot * 100, 1) if bot else None,
    }


def get_quality_per_author(period_days: int = 90,
                            repos: list[str] | None = None,
                            limit: int = 50) -> list[dict[str, Any]]:
    """Per-author bug-fix / revert / feature breakdown.

    Returns rows sorted by total commits desc, capped at `limit`.
    Joins against `users` so the canonical_name uses the AI-side
    full_name when matched, else falls back to git author name. Groups
    by user_id when linked so multiple aliases collapse to one row.
    """
    where, params = _date_filter_sql(period_days)
    repo_clause = ""
    if repos:
        repo_clause = f" AND c.repo IN ({','.join('?'*len(repos))}) "
        params = params + list(repos)
    sql = f"""
        SELECT
            COALESCE(u.full_name, c.author_name)   AS canonical_name,
            c.author_name                          AS git_name,
            c.user_id                              AS user_id,
            MAX(c.is_bot)                          AS is_bot,
            COUNT(*)                               AS commits,
            SUM(c.is_bug_fix)                      AS fixes,
            SUM(c.is_revert)                       AS reverts,
            SUM(c.is_feature)                      AS features,
            SUM(c.is_refactor)                     AS refactors,
            SUM(c.is_test)                         AS tests,
            SUM(c.additions)                       AS additions,
            SUM(c.deletions)                       AS deletions
        FROM git_commits c
        LEFT JOIN users u ON u.id = c.user_id
        WHERE 1=1
          {where}
          {repo_clause}
        GROUP BY COALESCE(c.user_id, c.author_name)
        ORDER BY commits DESC
        LIMIT ?
    """
    params = params + [limit]
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        commits = r["commits"] or 0
        fixes = r["fixes"] or 0
        reverts = r["reverts"] or 0
        out.append({
            "canonical_name": r["canonical_name"],
            "git_name": r["git_name"],
            "user_id": r["user_id"],
            "is_bot": bool(r["is_bot"]),
            "commits": commits,
            "fixes": fixes,
            "reverts": reverts,
            "features": r["features"] or 0,
            "refactors": r["refactors"] or 0,
            "tests": r["tests"] or 0,
            "additions": r["additions"] or 0,
            "deletions": r["deletions"] or 0,
            "bug_rate_pct": round(fixes / commits * 100, 1) if commits else None,
            "revert_rate_pct": round(reverts / commits * 100, 2) if commits else None,
        })
    return out


def get_ai_spend_per_fix(period_days: int = 30,
                         repos: list[str] | None = None) -> dict[str, Any]:
    """How many $ of AI spend each bug-fix 'costs' on average across the
    team. Useful as a debt indicator — high $/fix can mean the team
    debugs a lot with AI's help (which is fine) OR generates AI code
    that then needs fixing (which is concerning).

    The repo filter narrows the bug-fix denominator to the same scope
    the rest of the Code Quality section uses, so the numbers stay
    consistent (a hmnd-cloud-only view should NOT divide team-wide AI
    spend by the cross-repo bug-fix count).
    """
    end = datetime.utcnow()
    start = end - timedelta(days=period_days)
    s_iso = start.strftime("%Y-%m-%d %H:%M:%S")
    e_iso = end.strftime("%Y-%m-%d %H:%M:%S")
    cutoff = start.date().isoformat()

    repo_clause = ""
    repo_params: list = []
    if repos:
        repo_clause = f" AND repo IN ({','.join('?'*len(repos))}) "
        repo_params = list(repos)

    with get_conn() as conn:
        row = conn.execute(
            f"""SELECT
                  (SELECT COALESCE(SUM(cost_usd), 0)
                     FROM usage_events
                     WHERE occurred_at BETWEEN ? AND ?)                  AS ai_spend,
                  (SELECT COUNT(*)
                     FROM git_commits
                     WHERE is_bug_fix = 1
                       AND substr(author_date, 1, 10) >= ?
                       {repo_clause})                                    AS fixes
            """,
            [s_iso, e_iso, cutoff] + repo_params,
        ).fetchone()
    spend = float(row["ai_spend"] or 0)
    fixes = int(row["fixes"] or 0)
    return {
        "period_days": period_days,
        "ai_spend": round(spend, 2),
        "fixes": fixes,
        "ai_spend_per_fix": _safe_div(spend, fixes),
    }


def get_high_churn_files(period_days: int = 90,
                         repos: list[str] | None = None,
                         limit: int = 20) -> list[dict[str, Any]]:
    """Files most often touched in the window — proxy for 'problem
    areas' or 'hot spots' worth refactor attention. We don't have
    per-file rows in `git_commits` (collapsed to per-commit aggregate
    by the loader), so this is computed at runtime from the raw CSV.
    Returns [] when the per-commit CSV is missing.
    """
    from data.sources.git_csv import latest_git_commits_file
    f = latest_git_commits_file()
    if f is None:
        return []
    import csv
    from collections import Counter
    cutoff = (datetime.utcnow() - timedelta(days=period_days)).date().isoformat()
    repos_set = set(repos) if repos else None
    file_commits: Counter = Counter()
    file_add: dict[str, int] = {}
    file_del: dict[str, int] = {}
    file_repos: dict[str, set] = {}
    seen_per_file: dict[str, set] = {}
    with f.path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            date = (r.get("author_date") or "")[:10]
            if date < cutoff:
                continue
            repo = r.get("repo") or ""
            if repos_set and repo not in repos_set:
                continue
            path = r.get("file_path") or ""
            if not path:
                continue
            sha = r.get("commit_sha") or ""
            seen = seen_per_file.setdefault(path, set())
            if sha not in seen:
                seen.add(sha)
                file_commits[path] += 1
            try:
                file_add[path] = file_add.get(path, 0) + int(r.get("additions") or 0)
                file_del[path] = file_del.get(path, 0) + int(r.get("deletions") or 0)
            except ValueError:
                pass
            file_repos.setdefault(path, set()).add(repo)
    rows = [
        {
            "file": path,
            "commits": n,
            "additions": file_add.get(path, 0),
            "deletions": file_del.get(path, 0),
            "repos": ";".join(sorted(file_repos.get(path, set()))),
        }
        for path, n in file_commits.most_common(limit)
    ]
    return rows
