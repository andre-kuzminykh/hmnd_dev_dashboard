"""F-17 UC-17.3 — Cleanup git data when repo list is narrowed.

When `sources/git_repos.txt` is narrowed (12 → 3 in the rollback from
2026-05-16), sync only ADDS new rows; it never prunes data for repos
that left the list. `scripts/cleanup_removed_repos.py` does the pruning.
Tests verify dry-run safety, idempotency, and that core 3 repos are
never accidentally pruned.

Test taxonomy (F-17 four-layer convention):
  T-INFRA-17.3.* — script exists, callable, reads config file
  T-DATA-17.3.*  — DB rows actually deleted, idempotent
  T-SVC-17.3.*   — short-name extraction, dry-run vs apply contract
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.cleanup_removed_repos as cleanup
from data.db import get_conn, init_schema


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Each test gets a fresh tmp SQLite + repo_list_file."""
    db = tmp_path / "test.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db))

    # Reload data.db so the new HMND_DB_PATH is picked up
    import data.db as _db
    importlib.reload(_db)
    init_schema()

    # Point REPO_LIST_FILE at tmp path so tests can write their own list
    repo_list = tmp_path / "git_repos.txt"
    monkeypatch.setattr(cleanup, "REPO_LIST_FILE", repo_list)

    yield {"db": db, "repo_list": repo_list}


def _seed_git_commits(repos: list[str], rows_per_repo: int = 5):
    """Insert fake git_commits rows for each repo."""
    with get_conn() as conn:
        for repo in repos:
            for i in range(rows_per_repo):
                conn.execute(
                    "INSERT INTO git_commits(repo, sha, author_name, author_date, subject) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (repo, f"{repo}-sha-{i}", "test", "2026-05-01T00:00:00Z", f"commit {i}"),
                )
        conn.commit()


def _seed_author_repo_stats(repos: list[str]):
    """Insert fake git_author_repo_stats rows for each repo."""
    with get_conn() as conn:
        for repo in repos:
            conn.execute(
                "INSERT INTO git_author_repo_stats(name, repo, commits) VALUES (?, ?, ?)",
                ("test_author", repo, 5),
            )
        conn.commit()


def _commits_repos() -> set[str]:
    with get_conn() as conn:
        return {r["repo"] for r in conn.execute("SELECT DISTINCT repo FROM git_commits").fetchall()}


# ───────────────────────────────────────────────────────────────────────────
# T-INFRA — basic existence checks
# ───────────────────────────────────────────────────────────────────────────

def test_t_infra_17_3_1_script_module_loads():
    """T-INFRA-17.3.1 — Module imports cleanly and has the expected entry points."""
    assert callable(cleanup.main)
    assert callable(cleanup._canonical_short_names)
    assert callable(cleanup._repos_in_db)


def test_t_infra_17_3_2_committed_config_file_exists():
    """T-INFRA-17.3.2 — Production config file exists and is parseable."""
    prod_file = ROOT / "sources" / "git_repos.txt"
    assert prod_file.exists()
    content = prod_file.read_text(encoding="utf-8")
    assert "HumanoidTeam/hmnd" in content


# ───────────────────────────────────────────────────────────────────────────
# T-SVC — pure functions
# ───────────────────────────────────────────────────────────────────────────

def test_t_svc_17_3_1_canonical_short_names_parses(isolated_db):
    """T-SVC-17.3.1 — _canonical_short_names returns the short-name set."""
    isolated_db["repo_list"].write_text(
        "# header\n"
        "HumanoidTeam/hmnd\n"
        "HumanoidTeam/hmnd-cloud  # core infra\n"
        "\n"
        "#HumanoidTeam/disabled\n"
        "HumanoidTeam/hmnd-sim\n",
        encoding="utf-8",
    )
    assert cleanup._canonical_short_names() == {"hmnd", "hmnd-cloud", "hmnd-sim"}


def test_t_svc_17_3_2_skips_lines_without_slash(isolated_db):
    """T-SVC-17.3.2 — lines without '/' are skipped (won't claim 'somebadline')."""
    isolated_db["repo_list"].write_text(
        "HumanoidTeam/hmnd\n"
        "somebadline\n"
        "HumanoidTeam/hmnd-cloud\n",
        encoding="utf-8",
    )
    assert cleanup._canonical_short_names() == {"hmnd", "hmnd-cloud"}


# ───────────────────────────────────────────────────────────────────────────
# T-DATA — DB row contracts
# ───────────────────────────────────────────────────────────────────────────

def test_t_data_17_3_1_dry_run_does_not_modify_db(isolated_db, monkeypatch, capsys):
    """T-DATA-17.3.1 — Running without --apply must NOT change DB rows.

    Catches the worst-case bug: running the script for inspection and
    accidentally wiping good data.
    """
    isolated_db["repo_list"].write_text(
        "HumanoidTeam/hmnd\nHumanoidTeam/hmnd-cloud\nHumanoidTeam/hmnd-sim\n",
        encoding="utf-8",
    )
    _seed_git_commits(["hmnd", "hmnd-cloud", "hmnd-sim", "hm-ops", "Gripper_Firmware"])
    before = _commits_repos()
    assert before == {"hmnd", "hmnd-cloud", "hmnd-sim", "hm-ops", "Gripper_Firmware"}

    monkeypatch.setattr(sys, "argv", ["cleanup_removed_repos"])  # no --apply
    cleanup.main()

    after = _commits_repos()
    assert after == before, "Dry-run must not touch the DB"


def test_t_data_17_3_2_apply_removes_non_listed_repos(isolated_db, monkeypatch):
    """T-DATA-17.3.2 — With --apply, repos not in config file are removed."""
    isolated_db["repo_list"].write_text(
        "HumanoidTeam/hmnd\nHumanoidTeam/hmnd-cloud\nHumanoidTeam/hmnd-sim\n",
        encoding="utf-8",
    )
    _seed_git_commits(["hmnd", "hmnd-cloud", "hmnd-sim", "hm-ops", "Gripper_Firmware"])
    _seed_author_repo_stats(["hmnd", "hmnd-cloud", "hm-ops", "Gripper_Firmware"])

    monkeypatch.setattr(sys, "argv", ["cleanup_removed_repos", "--apply"])
    cleanup.main()

    # Only the 3 core remain
    assert _commits_repos() == {"hmnd", "hmnd-cloud", "hmnd-sim"}

    # Same for author_repo_stats
    with get_conn() as conn:
        stats_repos = {r["repo"] for r in conn.execute(
            "SELECT DISTINCT repo FROM git_author_repo_stats"
        ).fetchall()}
    assert stats_repos == {"hmnd", "hmnd-cloud"}  # hmnd-sim wasn't seeded here


def test_t_data_17_3_3_idempotent_on_clean_db(isolated_db, monkeypatch):
    """T-DATA-17.3.3 — Running --apply on already-clean DB is a no-op."""
    isolated_db["repo_list"].write_text(
        "HumanoidTeam/hmnd\nHumanoidTeam/hmnd-cloud\nHumanoidTeam/hmnd-sim\n",
        encoding="utf-8",
    )
    _seed_git_commits(["hmnd", "hmnd-cloud", "hmnd-sim"])
    before = _commits_repos()

    monkeypatch.setattr(sys, "argv", ["cleanup_removed_repos", "--apply"])
    cleanup.main()
    cleanup.main()  # second run shouldn't break
    after = _commits_repos()
    assert before == after


def test_t_data_17_3_4_core_repos_never_deleted(isolated_db, monkeypatch):
    """T-DATA-17.3.4 — If the canonical list includes a core repo, it's preserved.

    Critical invariant: the 3 core (hmnd, hmnd-cloud, hmnd-sim) MUST survive
    any cleanup run as long as they appear in sources/git_repos.txt.
    """
    isolated_db["repo_list"].write_text(
        "HumanoidTeam/hmnd\nHumanoidTeam/hmnd-cloud\nHumanoidTeam/hmnd-sim\n",
        encoding="utf-8",
    )
    _seed_git_commits(["hmnd", "hmnd-cloud", "hmnd-sim", "rogue_repo"])

    monkeypatch.setattr(sys, "argv", ["cleanup_removed_repos", "--apply"])
    cleanup.main()

    survivors = _commits_repos()
    for core in ["hmnd", "hmnd-cloud", "hmnd-sim"]:
        assert core in survivors, f"core repo {core} should not be deleted"
    assert "rogue_repo" not in survivors
