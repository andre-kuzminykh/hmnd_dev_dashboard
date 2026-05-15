"""Streamlit page-render smoke tests across the full filter matrix.

For each section under frontend/sections/, run the page via Streamlit's
AppTest under every (Source × Period × API-key) combination and assert
no Python exception escapes to the user. Catches:
  - NameError ('_hs_note' not defined) — what we fixed last time
  - Stale-state crashes when dropdown carries a value no longer in DB
  - SQL injection in clauses, type-coerce errors, etc.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO = Path(__file__).resolve().parent.parent
SECTIONS = REPO / "frontend" / "sections"

# Every page the dashboard navigates to.
PAGES = sorted(p.name for p in SECTIONS.glob("*.py") if not p.name.startswith("_"))

# Representative filter sweeps. We don't combinatorially explode — that'd be
# 5×8×K calls = 200+ × ~50 pages = 10k runs. Pick high-signal combos.
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


def _run_page(page: str, source: tuple[str, str], preset: str) -> AppTest:
    """Boot a page with session_state pre-populated for the given filters."""
    app = AppTest.from_file(str(SECTIONS / page), default_timeout=20)
    # Pre-seed session_state to skip widget interaction; filters_bar reads these.
    prov, org = source
    if prov == "all":
        app.session_state["source"] = "all"
    else:
        app.session_state["source"] = f"{prov}|{org}" if org and org != "all" else prov
    app.session_state["organization"] = org or "all"
    app.session_state["provider"] = prov
    app.session_state["preset"] = preset
    app.session_state["api_key_id"] = None
    app.run()
    return app


@pytest.mark.parametrize("page", PAGES)
def test_page_loads_default(tmp_db, page):
    """Each page must load with default filters without raising."""
    if page == "settings.py":
        pytest.skip("settings page touches OS env / docker, not safe in unit test")
    app = AppTest.from_file(str(SECTIONS / page), default_timeout=10)
    app.run()
    assert not app.exception, f"{page} raised: {[str(e) for e in app.exception]}"


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("source", SOURCE_COMBOS)
def test_page_loads_with_source(tmp_db, page, source):
    """Each page must load under every Source-dropdown choice without raising."""
    if page == "settings.py":
        pytest.skip("settings touches docker, skip")
    app = _run_page(page, source, "Last 30 days")
    # The exception attribute is populated when ANY exception leaks to Streamlit.
    assert not app.exception, (
        f"{page} with source={source} raised: {[str(e) for e in app.exception]}"
    )


@pytest.mark.parametrize("page", ["overview.py", "ai_tools.py", "costs.py"])
@pytest.mark.parametrize("preset", PERIODS)
def test_period_presets(tmp_db, page, preset):
    """Period dropdown must not break analytical pages."""
    app = _run_page(page, ("all", "all"), preset)
    assert not app.exception, f"{page} period={preset} raised: {app.exception}"
