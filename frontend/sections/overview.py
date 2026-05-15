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
    "Executive Overview",
    '<span class="accent">AIOps</span> Dashboard',
    "Who uses AI, how much it costs, how efficiently and how much AI-generated code lands in production.",
)
filters = filters_bar()

kpis = get_overview_kpis(filters)

# When the user filters to Anthropic and we have no usage events for it
# (no admin API key wired up), the OpenAI-shaped Overview gives all zeros.
# Surface where Claude data actually lives instead of leaving the user
# staring at $0.
if filters.provider == "anthropic" and kpis["total_spend"] == 0 and kpis["active_users"] == 0:
    st.markdown(
        """
        <div style="
            border:1px solid #c7d2fe; border-radius:14px; padding:18px 22px;
            background:#f5f3ff; color:#3730a3; margin: 6px 0 12px 0;
            font-size:14px; line-height:1.5;
        ">
            <b>Anthropic spend isn't tracked here.</b>
            We don't have an Anthropic Admin API key, so usage_events has
            no rows for this provider. Claude usage in your team comes from
            the Cursor CSV exports — open
            <b>AI Tools → Claude Users</b> for the leaderboard, or
            <b>AI Tools → Cursor</b> for team-wide model usage and DAU.
        </div>
        """,
        unsafe_allow_html=True,
    )

reported = kpis.get("reported_total")
total_note = "vs prev period"
if reported is not None and kpis["total_spend"]:
    diff_pct = (kpis["total_spend"] - reported) / reported * 100 if reported else 0
    total_note = f"reported by provider: {fmt_money(reported)}  ·  Δ {diff_pct:+.1f}%"

cached_note = (
    f"+ {fmt_int(kpis['tokens_cached'])} cached"
    if kpis.get("tokens_cached") else "billable (uncached)"
)
kpi_row([
    {"label": "Total spend",  "value": fmt_money(kpis["total_spend"]),
     "delta": kpis["total_spend_delta"], "note": total_note},
    {"label": "Tokens in",    "value": fmt_int(kpis["tokens_in"]),
     "delta": kpis["tokens_in_delta"], "note": cached_note},
    {"label": "Tokens out",   "value": fmt_int(kpis["tokens_out"]),
     "delta": kpis["tokens_out_delta"], "note": "output tokens"},
    {"label": "Active users", "value": str(kpis["active_users"]),
     "delta": kpis["active_users_delta"], "note": "with activity in period"},
])
if CFG.github_enabled:
    kpi_row([{
        "label": "AI code share", "value": fmt_pct(kpis["ai_code_share"]),
        "delta": kpis["ai_code_share_delta"], "note": "merged AI lines / total",
    }])

section("Spend over time")
series = get_daily_spend_series(filters)
if series:
    from frontend.components import PROVIDER_DISPLAY
    df = pd.DataFrame(series)
    df["day"] = pd.to_datetime(df["day"])
    df["provider"] = df["provider"].map(lambda n: PROVIDER_DISPLAY.get(n, n.capitalize()))
    # Re-key colour map to display names so the legend & colours stay aligned.
    display_colors = {
        PROVIDER_DISPLAY.get(k, k.capitalize()): v for k, v in PROVIDER_COLORS.items()
    }
    fig = px.area(
        df,
        x="day", y="cost", color="provider",
        color_discrete_map=display_colors,
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
