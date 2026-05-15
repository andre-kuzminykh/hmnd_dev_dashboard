"""Extract git stats from the three Humanoid repos on the VM and drop
CSVs into sources/ where the dashboard's loader will pick them up.

Run on the VM:
    docker compose exec dashboard python -m scripts.extract_git_stats

Reads GitHub PAT from env GITHUB_TOKEN (or HMND_GITHUB_TOKEN).
Clones / pulls the three repos shallow into /tmp/hmnd_repos_clone,
walks `git log --numstat`, and writes:
    sources/git_commit_file_stats_YYYYMMDD.csv  (per-commit-file)
    sources/git_authors_YYYYMMDD.csv            (per-author rollup)

Idempotent: re-runs do `git fetch` + replace the CSVs.
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

REPOS = [
    "HumanoidTeam/hmnd",
    "HumanoidTeam/hmnd-cloud",
    "HumanoidTeam/hmnd-sim",
]

CLONE_ROOT = Path("/tmp/hmnd_repos_clone")
ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"
TODAY = date.today().strftime("%Y%m%d")
OUT_COMMITS = SOURCES / f"git_commit_file_stats_{TODAY}.csv"
OUT_AUTHORS = SOURCES / f"git_authors_{TODAY}.csv"


def _token() -> str:
    tok = (os.environ.get("GITHUB_TOKEN")
           or os.environ.get("HMND_GITHUB_TOKEN") or "").strip()
    if not tok:
        print("ERROR: set GITHUB_TOKEN env var (PAT with repo:read scope)", file=sys.stderr)
        sys.exit(1)
    return tok


def _ensure_repo(token: str, full_name: str) -> Path:
    """Clone (shallow) or fast-forward the repo. Returns local .git dir."""
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
        print(f"[{name}] cloning (shallow bare)…")
        r = subprocess.run(
            ["git", "clone", "--bare", "--quiet", auth_url, str(target)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"  clone failed: {r.stderr.strip()[:200]}", file=sys.stderr)
            return target
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
    SOURCES.mkdir(parents=True, exist_ok=True)
    token = _token()

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
        for full in REPOS:
            short = full.split("/", 1)[1]
            repo_dir = _ensure_repo(token, full)
            n = _walk_repo(repo_dir, short, w)
            total += n
            print(f"  {short}: {n:,} file-rows")
        print(f"  TOTAL file-rows: {total:,}")

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
    print("    docker compose exec dashboard python -m scripts.reset --days 90")
    return 0


if __name__ == "__main__":
    sys.exit(main())
