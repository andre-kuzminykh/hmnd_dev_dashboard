"""Canonical user resolution across HMND email domains.

Pins the behaviour of data.sources._identity.resolve_canonical_user_id so
the dual-identity merge fix (Appendix A.10 of Report I) cannot silently
regress on the next sync.
"""
from __future__ import annotations

import pytest

from data.db import get_conn, init_schema
from data.sources._identity import resolve_canonical_user_id


@pytest.fixture()
def empty_db(tmp_path, monkeypatch):
    db = tmp_path / "identity.db"
    monkeypatch.setenv("HMND_DB_PATH", str(db))
    init_schema()
    yield db


def _emails_in_db() -> list[str]:
    with get_conn() as conn:
        return [r["email"] for r in conn.execute("SELECT email FROM users ORDER BY id").fetchall()]


def test_same_email_returns_same_id(empty_db):
    uid1 = resolve_canonical_user_id("foo@thehumanoid.ai", "Foo")
    uid2 = resolve_canonical_user_id("foo@thehumanoid.ai", "Foo")
    assert uid1 == uid2


def test_case_and_whitespace_normalized(empty_db):
    uid1 = resolve_canonical_user_id("Bar@thehumanoid.ai", "Bar")
    uid2 = resolve_canonical_user_id("  bar@thehumanoid.ai  ", "Bar")
    assert uid1 == uid2
    # only one user row created
    assert _emails_in_db() == ["bar@thehumanoid.ai"]


def test_hmnd_dual_domain_collapses_to_one_user(empty_db):
    """The Report I A.10 fix: same person under both HMND domains → one user."""
    uid_eng = resolve_canonical_user_id("alice@thehumanoid.ai", "Alice")
    uid_corp = resolve_canonical_user_id("alice@skl.vc", "Alice")
    assert uid_eng == uid_corp, "dual-domain identities should collapse"
    # users table still has only one row; alias table records the second email
    assert len(_emails_in_db()) == 1
    with get_conn() as conn:
        aliases = sorted(r["email"] for r in conn.execute("SELECT email FROM user_aliases").fetchall())
    assert aliases == ["alice@skl.vc", "alice@thehumanoid.ai"]


def test_dual_domain_in_reverse_order(empty_db):
    """The skl.vc account may arrive first (e.g. Cursor sync runs before Anthropic)."""
    uid_corp = resolve_canonical_user_id("bob@skl.vc", "Bob")
    uid_eng = resolve_canonical_user_id("bob@thehumanoid.ai", "Bob")
    assert uid_corp == uid_eng


def test_different_locals_stay_separate(empty_db):
    """Different humans should NOT collapse just because they share a domain."""
    uid_a = resolve_canonical_user_id("alice@thehumanoid.ai", "Alice")
    uid_b = resolve_canonical_user_id("bob@thehumanoid.ai", "Bob")
    assert uid_a != uid_b


def test_external_domain_never_merges(empty_db):
    """A vendor or partner with the same local-part shouldn't be folded into HMND."""
    uid_internal = resolve_canonical_user_id("ops@thehumanoid.ai", "HMND Ops")
    uid_external = resolve_canonical_user_id("ops@some-vendor.com", "Vendor Ops")
    assert uid_internal != uid_external


def test_name_upgrades_when_better(empty_db):
    """When the second-domain identity carries a real name, upgrade the user."""
    resolve_canonical_user_id("charlie@skl.vc", "")  # stub created first
    resolve_canonical_user_id("charlie@thehumanoid.ai", "Charlie Garcia")
    with get_conn() as conn:
        row = conn.execute("SELECT full_name FROM users WHERE email='charlie@skl.vc'").fetchone()
    assert row["full_name"] == "Charlie Garcia"


def test_alias_table_lookups_avoid_repeat_scans(empty_db):
    """After first dual-domain match, subsequent lookups go via user_aliases."""
    uid = resolve_canonical_user_id("dana@thehumanoid.ai", "Dana")
    resolve_canonical_user_id("dana@skl.vc", "Dana")  # registers alias
    # third lookup of the alias should still resolve to the same id
    uid_again = resolve_canonical_user_id("dana@skl.vc", "Dana")
    assert uid_again == uid


def test_env_override_for_domain_set(empty_db, monkeypatch):
    """HMND_IDENTITY_DOMAINS env var can extend / change the domain set."""
    monkeypatch.setenv("HMND_IDENTITY_DOMAINS", "thehumanoid.ai,skl.vc,future-co.io")
    uid1 = resolve_canonical_user_id("eve@thehumanoid.ai", "Eve")
    uid2 = resolve_canonical_user_id("eve@future-co.io", "Eve")
    assert uid1 == uid2
