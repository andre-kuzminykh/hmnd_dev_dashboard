"""One-time cleanup: merge users that differ only in email case.

Background: SQLite's UNIQUE on `users.email` is case-sensitive, so a sync
that writes 'Blake.Lieber@hmnd.ai' followed by another writing
'blake.lieber@hmnd.ai' creates two distinct user rows. The dashboard
then splits that person's spend / commits / segment across both.

What this does, for every pair of users sharing LOWER(email):
  1. Pick the lowest user_id as canonical.
  2. UPDATE every FK that points at the duplicates → canonical.
  3. DELETE the duplicates.
  4. Lowercase the canonical's email so future syncs match.

Idempotent: re-running is a no-op if there are no dupes.

Usage:
    docker compose exec dashboard python -m scripts.merge_dup_emails
"""
from __future__ import annotations

import sys

from data.db import get_conn


# Tables whose user_id we need to rewrite when merging.
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


def find_dup_groups() -> list[list[dict]]:
    """Groups of users where LOWER(email) matches across ≥ 2 rows."""
    with get_conn() as conn:
        # Find dup email keys first.
        keys = [r[0] for r in conn.execute(
            """SELECT LOWER(email) FROM users
               WHERE email IS NOT NULL AND email != ''
               GROUP BY LOWER(email) HAVING COUNT(*) > 1"""
        ).fetchall()]
        groups = []
        for k in keys:
            rows = [dict(r) for r in conn.execute(
                "SELECT id, email, full_name FROM users WHERE LOWER(email)=? ORDER BY id",
                (k,),
            ).fetchall()]
            groups.append(rows)
        return groups


def merge_group(group: list[dict]) -> dict:
    """Merge a group: lowest id wins, others get FKs rewritten + deleted."""
    canonical = group[0]
    dupes = group[1:]
    moved = {tbl: 0 for tbl, _ in USER_FK_TABLES}
    deleted = 0
    with get_conn() as conn:
        for dup in dupes:
            for tbl, col in USER_FK_TABLES:
                cur = conn.execute(
                    f"UPDATE {tbl} SET {col} = ? WHERE {col} = ?",
                    (canonical["id"], dup["id"]),
                )
                moved[tbl] += cur.rowcount
            # Now safe to delete the duplicate row.
            conn.execute("DELETE FROM users WHERE id = ?", (dup["id"],))
            deleted += 1
        # Lowercase the canonical email so future syncs hit the same row.
        conn.execute(
            "UPDATE users SET email = LOWER(email) WHERE id = ?",
            (canonical["id"],),
        )
        conn.commit()
    return {"canonical_id": canonical["id"], "canonical_email": canonical["email"],
            "deleted": deleted, "fks_rewritten": moved}


def main() -> int:
    groups = find_dup_groups()
    if not groups:
        print("No duplicate-email user groups found. Nothing to do.")
        return 0
    print(f"Found {len(groups)} duplicate-email user group(s):")
    for g in groups:
        print(f"  LOWER(email)={g[0]['email'].lower()}  ids={[r['id'] for r in g]}")
    print()
    for g in groups:
        rep = merge_group(g)
        print(f"  ✓ merged into id={rep['canonical_id']} ({rep['canonical_email']}):")
        print(f"      deleted {rep['deleted']} duplicate user row(s)")
        for tbl, n in rep["fks_rewritten"].items():
            if n:
                print(f"      rewrote {n:>5} FK(s) in {tbl}")
    # Also lowercase ANY user.email that still has uppercase, to be defensive.
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE users SET email = LOWER(email) WHERE email != LOWER(email)"
        )
        if cur.rowcount:
            print(f"  ✓ lowercased {cur.rowcount} additional email(s)")
        conn.commit()
    print("\nDone. Re-run audit to confirm:")
    print("  docker compose exec dashboard python -m scripts.audit_etl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
