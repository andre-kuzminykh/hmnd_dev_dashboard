"""Merge user_id rows that share LOWER(local_part(email)) across domains.

Background: HMND uses both @thehumanoid.ai and @skl.vc for the same
people. The user-loader creates a distinct user_id per email, so each
dual-domain person becomes 2 rows. Per-person spend / commits / segments
are then split across both.

This script merges every group of user rows sharing LOWER(local_part):
  • Picks the LOWEST user_id as canonical
  • Rewrites every FK in 10 child tables to canonical
  • Deletes the duplicates
  • Keeps the canonical's email as-is (you can still see both domains
    in usage_events.* historic source data if needed)

⚠️ DESTRUCTIVE — runs DELETE on users. Always:
  1. Run with --dry-run first to see the plan
  2. Backup DB if you have one
  3. Then run without --dry-run

Idempotent: re-running on a merged DB is a no-op.

Usage:
    # See the plan, no changes:
    docker compose exec -T dashboard python -m scripts.merge_dual_domain_identities --dry-run

    # Actually merge:
    docker compose exec -T dashboard python -m scripts.merge_dual_domain_identities
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from data.db import get_conn


# Same FK list as merge_dup_emails.py (case-only dupes), plus any
# user-referenced table.
USER_FK_TABLES = [
    ("usage_events",          "user_id"),
    ("daily_costs",           "user_id"),
    ("seats",                 "user_id"),
    ("api_keys",              "owner_user_id"),
    ("commits",               "author_id"),
    ("pull_requests",         "author_id"),
    ("ai_code_attribution",   "user_id"),
    ("git_authors",           "user_id"),
    ("git_author_repo_stats", "user_id"),
    ("git_commits",           "user_id"),
]


def find_dual_domain_groups() -> list[list[dict]]:
    """Groups of user rows sharing LOWER(local_part(email)) across ≥ 2 domains."""
    with get_conn() as conn:
        users = conn.execute(
            "SELECT id, LOWER(email) AS email, full_name FROM users "
            "WHERE email IS NOT NULL AND email != '' AND email LIKE '%@%'"
        ).fetchall()

    by_local: dict[str, list[dict]] = defaultdict(list)
    for u in users:
        local, _, _ = u["email"].partition("@")
        by_local[local].append(dict(u))

    groups: list[list[dict]] = []
    for local, rows in by_local.items():
        domains = {r["email"].partition("@")[2] for r in rows}
        if len(domains) >= 2 and len(rows) >= 2:
            # Sort by id so canonical is always the lowest
            rows.sort(key=lambda r: r["id"])
            groups.append(rows)
    return groups


def merge_group(group: list[dict], dry_run: bool) -> dict:
    """Merge a group: canonical (lowest id) absorbs others' FKs + emails."""
    canonical = group[0]
    dupes = group[1:]
    moved = {tbl: 0 for tbl, _ in USER_FK_TABLES}
    deleted = 0

    with get_conn() as conn:
        for dup in dupes:
            for tbl, col in USER_FK_TABLES:
                if dry_run:
                    n = conn.execute(
                        f"SELECT COUNT(*) AS n FROM {tbl} WHERE {col} = ?",
                        (dup["id"],),
                    ).fetchone()["n"]
                    moved[tbl] += n
                else:
                    cur = conn.execute(
                        f"UPDATE {tbl} SET {col} = ? WHERE {col} = ?",
                        (canonical["id"], dup["id"]),
                    )
                    moved[tbl] += cur.rowcount
            if not dry_run:
                conn.execute("DELETE FROM users WHERE id = ?", (dup["id"],))
                deleted += 1
        if not dry_run:
            conn.commit()

    return {
        "canonical": canonical,
        "dupes": dupes,
        "would_delete": len(dupes) if dry_run else deleted,
        "fks_to_rewrite": moved,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show the merge plan without modifying the DB")
    args = parser.parse_args()

    groups = find_dual_domain_groups()
    if not groups:
        print("No dual-domain identity groups found. Nothing to do.")
        return 0

    if args.dry_run:
        print(f"DRY RUN — no changes. {len(groups)} group(s) to merge:\n")
    else:
        print(f"MERGING {len(groups)} dual-domain identity group(s):\n")

    total_fk = 0
    total_dupes = 0
    for g in groups:
        rep = merge_group(g, dry_run=args.dry_run)
        canon = rep["canonical"]
        emails = ", ".join(d["email"] for d in rep["dupes"])
        verb = "would merge" if args.dry_run else "merged"
        print(f"  {verb}: canonical id={canon['id']} <{canon['email']}>")
        print(f"     ← absorbs {emails}")
        for tbl, n in rep["fks_to_rewrite"].items():
            if n:
                action = "would rewrite" if args.dry_run else "rewrote"
                print(f"     {action} {n:>5} FK(s) in {tbl}")
        total_fk += sum(rep["fks_to_rewrite"].values())
        total_dupes += rep["would_delete"]

    print()
    if args.dry_run:
        print(f"DRY-RUN SUMMARY:")
        print(f"  {total_dupes} duplicate user rows would be deleted")
        print(f"  {total_fk} FK rows would be rewritten to canonical user_ids")
        print(f"\n  To actually apply: re-run without --dry-run")
    else:
        print(f"DONE:")
        print(f"  {total_dupes} duplicate user rows deleted")
        print(f"  {total_fk} FK rows rewritten")
        print(f"\n  Re-run audit to confirm:")
        print(f"    docker compose exec -T dashboard python -m scripts.audit_identity_collisions")
        print(f"  Then re-run report_i_data to see the corrected Top spenders:")
        print(f"    docker compose exec -T dashboard python -m scripts.report_i_data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
