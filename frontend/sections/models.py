"""F-07 Models breakdown."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.services.models_svc import get_models_breakdown
from frontend.components import filters_bar, hero, section
from frontend.theme import NAVY, PROVIDER_COLORS

hero(
    "Models",
    'Compare <span class="accent">models</span>',
    "Which model burns most cash, who relies on it, where you can downgrade.",
)
filters = filters_bar()

rows = get_models_breakdown(filters)
if not rows:
    st.warning("No usage events.")
    st.stop()

df = pd.DataFrame(rows)
df["error_rate"] = df["error_rate"].apply(lambda v: "—" if v is None else f"{v}%")
df["main_users"] = df["main_users"].apply(lambda xs: ", ".join(xs[:3]) if xs else "—")
view = df[[
    "provider", "model", "requests", "tokens", "cost",
    "avg_latency", "error_rate", "main_users",
]].rename(columns={
    "provider": "Provider", "model": "Model", "requests": "Requests",
    "tokens": "Tokens", "cost": "Cost $", "avg_latency": "Avg latency, ms",
    "error_rate": "Error rate", "main_users": "Main users",
})
st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"), unsafe_allow_html=True)

section("Cost by model")
fig = px.bar(df, x="model", y="cost", color="provider",
             color_discrete_map=PROVIDER_COLORS)
fig.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                  margin=dict(l=10, r=10, t=10, b=10),
                  font=dict(family="Inter", color=NAVY),
                  xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#e8edf3"))
st.plotly_chart(fig, use_container_width=True)
