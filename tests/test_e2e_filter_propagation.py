"""End-to-end audit: simulate clicking through every Source × Period
combination on the dashboard via Streamlit AppTest, capture the rendered
KPI / breakdown values, and assert that filter narrowing is consistent
between the top KPI cards, AI Tools Overview tab, and the per-provider
tabs.

This is the 'protyk' (clicking-through) the user asked for — runs the
whole single-page app under each filter combo and verifies invariants.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO = Path(__file__).resolve().parent.parent
MAIN = REPO / "frontend" / "main.py"

SOURCES = [
    ("all", "all"),
    ("openai", "all"),
    ("openai", "Artem"),
    ("openai", "Humanoid"),
    ("anthropic", "all"),
    ("cursor", "all"),
]
PERIODS = ["Last 7 days", "Last 14 days", "Last 30 days", "Last 90 days"]


def _run(source: tuple[str, str], preset: str = "Last 30 days",
         api_key_id: int | None = None) -> AppTest:
    app = AppTest.from_file(str(MAIN), default_timeout=30)
    prov, org = source
    app.session_state["source"] = "all" if prov == "all" else (
        f"{prov}|{org}" if org and org != "all" else prov
    )
    app.session_state["organization"] = org or "all"
    app.session_state["provider"] = prov
    app.session_state["preset"] = preset
    app.session_state["api_key_id"] = api_key_id
    app.run()
    return app


def _markdown_text(app: AppTest) -> str:
    return "\n".join(getattr(e, "body", "") or "" for e in app.markdown)


def _money(s: str) -> float | None:
    """Pull '$X,YYY.ZZ' or '$N' out of a string, return float."""
    m = re.search(r"\$([\d,]+(?:\.\d+)?)", s)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


# ---------------------------------------------------------------------------
# 1. Page renders without exception under EVERY filter combo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("preset", PERIODS)
def test_no_exception_any_combo(tmp_db, source, preset):
    app = _run(source, preset)
    assert not app.exception, (
        f"source={source} preset={preset} raised: "
        f"{[str(e) for e in app.exception]}"
    )


# ---------------------------------------------------------------------------
# 2. AI Tools Overview tab respects Source filter
#    (When Source = openai, Spend Breakdown should NOT show Anthropic / Cursor)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source,expect_present,expect_absent", [
    (("openai", "all"),       ["ChatGPT"], ["Claude $1", "Cursor $1"]),
    (("openai", "Artem"),     ["ChatGPT"], ["Claude $1", "Cursor $1"]),
    (("openai", "Humanoid"),  ["ChatGPT"], ["Claude $1", "Cursor $1"]),
    (("anthropic", "all"),    ["Claude"],  ["ChatGPT $1", "Cursor $1"]),
    (("cursor", "all"),       ["Cursor"],  ["ChatGPT $1", "Claude $1"]),
])
def test_spend_breakdown_filtered_to_source(tmp_db, source, expect_present, expect_absent):
    """When Source narrows to one provider, the AI Tools Overview tab's
    Spend Breakdown card must zero out the other-provider rows.
    Spec: $0.00 / 0.0% on the unrelated tools.
    """
    app = _run(source)
    assert not app.exception, str(app.exception)
    body = _markdown_text(app)
    for token in expect_absent:
        # We accept the LABEL appearing (it does, e.g. 'Claude $0.00') but
        # NOT a non-zero $-amount tagged with that label.
        # Pattern: 'Claude $123' (any non-zero) should NOT appear.
        # We tolerate '$0', '$0.00', '$0.0%'.
        bad_pattern = token.replace("$1", r"\$\s*[1-9]")
        m = re.search(bad_pattern, body)
        assert not m, f"source={source}: unexpected non-zero '{token}' in body: ...{body[max(0, m.start()-20):m.end()+30]}..."


# ---------------------------------------------------------------------------
# 3. AI Tools Overview must SUM-MATCH the top-level KPI
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", SOURCES)
def test_overview_kpi_matches_ai_tools_breakdown(tmp_db, source):
    """Top KPI 'Total spend' should equal sum of the three tool cards in
    AI Tools / Overview tab. Both apply the same filters.
    """
    app = _run(source)
    body = _markdown_text(app)
    # Pull 'Total spend' value (first $X under Total spend label)
    m = re.search(r"Total spend.{0,200}?\$([\d,]+(?:\.\d+)?)", body, re.S)
    if not m:
        pytest.skip("no Total spend rendered")
    top_spend = float(m.group(1).replace(",", ""))
    # Pull AI Tools Overview tab "Total $X"
    m2 = re.search(r"Total\s+\$([\d,]+(?:\.\d+)?)", body)
    if not m2:
        pytest.skip("no AI Tools Total rendered")
    breakdown_total = float(m2.group(1).replace(",", ""))
    # Allow 5% tolerance for window-boundary drift between Overview KPI
    # (uses Filters.date_range) and AI Tools Overview (uses raw datetime).
    tol = max(top_spend * 0.05, 1.0)
    assert abs(top_spend - breakdown_total) <= tol, (
        f"source={source}: top KPI ${top_spend} vs AI Tools Total ${breakdown_total} (Δ > 5%)"
    )


# ---------------------------------------------------------------------------
# 4. Org-narrowed Source actually changes numbers
#    (Artem ≠ Humanoid; both ≤ all-openai)
# ---------------------------------------------------------------------------

def _seed_two_orgs(known_artem: float, known_humanoid: float) -> None:
    """Add OpenAI 'Artem' and 'Humanoid' orgs and one event each so the
    Source dropdown in filters_bar picks them up (otherwise it resets
    to 'all' when the source key isn't in DB).
    """
    from data.db import get_conn
    with get_conn() as conn:
        pid = conn.execute("SELECT id FROM providers WHERE name='openai'").fetchone()["id"]
        for label in ("Artem", "Humanoid"):
            conn.execute(
                "INSERT OR IGNORE INTO organizations(provider_id, label) VALUES(?, ?)",
                (pid, label),
            )
        a_id = conn.execute(
            "SELECT id FROM organizations WHERE provider_id=? AND label='Artem'", (pid,)
        ).fetchone()["id"]
        h_id = conn.execute(
            "SELECT id FROM organizations WHERE provider_id=? AND label='Humanoid'", (pid,)
        ).fetchone()["id"]
        uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
        mid = conn.execute(
            "SELECT id FROM models WHERE provider_id=? LIMIT 1", (pid,)
        ).fetchone()["id"]
        for org_id, cost in [(a_id, known_artem), (h_id, known_humanoid)]:
            conn.execute(
                """INSERT INTO usage_events(user_id, provider_id, model_id, organization_id,
                                             occurred_at, tokens_in, tokens_out, tokens_cached,
                                             cost_usd, is_error, purpose)
                   VALUES(?, ?, ?, ?, datetime('now', '-1 day'), 100, 50, 0, ?, 0, 'API')""",
                (uid, pid, mid, org_id, cost),
            )
        conn.commit()


def test_artem_humanoid_are_distinct(tmp_db):
    """Source=Artem and Source=Humanoid must return DIFFERENT total spend
    numbers — otherwise the org filter isn't doing anything.
    """
    _seed_two_orgs(known_artem=11.11, known_humanoid=22.22)
    artem = _run(("openai", "Artem"))
    humanoid = _run(("openai", "Humanoid"))
    a_body = _markdown_text(artem)
    h_body = _markdown_text(humanoid)
    a = float(re.search(r"Total spend.{0,200}?\$([\d,]+(?:\.\d+)?)", a_body, re.S).group(1).replace(",", ""))
    h = float(re.search(r"Total spend.{0,200}?\$([\d,]+(?:\.\d+)?)", h_body, re.S).group(1).replace(",", ""))
    assert a != h, f"Artem ${a} == Humanoid ${h} — org filter not honored"
    # Specifically: each should be the known value we seeded, not the sum
    # of both (= $33.33). Allow ±1 for window/rounding.
    assert abs(a - 11.11) < 1.0, f"Artem expected $11.11, got ${a}"
    assert abs(h - 22.22) < 1.0, f"Humanoid expected $22.22, got ${h}"


# ---------------------------------------------------------------------------
# 5. Period monotonicity (90d ≥ 30d ≥ 14d ≥ 7d total)
# ---------------------------------------------------------------------------

def test_period_monotone(tmp_db):
    spends = []
    for p in ["Last 7 days", "Last 14 days", "Last 30 days", "Last 90 days"]:
        app = _run(("all", "all"), p)
        body = _markdown_text(app)
        m = re.search(r"Total spend.{0,200}?\$([\d,]+(?:\.\d+)?)", body, re.S)
        spends.append(float(m.group(1).replace(",", "")) if m else 0)
    # 7 ≤ 14 ≤ 30 ≤ 90 (allowing equality + 1% slack)
    for i in range(len(spends) - 1):
        assert spends[i] <= spends[i + 1] * 1.01 + 0.5, (
            f"non-monotone: {spends[i]} > {spends[i+1]}"
        )


# ---------------------------------------------------------------------------
# 6. Cross-tool sections always show data even when Source narrowed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", SOURCES)
def test_top_spenders_panel_renders_under_any_source(tmp_db, source):
    """F-27 — Overview now shows a "High Spenders" block instead of the
    old "Top Spenders — All Tools" header. The block is cross-tool by
    design, so we just verify it renders without exception under any
    Source filter, with the High Spenders title present.
    """
    app = _run(source)
    assert not app.exception, str(app.exception)
    body = _markdown_text(app)
    assert ("High Spenders" in body or "no spend recorded" in body.lower()
            or "no users at or above" in body.lower()), (
        f"source={source}: 'High Spenders' block missing"
    )


# ---------------------------------------------------------------------------
# 7. Source filter HINT banners on incompatible tabs
# ---------------------------------------------------------------------------

@pytest.mark.skip(
    reason="F-20: ChatGPT-specific tab removed in the unified layout — "
           "OpenAI content now lives under Overview's `_show_openai` "
           "gating, which hides the section entirely when Source=Anthropic. "
           "No mismatch banner needed."
)
def test_chatgpt_tab_hint_on_anthropic_source(tmp_db):
    pass


@pytest.mark.skip(
    reason="F-20: Claude-Code tab removed in the unified layout — Anthropic "
           "events live under Overview's `_show_anthropic` gating, which "
           "hides the section entirely when Source=OpenAI."
)
def test_claude_code_tab_hint_on_openai_source(tmp_db):
    pass


# ---------------------------------------------------------------------------
# 8. Models tab respects Source filter
# ---------------------------------------------------------------------------

def test_models_tab_only_openai_when_source_openai(tmp_db):
    """Picking Source=openai|Artem must NOT show Anthropic or Cursor models
    in the Model Landscape table.
    """
    _seed_two_orgs(known_artem=10.0, known_humanoid=20.0)
    app = _run(("openai", "Artem"))
    body = _markdown_text(app)
    # Find the Model landscape section and check what providers appear
    # We expect 'ChatGPT' tool labels but no 'Chat + CC' (Anthropic) or
    # 'Cursor' tool labels in the landscape table.
    # The landscape rows look like '<td>ChatGPT</td>' or '<td>Chat + CC</td>'.
    landscape_section = body.split("Model landscape")[-1] if "Model landscape" in body else ""
    if not landscape_section:
        pytest.skip("Model landscape not in body")
    assert "Chat + CC" not in landscape_section, (
        "Source=Artem should NOT show 'Chat + CC' (Anthropic) in landscape"
    )
    assert ">Cursor<" not in landscape_section, (
        "Source=Artem should NOT show 'Cursor' tool rows in landscape"
    )
