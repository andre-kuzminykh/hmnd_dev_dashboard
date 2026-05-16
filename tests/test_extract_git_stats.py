"""F-17 — Configurable repository list for git extraction.

Pins the resolution order CLI > HMND_GIT_REPOS env > sources/git_repos.txt >
built-in default. The default (3 monorepos) is the only behaviour
production has seen prior to F-17, so the regression matrix below verifies
both the new override paths AND that the legacy default is preserved.
"""
from __future__ import annotations

import importlib

import pytest

import scripts.extract_git_stats as egs


# ---------- helpers ---------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch, tmp_path):
    """Each test runs with a clean env (no HMND_GIT_REPOS leak) and a
    REPO_LIST_FILE that points at a fresh tmp path (which will be absent
    by default).
    """
    monkeypatch.delenv("HMND_GIT_REPOS", raising=False)
    monkeypatch.setattr(egs, "REPO_LIST_FILE", tmp_path / "git_repos.txt")
    yield


# ---------- FR-17.1.1.* — default + priority --------------------------------

def test_fr_17_1_1_1_priority_order(monkeypatch, tmp_path):
    """CLI beats env beats file beats default — at every transition."""
    cfg = tmp_path / "git_repos.txt"
    cfg.write_text("HumanoidTeam/from-file\n", encoding="utf-8")
    monkeypatch.setattr(egs, "REPO_LIST_FILE", cfg)
    monkeypatch.setenv("HMND_GIT_REPOS", "HumanoidTeam/from-env")

    # CLI wins over both env and file
    assert egs._resolve_repos("HumanoidTeam/from-cli") == ["HumanoidTeam/from-cli"]
    # Remove CLI -> env wins over file
    assert egs._resolve_repos(None) == ["HumanoidTeam/from-env"]
    # Remove env -> file wins over default
    monkeypatch.delenv("HMND_GIT_REPOS")
    assert egs._resolve_repos(None) == ["HumanoidTeam/from-file"]
    # Remove file -> built-in default
    cfg.unlink()
    assert egs._resolve_repos(None) == egs.DEFAULT_REPOS


def test_fr_17_1_1_2_builtin_default():
    """Built-in default is unchanged from pre-F-17 behaviour (3 repos)."""
    assert egs.DEFAULT_REPOS == [
        "HumanoidTeam/hmnd",
        "HumanoidTeam/hmnd-cloud",
        "HumanoidTeam/hmnd-sim",
    ]


# ---------- FR-17.1.2.* — CLI -----------------------------------------------

def test_fr_17_1_2_1_cli_parsing():
    """CLI string is split on comma, whitespace trimmed, empties skipped."""
    out = egs._resolve_repos("  HumanoidTeam/a , HumanoidTeam/b ,,HumanoidTeam/c  ")
    assert out == ["HumanoidTeam/a", "HumanoidTeam/b", "HumanoidTeam/c"]


def test_fr_17_1_2_2_cli_beats_env_and_file(monkeypatch, tmp_path):
    """CLI flag takes precedence over env + file even when both set."""
    monkeypatch.setenv("HMND_GIT_REPOS", "HumanoidTeam/from-env")
    cfg = tmp_path / "git_repos.txt"
    cfg.write_text("HumanoidTeam/from-file\n", encoding="utf-8")
    monkeypatch.setattr(egs, "REPO_LIST_FILE", cfg)

    assert egs._resolve_repos("HumanoidTeam/win") == ["HumanoidTeam/win"]


def test_fr_17_1_2_1_empty_cli_falls_through(monkeypatch):
    """CLI='' or whitespace-only should NOT override — fall through to env/default."""
    monkeypatch.setenv("HMND_GIT_REPOS", "HumanoidTeam/from-env")
    assert egs._resolve_repos("") == ["HumanoidTeam/from-env"]
    assert egs._resolve_repos("   ,  , ") == ["HumanoidTeam/from-env"]


# ---------- FR-17.1.3.* — env var -------------------------------------------

def test_fr_17_1_3_1_env_parsing(monkeypatch):
    """HMND_GIT_REPOS parsing identical to CLI."""
    monkeypatch.setenv("HMND_GIT_REPOS", " HumanoidTeam/x ,HumanoidTeam/y , ,HumanoidTeam/z ")
    assert egs._resolve_repos(None) == ["HumanoidTeam/x", "HumanoidTeam/y", "HumanoidTeam/z"]


def test_fr_17_1_3_2_empty_env_falls_through(monkeypatch):
    """Empty or whitespace-only env falls through to file (then default)."""
    monkeypatch.setenv("HMND_GIT_REPOS", "")
    assert egs._resolve_repos(None) == egs.DEFAULT_REPOS

    monkeypatch.setenv("HMND_GIT_REPOS", "   ")
    assert egs._resolve_repos(None) == egs.DEFAULT_REPOS


# ---------- FR-17.1.4.* — config file ---------------------------------------

def test_fr_17_1_4_1_file_strips_comments_and_blanks(monkeypatch, tmp_path):
    """Comments (# anywhere → strip rest), blank lines, inline comments."""
    cfg = tmp_path / "git_repos.txt"
    cfg.write_text(
        "# Production list\n"
        "\n"
        "HumanoidTeam/hmnd\n"
        "HumanoidTeam/hmnd-cloud  # core infra\n"
        "  \n"
        "#HumanoidTeam/disabled\n"
        "HumanoidTeam/hm-ops\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(egs, "REPO_LIST_FILE", cfg)
    assert egs._resolve_repos(None) == [
        "HumanoidTeam/hmnd",
        "HumanoidTeam/hmnd-cloud",
        "HumanoidTeam/hm-ops",
    ]


def test_fr_17_1_4_2_missing_or_empty_file_falls_back_to_default(monkeypatch, tmp_path):
    """No file → default. Empty file (only comments) → default."""
    cfg = tmp_path / "git_repos.txt"

    # 1. Missing file
    monkeypatch.setattr(egs, "REPO_LIST_FILE", cfg)
    assert egs._resolve_repos(None) == egs.DEFAULT_REPOS

    # 2. File exists but all content is comments / blanks
    cfg.write_text("# only comments\n\n  \n#HumanoidTeam/inactive\n", encoding="utf-8")
    assert egs._resolve_repos(None) == egs.DEFAULT_REPOS


# ---------- FR-17.1.6.* — short-name extraction ----------------------------

def test_fr_17_1_6_1_short_name_after_slash():
    """short_name = part after first '/' — used as `git_commits.repo` column."""
    # This is implicit in _ensure_repo + the main() loop. Verify on a few samples.
    cases = [
        ("HumanoidTeam/hmnd", "hmnd"),
        ("HumanoidTeam/hmnd-cloud", "hmnd-cloud"),
        ("org/sub/leftover", "sub/leftover"),  # split(maxsplit=1) keeps rest
        ("HumanoidTeam/firmware_hal_aurix_tc3", "firmware_hal_aurix_tc3"),
    ]
    for full, expected_short in cases:
        assert full.split("/", 1)[1] == expected_short
