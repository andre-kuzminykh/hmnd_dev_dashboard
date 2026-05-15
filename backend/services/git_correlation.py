"""Git × AI correlation — joins per-user git activity (from
`git_authors` table) with per-user AI spend / lines (from `usage_events`
and the Cursor leaderboard) and classifies each person into one of 7
segments.

Used by the 'Developers (Git × AI)' tab in AI Tools.

Spec for the segments (thresholds tuned to the dataset distribution —
each is computed against the population's median so the buckets stay
meaningful regardless of absolute scale):

    HIGH_AI_SPEND_HIGH_GIT_OUTPUT   — top-quartile AI cost & top-quartile commits/additions
    HIGH_AI_SPEND_LOW_GIT_OUTPUT    — top-quartile AI cost & bottom-quartile commits
    HIGH_AI_LINES_LOW_COMMITS       — top-quartile ai_lines but bottom-quartile commits
    LOW_AI_SPEND_HIGH_GIT_OUTPUT    — bottom-quartile AI cost & top-quartile commits
    AI_ACTIVE_BUT_NO_GIT            — has AI activity & zero commits in git
    GIT_ACTIVE_BUT_NO_AI            — has commits & zero AI activity
    NORMAL                          — everything else
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from data.db import get_conn


def _quartiles(values: list[float]) -> tuple[float, float]:
    """Return (q1, q3) cutoffs ignoring zeros so the segment bands
    are meaningful for users with at least some activity.
    """
    pos = sorted(v for v in values if v and v > 0)
    if len(pos) < 4:
        # Too few non-zero points to compute quartiles meaningfully.
        return 0.0, 0.0
    n = len(pos)
    q1 = pos[max(0, n // 4 - 1)]
    q3 = pos[min(n - 1, (3 * n) // 4)]
    return q1, q3


def _segment(ai_cost: float, ai_lines: int, commits: int,
             additions: int,
             cost_q3: float, lines_q3: float,
             commits_q3: float, commits_q1: float,
             adds_q3: float) -> str:
    has_ai = ai_cost > 0 or ai_lines > 0
    has_git = commits > 0
    if has_ai and not has_git:
        return "AI_ACTIVE_BUT_NO_GIT"
    if has_git and not has_ai:
        return "GIT_ACTIVE_BUT_NO_AI"
    high_cost = cost_q3 > 0 and ai_cost >= cost_q3
    high_lines = lines_q3 > 0 and ai_lines >= lines_q3
    high_commits = commits_q3 > 0 and commits >= commits_q3
    high_adds = adds_q3 > 0 and additions >= adds_q3
    low_commits = commits_q1 > 0 and commits <= commits_q1
    if high_cost and (high_commits or high_adds):
        return "HIGH_AI_SPEND_HIGH_GIT_OUTPUT"
    if high_cost and low_commits:
        return "HIGH_AI_SPEND_LOW_GIT_OUTPUT"
    if high_lines and low_commits:
        return "HIGH_AI_LINES_LOW_COMMITS"
    if (cost_q3 > 0 and ai_cost <= cost_q3 / 4) and (high_commits or high_adds):
        return "LOW_AI_SPEND_HIGH_GIT_OUTPUT"
    return "NORMAL"


def _safe_div(a: float, b: float) -> float | None:
    if not b:
        return None
    return round(a / b, 3)


def get_git_ai_correlation(period_days: int = 30,
                            repos: list[str] | None = None) -> list[dict[str, Any]]:
    """Return one row per developer with the cross-product of metrics
    from `git_authors` (snapshot from CSV drop) and AI spend / lines
    (last `period_days` from usage_events and Cursor leaderboard).

    `repos` (optional): when provided, narrow git-side stats to those
    specific repositories (joins on `git_author_repo_stats` instead of
    the aggregated `git_authors` table). Pass None or empty list to use
    the all-repos rollup.

    Output columns match the user's spec:
      canonical_name, ai_name, git_author_name, git_email, repos,
      ai_cost_usd, ai_lines, agent_completions, tab_completions,
      commits, git_additions, git_deletions, net_lines,
      cost_per_commit, cost_per_1000_git_additions, ai_lines_per_commit,
      git_additions_to_ai_lines_ratio, ai_share_of_additions, segment.
    """
    end = datetime.utcnow()
    start = end - timedelta(days=period_days)
    s_iso = start.strftime("%Y-%m-%d %H:%M:%S")
    e_iso = end.strftime("%Y-%m-%d %H:%M:%S")
    # Filter git-side data to selected repos (if any).
    use_repo_filter = bool(repos)
    with get_conn() as conn:
        if use_repo_filter:
            placeholders = ",".join("?" * len(repos))
            git_rows = conn.execute(
                f"""SELECT ga.name        AS git_name,
                           GROUP_CONCAT(DISTINCT ga.repo)  AS repos,
                           SUM(ga.commits)                 AS commits,
                           SUM(ga.additions)               AS additions,
                           SUM(ga.deletions)               AS deletions,
                           ga.user_id                      AS user_id,
                           u.full_name                     AS ai_name,
                           u.email                         AS canonical_email,
                           (SELECT emails FROM git_authors WHERE name = ga.name)
                                                          AS git_emails
                    FROM git_author_repo_stats ga
                    LEFT JOIN users u ON u.id = ga.user_id
                    WHERE ga.repo IN ({placeholders})
                    GROUP BY ga.name
                    ORDER BY SUM(ga.commits) DESC""",
                repos,
            ).fetchall()
        else:
            git_rows = conn.execute(
                """SELECT ga.name        AS git_name,
                          ga.emails      AS git_emails,
                          ga.repos       AS repos,
                          ga.commits     AS commits,
                          ga.additions   AS additions,
                          ga.deletions   AS deletions,
                          ga.user_id     AS user_id,
                          u.full_name    AS ai_name,
                          u.email        AS canonical_email
                   FROM git_authors ga
                   LEFT JOIN users u ON u.id = ga.user_id
                   ORDER BY ga.commits DESC"""
            ).fetchall()

        # 2. AI users with their spend / lines (rolled-up).
        ai_rows = conn.execute(
            f"""SELECT u.id            AS user_id,
                       u.full_name     AS name,
                       u.email         AS email,
                       ROUND(SUM(ue.cost_usd), 2)  AS ai_cost_usd
                FROM usage_events ue
                JOIN users u ON u.id = ue.user_id
                WHERE ue.occurred_at BETWEEN ? AND ?
                GROUP BY u.id""",
            (s_iso, e_iso),
        ).fetchall()
    ai_by_user: dict[int, dict[str, Any]] = {r["user_id"]: dict(r) for r in ai_rows}

    # 3. Cursor leaderboard for ai_lines / agent / tab counters.
    from backend.services.cursor_analytics import load_user_leaderboard
    cursor_by_email: dict[str, dict[str, Any]] = {}
    for r in load_user_leaderboard():
        cursor_by_email[(r.get("email") or "").lower()] = r

    out: list[dict[str, Any]] = []
    for row in git_rows:
        emails = [e for e in (row["git_emails"] or "").split(";") if e]
        user_id = row["user_id"]
        ai_data = ai_by_user.get(user_id) if user_id is not None else None
        ai_cost = float(ai_data["ai_cost_usd"]) if ai_data else 0.0
        # Cursor leaderboard hit: try every email this git-author used.
        cursor_hit = next(
            (cursor_by_email[e] for e in emails if e in cursor_by_email),
            None,
        )
        ai_lines = int((cursor_hit or {}).get("ai_lines") or 0)
        agent_completions = int((cursor_hit or {}).get("agent_completions") or 0)
        tab_completions = int((cursor_hit or {}).get("tab_completions") or 0)

        commits = int(row["commits"] or 0)
        additions = int(row["additions"] or 0)
        deletions = int(row["deletions"] or 0)

        out.append({
            "canonical_name": row["ai_name"] or row["git_name"],
            "ai_name": row["ai_name"] or "",
            "git_author_name": row["git_name"],
            "git_email": emails[0] if emails else "",
            "repos": row["repos"] or "",
            "ai_cost_usd": ai_cost,
            "ai_lines": ai_lines,
            "agent_completions": agent_completions,
            "tab_completions": tab_completions,
            "commits": commits,
            "git_additions": additions,
            "git_deletions": deletions,
            "net_lines": additions - deletions,
            "cost_per_commit": _safe_div(ai_cost, commits),
            "cost_per_1000_git_additions": _safe_div(ai_cost * 1000.0, additions),
            "ai_lines_per_commit": _safe_div(ai_lines, commits),
            "git_additions_to_ai_lines_ratio": _safe_div(additions, ai_lines or 0),
            # % of git additions that came from AI tooling. ai_lines is
            # Cursor's reported AI-generated lines (tab + agent), capped at
            # the git additions for a sane upper bound. None when either
            # number is 0.
            "ai_share_of_additions": (
                round(min(ai_lines, additions) / additions * 100, 1)
                if additions > 0 and ai_lines > 0 else None
            ),
        })

    # 4. Also pull AI-only users (have AI cost but NO git author row) so the
    # segment 'AI_ACTIVE_BUT_NO_GIT' isn't silently empty.
    git_user_ids = {r["user_id"] for r in git_rows if r["user_id"] is not None}
    for uid, ai in ai_by_user.items():
        if uid in git_user_ids:
            continue
        # Match Cursor by canonical email
        email = (ai.get("email") or "").lower()
        cursor_hit = cursor_by_email.get(email)
        out.append({
            "canonical_name": ai["name"] or email,
            "ai_name": ai["name"] or "",
            "git_author_name": "",
            "git_email": email,
            "repos": "",
            "ai_cost_usd": float(ai["ai_cost_usd"] or 0),
            "ai_lines": int((cursor_hit or {}).get("ai_lines") or 0),
            "agent_completions": int((cursor_hit or {}).get("agent_completions") or 0),
            "tab_completions": int((cursor_hit or {}).get("tab_completions") or 0),
            "commits": 0,
            "git_additions": 0,
            "git_deletions": 0,
            "net_lines": 0,
            "cost_per_commit": None,
            "cost_per_1000_git_additions": None,
            "ai_lines_per_commit": None,
            "git_additions_to_ai_lines_ratio": None,
            "ai_share_of_additions": None,
        })

    # 5. Classify segments using population quartiles.
    cost_q1, cost_q3 = _quartiles([r["ai_cost_usd"] for r in out])
    lines_q1, lines_q3 = _quartiles([r["ai_lines"] for r in out])
    commits_q1, commits_q3 = _quartiles([r["commits"] for r in out])
    adds_q1, adds_q3 = _quartiles([r["git_additions"] for r in out])

    for r in out:
        r["segment"] = _segment(
            r["ai_cost_usd"], r["ai_lines"], r["commits"], r["git_additions"],
            cost_q3=cost_q3, lines_q3=lines_q3,
            commits_q3=commits_q3, commits_q1=commits_q1,
            adds_q3=adds_q3,
        )

    # Sort by total impact (commits + ai_cost) descending so the most
    # visible rows are at the top.
    out.sort(key=lambda r: (r["commits"] + r["ai_cost_usd"] * 0.1), reverse=True)
    return out


def get_segment_counts(period_days: int = 30) -> dict[str, int]:
    """Distribution of devs across the 7 segments."""
    rows = get_git_ai_correlation(period_days=period_days)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["segment"]] = counts.get(r["segment"], 0) + 1
    return counts
