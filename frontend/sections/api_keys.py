"""F-11 API Keys breakdown section."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.services.api_keys import get_api_keys_breakdown, get_orphan_usage
from frontend.components import badge, filters_bar, fmt_money, hero, kpi_row, section
from frontend.theme import ANTHROPIC, NAVY, OPENAI, PROVIDER_COLORS

hero(
    "F-11 · API Keys",
    'Spend per <span class="accent">API key</span>',
    "Which keys generate the most traffic and cost. Helps with rotation and cleanup.",
)
filters = filters_bar()

rows = get_api_keys_breakdown(filters)
orphan = get_orphan_usage(filters)

if not rows and not orphan["requests"]:
    st.info(
        "No API keys yet. After running a sync from Settings, OpenAI keys will be "
        "pulled via Admin API and listed here. Anthropic keys appear once admin "
        "API is connected."
    )
    st.stop()

df = pd.DataFrame(rows)
total_cost = float(df["cost"].sum()) if not df.empty else 0.0
total_requests = int(df["requests"].sum()) if not df.empty else 0
admin_count = int(df["is_admin"].sum()) if not df.empty else 0

kpi_row([
    {"label": "API keys",        "value": str(len(rows))},
    {"label": "Admin keys",      "value": str(admin_count)},
    {"label": "Tracked spend",   "value": fmt_money(total_cost)},
    {"label": "Tracked requests","value": f"{total_requests:,}"},
])

if not df.empty:
    df["admin_badge"] = df["is_admin"].apply(lambda x: badge("admin", "review") if x else "")
    df["last_used"] = pd.to_datetime(df["last_used"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M").fillna("—")
    view = df[[
        "name", "redacted", "provider", "owner",
        "requests", "tokens_in", "tokens_out", "cost", "last_used", "admin_badge",
    ]].rename(columns={
        "name": "Name", "redacted": "Key", "provider": "Provider",
        "owner": "Owner", "requests": "Requests",
        "tokens_in": "Tokens in", "tokens_out": "Tokens out", "cost": "Cost $",
        "last_used": "Last used", "admin_badge": "Type",
    })

    section("Breakdown")
    st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"), unsafe_allow_html=True)

    section("Spend by key")
    fig = px.bar(
        df.head(20),
        x="name", y="cost", color="provider",
        color_discrete_map=PROVIDER_COLORS,
        labels={"name": "API key", "cost": "Cost, $"},
    )
    fig.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(l=10, r=10, t=10, b=10),
                      font=dict(family="Inter", color=NAVY),
                      xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#e8edf3"))
    st.plotly_chart(fig, use_container_width=True)

if orphan["requests"]:
    section("Usage without an API key")
    st.markdown(
        f"""
        <div style="font-size:14px;color:#475569">
            {orphan['requests']:,} requests · {fmt_money(orphan['cost'])} ·
            {orphan['tokens_in']:,} in / {orphan['tokens_out']:,} out tokens were
            recorded without an API key (e.g. ChatGPT web sessions, batch jobs,
            or Anthropic mock data).
        </div>
        """,
        unsafe_allow_html=True,
    )
