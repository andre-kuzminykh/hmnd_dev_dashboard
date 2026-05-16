"""Find users that exist as multiple user_ids due to multiple email domains.

Background: HMND uses two email domains in practice:
  - @thehumanoid.ai (engineering / work email)
  - @skl.vc        (Sycamore investor / corporate email)

The same person logs in to Anthropic / Cursor / OpenAI under different
emails. Our loaders create distinct user_id per email (case-sensitive
UNIQUE on users.email), so a single human shows up as 2 rows.

Impact:
  - Top spenders list shows fragmented entries (e.g. 'atin' Anthropic
    only, 'anai@skl.vc' Cursor only).
  - Per-user 30d totals are split, understating true per-person spend.
  - Segments like 'AI_ACTIVE_BUT_NO_GIT' may be inflated because git
    authors use thehumanoid.ai while Cursor users use skl.vc → no match
    in the segment classifier.

This script finds those collisions WITHOUT mutating data — pure read.
After confirming the scope, run merge_dup_emails.py with extended logic
(separate next iteration) to merge.

Usage:
    docker compose exec -T dashboard python -m scripts.audit_identity_collisions
"""
from __future__ import annotations

import sys
from collections import defaultdict

from data.db import get_conn


def main() -> int:
    with get_conn() as conn:
        users = conn.execute(
            """SELECT u.id, LOWER(u.email) AS email, u.full_name,
                      COALESCE(ROUND(SUM(ue.cost_usd), 2), 0) AS spend
               FROM users u
               LEFT JOIN usage_events ue ON ue.user_id = u.id
               WHERE u.email IS NOT NULL AND u.email != ''
               GROUP BY u.id
               ORDER BY u.email"""
        ).fetchall()

    # Group by local-part (before @)
    by_local: dict[str, list[dict]] = defaultdict(list)
    for u in users:
        local = u["email"].split("@", 1)[0] if "@" in u["email"] else u["email"]
        by_local[local].append(dict(u))

    # Filter to local-parts seen with ≥ 2 distinct domains
    multi_domain = {
        lp: rows for lp, rows in by_local.items()
        if len({(r["email"].split("@", 1)[1] if "@" in r["email"] else "") for r in rows}) >= 2
    }

    if not multi_domain:
        print("No dual-domain identity collisions found.")
        return 0

    print(f"Found {len(multi_domain)} people existing under 2+ email domains:")
    print()
    print(f"  {'local-part':25s}  {'#rows':>5s}  {'total $':>10s}  identities")
    print(f"  {'-'*25}  {'-'*5}  {'-'*10}  {'-'*60}")
    total_split = 0
    total_spend_affected = 0.0
    for lp, rows in sorted(multi_domain.items(), key=lambda x: -sum(r["spend"] for r in x[1])):
        n = len(rows)
        s = sum(r["spend"] for r in rows)
        total_split += n
        total_spend_affected += s
        emails = ", ".join(
            f"{r['email']} (id={r['id']}, ${r['spend']:.0f})"
            for r in sorted(rows, key=lambda r: -r["spend"])
        )
        print(f"  {lp[:25]:25s}  {n:>5}  ${s:>8,.2f}  {emails}")

    print()
    print(f"  TOTAL: {len(multi_domain)} people split across {total_split} user_id rows")
    print(f"         ${total_spend_affected:,.2f} of spend is on these fragmented identities")

    # Also surface: how many distinct user.email rows have @skl.vc only,
    # @thehumanoid.ai only, vs both
    domains_per_local: dict[str, set] = {}
    for lp, rows in by_local.items():
        domains_per_local[lp] = {
            (r["email"].split("@", 1)[1] if "@" in r["email"] else "")
            for r in rows
        }
    both = sum(1 for lp, d in domains_per_local.items()
               if "thehumanoid.ai" in d and "skl.vc" in d)
    only_hmnd = sum(1 for lp, d in domains_per_local.items()
                    if d == {"thehumanoid.ai"})
    only_skl  = sum(1 for lp, d in domains_per_local.items()
                    if d == {"skl.vc"})
    print()
    print(f"  Identity by domain mix:")
    print(f"    {both:>3} local-parts have BOTH @thehumanoid.ai AND @skl.vc")
    print(f"    {only_hmnd:>3} local-parts have ONLY @thehumanoid.ai")
    print(f"    {only_skl:>3} local-parts have ONLY @skl.vc")
    print()
    print("If a person uses thehumanoid.ai in Anthropic but skl.vc in Cursor,")
    print("they show up TWICE in the dashboard with split spend per tool.")
    print()
    print("To merge: write a follow-up script that picks a canonical user_id")
    print("per local-part (lowest id wins) and rewrites all 10 FK tables")
    print("(like scripts/merge_dup_emails.py does for case-only dupes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
