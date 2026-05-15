"""Streamlit page-render smoke test for the single-page dashboard.

The dashboard is now one page: Overview hero/KPIs/chart + AI Tools tabs.
This test boots that page via AppTest under several filter combinations
and asserts no Python exception escapes to the user. Catches:
  - NameError ('_hs_note' not defined) — what we fixed before
  - Stale-state crashes when dropdown carries a value no longer in DB
  - SQL injection in clauses, type-coerce errors, etc.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO = Path(__file__).resolve().parent.parent
MAIN = REPO / "frontend" / "main.py"

SOURCE_COMBOS = [
    ("all", "all"),
    ("openai", "all"),
    ("openai", "Artem"),
    ("openai", "Humanoid"),
    ("anthropic", "all"),
    ("cursor", "all"),
    ("ghost-provider", "all"),  # stale state
]
PERIODS = ["Last 7 days", "Last 30 days", "Month to date"]


def _run(source: tuple[str, str], preset: str) -> AppTest:
    app = AppTest.from_file(str(MAIN), default_timeout=30)
    prov, org = source
    app.session_state["source"] = "all" if prov == "all" else (
        f"{prov}|{org}" if org and org != "all" else prov
    )
    app.session_state["organization"] = org or "all"
    app.session_state["provider"] = prov
    app.session_state["preset"] = preset
    app.session_state["api_key_id"] = None
    app.run()
    return app


def test_main_page_loads_default(tmp_db):
    """Single-page dashboard must boot with default filters."""
    app = AppTest.from_file(str(MAIN), default_timeout=30)
    app.run()
    assert not app.exception, f"main page raised: {[str(e) for e in app.exception]}"


@pytest.mark.parametrize("source", SOURCE_COMBOS)
def test_main_page_loads_with_source(tmp_db, source):
    app = _run(source, "Last 30 days")
    assert not app.exception, (
        f"main page with source={source} raised: {[str(e) for e in app.exception]}"
    )


@pytest.mark.parametrize("preset", PERIODS)
def test_main_page_with_period(tmp_db, preset):
    app = _run(("all", "all"), preset)
    assert not app.exception, f"main period={preset} raised: {app.exception}"
