"""HMND AIOps Dashboard — entry script.

Uses Streamlit's `st.navigation` to render a custom sidebar so the brand
sits ABOVE the page list and we can attach Material icons to every entry.
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
    initial_sidebar_state="expanded",
)
inject()

CFG = load_config()


def _bootstrap_db() -> None:
    init_schema()
    if (not DB_PATH.exists() or os.environ.get("HMND_FORCE_SEED") == "1") and CFG.demo_data:
        with st.spinner("Initialising demo dataset…"):
            seed()


_bootstrap_db()


# Brand sits at the very top of the sidebar, above the auto-rendered nav.
st.sidebar.markdown(
    """
    <div class="hmnd-brand">
        <div class="dot"></div>
        <div class="title">HUMANOID</div>
    </div>
    <div class="hmnd-brand-sub">AIOps Dashboard</div>
    """,
    unsafe_allow_html=True,
)


# Page registry. Each section lives in frontend/sections/* and renders its
# content as a normal Streamlit script (no st.set_page_config).
overview = st.Page("sections/overview.py",     title="Overview",         icon=":material/dashboard:", default=True)
costs    = st.Page("sections/costs.py",        title="Costs by People",  icon=":material/payments:")
seats    = st.Page("sections/seats.py",        title="Seats & Licenses", icon=":material/badge:")
devs     = st.Page("sections/developers.py",   title="Developer Usage",  icon=":material/code:")
keys     = st.Page("sections/api_keys.py",     title="API Keys",         icon=":material/key:")
models   = st.Page("sections/models.py",       title="Models",           icon=":material/smart_toy:")
alerts   = st.Page("sections/alerts.py",       title="Alerts",           icon=":material/notifications:")
settings = st.Page("sections/settings.py",     title="Settings",         icon=":material/settings:")

pages = [overview, costs, seats, devs, keys, models, alerts, settings]
if CFG.github_enabled:
    repos    = st.Page("sections/repositories.py", title="Repositories", icon=":material/folder:")
    pr_qual  = st.Page("sections/pr_quality.py",   title="PR Quality",   icon=":material/rule:")
    pages = [overview, costs, seats, devs, keys, repos, pr_qual, models, alerts, settings]

nav = st.navigation(pages)
nav.run()
