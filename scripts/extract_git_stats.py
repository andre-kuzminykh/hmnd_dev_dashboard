"""Extract git stats from Humanoid repos on the VM and drop CSVs into
sources/ where the dashboard's loader will pick them up.

Run on the VM:
    docker compose exec dashboard python -m scripts.extract_git_stats

Reads GitHub PAT from env GITHUB_TOKEN (or HMND_GITHUB_TOKEN).
Clones / pulls each repo shallow into /tmp/hmnd_repos_clone,
walks `git log --numstat`, and writes:
    sources/git_commit_file_stats_YYYYMMDD.csv  (per-commit-file)
    sources/git_authors_YYYYMMDD.csv            (per-author rollup)

Repository list — resolution order (first match wins):
  1. --repos a/b,c/d on the command line
  2. HMND_GIT_REPOS env var (comma-separated org/repo names)
  3. sources/git_repos.txt — one "org/repo" per line, blank lines and
     lines starting with '#' ignored
  4. Built-in default: HumanoidTeam/{hmnd, hmnd-cloud, hmnd-sim}

Idempotent: re-runs do `git fetch` + replace the CSVs.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

# Built-in default — the three core monorepos. Override via --repos /
# HMND_GIT_REPOS / sources/git_repos.txt to widen the audit scope.
DEFAULT_REPOS = [
    "HumanoidTeam/hmnd",
    "HumanoidTeam/hmnd-cloud",
    "HumanoidTeam/hmnd-sim",
]

CLONE_ROOT = Path("/tmp/hmnd_repos_clone")
ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"
REPO_LIST_FILE = SOURCES / "git_repos.txt"
TODAY = date.today().strftime("%Y%m%d")
OUT_COMMITS = SOURCES / f"git_commit_file_stats_{TODAY}.csv"
OUT_AUTHORS = SOURCES / f"git_authors_{TODAY}.csv"


def _resolve_repos(cli_arg: str | None) -> list[str]:
    """Pick the repo list from CLI / env / config / default."""
    # 1. CLI takes precedence
    if cli_arg:
        repos = [r.strip() for r in cli_arg.split(",") if r.strip()]
        if repos:
            print(f"[repos] using --repos: {len(repos)} repo(s)")
            return repos
    # 2. Env var
    env = os.environ.get("HMND_GIT_REPOS", "").strip()
    if env:
        repos = [r.strip() for r in env.split(",") if r.strip()]
        if repos:
            print(f"[repos] using HMND_GIT_REPOS: {len(repos)} repo(s)")
            return repos
    # 3. Config file
    if REPO_LIST_FILE.exists():
        repos = []
        for raw in REPO_LIST_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                repos.append(line)
        if repos:
            print(f"[repos] using {REPO_LIST_FILE.name}: {len(repos)} repo(s)")
            return repos
    # 4. Built-in
    print(f"[repos] using built-in default: {len(DEFAULT_REPOS)} repo(s)")
    return list(DEFAULT_REPOS)


def _token() -> str:
    tok = (os.environ.get("GITHUB_TOKEN")
           or os.environ.get("HMND_GITHUB_TOKEN") or "").strip()
    if not tok:
        print("ERROR: set GITHUB_TOKEN env var (PAT with repo:read scope)", file=sys.stderr)
        sys.exit(1)
    return tok


def _ensure_repo(token: str, full_name: str) -> Path | None:
    """Clone (shallow) or fast-forward the repo. Returns local .git dir,
    or None if cloning failed (e.g. repo is private and PAT lacks access).
    """
    if "/" not in full_name:
        print(f"  skip: '{full_name}' is not in org/repo form", file=sys.stderr)
        return None
    org, name = full_name.split("/", 1)
    target = CLONE_ROOT / f"{name}.git"
    auth_url = f"https://{token}@github.com/{full_name}.git"
    if target.exists():
        print(f"[{name}] fetching updates…")
        r = subprocess.run(
            ["git", f"--git-dir={target}", "fetch", "--all", "--prune", "--quiet"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"  fetch failed: {r.stderr.strip()[:200]}", file=sys.stderr)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"[{name}] cloning (bare)…")
        r = subprocess.run(
            ["git", "clone", "--bare", "--quiet", auth_url, str(target)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"  clone failed: {r.stderr.strip()[:200]}", file=sys.stderr)
            # Clean up partial clone so next run can retry cleanly
            subprocess.run(["rm", "-rf", str(target)], check=False)
            return None
    return target


def _walk_repo(repo_dir: Path, repo_short: str, writer: csv.writer) -> int:
    """Run `git log --numstat` and write per-commit-file rows. Returns
    number of file-rows emitted.
    """
    cmd = [
        "git", f"--git-dir={repo_dir}",
        "log", "--all", "--numstat", "--date=iso-strict",
        "--pretty=format:COMMIT|%H|%aN|%aE|%aI|%cN|%cE|%cI|%s",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(f"  log failed: {r.stderr.strip()[:200]}", file=sys.stderr)
        return 0
    n = 0
    cur: dict | None = None
    for line in r.stdout.splitlines():
        if line.startswith("COMMIT|"):
            parts = line.split("|", 8)
            if len(parts) != 9:
                continue
            cur = {
                "sha": parts[1], "an": parts[2], "ae": parts[3],
                "ad": parts[4], "cn": parts[5], "ce": parts[6],
                "cd": parts[7], "subj": parts[8],
            }
        elif cur and line.strip():
            parts = line.split("\t")
            if len(parts) >= 3:
                add_raw, del_raw, path = parts[0], parts[1], parts[2]
                is_binary = (add_raw == "-" or del_raw == "-")
                add = 0 if is_binary else int(add_raw)
                rm = 0 if is_binary else int(del_raw)
                writer.writerow([
                    repo_short, cur["sha"], cur["an"], cur["ae"], cur["ad"],
                    cur["cn"], cur["ce"], cur["cd"], cur["subj"],
                    path, add, rm, is_binary,
                ])
                n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract git stats from Humanoid repos")
    parser.add_argument("--repos", help="Comma-separated 'org/repo' list (overrides env + file)")
    args = parser.parse_args()

    SOURCES.mkdir(parents=True, exist_ok=True)
    token = _token()
    repos = _resolve_repos(args.repos)

    # 1) Per-commit-file CSV
    print(f"\n→ writing {OUT_COMMITS}")
    with OUT_COMMITS.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "repo", "commit_sha", "author_name", "author_email", "author_date",
            "committer_name", "committer_email", "committer_date", "subject",
            "file_path", "additions", "deletions", "is_binary",
        ])
        total = 0
        skipped: list[str] = []
        for full in repos:
            short = full.split("/", 1)[1] if "/" in full else full
            repo_dir = _ensure_repo(token, full)
            if repo_dir is None:
                skipped.append(full)
                continue
            n = _walk_repo(repo_dir, short, w)
            total += n
            print(f"  {short}: {n:,} file-rows")
        print(f"  TOTAL file-rows: {total:,}  (across {len(repos) - len(skipped)} repo(s))")
        if skipped:
            print(f"  SKIPPED {len(skipped)} (clone failed — check PAT access):")
            for s in skipped:
                print(f"    - {s}")

    # 2) Per-author rollup from the per-commit-file CSV
    print(f"\n→ aggregating to {OUT_AUTHORS}")
    authors: dict[str, dict] = defaultdict(lambda: {
        "emails": set(), "repos": set(), "shas": set(),
        "add": 0, "del": 0, "first": None, "last": None,
    })
    with OUT_COMMITS.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = (r.get("author_name") or "").strip()
            if not name:
                continue
            email = (r.get("author_email") or "").strip().lower()
            d = r.get("author_date") or ""
            try:
                add = int(r.get("additions") or 0)
                rm = int(r.get("deletions") or 0)
            except ValueError:
                continue
            s = authors[name]
            s["emails"].add(email)
            s["repos"].add(r.get("repo") or "")
            s["shas"].add(r.get("commit_sha") or "")
            s["add"] += add
            s["del"] += rm
            if d:
                if s["first"] is None or d < s["first"]:
                    s["first"] = d
                if s["last"] is None or d > s["last"]:
                    s["last"] = d
    with OUT_AUTHORS.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "git_author_name", "git_author_emails", "repos", "commits",
            "additions", "deletions", "net_lines", "first_commit", "last_commit",
        ])
        for name, s in sorted(authors.items(),
                              key=lambda kv: len(kv[1]["shas"]), reverse=True):
            w.writerow([
                name,
                ";".join(sorted(s["emails"])),
                ";".join(sorted(s["repos"])),
                len(s["shas"]),
                s["add"],
                s["del"],
                s["add"] - s["del"],
                s["first"],
                s["last"],
            ])
    print(f"  authors: {len(authors)}")
    print("\n✓ done. The next sync tick will load both CSVs into the dashboard.")
    print("  To trigger now:")
    print("    docker compose exec dashboard python -m scripts.sync --days 90")
    return 0


if __name__ == "__main__":
    sys.exit(main())
