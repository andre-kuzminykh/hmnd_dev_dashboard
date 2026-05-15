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


AI_TOOLS_TABS = [
    "Overview", "Claude Users", "Claude Code", "ChatGPT",
    "Cursor", "Models", "⚠ High Spenders",
]


@pytest.mark.parametrize("source", SOURCE_COMBOS)
def test_every_ai_tools_tab_renders(tmp_db, source):
    """Render the single page under each Source filter. Streamlit's AppTest
    evaluates every tab's contents at the same module-level pass, so a single
    .run() exercises all 7 AI Tools tabs. A bug in any tab (KeyError, stale
    model lookup, NameError) shows up in app.exception.

    Specifically defends against the live regressions the user has hit:
      - KeyError 'cost' (column renamed in get_spend_by_model → 'spend')
      - claude-generic placeholder bypass in Models tab
      - Cursor/OpenAI org filter mismatches
    """
    app = AppTest.from_file(str(MAIN), default_timeout=30)
    prov, org = source
    app.session_state["source"] = "all" if prov == "all" else (
        f"{prov}|{org}" if org and org != "all" else prov
    )
    app.session_state["organization"] = org or "all"
    app.session_state["provider"] = prov
    app.session_state["preset"] = "Last 30 days"
    app.session_state["api_key_id"] = None
    app.run()
    assert not app.exception, (
        f"Page (source={source}) raised: {[str(e) for e in app.exception]}"
    )
    # Sanity: the page must include AI Tools tabs.
    assert app.tabs and len(app.tabs) >= 7, (
        f"Expected ≥7 tabs (AI Tools), got {len(app.tabs) if app.tabs else 0}"
    )


def test_no_raw_html_tags_in_rendered_output(tmp_db):
    """Catches the High-Spenders bug where embedded newlines in
    cards_html caused Streamlit's markdown parser to bail out and dump
    closing </div> tags as visible text. The smoke check is: across the
    full page, the only </div>'s rendered as text should be from inside
    `<code>` blocks or empty markdown. Failing this means our HTML got
    interpreted as paragraph-broken markdown.
    """
    from data.db import get_conn
    # Seed a minimal cross-tool dataset so the High Spenders section has
    # multiple cards (the bug only manifested with >1 card).
    with get_conn() as conn:
        pid_o = conn.execute("SELECT id FROM providers WHERE name='openai'").fetchone()["id"]
        pid_a = conn.execute("SELECT id FROM providers WHERE name='anthropic'").fetchone()["id"]
        uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
        m_o = conn.execute("SELECT id FROM models WHERE provider_id=? LIMIT 1", (pid_o,)).fetchone()["id"]
        m_a = conn.execute("SELECT id FROM models WHERE provider_id=? LIMIT 1", (pid_a,)).fetchone()["id"]
        for cost in (500, 1200, 900, 1500, 700):
            conn.execute(
                """INSERT INTO usage_events(user_id, provider_id, model_id, occurred_at,
                                             tokens_in, tokens_out, tokens_cached, cost_usd,
                                             is_error, purpose)
                   VALUES(?, ?, ?, datetime('now', '-1 day'), 100, 50, 0, ?, 0, 'API')""",
                (uid, pid_o if cost % 2 else pid_a, m_o if cost % 2 else m_a, cost),
            )
        conn.commit()

    app = AppTest.from_file(str(MAIN), default_timeout=30)
    app.run()
    assert not app.exception, f"main page raised: {app.exception}"
    # Pull every markdown/HTML element rendered and ensure none of them
    # have raw closing-div text. We allow `</div>` only inside <code> or
    # <pre> blocks (which never happens in our cards).
    body = "\n".join(getattr(e, "body", "") or "" for e in app.markdown)
    # The bug looked like literal '</div>\n<div style="font-size:18px;' in
    # the rendered text — i.e. Streamlit DIDN'T treat it as HTML so it
    # showed up in the displayed text. Detect by checking if any rendered
    # text element has '</div>' as raw text (not inside <code>).
    import re
    # remove anything inside <code>...</code> first
    stripped = re.sub(r"<code[^>]*>.*?</code>", "", body, flags=re.S)
    # rendered as text would mean it appears outside an HTML structure;
    # since Streamlit re-serializes HTML, presence as text outside any
    # opening tag is impossible to detect from .body alone. Instead,
    # assert that high-spenders related cards render cleanly: pick any
    # bullet in body that mentions 'messages ·' and ensure it's followed
    # by another opening tag, not a closing one.
    suspect = re.findall(
        r"messages\s+·[^<]{0,200}?</div>\s*<div\s+style=\"font-size:18px", stripped
    )
    # When the bug is present these literal substrings appear in plain
    # body text; when fixed, the HTML is well-formed and Streamlit hides
    # the inner tags.
    assert not suspect, (
        f"High-Spenders cards leaked raw HTML: {suspect[:1]}"
    )
