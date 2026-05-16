"""Tests for the Code Quality (Git × AI) analytics service.

Covers:
  - Subject regex correctly tags bug-fix / revert / feature / refactor / test / docs
  - Team-wide rollup with bug-rate / revert-rate / human-vs-bot split
  - Per-author rollup with bug_rate_pct + alias dedup by user_id
  - AI-spend-per-fix debt indicator joins usage_events × git_commits
  - High-churn files rollup from the per-commit-file CSV
  - Repo and date filters narrow the result
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta


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


def _today_offset(days_ago: int) -> str:
    return (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S")


def test_classify_subject_tags_bug_fix_and_revert():
    from data.sources.git_csv import _classify_subject as c

    assert c("fix: null pointer in foo.py")["is_bug_fix"] == 1
    assert c("Fix typo in README")["is_bug_fix"] == 1
    assert c("hotfix(auth): expired token")["is_bug_fix"] == 1
    assert c("patch a memory leak")["is_bug_fix"] == 1
    assert c('Revert "feat: add new flow"')["is_revert"] == 1
    assert c("revert: bad merge")["is_revert"] == 1
    # Feature should NOT be flagged as bug-fix
    assert c("feat: add new auth flow")["is_bug_fix"] == 0
    assert c("feat: add new auth flow")["is_feature"] == 1
    assert c("refactor(payments): extract helper")["is_refactor"] == 1
    assert c("test: cover edge case")["is_test"] == 1
    assert c("docs: update README")["is_docs"] == 1


def test_classify_subject_empty_returns_zeros():
    from data.sources.git_csv import _classify_subject as c

    z = c("")
    assert all(v == 0 for v in z.values())
    z2 = c(None)  # type: ignore[arg-type]
    assert all(v == 0 for v in z2.values())


def test_load_commits_populates_git_commits_with_flags(tmp_db, tmp_path):
    """The CSV loader writes per-commit rows with classification flags."""
    csv_path = tmp_path / "git_commit_file_stats.csv"
    date = _today_offset(1)
    _write_commits_csv(csv_path, [
        ("hmnd", "sha-fix",  "Alice", "a@x", date, "Alice", "a@x", date,
         "fix: null pointer", "a.py", "10", "2", "False"),
        ("hmnd", "sha-feat", "Alice", "a@x", date, "Alice", "a@x", date,
         "feat: add login", "b.py", "100", "0", "False"),
        ("hmnd", "sha-rev",  "Bob",   "b@x", date, "Bob",   "b@x", date,
         'Revert "feat: add login"', "b.py", "0", "100", "False"),
    ])
    from data.db import get_conn
    from data.sources.git_csv import load_git_commits_csv

    load_git_commits_csv(csv_path)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT sha, is_bug_fix, is_revert, is_feature FROM git_commits ORDER BY sha"
        ).fetchall()
    flags = {r["sha"]: dict(r) for r in rows}
    assert flags["sha-fix"]["is_bug_fix"] == 1
    assert flags["sha-fix"]["is_revert"] == 0
    assert flags["sha-feat"]["is_feature"] == 1
    assert flags["sha-feat"]["is_bug_fix"] == 0
    assert flags["sha-rev"]["is_revert"] == 1


def test_get_team_quality_computes_rates(tmp_db, tmp_path):
    """3 fixes / 10 commits → bug_rate_pct = 30%."""
    csv_path = tmp_path / "git_commit_file_stats.csv"
    date = _today_offset(2)
    rows = []
    # 3 bug-fix commits, 7 features → bug_rate = 30%
    for i in range(3):
        rows.append(("hmnd", f"fix{i}", "Alice", "a@x", date, "Alice", "a@x", date,
                     f"fix: bug {i}", "a.py", "5", "1", "False"))
    for i in range(7):
        rows.append(("hmnd", f"feat{i}", "Alice", "a@x", date, "Alice", "a@x", date,
                     f"feat: feature {i}", "b.py", "20", "0", "False"))
    _write_commits_csv(csv_path, rows)

    from backend.services.git_quality import get_team_quality
    from data.sources.git_csv import load_git_commits_csv

    load_git_commits_csv(csv_path)
    tq = get_team_quality(period_days=30)
    assert tq["commits"] == 10
    assert tq["fixes"] == 3
    assert tq["features"] == 7
    assert tq["bug_rate_pct"] == 30.0
    assert tq["revert_rate_pct"] == 0.00


def test_get_team_quality_human_vs_bot_split(tmp_db, tmp_path):
    """Bots and humans get separate bug-rate columns."""
    csv_path = tmp_path / "git_commit_file_stats.csv"
    date = _today_offset(2)
    rows = []
    # Human Alice: 4 commits, 1 fix → human_bug_rate = 25%
    for i in range(3):
        rows.append(("hmnd", f"af{i}", "Alice", "a@x", date, "Alice", "a@x", date,
                     "feat: x", "a.py", "10", "0", "False"))
    rows.append(("hmnd", "afix", "Alice", "a@x", date, "Alice", "a@x", date,
                 "fix: bug", "a.py", "5", "1", "False"))
    # Bot github-actions[bot]: 2 commits, 1 fix → bot_bug_rate = 50%
    rows.append(("hmnd", "bf1", "github-actions[bot]", "ga@github.com", date,
                 "github-actions[bot]", "ga@github.com", date,
                 "chore: bump deps", "d.py", "5", "5", "False"))
    rows.append(("hmnd", "bfix", "github-actions[bot]", "ga@github.com", date,
                 "github-actions[bot]", "ga@github.com", date,
                 "fix: revert bad bump", "d.py", "5", "5", "False"))
    _write_commits_csv(csv_path, rows)

    from backend.services.git_quality import get_team_quality
    from data.sources.git_csv import load_git_commits_csv

    load_git_commits_csv(csv_path)
    tq = get_team_quality(period_days=30)
    assert tq["human_commits"] == 4
    assert tq["bot_commits"] == 2
    assert tq["human_bug_rate_pct"] == 25.0
    assert tq["bot_bug_rate_pct"] == 50.0


def test_get_team_quality_repo_filter(tmp_db, tmp_path):
    """repos=['hmnd'] narrows the rollup."""
    csv_path = tmp_path / "git_commit_file_stats.csv"
    date = _today_offset(2)
    _write_commits_csv(csv_path, [
        ("hmnd",       "h1", "A", "a@x", date, "A", "a@x", date, "fix: bug",    "a.py", "1", "0", "False"),
        ("hmnd",       "h2", "A", "a@x", date, "A", "a@x", date, "feat: thing", "a.py", "1", "0", "False"),
        ("hmnd-cloud", "c1", "A", "a@x", date, "A", "a@x", date, "fix: bug",    "b.py", "1", "0", "False"),
    ])
    from backend.services.git_quality import get_team_quality
    from data.sources.git_csv import load_git_commits_csv

    load_git_commits_csv(csv_path)
    tq_all = get_team_quality(period_days=30)
    tq_hmnd = get_team_quality(period_days=30, repos=["hmnd"])
    assert tq_all["commits"] == 3
    assert tq_hmnd["commits"] == 2
    assert tq_hmnd["fixes"] == 1


def test_get_team_quality_date_filter(tmp_db, tmp_path):
    """Commits older than period_days are excluded."""
    csv_path = tmp_path / "git_commit_file_stats.csv"
    recent = _today_offset(2)
    old = _today_offset(100)  # outside a 30-day window
    _write_commits_csv(csv_path, [
        ("hmnd", "r1", "A", "a@x", recent, "A", "a@x", recent, "fix: bug", "a.py", "1", "0", "False"),
        ("hmnd", "o1", "A", "a@x", old,    "A", "a@x", old,    "fix: bug", "a.py", "1", "0", "False"),
    ])
    from backend.services.git_quality import get_team_quality
    from data.sources.git_csv import load_git_commits_csv

    load_git_commits_csv(csv_path)
    tq_30 = get_team_quality(period_days=30)
    tq_all = get_team_quality(period_days=0)  # period 0 disables filter
    assert tq_30["commits"] == 1
    assert tq_all["commits"] == 2


def test_get_team_quality_empty_returns_safe_zeros(tmp_db):
    """No commits → all zeros, no NaNs, rates are None."""
    from backend.services.git_quality import get_team_quality

    tq = get_team_quality(period_days=30)
    assert tq["commits"] == 0
    assert tq["bug_rate_pct"] is None
    assert tq["fixes"] == 0


def test_get_quality_per_author_dedupes_by_user_id(tmp_db, tmp_path):
    """Two git author aliases linked to the same user → ONE row."""
    from data.db import get_conn

    with get_conn() as conn:
        conn.execute("INSERT INTO users(email, full_name) VALUES('alice@x', 'Alice')")
        uid = conn.execute("SELECT id FROM users WHERE email='alice@x'").fetchone()["id"]
        conn.commit()

    csv_path = tmp_path / "git_commit_file_stats.csv"
    date = _today_offset(2)
    _write_commits_csv(csv_path, [
        ("hmnd", "s1", "Alice",  "alice@x", date, "Alice", "alice@x", date,
         "fix: bug", "a.py", "5", "0", "False"),
        ("hmnd", "s2", "alice2", "alice@x", date, "alice2", "alice@x", date,
         "feat: thing", "b.py", "10", "0", "False"),
    ])
    from backend.services.git_quality import get_quality_per_author
    from data.sources.git_csv import load_git_commits_csv

    load_git_commits_csv(csv_path)
    rows = get_quality_per_author(period_days=30)
    alice_rows = [r for r in rows if r["user_id"] == uid]
    # Both commits map to the same user — collapsed to one row.
    assert len(alice_rows) == 1
    assert alice_rows[0]["commits"] == 2
    assert alice_rows[0]["fixes"] == 1
    assert alice_rows[0]["bug_rate_pct"] == 50.0


def test_get_ai_spend_per_fix(tmp_db, tmp_path):
    """spend = $100, fixes = 4 → $25 per fix."""
    from data.db import get_conn

    with get_conn() as conn:
        # Wipe seed-supplied usage_events so we control the spend total.
        conn.execute("DELETE FROM usage_events")
        pid = conn.execute("SELECT id FROM providers WHERE name='openai'").fetchone()["id"]
        mid = conn.execute(
            "SELECT id FROM models WHERE provider_id=? LIMIT 1", (pid,)
        ).fetchone()["id"]
        conn.execute("INSERT INTO users(email, full_name) VALUES('u@x', 'U')")
        uid = conn.execute("SELECT id FROM users WHERE email='u@x'").fetchone()["id"]
        conn.execute(
            """INSERT INTO usage_events(user_id, provider_id, model_id, occurred_at,
                                         tokens_in, tokens_out, tokens_cached,
                                         cost_usd, is_error, purpose)
               VALUES(?, ?, ?, datetime('now', '-1 day'), 100, 50, 0, 100.0, 0, 'API')""",
            (uid, pid, mid),
        )
        conn.commit()

    csv_path = tmp_path / "git_commit_file_stats.csv"
    date = _today_offset(2)
    rows = []
    for i in range(4):
        rows.append(("hmnd", f"f{i}", "A", "a@x", date, "A", "a@x", date,
                     f"fix: bug {i}", "a.py", "1", "0", "False"))
    rows.append(("hmnd", "f-feat", "A", "a@x", date, "A", "a@x", date,
                 "feat: thing", "a.py", "1", "0", "False"))
    _write_commits_csv(csv_path, rows)
    from backend.services.git_quality import get_ai_spend_per_fix
    from data.sources.git_csv import load_git_commits_csv

    load_git_commits_csv(csv_path)
    r = get_ai_spend_per_fix(period_days=30)
    assert r["fixes"] == 4
    assert r["ai_spend"] == 100.0
    assert r["ai_spend_per_fix"] == 25.0


def test_get_ai_spend_per_fix_zero_fixes_safe(tmp_db, tmp_path):
    """Zero fixes → ai_spend_per_fix is None (no DivisionByZero)."""
    from backend.services.git_quality import get_ai_spend_per_fix

    r = get_ai_spend_per_fix(period_days=30)
    assert r["fixes"] == 0
    assert r["ai_spend_per_fix"] is None


def test_get_ai_spend_per_fix_repo_filter(tmp_db, tmp_path):
    """repos=['hmnd'] narrows the bug-fix denominator to that repo only.
    Fixes the user-spotted bug: '$/fix shows 259 fixes when hmnd-cloud
    is selected and Code Quality says only 4 commits there'.
    """
    csv_path = tmp_path / "git_commit_file_stats.csv"
    date = _today_offset(2)
    rows = []
    # 3 fixes in hmnd
    for i in range(3):
        rows.append(("hmnd", f"h{i}", "A", "a@x", date, "A", "a@x", date,
                     f"fix: bug {i}", "a.py", "1", "0", "False"))
    # 1 fix in hmnd-cloud
    rows.append(("hmnd-cloud", "c1", "A", "a@x", date, "A", "a@x", date,
                 "fix: cloud bug", "b.py", "1", "0", "False"))
    _write_commits_csv(csv_path, rows)
    from backend.services.git_quality import get_ai_spend_per_fix
    from data.sources.git_csv import load_git_commits_csv

    load_git_commits_csv(csv_path)
    # No filter → 4 fixes
    r_all = get_ai_spend_per_fix(period_days=30)
    assert r_all["fixes"] == 4
    # repos=['hmnd-cloud'] → 1 fix
    r_cloud = get_ai_spend_per_fix(period_days=30, repos=["hmnd-cloud"])
    assert r_cloud["fixes"] == 1
    # repos=['hmnd'] → 3 fixes
    r_hmnd = get_ai_spend_per_fix(period_days=30, repos=["hmnd"])
    assert r_hmnd["fixes"] == 3


def test_get_high_churn_files(tmp_db, tmp_path, monkeypatch):
    """File-level rollup from the per-commit CSV."""
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    csv_path = tmp_path / "git_commit_file_stats_20260515.csv"
    date = _today_offset(2)
    # `auth.py` touched in 3 different commits → most-churn
    # `util.py` in 1 commit
    _write_commits_csv(csv_path, [
        ("hmnd", "s1", "A", "a@x", date, "A", "a@x", date, "fix",     "auth.py",  "10", "5", "False"),
        ("hmnd", "s2", "A", "a@x", date, "A", "a@x", date, "fix",     "auth.py",  "20", "8", "False"),
        ("hmnd", "s3", "B", "b@x", date, "B", "b@x", date, "refactor","auth.py",   "5", "2", "False"),
        ("hmnd", "s4", "A", "a@x", date, "A", "a@x", date, "feat",    "util.py",  "30", "0", "False"),
    ])
    import importlib

    import data.sources.git_csv as gc
    importlib.reload(gc)  # pick up the new HMND_SOURCES_DIR
    from backend.services.git_quality import get_high_churn_files

    files = get_high_churn_files(period_days=30, limit=10)
    by_path = {f["file"]: f for f in files}
    assert by_path["auth.py"]["commits"] == 3
    assert by_path["auth.py"]["additions"] == 35
    assert by_path["util.py"]["commits"] == 1
    # Sorted by commits desc → auth.py first
    assert files[0]["file"] == "auth.py"


def test_get_high_churn_files_repo_filter(tmp_db, tmp_path, monkeypatch):
    monkeypatch.setenv("HMND_SOURCES_DIR", str(tmp_path))
    csv_path = tmp_path / "git_commit_file_stats_20260515.csv"
    date = _today_offset(2)
    _write_commits_csv(csv_path, [
        ("hmnd",       "s1", "A", "a@x", date, "A", "a@x", date, "x", "shared.py", "10", "0", "False"),
        ("hmnd-cloud", "s2", "A", "a@x", date, "A", "a@x", date, "x", "shared.py", "20", "0", "False"),
    ])
    import importlib

    import data.sources.git_csv as gc
    importlib.reload(gc)
    from backend.services.git_quality import get_high_churn_files

    only_hmnd = get_high_churn_files(period_days=30, repos=["hmnd"], limit=10)
    assert len(only_hmnd) == 1
    assert only_hmnd[0]["commits"] == 1
    assert only_hmnd[0]["additions"] == 10
