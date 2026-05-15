"""Tests for the Git × AI correlation pipeline.

Covers:
  - CSV loader for `git_authors_*.csv` (aggregated per-author)
  - CSV loader for `git_commit_file_stats_*.csv` (per-commit-file ->
    per-(author, repo) rollup)
  - User-matching by email / name / local-part fallback
  - Repository filter narrows correlation result
  - Segment classifier puts every dev into one of the 7 buckets
  - AI share % computation
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta

import pytest


def _write_authors_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "git_author_name", "git_author_emails", "repos", "commits",
            "additions", "deletions", "net_lines", "first_commit", "last_commit",
        ])
        for r in rows:
            w.writerow(r)


def _write_commits_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "repo", "commit_sha", "author_name", "author_email", "author_date",
            "committer_name", "committer_email", "committer_date", "subject",
            "file_path", "additions", "deletions", "is_binary",
        ])
        for r in rows:
            w.writerow(r)


def test_load_git_authors_csv_idempotent(tmp_db, tmp_path):
    """Loading twice replaces, doesn't append."""
    csv_path = tmp_path / "git_authors_20260515.csv"
    _write_authors_csv(csv_path, [
        ("Alice", "alice@x.com", "hmnd;hmnd-cloud", 50, 1000, 200, 800,
         "2026-04-01T00:00:00", "2026-05-10T00:00:00"),
        ("Bob",   "bob@x.com",   "hmnd", 20, 400, 50, 350,
         "2026-04-05T00:00:00", "2026-05-08T00:00:00"),
    ])
    from data.sources.git_csv import load_git_authors_csv
    from data.db import get_conn

    r1 = load_git_authors_csv(csv_path)
    assert r1["inserted"] == 2

    r2 = load_git_authors_csv(csv_path)
    assert r2["inserted"] == 2

    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM git_authors").fetchone()["n"]
    assert n == 2  # NOT 4 — idempotent


def test_user_matching_by_email(tmp_db, tmp_path):
    """When git author's email matches a user.email, user_id is set."""
    from data.db import get_conn
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users(email, full_name) VALUES('alice@x.com', 'Alice Smith')"
        )
        conn.commit()
        uid = conn.execute("SELECT id FROM users WHERE email='alice@x.com'").fetchone()["id"]

    csv_path = tmp_path / "git_authors.csv"
    _write_authors_csv(csv_path, [
        ("Alice Smith", "alice@x.com", "hmnd", 10, 200, 50, 150,
         "2026-04-01", "2026-05-10"),
    ])
    from data.sources.git_csv import load_git_authors_csv
    r = load_git_authors_csv(csv_path)
    assert r["matched_to_users"] == 1

    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM git_authors WHERE name='Alice Smith'"
        ).fetchone()
    assert row["user_id"] == uid


def test_user_matching_by_local_part(tmp_db, tmp_path):
    """If git email is 'alice@gh.com' but user is 'alice@x.com', match by
    local-part 'alice' fallback.
    """
    from data.db import get_conn
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users(email, full_name) VALUES('alice@x.com', 'Anna')"
        )
        conn.commit()

    csv_path = tmp_path / "git_authors.csv"
    _write_authors_csv(csv_path, [
        ("Alex", "alice@gh.com", "hmnd", 5, 100, 30, 70, "2026-04-01", "2026-05-10"),
    ])
    from data.sources.git_csv import load_git_authors_csv
    load_git_authors_csv(csv_path)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM git_authors WHERE name='Alex'"
        ).fetchone()
    assert row["user_id"] is not None, "should match by local-part 'alice'"


def test_load_git_commits_csv_per_repo_rollup(tmp_db, tmp_path):
    """Granular CSV → per-(author, repo) rollup with correct counters."""
    csv_path = tmp_path / "git_commit_file_stats.csv"
    rows = []
    # Author A in hmnd: 2 commits, 100+200 = 300 add, 50+10 = 60 del
    rows += [
        ("hmnd", "sha1", "Alice", "alice@x", "2026-05-01T00:00:00", "Alice", "alice@x", "2026-05-01T00:00:00", "feat", "file.py", "100", "50", "False"),
        ("hmnd", "sha2", "Alice", "alice@x", "2026-05-02T00:00:00", "Alice", "alice@x", "2026-05-02T00:00:00", "fix", "file.py", "200", "10", "False"),
    ]
    # Author A in hmnd-cloud: 1 commit, 80 add
    rows += [
        ("hmnd-cloud", "sha3", "Alice", "alice@x", "2026-05-03T00:00:00", "Alice", "alice@x", "2026-05-03T00:00:00", "wip", "x.py", "80", "20", "False"),
    ]
    # Author B in hmnd: 1 commit
    rows += [
        ("hmnd", "sha4", "Bob", "bob@y", "2026-05-04T00:00:00", "Bob", "bob@y", "2026-05-04T00:00:00", "doc", "README.md", "5", "0", "False"),
    ]
    _write_commits_csv(csv_path, rows)
    from data.sources.git_csv import load_git_commits_csv
    r = load_git_commits_csv(csv_path)
    assert r["inserted"] == 3  # 3 (author, repo) pairs
    assert r["unique_authors"] == 2
    assert r["unique_repos"] == 2

    from data.db import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name, repo, commits, additions, deletions "
            "FROM git_author_repo_stats ORDER BY name, repo"
        ).fetchall()
    by_key = {(r["name"], r["repo"]): dict(r) for r in rows}
    assert by_key[("Alice", "hmnd")]["commits"] == 2
    assert by_key[("Alice", "hmnd")]["additions"] == 300
    assert by_key[("Alice", "hmnd")]["deletions"] == 60
    assert by_key[("Alice", "hmnd-cloud")]["commits"] == 1
    assert by_key[("Alice", "hmnd-cloud")]["additions"] == 80
    assert by_key[("Bob", "hmnd")]["commits"] == 1


def test_correlation_with_repo_filter(tmp_db, tmp_path):
    """When repos=['hmnd'] is passed, narrow git side to that repo only."""
    csv_path = tmp_path / "git_commit_file_stats.csv"
    _write_commits_csv(csv_path, [
        ("hmnd",       "s1", "Alice", "a@x", "2026-05-01T00:00:00", "Alice", "a@x", "2026-05-01T00:00:00", "f", "a.py", "1000", "100", "False"),
        ("hmnd-cloud", "s2", "Alice", "a@x", "2026-05-02T00:00:00", "Alice", "a@x", "2026-05-02T00:00:00", "f", "b.py", "500", "50", "False"),
    ])
    from data.sources.git_csv import load_git_commits_csv
    load_git_commits_csv(csv_path)

    from backend.services.git_correlation import get_git_ai_correlation
    # Only the granular table is populated here, so we test the repo filter
    # path. The unfiltered path uses git_authors which would be empty.
    hmnd_only = get_git_ai_correlation(period_days=30, repos=["hmnd"])
    alice_hmnd = next(r for r in hmnd_only if r["git_author_name"] == "Alice")
    assert alice_hmnd["git_additions"] == 1000, (
        f"hmnd-only should be 1000 additions, got {alice_hmnd['git_additions']}"
    )
    # Multi-repo filter sums across selected repos
    both = get_git_ai_correlation(period_days=30, repos=["hmnd", "hmnd-cloud"])
    alice_both = next(r for r in both if r["git_author_name"] == "Alice")
    assert alice_both["git_additions"] == 1500, (
        f"hmnd+hmnd-cloud sum should be 1500, got {alice_both['git_additions']}"
    )


def test_segments_classify_into_seven_buckets(tmp_db, tmp_path):
    """Drop a mix of AI users + git authors; verify each gets exactly one
    of the 7 segment labels.
    """
    from data.db import get_conn
    # Seed two users on the AI side with different spend levels.
    with get_conn() as conn:
        pid = conn.execute("SELECT id FROM providers WHERE name='openai'").fetchone()["id"]
        mid = conn.execute("SELECT id FROM models WHERE provider_id=? LIMIT 1", (pid,)).fetchone()["id"]
        # High-spend dev
        conn.execute(
            "INSERT INTO users(email, full_name) VALUES('hi@x', 'Hi Spender')"
        )
        # Low-spend dev
        conn.execute(
            "INSERT INTO users(email, full_name) VALUES('lo@x', 'Lo Spender')"
        )
        # AI-only dev (no git author)
        conn.execute(
            "INSERT INTO users(email, full_name) VALUES('ai@x', 'AI Only')"
        )
        uid_hi = conn.execute("SELECT id FROM users WHERE email='hi@x'").fetchone()["id"]
        uid_lo = conn.execute("SELECT id FROM users WHERE email='lo@x'").fetchone()["id"]
        uid_ai = conn.execute("SELECT id FROM users WHERE email='ai@x'").fetchone()["id"]
        for uid, cost in [(uid_hi, 1000.0), (uid_lo, 1.0), (uid_ai, 50.0)]:
            conn.execute(
                """INSERT INTO usage_events(user_id, provider_id, model_id,
                                             occurred_at, tokens_in, tokens_out,
                                             tokens_cached, cost_usd, is_error, purpose)
                   VALUES(?, ?, ?, datetime('now', '-1 day'), 100, 50, 0, ?, 0, 'API')""",
                (uid, pid, mid, cost),
            )
        conn.commit()

    # Git authors: high & low overlap with AI users + 1 git-only
    csv_path = tmp_path / "git_authors.csv"
    _write_authors_csv(csv_path, [
        ("Hi Spender",  "hi@x", "hmnd", 500, 50000, 5000, 45000, "2026-04-01", "2026-05-10"),
        ("Lo Spender",  "lo@x", "hmnd",   5,   100,   10,    90, "2026-04-01", "2026-05-10"),
        ("Git Only",    "git@x","hmnd", 100,  5000,  500,  4500, "2026-04-01", "2026-05-10"),
    ])
    from data.sources.git_csv import load_git_authors_csv
    load_git_authors_csv(csv_path)

    from backend.services.git_correlation import get_git_ai_correlation
    devs = get_git_ai_correlation(period_days=30)
    by_name = {r["canonical_name"]: r for r in devs}

    # AI Only is in usage_events but not in git_authors → AI_ACTIVE_BUT_NO_GIT
    assert by_name["AI Only"]["segment"] == "AI_ACTIVE_BUT_NO_GIT"
    # Git Only has commits but never appeared in usage_events → GIT_ACTIVE_BUT_NO_AI
    assert by_name["Git Only"]["segment"] == "GIT_ACTIVE_BUT_NO_AI"
    # Every dev must have one of the 7 segments
    valid_segments = {
        "HIGH_AI_SPEND_HIGH_GIT_OUTPUT", "HIGH_AI_SPEND_LOW_GIT_OUTPUT",
        "HIGH_AI_LINES_LOW_COMMITS", "LOW_AI_SPEND_HIGH_GIT_OUTPUT",
        "AI_ACTIVE_BUT_NO_GIT", "GIT_ACTIVE_BUT_NO_AI", "NORMAL",
    }
    for r in devs:
        assert r["segment"] in valid_segments, f"{r['canonical_name']}: bad segment {r['segment']}"


def test_repo_filter_changes_correlation_totals(tmp_db, tmp_path):
    """Selecting 'hmnd' must give different totals than selecting both
    'hmnd' and 'hmnd-cloud'. Pinpoints the UI bug user reported:
    'когда репозитории тыкаю - то ничего не меняется'.
    """
    csv_path = tmp_path / "git_commit_file_stats.csv"
    _write_commits_csv(csv_path, [
        ("hmnd",       "s1", "Alice", "a@x", "2026-05-01T00:00:00", "Alice", "a@x", "2026-05-01T00:00:00", "f", "a.py", "100", "10", "False"),
        ("hmnd-cloud", "s2", "Alice", "a@x", "2026-05-02T00:00:00", "Alice", "a@x", "2026-05-02T00:00:00", "f", "b.py", "900", "90", "False"),
        ("hmnd-sim",   "s3", "Alice", "a@x", "2026-05-03T00:00:00", "Alice", "a@x", "2026-05-03T00:00:00", "f", "c.py", "200", "20", "False"),
    ])
    from data.sources.git_csv import load_git_commits_csv
    load_git_commits_csv(csv_path)

    from backend.services.git_correlation import get_git_ai_correlation
    hmnd = get_git_ai_correlation(period_days=30, repos=["hmnd"])
    hmnd_cloud = get_git_ai_correlation(period_days=30, repos=["hmnd", "hmnd-cloud"])
    all_three = get_git_ai_correlation(period_days=30, repos=["hmnd", "hmnd-cloud", "hmnd-sim"])

    a_hmnd = next(r for r in hmnd if r["git_author_name"] == "Alice")
    a_two = next(r for r in hmnd_cloud if r["git_author_name"] == "Alice")
    a_all = next(r for r in all_three if r["git_author_name"] == "Alice")
    assert a_hmnd["git_additions"] == 100
    assert a_two["git_additions"] == 1000
    assert a_all["git_additions"] == 1200
    assert a_hmnd["git_additions"] != a_two["git_additions"] != a_all["git_additions"]


def test_bot_author_marked_and_segmented(tmp_db, tmp_path):
    """Authors like 'github-actions[bot]', 'Cursor Agent' get is_bot=True
    and segment 'BOT_AUTOMATION'; their additions don't poison the human
    quartile thresholds.
    """
    csv_path = tmp_path / "git_authors.csv"
    _write_authors_csv(csv_path, [
        ("github-actions[bot]", "actions@github.com", "hmnd", 500, 50000, 0, 50000, "2026-04-01", "2026-05-10"),
        ("Cursor Agent",        "agent@cursor.sh",    "hmnd", 100, 10000, 0, 10000, "2026-04-01", "2026-05-10"),
        ("Alice",               "alice@x",            "hmnd",  10,   200, 50,  150, "2026-04-01", "2026-05-10"),
    ])
    from data.sources.git_csv import load_git_authors_csv
    load_git_authors_csv(csv_path)

    from backend.services.git_correlation import get_git_ai_correlation
    devs = get_git_ai_correlation(period_days=30)
    by_name = {r["git_author_name"]: r for r in devs}
    assert by_name["github-actions[bot]"]["is_bot"] is True
    assert by_name["github-actions[bot]"]["segment"] == "BOT_AUTOMATION"
    assert by_name["Cursor Agent"]["is_bot"] is True
    assert by_name["Cursor Agent"]["segment"] == "BOT_AUTOMATION"
    assert by_name["Alice"]["is_bot"] is False
    assert by_name["Alice"]["segment"] != "BOT_AUTOMATION"


def test_team_ai_share_includes_bots(tmp_db, tmp_path):
    """get_team_ai_share treats every bot addition as 100% AI."""
    csv_path = tmp_path / "git_authors.csv"
    _write_authors_csv(csv_path, [
        ("github-actions[bot]", "ga@github.com", "hmnd", 100, 2000, 0, 2000, "2026-04-01", "2026-05-10"),
        ("Alice",               "alice@x",       "hmnd",  10, 1000, 0, 1000, "2026-04-01", "2026-05-10"),
    ])
    from data.sources.git_csv import load_git_authors_csv
    load_git_authors_csv(csv_path)

    from backend.services.git_correlation import get_team_ai_share
    s = get_team_ai_share(period_days=30)
    assert s["total_additions"] == 3000  # 2000 bot + 1000 human
    assert s["bot_additions"] == 2000
    assert s["human_additions"] == 1000
    # No Cursor leaderboard hit for Alice so human_ai_lines = 0
    assert s["human_ai_lines"] == 0
    # ai_lines_total = bot (2000) + human_ai (0) = 2000
    assert s["ai_lines_total"] == 2000
    # ai_share = 2000 / 3000 = 66.7%
    assert s["ai_share_pct"] == pytest.approx(66.7, abs=0.1)


def test_ai_share_percent(tmp_db, tmp_path):
    """ai_share_of_additions = min(ai_lines, additions) / additions * 100."""
    from data.db import get_conn
    # Create a user, then write a Cursor-leaderboard-like row via a real CSV.
    import os
    cursor_dir = tmp_path / "cursor_export"
    cursor_dir.mkdir()
    os.environ["HMND_CURSOR_EXPORT_DIR"] = str(cursor_dir)
    os.environ["HMND_SOURCES_DIR"] = str(cursor_dir)
    (cursor_dir / "User_Leaderboard_2026-04-30_2026-05-06.csv").write_text(
        "Email,Name,Agent Completions,Agent Lines,Tab Completions,Tab Lines,Ai Lines,Favorite Model\n"
        "alice@x,Alice,10,500,0,0,500,claude-opus\n"
    )
    import importlib
    import backend.services.cursor_analytics as ca
    importlib.reload(ca)

    with get_conn() as conn:
        conn.execute("INSERT INTO users(email, full_name) VALUES('alice@x', 'Alice')")
        conn.commit()

    # Alice has 500 ai_lines, 1000 git additions → 50% AI share
    csv_path = tmp_path / "git_authors.csv"
    _write_authors_csv(csv_path, [
        ("Alice", "alice@x", "hmnd", 10, 1000, 200, 800, "2026-04-01", "2026-05-10"),
    ])
    from data.sources.git_csv import load_git_authors_csv
    load_git_authors_csv(csv_path)

    from backend.services.git_correlation import get_git_ai_correlation
    devs = get_git_ai_correlation(period_days=30)
    alice = next(r for r in devs if r["git_author_name"] == "Alice")
    assert alice["ai_lines"] == 500, alice
    assert alice["git_additions"] == 1000
    assert alice["ai_share_of_additions"] == 50.0
