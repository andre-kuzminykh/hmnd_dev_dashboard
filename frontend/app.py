"""Entry point — F-01 Executive Overview."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.services.overview import get_overview_kpis, get_daily_spend_series
from data.db import DB_PATH, init_schema
from data.seed import seed
from frontend.components import (
    filters_bar, fmt_int, fmt_money, fmt_pct, hero, kpi_row, section,
)
from frontend.theme import BLUE, NAVY, inject, render_brand


st.set_page_config(
    page_title="HMND · AI Governance",
    page_icon="https://i.ibb.co/nsfMVMGM/1.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject()
render_brand()


def _bootstrap_db():
    if not DB_PATH.exists() or os.environ.get("HMND_FORCE_SEED") == "1":
        with st.spinner("Initialising demo dataset…"):
            seed()
    else:
        init_schema()


_bootstrap_db()


hero(
    "F-01 · Executive Overview",
    'AI <span class="accent">Governance</span> Dashboard',
    "Кто использует ИИ, сколько это стоит, насколько эффективно и сколько AI-кода реально попадает в production.",
)

filters = filters_bar()
kpis = get_overview_kpis(filters)


# FR-01.1.1.4 — 7 видимых KPI-карточек (suspicious_count выводим в нижнем ряду)
kpi_row([
    {"label": "Total spend",   "value": fmt_money(kpis["total_spend"]),
     "delta": kpis["total_spend_delta"], "note": "vs prev period"},
    {"label": "Tokens in",     "value": fmt_int(kpis["tokens_in"]),
     "delta": kpis["tokens_in_delta"], "note": "input tokens"},
    {"label": "Tokens out",    "value": fmt_int(kpis["tokens_out"]),
     "delta": kpis["tokens_out_delta"], "note": "output tokens"},
    {"label": "Active users",  "value": str(kpis["active_users"]),
     "delta": kpis["active_users_delta"], "note": "with activity in period"},
])
kpi_row([
    {"label": "Seats used",       "value": str(kpis["seats_used"]),
     "delta": None, "note": "assigned seats"},
    {"label": "Cost per user",    "value": fmt_money(kpis["cost_per_user"]),
     "delta": kpis["cost_per_user_delta"], "note": "average"},
    {"label": "AI code share",    "value": fmt_pct(kpis["ai_code_share"]),
     "delta": kpis["ai_code_share_delta"], "note": "merged AI lines / total"},
    {"label": "Suspicious",       "value": str(kpis["suspicious_count"]),
     "delta": None, "note": "open alerts"},
])

# Время & провайдер
section("Spend over time")
series = get_daily_spend_series(filters)
if series:
    df = pd.DataFrame(series)
    df["day"] = pd.to_datetime(df["day"])
    fig = px.area(
        df,
        x="day", y="cost", color="provider",
        color_discrete_map={"openai": "#10b981", "anthropic": BLUE},
    )
    fig.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=10, r=10, t=10, b=10),
        legend_title_text="",
        font=dict(family="Inter", color=NAVY),
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor="#e8edf3", title="$ per day"),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No usage events in the selected window. Run the seed script.")

st.markdown(
    f"""
    <div style="margin-top:8px;font-size:12px;color:#64748b">
        Data source: <code>{DB_PATH.name}</code> · Filters cached per session ·
        See <code>docs/SPEC.md</code> for feature → requirement → test mapping.
    </div>
    """,
    unsafe_allow_html=True,
)
