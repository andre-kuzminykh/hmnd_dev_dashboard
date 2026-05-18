"""F-30 · Internal consistency fixes per user audit.

Two specific bugs found by manual sweep of dashboard screenshots:

1. ChatGPT Users org branch SQL ignored api_key_id filter, so KPI
   Total spend (filtered by org+key) drifted from ChatGPT Users
   Total spend (filtered by org only).

2. Claude Top Models showed the JSON-rollup model spend at lifetime
   scale (~90 days) regardless of the user's Period filter. The
   number "Claude Opus 4.7 $23,662" would not change if Period went
   from 90d to 7d.

Tests:
  - test_fr_30_1_chatgpt_users_honours_api_key — both branches of the
    ChatGPT Users SQL must filter by api_key_id when one is provided.
  - test_fr_30_2_claude_top_models_scaled_to_period — Claude Top
    Models bars must scale by (period_anthropic_spend / json_rollup).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AI_TOOLS = ROOT / "frontend" / "sections" / "ai_tools.py"


@pytest.fixture(scope="module")
def source() -> str:
    return AI_TOOLS.read_text(encoding="utf-8")


# ── FR-30.1 — ChatGPT Users org branch must filter by api_key_id ────────────

def test_fr_30_1_chatgpt_users_honours_api_key(source: str):
    """The org-branch SQL in ChatGPT Users MUST include `(? IS NULL OR
    ue.api_key_id = ?)` so KPI Total spend and ChatGPT Users Total spend
    stay consistent when both org and key are selected.
    """
    # Narrow to the ChatGPT Users section first.
    cg_marker = "# ---- ChatGPT Users"
    cg_start = source.find(cg_marker)
    assert cg_start > 0, "ChatGPT Users marker not found"
    cg_end = source.find("# ---- ", cg_start + len(cg_marker))
    cg_section = source[cg_start:cg_end if cg_end > 0 else len(source)]
    # Inside the section, capture the full org branch INCLUDING the
    # `.fetchall()` line so the params tuple is also in the block.
    block_pat = re.compile(
        r"if f\.organization and f\.organization != \"all\":.*?\.fetchall\(\)",
        re.DOTALL,
    )
    m = block_pat.search(cg_section)
    assert m, "ChatGPT Users org branch not found in source"
    block = m.group(0)
    assert "AND (? IS NULL OR ue.api_key_id = ?)" in block, (
        "FR-30.1 violated: ChatGPT Users org branch SQL must filter by "
        "api_key_id — otherwise KPI total drifts vs ChatGPT Users total "
        "when both org and api_key are selected."
    )
    # And the params tuple must be (org, period, api_key_id, api_key_id).
    assert "f.api_key_id, f.api_key_id" in block, (
        "FR-30.1 violated: api_key_id placeholder must be bound twice "
        "(once for the NULL-check, once for the equality check)."
    )


# ── FR-30.2 — Claude Top Models scale to active period ──────────────────────

def test_fr_30_2_claude_top_models_scaled_to_period(source: str):
    """The Claude Top Models bars MUST scale the JSON-rollup model spend
    by (period_anthropic_spend / json_rollup_total) — otherwise a 7-day
    Period still shows "$23,662 Claude Opus 4.7" lifetime-scale.
    """
    # Find the Claude Top Models block.
    block_pat = re.compile(
        r"# ---- Claude Top Models.*?_bar_list\(\s*_top_anm",
        re.DOTALL,
    )
    m = block_pat.search(source)
    assert m, "Claude Top Models block not found"
    block = m.group(0)
    # Must compute a scale factor based on active anthropic spend / rollup.
    assert "_rollup_total" in block and "_scale" in block, (
        "FR-30.2 violated: Claude Top Models must compute a scale factor."
    )
    assert "_period_anth_spend" in block, (
        "FR-30.2 violated: scaling needs the in-period anthropic total "
        "(claude_v) as the numerator."
    )
    assert "_period_anth_spend / _rollup_total" in block or \
           re.search(r"_period_anth_spend\s*/\s*_rollup_total", block), (
        "FR-30.2 violated: scale = period_anth_spend / json_rollup_total"
    )
    # And the bar data must use the scaled values, not raw m['spend'].
    assert "float(m.get(\"spend\") or 0) * _scale" in block, (
        "FR-30.2 violated: bar `spend` must be raw × scale"
    )
