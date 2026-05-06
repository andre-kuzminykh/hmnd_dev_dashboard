"""F-01 Executive Overview section."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.config import load_config
from backend.services.overview import get_daily_spend_series, get_overview_kpis
from frontend.components import filters_bar, fmt_int, fmt_money, fmt_pct, hero, kpi_row, section
from frontend.theme import ANTHROPIC, NAVY, OPENAI, PROVIDER_COLORS

CFG = load_config()

hero(
    "F-01 · Executive Overview",
    '<span class="accent">AIOps</span> Dashboard',
    "Who uses AI, how much it costs, how efficiently and how much AI-generated code lands in production.",
)
filters = filters_bar()

kpis = get_overview_kpis(filters)

kpi_row([
    {"label": "Total spend",  "value": fmt_money(kpis["total_spend"]),
     "delta": kpis["total_spend_delta"], "note": "vs prev period"},
    {"label": "Tokens in",    "value": fmt_int(kpis["tokens_in"]),
     "delta": kpis["tokens_in_delta"], "note": "input tokens"},
    {"label": "Tokens out",   "value": fmt_int(kpis["tokens_out"]),
     "delta": kpis["tokens_out_delta"], "note": "output tokens"},
    {"label": "Active users", "value": str(kpis["active_users"]),
     "delta": kpis["active_users_delta"], "note": "with activity in period"},
])
bottom = [
    {"label": "Seats used",     "value": str(kpis["seats_used"]),
     "delta": None, "note": "assigned seats"},
    {"label": "Cost per user", "value": fmt_money(kpis["cost_per_user"]),
     "delta": kpis["cost_per_user_delta"], "note": "average"},
    {"label": "Suspicious",    "value": str(kpis["suspicious_count"]),
     "delta": None, "note": "open alerts"},
]
if CFG.github_enabled:
    bottom.insert(2, {
        "label": "AI code share", "value": fmt_pct(kpis["ai_code_share"]),
        "delta": kpis["ai_code_share_delta"], "note": "merged AI lines / total",
    })
kpi_row(bottom)

section("Spend over time")
series = get_daily_spend_series(filters)
if series:
    df = pd.DataFrame(series)
    df["day"] = pd.to_datetime(df["day"])
    fig = px.area(
        df,
        x="day", y="cost", color="provider",
        color_discrete_map=PROVIDER_COLORS,
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
    st.info("No usage events in the selected window. Run a sync from Settings.")
