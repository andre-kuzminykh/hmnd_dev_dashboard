"""F-04 Developer Usage section."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.config import load_config
from backend.services.developers import get_developer_usage
from frontend.components import filters_bar, hero, section
from frontend.theme import BLUE, NAVY

CFG = load_config()

hero(
    "F-04 · Developer Usage",
    'Activity of <span class="accent">developers</span>',
    "How much each developer spends, how active they are and what share of code is AI-generated.",
)
filters = filters_bar()

rows = get_developer_usage(filters)
if not rows:
    st.warning("No developer activity for filters.")
    st.stop()

df = pd.DataFrame(rows)
df["ai_code_pct_str"] = df["ai_code_pct"].apply(lambda v: "—" if v is None else f"{v}%")

base_cols = ["user_name", "team", "ai_requests", "tokens", "cost"]
gh_cols = ["repos_touched", "prs", "ai_code_pct_str", "review_issues"]
cols_order = base_cols + (gh_cols if CFG.github_enabled else [])

rename = {
    "user_name": "Developer", "team": "Team",
    "ai_requests": "AI requests", "tokens": "Tokens", "cost": "Cost $",
    "repos_touched": "Repos", "prs": "PRs",
    "ai_code_pct_str": "AI code %", "review_issues": "Review issues",
}
view = df[cols_order].rename(columns=rename)
st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"), unsafe_allow_html=True)

if not CFG.github_enabled:
    st.caption("GitHub-related columns (repos, PRs, AI code %) are hidden — connect GitHub in Settings.")

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
    if CFG.github_enabled:
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
    else:
        section("Tokens by developer")
        fig3 = px.bar(df.head(15), x="user_name", y="tokens", color_discrete_sequence=[BLUE])
        fig3.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                           margin=dict(l=10, r=10, t=10, b=10),
                           font=dict(family="Inter", color=NAVY),
                           xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#e8edf3"))
        st.plotly_chart(fig3, use_container_width=True)
