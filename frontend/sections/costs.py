"""F-02 Costs by People section."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.services.costs import detect_spend_spikes, get_costs_by_user, heatmap_user_day
from frontend.components import badge, filters_bar, hero, section
from frontend.theme import ANTHROPIC, BLUE, NAVY, OPENAI, PROVIDER_COLORS

hero(
    "F-02 · Costs by People",
    'Spend per <span class="accent">person</span>',
    "Find outliers, who burns most tokens, who hits monthly limits.",
)
filters = filters_bar()
rows = get_costs_by_user(filters)
spikes = {s["user_id"] for s in detect_spend_spikes()}

if not rows:
    st.warning("No data for selected filters.")
    st.stop()

df = pd.DataFrame(rows)
df["models"] = df["models"].apply(lambda xs: ", ".join(xs[:3]))
df["limit_badge"] = df["limit_status"].apply(lambda s: badge(s, s))
df["spike"] = df["user_id"].apply(lambda uid: badge("spike", "high") if uid in spikes else "")
df["last_activity"] = pd.to_datetime(df["last_activity"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")

view = df[[
    "user_name", "team", "cost_openai", "cost_anthropic", "cost_total",
    "tokens_in", "tokens_out", "models", "last_activity", "limit_badge", "spike",
]].rename(columns={
    "user_name": "User", "team": "Team",
    "cost_openai": "OpenAI $", "cost_anthropic": "Anthropic $", "cost_total": "Total $",
    "tokens_in": "Tokens in", "tokens_out": "Tokens out",
    "models": "Models", "last_activity": "Last activity",
    "limit_badge": "Limit", "spike": "Anomaly",
})

section("Breakdown")
st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"), unsafe_allow_html=True)

c1, c2 = st.columns(2)
with c1:
    section("Cost by user")
    fig = px.bar(
        df.head(15), x="user_name", y="cost_total",
        labels={"user_name": "User", "cost_total": "Cost, $"},
        color_discrete_sequence=[BLUE],
    )
    fig.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(l=10, r=10, t=10, b=10),
                      font=dict(family="Inter", color=NAVY),
                      xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#e8edf3"))
    st.plotly_chart(fig, use_container_width=True)

with c2:
    section("OpenAI vs Anthropic")
    long_df = df.melt(
        id_vars="user_name",
        value_vars=["cost_openai", "cost_anthropic"],
        var_name="provider", value_name="cost",
    )
    long_df["provider"] = long_df["provider"].map(
        {"cost_openai": "OpenAI", "cost_anthropic": "Anthropic"}
    )
    fig2 = px.bar(
        long_df.head(30), x="user_name", y="cost", color="provider", barmode="stack",
        color_discrete_map={"OpenAI": OPENAI, "Anthropic": ANTHROPIC},
    )
    fig2.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                       margin=dict(l=10, r=10, t=10, b=10),
                       font=dict(family="Inter", color=NAVY),
                       xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#e8edf3"))
    st.plotly_chart(fig2, use_container_width=True)

section("Heatmap · activity by user × day")
heat = heatmap_user_day(filters)
if heat:
    h = pd.DataFrame(heat)
    h["day"] = pd.to_datetime(h["day"])
    pivot = h.pivot_table(index="user_name", columns="day", values="tokens", fill_value=0)
    fig3 = px.imshow(
        pivot, aspect="auto",
        color_continuous_scale=[(0, "#f8fafc"), (1, BLUE)],
        labels=dict(color="tokens"),
    )
    fig3.update_layout(margin=dict(l=10, r=10, t=10, b=10),
                       font=dict(family="Inter", color=NAVY))
    st.plotly_chart(fig3, use_container_width=True)
