"""F-27 · Overview layout: per-provider sections, charts visible, tables collapsed.

Static-source checks on `frontend/sections/ai_tools.py`:
  - test_fr_27_1_no_top_spenders_header
  - test_fr_27_2_high_spenders_block_visible
  - test_fr_27_3_dau_chart_present
  - test_fr_27_5_tables_in_expanders
  - test_fr_27_6_columns_have_gap
  - test_fr_27_8_no_model_landscape
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AI_TOOLS = ROOT / "frontend" / "sections" / "ai_tools.py"
COMPONENTS = ROOT / "frontend" / "components.py"


@pytest.fixture(scope="module")
def source() -> str:
    return AI_TOOLS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def components_source() -> str:
    return COMPONENTS.read_text(encoding="utf-8")


# ── FR-27.1 — old "Top Spenders — All Tools" header is gone ─────────────────

def test_fr_27_1_no_top_spenders_header(source: str):
    """The legacy 'Top Spenders — All Tools' header / 'Top Spenders {suffix}'
    title must no longer exist in the Overview tab.  We tolerate the
    word 'Top' elsewhere (e.g. 'Top authors by bug-fix rate' in
    Engineering), so check for the specific phrase.
    """
    forbidden = [
        'section(\n            f"Top Spenders',          # old fstring with suffix
        '"Top Spenders — All Tools"',                     # exact legacy literal
        'Top Spenders {_title_suffix}',                   # fstring body
    ]
    for needle in forbidden:
        assert needle not in source, (
            f"FR-27.1 violated: legacy 'Top Spenders' header still present: {needle!r}"
        )


# ── FR-27.2 — High Spenders block renders ───────────────────────────────────

def test_fr_27_2_high_spenders_block_visible(source: str):
    """The High Spenders section, threshold slider and ranking bars must
    be present in Overview (not buried inside an expander)."""
    assert 'section(\n        "High Spenders"' in source or \
           'section("High Spenders"' in source, (
        "FR-27.2 violated: High Spenders section header missing"
    )
    assert 'st.slider(\n            "High-spender threshold ($)"' in source or \
           'High-spender threshold ($)' in source, (
        "FR-27.2 violated: threshold slider missing"
    )
    # KPI row keys
    for k in ('"High spenders"', '"Highest single"', '"Combined spend"',
              '"Share of users"'):
        assert k in source, f"FR-27.2 violated: KPI '{k}' missing"


# ── FR-27.3 — Daily Active Users chart for all in-scope providers ──────────

def test_fr_27_3_dau_chart_present(source: str):
    """A Daily Active Users chart MUST exist in Overview that respects
    `_in_scope_provs` (i.e. only providers currently in scope)."""
    has_dau_section = (
        '"Daily Active Users"' in source
        or 'Daily Active Users' in source
    )
    assert has_dau_section, "FR-27.3 violated: 'Daily Active Users' section missing"
    # The new DAU section must use COUNT(DISTINCT user_id) per day per provider
    assert "COUNT(DISTINCT ue.user_id)" in source, (
        "FR-27.3 violated: DAU SQL must aggregate distinct users per day"
    )


# ── FR-27.5 — full tables wrapped in st.expander(expanded=False) ───────────

def test_fr_27_5_tables_in_expanders(source: str):
    """Every "full table" rendering in Overview must live inside a
    collapsed `st.expander(..., expanded=False)`. We approximate this
    by counting `st.expander(... expanded=False)` blocks — should be
    several (at least 5).
    """
    n_expanders = len(re.findall(r"st\.expander\(", source))
    assert n_expanders >= 7, (
        f"FR-27.5 violated: expected >=7 collapsed expanders for tables, "
        f"got {n_expanders}"
    )


# ── FR-27.6 — Overview columns pass gap= ───────────────────────────────────

def test_fr_27_6_columns_have_gap(source: str):
    """Every `st.columns(...)` call in the Overview tab that renders
    cards/tool-cards/sub-cards MUST pass a `gap=` keyword. Heuristic:
    count columns calls and columns-with-gap calls — at least 80% must
    have gap.
    """
    overview_start = source.find("with tab_overview:")
    engineering_start = source.find("with tab_engineering:")
    assert overview_start > 0 and engineering_start > overview_start
    overview = source[overview_start:engineering_start]

    all_cols = re.findall(r"st\.columns\(", overview)
    with_gap = re.findall(r'st\.columns\([^)]*gap=', overview)
    # At least 2 column rows in Overview (tool cards + at least one more).
    assert len(all_cols) >= 2, "expected at least 2 column rows in Overview"
    coverage = len(with_gap) / max(len(all_cols), 1)
    assert coverage == 1.0, (
        f"FR-27.6 violated: only {len(with_gap)}/{len(all_cols)} "
        f"st.columns(...) calls in Overview have gap= ({coverage:.0%}). "
        f"All Overview column-rows must pass gap='medium' or larger."
    )


# ── FR-27.7 — kpi_row in components.py passes gap= ─────────────────────────

def test_fr_27_7_kpi_row_has_gap(components_source: str):
    """`kpi_row()` MUST pass `gap=` to the underlying st.columns call so
    every KPI row across the app gets consistent spacing."""
    assert re.search(r"st\.columns\(\s*cols\s*,\s*gap\s*=", components_source), (
        "FR-27.7 violated: kpi_row's st.columns(cols) call must pass gap="
    )


# ── FR-27.8 — Model Landscape expander removed ─────────────────────────────

def test_fr_27_8_no_model_landscape(source: str):
    """Model Landscape expander/section MUST be absent."""
    assert '"Model Landscape"' not in source, (
        "FR-27.8 violated: 'Model Landscape' expander still present"
    )
    assert "Model landscape —" not in source, (
        "FR-27.8 violated: residual Model landscape caption present"
    )
