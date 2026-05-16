"""Cleanup git data for repos that are no longer in sources/git_repos.txt.

When the repo list is narrowed (e.g. 12 → 3), the sync sidecar will keep
re-loading CSVs but the **old** repo rows in `git_commits` /
`git_author_repo_stats` stay in the DB forever — sync only ADDS, never
prunes.

This script:
  1. Reads the canonical repo list from sources/git_repos.txt
  2. Computes short_names (`hmnd-cloud` from `HumanoidTeam/hmnd-cloud`)
  3. Lists distinct `repo` values in `git_commits` + `git_author_repo_stats`
  4. DELETEs rows where `repo` is NOT in the canonical short_name set
  5. Prints summary of what was removed (commits / authors_repo_stats rows)

Run on the VM after editing sources/git_repos.txt to narrow scope:

    docker compose exec -T dashboard python -m scripts.cleanup_removed_repos
    docker compose exec -T dashboard python -m scripts.cleanup_removed_repos --apply

Without --apply it's a DRY RUN: only shows what would be deleted.

Idempotent: re-running on an already-clean DB is a no-op.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data.db import get_conn


ROOT = Path(__file__).resolve().parent.parent
REPO_LIST_FILE = ROOT / "sources" / "git_repos.txt"


def _canonical_short_names() -> set[str]:
    """Read sources/git_repos.txt → set of short names (`hmnd-cloud` etc)."""
    if not REPO_LIST_FILE.exists():
        print(f"ERROR: {REPO_LIST_FILE} not found", file=sys.stderr)
        sys.exit(1)
    out: set[str] = set()
    for raw in REPO_LIST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "/" not in line:
            continue
        out.add(line.split("/", 1)[1])
    return out


def _repos_in_db() -> dict[str, dict[str, int]]:
    """Per-table count of rows grouped by `repo` column."""
    out: dict[str, dict[str, int]] = {}
    with get_conn() as conn:
        for table in ("git_commits", "git_author_repo_stats"):
            try:
                rows = conn.execute(
                    f"SELECT repo, COUNT(*) AS n FROM {table} GROUP BY repo"
                ).fetchall()
                for r in rows:
                    out.setdefault(r["repo"], {})[table] = r["n"]
            except Exception as e:
                print(f"  (skipping {table}: {e})", file=sys.stderr)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove DB rows for repos no longer tracked")
    parser.add_argument("--apply", action="store_true",
                        help="Actually delete (default is dry-run)")
    args = parser.parse_args()

    canonical = _canonical_short_names()
    in_db = _repos_in_db()

    try:
        list_display = str(REPO_LIST_FILE.relative_to(ROOT))
    except ValueError:
        list_display = str(REPO_LIST_FILE)
    print(f"Canonical repo list (from {list_display}):")
    for r in sorted(canonical):
        print(f"  ✓ {r}")
    print()

    keep, remove = [], []
    for repo, counts in sorted(in_db.items()):
        if repo in canonical:
            keep.append((repo, counts))
        else:
            remove.append((repo, counts))

    print(f"In DB but in canonical list — KEEP ({len(keep)}):")
    for r, c in keep:
        commits = c.get("git_commits", 0)
        stats = c.get("git_author_repo_stats", 0)
        print(f"  ✓ {r:40s} commits={commits:>7,}  author_repo_stats={stats}")
    print()

    print(f"In DB but NOT in canonical list — {'WILL REMOVE' if args.apply else 'WOULD REMOVE (dry-run)'} ({len(remove)}):")
    if not remove:
        print("  (nothing to do — DB is already clean)")
        return 0
    total_commits = 0
    total_stats = 0
    for r, c in remove:
        commits = c.get("git_commits", 0)
        stats = c.get("git_author_repo_stats", 0)
        total_commits += commits
        total_stats += stats
        print(f"  ✗ {r:40s} commits={commits:>7,}  author_repo_stats={stats}")
    print(f"  TOTAL: {total_commits:,} commits + {total_stats} author_repo_stats rows")
    print()

    if not args.apply:
        print("DRY-RUN. To apply: docker compose exec -T dashboard python -m scripts.cleanup_removed_repos --apply")
        return 0

    # Apply
    with get_conn() as conn:
        for repo, _ in remove:
            conn.execute("DELETE FROM git_commits WHERE repo = ?", (repo,))
            conn.execute("DELETE FROM git_author_repo_stats WHERE repo = ?", (repo,))
        conn.commit()

    print(f"✅ Removed {total_commits:,} git_commits rows + {total_stats} git_author_repo_stats rows.")
    print()
    print("⚠️  IMPORTANT — DB cleanup is only half the job:")
    print()
    print("    Existing CSVs in sources/ (git_commit_file_stats_*.csv,")
    print("    git_authors_*.csv) STILL contain rows for the removed repos.")
    print("    On the next sync (~15 min) the loader will re-insert them and")
    print("    the dashboard dropdown will show the removed repos again.")
    print()
    print("    To complete the cleanup, re-extract with the new repo list:")
    print()
    print("      docker compose exec -T dashboard python -m scripts.extract_git_stats")
    print("      docker compose exec -T dashboard python -m scripts.sync --days 90")
    print("      docker compose kill dashboard && docker compose up -d dashboard")
    print()
    print("    Then verify:")
    print("      docker compose exec -T dashboard python -m scripts.audit_etl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
