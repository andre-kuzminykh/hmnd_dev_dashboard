"""Canonical user resolution across HMND email domains.

HMND people often appear under two email domains:
  - @thehumanoid.ai  — engineering / work email; primary in Anthropic + Git
  - @skl.vc          — Sycamore corporate email; primary in Cursor + OpenAI

Without unification, `INSERT OR IGNORE INTO users(email)` creates a separate
`user_id` for each domain, splitting one human's spend / activity / segment
classification across two rows. Surfaced by scripts/audit_identity_collisions.py
and patched once via scripts/merge_dual_domain_identities.py; this module
prevents the loaders from re-creating the split on the next sync.

Policy:
  1. Exact email match → use that user.
  2. If the incoming email is in a known HMND domain, look for an existing
     user with the same local-part in ANY known HMND domain → use that user
     (canonical), ALSO register the incoming email as an alias.
  3. Otherwise insert a new user.

Aliases are stored in user_aliases(user_id, email) so the next sync can find
canonical user from either email without re-checking domain-local-part rules.
"""
from __future__ import annotations

import os
from typing import Iterable

from data.db import get_conn


# Tunable via env if HMND ever adds a third domain. Default to the two
# we have today.
def _hmnd_domains() -> set[str]:
    raw = os.environ.get("HMND_IDENTITY_DOMAINS", "thehumanoid.ai,skl.vc")
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def _ensure_alias_table(conn) -> None:
    """Idempotent — also called by db.init_schema migrations."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_aliases (
            id         INTEGER PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            email      TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_user_aliases_user ON user_aliases(user_id)")


def _register_alias(conn, user_id: int, email: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO user_aliases(user_id, email) VALUES (?, ?)",
        (user_id, email),
    )


def resolve_canonical_user_id(email: str, name: str | None = None) -> int:
    """Return canonical user_id for `email`. Creates a new user only when no
    existing user (by exact email, alias, or HMND-domain local-part) matches.

    Side effects:
      - Updates users.full_name when a better (longer/non-empty) name is given.
      - Registers `email` in user_aliases so future lookups are O(1).

    Idempotent: calling twice with the same email returns the same id.
    """
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("email is required")
    local, _, domain = email.partition("@")
    domain = domain.lower()
    hmnd_domains = _hmnd_domains()

    with get_conn() as conn:
        _ensure_alias_table(conn)

        # 1. Exact email match — fastest, covers steady-state.
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            uid = row["id"]
            if name and len(name) > 1:
                conn.execute("UPDATE users SET full_name = ? WHERE id = ?", (name, uid))
            conn.commit()
            return uid

        # 2. Alias hit — covers post-merge re-syncs (the @skl.vc identity
        #    of a person already in users under @thehumanoid.ai).
        row = conn.execute(
            "SELECT user_id FROM user_aliases WHERE email = ?", (email,)
        ).fetchone()
        if row:
            uid = row["user_id"]
            if name and len(name) > 1:
                conn.execute(
                    "UPDATE users SET full_name = ? WHERE id = ? AND (full_name IS NULL OR full_name = '' OR length(full_name) < length(?))",
                    (name, uid, name),
                )
            conn.commit()
            return uid

        # 3. HMND-domain local-part match — covers the FIRST time a
        #    @skl.vc email arrives for someone who's already in users under
        #    @thehumanoid.ai (or vice versa).
        if domain in hmnd_domains:
            # Find existing users whose email is "<same local>@<some HMND domain>".
            # We can't use indexes for substring matching so this is a small linear
            # scan, but users table is bounded by team size and queried infrequently.
            placeholders = ",".join("?" * len(hmnd_domains))
            row = conn.execute(
                f"""SELECT id, full_name FROM users
                    WHERE lower(substr(email, 1, instr(email, '@') - 1)) = ?
                      AND lower(substr(email, instr(email, '@') + 1)) IN ({placeholders})
                    ORDER BY id LIMIT 1""",
                [local, *sorted(hmnd_domains)],
            ).fetchone()
            if row:
                canonical_uid = row["id"]
                _register_alias(conn, canonical_uid, email)
                # Improve name only if new one is meaningfully better.
                if name and len(name) > 1 and (
                    not row["full_name"] or len(row["full_name"]) < len(name)
                ):
                    conn.execute(
                        "UPDATE users SET full_name = ? WHERE id = ?",
                        (name, canonical_uid),
                    )
                conn.commit()
                return canonical_uid

        # 4. Brand-new user — insert.
        conn.execute(
            """INSERT INTO users(email, full_name, monthly_limit_usd, is_active)
               VALUES (?, ?, 200, 1)""",
            (email, name or local),
        )
        uid = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]
        _register_alias(conn, uid, email)  # self-alias for symmetric lookups
        conn.commit()
        return uid
