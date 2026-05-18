"""One-off identity merge: rename `Dr. Klingensmith` → `Matt Klingensmith`.

Background: audit_report_full found that user id=5 was stored as
'Dr. Klingensmith' (OpenAI display name) while the CEO report
references him as 'Matt Klingensmith' (Slack / Git name). All other
data (spend, events) matches between report and DB — only the
display name disagrees.

This script is idempotent — it only updates when the current name
is still 'Dr. Klingensmith'. Safe to re-run.

Usage on the VM:
    docker compose exec dashboard python -m scripts.merge_matt_klingensmith
"""
from __future__ import annotations

import sys

from data.db import get_conn

USER_ID = 5
EXPECTED_OLD = "Dr. Klingensmith"
NEW = "Matt Klingensmith"


def main() -> int:
    with get_conn() as c:
        row = c.execute(
            "SELECT id, full_name, email FROM users WHERE id=?",
            (USER_ID,),
        ).fetchone()
        if not row:
            print(f"  ???  user id={USER_ID} not found — nothing to merge.")
            return 1
        current = row["full_name"]
        email = row["email"]
        print(f"  Current: id={USER_ID} full_name='{current}' email='{email}'")

        if current == NEW:
            print(f"  Already '{NEW}' — nothing to do.")
            return 0

        if current != EXPECTED_OLD:
            print(f"  ???  Refusing to update: expected '{EXPECTED_OLD}', "
                  f"got '{current}'. If this is intentional, edit "
                  f"EXPECTED_OLD in this script.")
            return 1

        c.execute("UPDATE users SET full_name=? WHERE id=?",
                  (NEW, USER_ID))
        c.commit()

        after = c.execute(
            "SELECT full_name FROM users WHERE id=?", (USER_ID,)
        ).fetchone()["full_name"]
        print(f"  Updated: id={USER_ID} full_name='{after}'")
        return 0


if __name__ == "__main__":
    sys.exit(main())
