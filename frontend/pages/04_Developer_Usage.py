"""F-04 Developer Usage."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.services.developers import get_developer_usage
from frontend.components import filters_bar, fmt_money, hero, section
from frontend.theme import BLUE, NAVY, inject, render_brand


st.set_page_config(page_title="Developer Usage · HMND", layout="wide")
inject()
render_brand()

hero(
    "F-04 · Developer Usage",
    'Активность <span class="accent">разработчиков</span>',
    "Сколько каждый разработчик тратит, сколько коммитит, какую долю AI-кода даёт.",
)
filters = filters_bar()

rows = get_developer_usage(filters)
if not rows:
    st.warning("No developer activity for filters.")
    st.stop()

df = pd.DataFrame(rows)
df["ai_code_pct_str"] = df["ai_code_pct"].apply(lambda v: "—" if v is None else f"{v}%")

view = df[[
    "user_name", "team", "ai_requests", "tokens", "cost",
    "repos_touched", "prs", "ai_code_pct_str", "review_issues",
]].rename(columns={
    "user_name": "Developer",
    "team": "Team",
    "ai_requests": "AI requests",
    "tokens": "Tokens",
    "cost": "Cost $",
    "repos_touched": "Repos",
    "prs": "PRs",
    "ai_code_pct_str": "AI code %",
    "review_issues": "Review issues",
})
st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"), unsafe_allow_html=True)

c1, c2 = st.columns(2)
with c1:
    section("Cost by developer")
    fig = px.bar(df.head(15), x="user_name", y="cost", color_discrete_sequence=[BLUE])
    fig.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(l=10, r=10, t=10, b=10),
                      font=dict(family="Inter", color=NAVY),
                      xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#e8edf3"))
    st.plotly_chart(fig, use_container_width=True)

with c2:
    section("AI usage vs code output")
    df_scatter = df.copy()
    df_scatter["ai_code_pct"] = df_scatter["ai_code_pct"].fillna(0)
    fig2 = px.scatter(
        df_scatter, x="cost", y="ai_code_pct",
        size="prs", hover_name="user_name",
        labels={"cost": "AI cost, $", "ai_code_pct": "AI code %"},
        color_discrete_sequence=[BLUE],
    )
    fig2.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                       margin=dict(l=10, r=10, t=10, b=10),
                       font=dict(family="Inter", color=NAVY))
    st.plotly_chart(fig2, use_container_width=True)
