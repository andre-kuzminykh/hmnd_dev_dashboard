"""HMND AIOps Dashboard — entry script.

Single-page layout: Overview hero + KPIs + spend chart on top, AI Tools
tabs (Overview / Claude Users / Claude Code / ChatGPT / Cursor / Models /
High Spenders) below. Sidebar is hidden — the dashboard is one page.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from backend.config import load_config
from data.db import DB_PATH, init_schema
from data.seed import seed
from frontend.theme import inject


st.set_page_config(
    page_title="HMND · AIOps",
    page_icon="https://i.ibb.co/nsfMVMGM/1.png",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject()

# Hide sidebar / nav entirely — this is a single-page dashboard.
st.markdown(
    """
    <style>
      [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
      header[data-testid="stHeader"] { display: none !important; }
      [data-testid="stAppViewContainer"] > .main { margin-left: 0 !important; }
      .block-container { padding-top: 1.5rem !important; max-width: 1280px; }
    </style>
    """,
    unsafe_allow_html=True,
)

CFG = load_config()


def _bootstrap_db() -> None:
    init_schema()
    if (not DB_PATH.exists() or os.environ.get("HMND_FORCE_SEED") == "1") and CFG.demo_data:
        with st.spinner("Initialising demo dataset…"):
            seed()


_bootstrap_db()

# Render the single page directly — no navigation, no sidebar.
# Brand/title is rendered inline by overview.py (logo + "AIOps Dashboard").
# overview.py renders the Executive Overview block (hero + freshness chips +
# filters bar + KPI cards + spend-over-time chart). Then ai_tools.py is
# sourced into the SAME globals dict, picking up the `filters` variable
# Overview just set, and renders the AI Tools tabbed section underneath.
shared_globals: dict = {"__name__": "__main__"}
for rel in ["frontend/sections/overview.py", "frontend/sections/ai_tools.py"]:
    path = ROOT / rel
    code = path.read_text(encoding="utf-8")
    # Drop 'from __future__' lines — exec() rejects future imports.
    code = "\n".join(l for l in code.splitlines() if not l.startswith("from __future__"))
    shared_globals["__file__"] = str(path)
    exec(compile(code, str(path), "exec"), shared_globals)
