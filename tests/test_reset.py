"""Tests for scripts.reset.wipe()."""
from __future__ import annotations


def test_wipe_clears_every_table(tmp_db):
    """After wipe(), every analytical table must be empty."""
    from scripts.reset import TABLES_IN_DEPENDENCY_ORDER, wipe
    from data.db import get_conn

    # sanity: seed (called by tmp_db) put rows in at least these tables
    with get_conn() as conn:
        before = {
            t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            for t in TABLES_IN_DEPENDENCY_ORDER
        }
    assert any(v > 0 for v in before.values()), "seed produced no data — fixture broken?"

    wipe()

    with get_conn() as conn:
        after = {
            t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            for t in TABLES_IN_DEPENDENCY_ORDER
        }
    for t, n in after.items():
        assert n == 0, f"after wipe(), {t} still has {n} rows"


def test_wipe_is_idempotent(tmp_db):
    """Calling wipe() twice in a row is fine and returns 0 rows the 2nd time."""
    from scripts.reset import wipe
    wipe()
    second = wipe()
    # zero rows everywhere on the 2nd pass
    for table, n in second.items():
        if table.endswith("_error"):
            continue
        assert n == 0, f"{table}: {n}"
