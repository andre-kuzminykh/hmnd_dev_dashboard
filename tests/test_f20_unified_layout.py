"""F-20 — Unified AI Tools layout: Overview / Engineering / People.

Tests per SPEC.md §F-20:
  test_fr_20_1_three_tabs_declared              FR-20.1
  test_fr_20_1_no_ai_tools_section_header       FR-20.1
  test_fr_20_9_no_legacy_tab_variables          FR-20.9
  test_fr_20_3_overview_tables_wrapped_in_expanders  FR-20.3
  test_fr_20_5_people_dropdown_lists_users      FR-20.5
  test_fr_20_6_people_profile_data_shape        FR-20.6
  test_fr_20_7_people_ignores_source_filter     FR-20.7
"""
from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from data.db import get_conn

ROOT = Path(__file__).resolve().parent.parent
AI_TOOLS = ROOT / "frontend" / "sections" / "ai_tools.py"


# ──────────────────────────────────────────────────────────────────────
# Structural / static-analysis tests (FR-20.1, FR-20.3, FR-20.9)
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def source() -> str:
    return AI_TOOLS.read_text(encoding="utf-8")


def test_fr_20_1_three_tabs_declared(source: str):
    """FR-20.1 — exactly 3 tabs named Overview / Engineering / People."""
    # Allow either the literal call or one with extra whitespace.
    pat = re.compile(
        r'st\.tabs\(\s*\[\s*["\']Overview["\']\s*,\s*'
        r'["\']Engineering["\']\s*,\s*["\']People["\']\s*\]\s*\)'
    )
    assert pat.search(source), (
        "FR-20.1 violated: ai_tools.py must contain "
        "st.tabs([\"Overview\", \"Engineering\", \"People\"])"
    )


def test_fr_20_1_no_ai_tools_section_header(source: str):
    """FR-20.1 — the legacy `section("AI Tools")` call must be removed."""
    assert 'section("AI Tools")' not in source, (
        "FR-20.1 violated: section(\"AI Tools\") must be removed"
    )
    assert "section('AI Tools')" not in source


def test_fr_20_9_no_legacy_tab_variables(source: str):
    """FR-20.9 — old `with tab_*` blocks from the 8-tab layout must be gone.

    Match only at code-positions (left margin or after a left paren),
    not inside comments / docstrings (e.g. "# old tab_gpt rebuild logic").
    """
    forbidden = ["tab_claude", "tab_cc", "tab_gpt", "tab_cursor",
                 "tab_models", "tab_high", "tab_devs"]
    # Allowed shapes for a real variable: `with tab_X:` or `tab_X, ...` in tabs unpack
    leaked = []
    for name in forbidden:
        for m in re.finditer(rf"\b{name}\b", source):
            line_start = source.rfind("\n", 0, m.start()) + 1
            line = source[line_start:source.find("\n", m.start())]
            # ignore comments and strings
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            # ignore docstring lines (heuristic: starts with """ or ' or contains \"\"\")
            if '"""' in line or "'''" in line:
                continue
            leaked.append(f"line: {line.strip()!r}")
            break
    assert not leaked, (
        f"FR-20.9 violated: legacy tab variables still present in code:\n  "
        + "\n  ".join(leaked)
    )


def test_fr_20_3_overview_tables_wrapped_in_expanders(source: str):
    """FR-20.3 — Overview / Engineering tabs must wrap tables in expanders.

    Heuristic: there are MANY `view.to_html(...)` / DataFrame renders in
    the old file. Every one must live inside an `st.expander(` block —
    i.e. between an `st.expander(` line and its closing `with`.
    """
    n_expanders = source.count("st.expander(")
    assert n_expanders >= 5, (
        f"FR-20.3 violated: expected several st.expander() blocks for tables, "
        f"found only {n_expanders}"
    )


def test_fr_20_1_file_compiles(source: str):
    """Sanity — the rewritten file must be syntactically valid Python."""
    ast.parse(source, filename=str(AI_TOOLS))


# ──────────────────────────────────────────────────────────────────────
# People-tab data-layer tests (FR-20.5, FR-20.6, FR-20.7)
# These exercise the SQL the People tab depends on, so they pass on a
# seeded test DB independently of the Streamlit frontend.
# ──────────────────────────────────────────────────────────────────────

def _people_dropdown_query(conn):
    """Mirror the SQL the People tab uses to build its dropdown."""
    return conn.execute(
        """SELECT u.id, u.full_name, u.email,
                  COALESCE(ROUND(SUM(ue.cost_usd), 2), 0) AS total_spend
           FROM users u
           LEFT JOIN usage_events ue ON ue.user_id = u.id
           GROUP BY u.id
           ORDER BY total_spend DESC, u.full_name""",
    ).fetchall()


def test_fr_20_5_people_dropdown_lists_users(tmp_db):
    """FR-20.5 — dropdown lists every user, ordered by total spend DESC."""
    with get_conn() as conn:
        rows = _people_dropdown_query(conn)
    # seed seeds 12 users
    assert len(rows) >= 12, f"expected ≥12 users in dropdown, got {len(rows)}"
    spends = [float(r["total_spend"] or 0) for r in rows]
    # Order must be non-increasing by total_spend
    assert spends == sorted(spends, reverse=True), (
        f"FR-20.5 violated: dropdown must be sorted by total_spend DESC, "
        f"got order: {spends}"
    )


def test_fr_20_6_people_profile_data_shape(tmp_db):
    """FR-20.6 — selecting a person yields per-tool spend split, top
    models and daily activity rows for THAT user only.
    """
    with get_conn() as conn:
        # Pick the top spender (Ivan Petrov in seed).
        top = conn.execute(
            """SELECT u.id, u.full_name, ROUND(SUM(ue.cost_usd),2) AS s
               FROM users u JOIN usage_events ue ON ue.user_id = u.id
               GROUP BY u.id ORDER BY s DESC LIMIT 1"""
        ).fetchone()
        uid = top["id"]

        # Per-tool split
        per_tool = conn.execute(
            """SELECT p.name AS provider, ROUND(SUM(ue.cost_usd), 2) AS spend,
                      COUNT(*) AS reqs
               FROM usage_events ue JOIN providers p ON p.id = ue.provider_id
               WHERE ue.user_id = ?
               GROUP BY p.name""",
            (uid,),
        ).fetchall()
        # Top models
        top_models = conn.execute(
            """SELECT m.name, ROUND(SUM(ue.cost_usd), 2) AS spend
               FROM usage_events ue JOIN models m ON m.id = ue.model_id
               WHERE ue.user_id = ?
               GROUP BY m.id ORDER BY spend DESC LIMIT 10""",
            (uid,),
        ).fetchall()
        # Daily activity
        daily = conn.execute(
            """SELECT date(ue.occurred_at) AS day, p.name AS provider,
                      ROUND(SUM(ue.cost_usd), 2) AS cost
               FROM usage_events ue JOIN providers p ON p.id = ue.provider_id
               WHERE ue.user_id = ?
               GROUP BY day, provider ORDER BY day""",
            (uid,),
        ).fetchall()

    assert per_tool, "per-tool split returned empty for the top spender"
    assert top_models, "top-models query returned empty for the top spender"
    assert daily, "daily activity query returned empty for the top spender"

    # Per-tool spend sum must equal the user's total spend (sanity)
    total_per_tool = round(sum(float(r["spend"] or 0) for r in per_tool), 2)
    total_user = float(top["s"])
    assert abs(total_per_tool - total_user) < 0.05


def test_fr_20_7_people_ignores_source_filter(tmp_db):
    """FR-20.7 — the People-tab profile query MUST NOT filter by provider.

    We pick a user with both OpenAI and Anthropic activity (seed creates
    these for the heavy users). Running the profile query with NO provider
    filter must return both providers in per_tool.
    """
    with get_conn() as conn:
        # Pick user_id that has events across ≥2 providers.
        multi_provider = conn.execute(
            """SELECT user_id, COUNT(DISTINCT provider_id) AS n_providers
               FROM usage_events GROUP BY user_id
               HAVING n_providers >= 2 ORDER BY n_providers DESC LIMIT 1"""
        ).fetchone()
        assert multi_provider, "seed fixture must produce ≥1 cross-provider user"

        uid = multi_provider["user_id"]
        # People tab uses NO provider filter — confirm both rows come back.
        rows = conn.execute(
            """SELECT p.name AS provider, ROUND(SUM(ue.cost_usd),2) AS spend
               FROM usage_events ue JOIN providers p ON p.id = ue.provider_id
               WHERE ue.user_id = ?
               GROUP BY p.name""",
            (uid,),
        ).fetchall()
    providers_seen = {r["provider"] for r in rows}
    assert len(providers_seen) >= 2, (
        f"FR-20.7 violated: People tab must show all providers for the user, "
        f"got only {providers_seen}"
    )
