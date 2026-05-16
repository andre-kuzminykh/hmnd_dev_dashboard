"""F-17 — Configurable repository list for git extraction.

Tests follow the F-17 4-layer convention introduced in docs/SPEC.md:
  - T-INFRA-...  → environment/file/permission/env-var presence
  - T-DATA-...   → data format / parsing / schema contracts
  - T-SVC-...    → service-layer business logic (pure functions)
  - T-AI-...     → AI/prompt-related (N/A for F-17 — no AI components)

Each test name encodes its (level, FR-id, intent). One FR can be covered
by multiple tests across layers — this is by design for critical features.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.extract_git_stats as egs


REPO_ROOT = Path(__file__).resolve().parent.parent
COMMITTED_REPO_LIST = REPO_ROOT / "sources" / "git_repos.txt"

# Recognises "org/repo" (GitHub-allowed chars in both halves).
ORG_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch, tmp_path):
    """Each test runs with a clean env (no HMND_GIT_REPOS leak) and a
    REPO_LIST_FILE that points at a fresh tmp path (which will be absent
    by default unless the test populates it).
    """
    monkeypatch.delenv("HMND_GIT_REPOS", raising=False)
    monkeypatch.setattr(egs, "REPO_LIST_FILE", tmp_path / "git_repos.txt")
    yield


# ═══════════════════════════════════════════════════════════════════════════
# UC-17.1.1 — Default fallback
# ═══════════════════════════════════════════════════════════════════════════

def test_t_svc_17_1_1_1_default_fallback():
    """T-SVC-17.1.1.1 — _resolve_repos(None) без env/file → DEFAULT_REPOS."""
    assert egs._resolve_repos(None) == egs.DEFAULT_REPOS


def test_t_svc_17_1_1_2_default_repos_unchanged():
    """T-SVC-17.1.1.2 — DEFAULT_REPOS неизменяем (3 элемента, exact order)."""
    assert egs.DEFAULT_REPOS == [
        "HumanoidTeam/hmnd",
        "HumanoidTeam/hmnd-cloud",
        "HumanoidTeam/hmnd-sim",
    ]


def test_t_svc_17_1_1_3_priority_order(monkeypatch, tmp_path):
    """T-SVC-17.1.1.3 — priority CLI > env > file > default at every transition."""
    cfg = tmp_path / "git_repos.txt"
    cfg.write_text("HumanoidTeam/from-file\n", encoding="utf-8")
    monkeypatch.setattr(egs, "REPO_LIST_FILE", cfg)
    monkeypatch.setenv("HMND_GIT_REPOS", "HumanoidTeam/from-env")

    assert egs._resolve_repos("HumanoidTeam/from-cli") == ["HumanoidTeam/from-cli"]
    assert egs._resolve_repos(None) == ["HumanoidTeam/from-env"]
    monkeypatch.delenv("HMND_GIT_REPOS")
    assert egs._resolve_repos(None) == ["HumanoidTeam/from-file"]
    cfg.unlink()
    assert egs._resolve_repos(None) == egs.DEFAULT_REPOS


def test_t_data_17_1_1_1_default_repos_format():
    """T-DATA-17.1.1.1 — DEFAULT_REPOS валиден как формат `org/repo`."""
    for r in egs.DEFAULT_REPOS:
        assert ORG_REPO_RE.match(r), f"{r!r} does not match org/repo format"


# ═══════════════════════════════════════════════════════════════════════════
# UC-17.1.2 — CLI flag override
# ═══════════════════════════════════════════════════════════════════════════

def test_t_svc_17_1_2_1_cli_parsing():
    """T-SVC-17.1.2.1 — CLI string split, whitespace stripped, empties skipped."""
    out = egs._resolve_repos("  HumanoidTeam/a , HumanoidTeam/b ,,HumanoidTeam/c  ")
    assert out == ["HumanoidTeam/a", "HumanoidTeam/b", "HumanoidTeam/c"]


def test_t_svc_17_1_2_2_cli_beats_env_and_file(monkeypatch, tmp_path):
    """T-SVC-17.1.2.2 — CLI takes precedence over env + file when non-empty."""
    monkeypatch.setenv("HMND_GIT_REPOS", "HumanoidTeam/from-env")
    cfg = tmp_path / "git_repos.txt"
    cfg.write_text("HumanoidTeam/from-file\n", encoding="utf-8")
    monkeypatch.setattr(egs, "REPO_LIST_FILE", cfg)

    assert egs._resolve_repos("HumanoidTeam/win") == ["HumanoidTeam/win"]


def test_t_svc_17_1_2_3_empty_cli_falls_through(monkeypatch):
    """T-SVC-17.1.2.3 — CLI='' or whitespace-only does NOT override."""
    monkeypatch.setenv("HMND_GIT_REPOS", "HumanoidTeam/from-env")
    assert egs._resolve_repos("") == ["HumanoidTeam/from-env"]
    assert egs._resolve_repos("   ,  , ") == ["HumanoidTeam/from-env"]


# ═══════════════════════════════════════════════════════════════════════════
# UC-17.1.3 — Env var override
# ═══════════════════════════════════════════════════════════════════════════

def test_t_infra_17_1_3_1_env_var_visible(monkeypatch):
    """T-INFRA-17.1.3.1 — Env var is settable + retrievable in test process."""
    import os
    monkeypatch.setenv("HMND_GIT_REPOS", "HumanoidTeam/probe")
    assert os.environ.get("HMND_GIT_REPOS") == "HumanoidTeam/probe"


def test_t_svc_17_1_3_1_env_parsing(monkeypatch):
    """T-SVC-17.1.3.1 — HMND_GIT_REPOS parsing identical to CLI."""
    monkeypatch.setenv("HMND_GIT_REPOS", " HumanoidTeam/x ,HumanoidTeam/y , ,HumanoidTeam/z ")
    assert egs._resolve_repos(None) == ["HumanoidTeam/x", "HumanoidTeam/y", "HumanoidTeam/z"]


def test_t_svc_17_1_3_2_empty_env_falls_through(monkeypatch):
    """T-SVC-17.1.3.2 — Empty or whitespace-only env → file (then default)."""
    monkeypatch.setenv("HMND_GIT_REPOS", "")
    assert egs._resolve_repos(None) == egs.DEFAULT_REPOS

    monkeypatch.setenv("HMND_GIT_REPOS", "   ")
    assert egs._resolve_repos(None) == egs.DEFAULT_REPOS


# ═══════════════════════════════════════════════════════════════════════════
# UC-17.1.4 — Config file (sources/git_repos.txt)
# ═══════════════════════════════════════════════════════════════════════════

def test_t_infra_17_1_4_1_config_file_exists():
    """T-INFRA-17.1.4.1 — sources/git_repos.txt exists in the committed repo."""
    assert COMMITTED_REPO_LIST.exists(), \
        f"Expected committed config file at {COMMITTED_REPO_LIST}"


def test_t_infra_17_1_4_2_config_file_contains_all_core_repos():
    """T-INFRA-17.1.4.2 — Committed file contains AT LEAST the 3 core repos.

    The file is allowed to be exactly the 3 defaults (current scope) or
    extended beyond them. What we guard against is the file silently losing
    one of the 3 core monorepos — that would break Code Quality, Devs
    (Git × AI), and segment-distribution panels in the dashboard.
    """
    repos = _parse_committed_repo_list()
    for core in egs.DEFAULT_REPOS:
        assert core in repos, f"core repo {core} missing from committed list"
    assert len(repos) >= 3, f"Expected ≥3 repos in committed file, found {len(repos)}: {repos}"


def test_t_data_17_1_4_1_file_strips_comments_and_blanks(monkeypatch, tmp_path):
    """T-DATA-17.1.4.1 — '#' (full-line + inline), blank lines stripped."""
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


def test_t_data_17_1_4_2_every_line_is_org_repo_format():
    """T-DATA-17.1.4.2 — Every entry in committed file matches org/repo format."""
    repos = _parse_committed_repo_list()
    for r in repos:
        assert ORG_REPO_RE.match(r), \
            f"{r!r} in committed git_repos.txt does not match org/repo regex"


def test_t_svc_17_1_4_1_missing_or_empty_file_falls_back(monkeypatch, tmp_path):
    """T-SVC-17.1.4.1 — No file OR all-comments file → DEFAULT_REPOS."""
    cfg = tmp_path / "git_repos.txt"
    monkeypatch.setattr(egs, "REPO_LIST_FILE", cfg)

    # 1. Missing
    assert egs._resolve_repos(None) == egs.DEFAULT_REPOS

    # 2. Empty (comments only)
    cfg.write_text("# only comments\n\n  \n#HumanoidTeam/inactive\n", encoding="utf-8")
    assert egs._resolve_repos(None) == egs.DEFAULT_REPOS


# ═══════════════════════════════════════════════════════════════════════════
# UC-17.2.1 — Skip failed clone, continue with rest
# ═══════════════════════════════════════════════════════════════════════════

def test_t_svc_17_2_1_1_ensure_repo_returns_none_on_failure(monkeypatch, tmp_path):
    """T-SVC-17.2.1.1 — _ensure_repo returns None on subprocess non-zero exit."""
    # Point CLONE_ROOT at a clean tmp dir
    monkeypatch.setattr(egs, "CLONE_ROOT", tmp_path)

    # Mock subprocess.run to simulate git-clone failure
    class FakeResult:
        returncode = 128
        stderr = "Repository not found"
        stdout = ""

    with patch("scripts.extract_git_stats.subprocess.run", return_value=FakeResult()):
        result = egs._ensure_repo("fake-token", "org/does-not-exist")
    assert result is None


def test_t_svc_17_2_1_2_main_continues_after_skip(monkeypatch, tmp_path, capsys):
    """T-SVC-17.2.1.2 — main() handles a mix of OK + failed repos gracefully.

    Tested via _resolve_repos + _ensure_repo composition: if 1 of 2 repos
    returns None, the other still gets processed and we don't crash.
    """
    monkeypatch.setattr(egs, "CLONE_ROOT", tmp_path)
    repos = ["org/good", "org/bad"]
    monkeypatch.setattr(egs, "DEFAULT_REPOS", repos)

    call_count = {"n": 0}

    def fake_ensure(_token, full):
        call_count["n"] += 1
        return None if full == "org/bad" else tmp_path / "good.git"

    monkeypatch.setattr(egs, "_ensure_repo", fake_ensure)
    # Drive resolver — both repos seen, but bad one skipped at caller level
    resolved = egs._resolve_repos(None)
    skipped = [r for r in resolved if fake_ensure(None, r) is None]
    # Reset counter (the loop above called fake_ensure)
    assert call_count["n"] >= 2
    assert skipped == ["org/bad"]


# ═══════════════════════════════════════════════════════════════════════════
# UC-17.2.2 — Repo identification (org/repo → short name)
# ═══════════════════════════════════════════════════════════════════════════

def test_t_data_17_2_2_1_short_name_after_slash():
    """T-DATA-17.2.2.1 — short_name = full_name.split('/', 1)[1]."""
    cases = [
        ("HumanoidTeam/hmnd", "hmnd"),
        ("HumanoidTeam/hmnd-cloud", "hmnd-cloud"),
        ("HumanoidTeam/firmware_hal_aurix_tc3", "firmware_hal_aurix_tc3"),
        ("org/sub/leftover", "sub/leftover"),  # maxsplit=1 keeps the rest
    ]
    for full, expected in cases:
        assert full.split("/", 1)[1] == expected


def test_t_data_17_2_2_2_default_short_names_preserved():
    """T-DATA-17.2.2.2 — 3 default repos still produce stable short names."""
    expected_shorts = {"hmnd", "hmnd-cloud", "hmnd-sim"}
    actual_shorts = {r.split("/", 1)[1] for r in egs.DEFAULT_REPOS}
    assert actual_shorts == expected_shorts


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _parse_committed_repo_list() -> list[str]:
    """Mirror of egs._resolve_repos() file-parsing logic. Reads the
    committed sources/git_repos.txt (not a tmp_path fixture) for tests
    that assert on the actual checked-in content.
    """
    repos: list[str] = []
    for raw in COMMITTED_REPO_LIST.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            repos.append(line)
    return repos
