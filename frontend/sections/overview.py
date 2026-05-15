"""F-01 Executive Overview section."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.config import load_config
from backend.services.overview import (
    get_daily_spend_series, get_overview_kpis, get_source_freshness,
)
from frontend.components import filters_bar, fmt_int, fmt_money, fmt_pct, hero, kpi_row, section
from frontend.theme import ANTHROPIC, NAVY, OPENAI, PROVIDER_COLORS

CFG = load_config()

st.markdown(
    """
    <div style="display:flex; align-items:center; gap:14px; margin: 4px 0 18px 0;">
        <img src="https://i.ibb.co/nsfMVMGM/1.png" alt="HMND"
             style="width:36px; height:36px; border-radius:10px;" />
        <h1 style="margin:0; font-family:Inter, sans-serif; font-weight:500;
                   font-size:34px; line-height:1;">
            <span style="color:#4953d8;">AIOps</span>
            <span style="color:#06091c;">Dashboard</span>
        </h1>
    </div>
    """,
    unsafe_allow_html=True,
)

# Data freshness chips — makes it obvious WHEN each source last logged
# data, so a sparse 'Today' view isn't read as a bug. JSON-snapshot
# sources stop at the dump date; API sources stay live.
_fresh = get_source_freshness()
if _fresh:
    chips = []
    for s in _fresh:
        label = s["provider"].capitalize().replace("Openai", "OpenAI").replace("Github", "GitHub")
        if s["org_label"]:
            label = f"{label} · {s['org_label']}"
        if s["is_live"]:
            badge_color, badge_text = "#16a34a", "live"
        elif s["days_old"] <= 7:
            badge_color, badge_text = "#f59e0b", f"{s['days_old']}d old"
        else:
            badge_color, badge_text = "#ef4444", f"{s['days_old']}d stale"
        chips.append(
            f'<span style="display:inline-flex;align-items:center;gap:6px;'
            f'padding:4px 10px;border-radius:999px;background:#f1f5f9;'
            f'color:#475569;font-size:12px;font-weight:500;margin-right:6px;'
            f'margin-bottom:6px">'
            f'<span style="width:6px;height:6px;border-radius:50%;background:{badge_color}"></span>'
            f'{label}<span style="color:#94a3b8">·</span>'
            f'<span style="color:{badge_color}">{badge_text}</span>'
            f'<span style="color:#94a3b8">last {s["last_day"]}</span>'
            f'</span>'
        )
    st.markdown(
        '<div style="margin: -8px 0 14px 0; display:flex; flex-wrap:wrap">'
        + "".join(chips) + "</div>",
        unsafe_allow_html=True,
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

kpi_row([
    {"label": "Total spend",  "value": fmt_money(kpis["total_spend"]),
     "delta": kpis["total_spend_delta"],
     "help": "Сколько мы заплатили за все AI-инструменты за выбранный период "
             "(OpenAI API + Anthropic API + Cursor). Стрелка — изменение vs "
             "предыдущий такой же период."},
    {"label": "Tokens in",    "value": fmt_int(kpis["tokens_in"]),
     "delta": kpis["tokens_in_delta"],
     "help": "Сколько токенов мы отправили моделям (вход). Грубо — объём "
             "контекста, промптов и истории чатов."},
    {"label": "Tokens out",   "value": fmt_int(kpis["tokens_out"]),
     "delta": kpis["tokens_out_delta"],
     "help": "Сколько токенов модели сгенерировали (ответы). Выходные токены "
             "обычно в 3-5x дороже входных."},
    {"label": "Active users", "value": str(kpis["active_users"]),
     "delta": kpis["active_users_delta"],
     "help": "Уникальные пользователи, которые сделали хотя бы 1 запрос за "
             "период. Помогает понять реальный охват AI-инструментов в "
             "команде."},
])
if CFG.github_enabled:
    kpi_row([{
        "label": "AI code share", "value": fmt_pct(kpis["ai_code_share"]),
        "delta": kpis["ai_code_share_delta"],
        "help": "Доля строк кода, сгенерированных AI, от общего числа "
                "коммитов команды. Cursor отмечает ai_lines напрямую; коммиты "
                "ботов считаем 100% AI.",
    }])

section(
    "Spend over time",
    help="Дневной трат по каждому провайдеру за период. Резкие пики обычно "
         "= новый юзер с heavy use, или автоматизация / cron, или дорогой "
         "reasoning-модель.",
)
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
    # When the period collapses to ≤ 2 distinct days (e.g. Today / Yesterday)
    # an area/line chart looks empty. Draw a bar chart instead so the user
    # can see the actual numbers per provider.
    distinct_days = df["day"].nunique()
    if distinct_days <= 2:
        fig = px.bar(
            df, x="day", y="cost", color="provider",
            color_discrete_map=display_colors, barmode="group",
            text_auto=".2f",
        )
        fig.update_traces(textposition="outside")
    else:
        fig = px.area(
            df, x="day", y="cost", color="provider",
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
