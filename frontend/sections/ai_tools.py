"""F-12 AI Tools Dashboard — tool-centric tabs."""
from __future__ import annotations

from typing import Iterable

import pandas as pd
import streamlit as st

from backend.services.ai_tools import (
    chatgpt_flag,
    classify_risk,
    get_ai_tools_overview,
    get_high_spenders,
    get_provider_freshness,
    get_users_for_provider,
)
from frontend.components import badge, filters_bar, fmt_int, fmt_money, hero, kpi_row, section
from frontend.theme import NAVY


def _fmt_int(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)) and v >= 1000:
        return fmt_int(int(v))
    return str(int(v))


def _fmt_dash(v, formatter=str) -> str:
    return "—" if v is None else formatter(v)


def _freshness_header() -> None:
    f = get_provider_freshness()
    parts = []
    for prov, css in (("anthropic", "claude"), ("openai", "chatgpt"), ("cursor", "cursor")):
        info = f.get(prov, {})
        label = {"anthropic": "Claude", "openai": "ChatGPT", "cursor": "Cursor"}[prov]
        if info.get("source") == "absent":
            text = '<span class="source-absent">not connected</span>'
        else:
            start = info.get("start_date") or "?"
            end = info.get("end_date") or "?"
            window = f"{start} – {end}" if start != end else start
            klass = "source-real" if info["source"] == "real" else "source-mock"
            text = f"{window} · <span class=\"{klass}\">{info['source'].title()}</span>"
        parts.append(
            f'<span class="item {css}"><span class="dot"></span><span class="label">{label}:</span> {text}</span>'
        )
    st.markdown(f'<div class="hmnd-fresh">{" | ".join(parts)}</div>', unsafe_allow_html=True)


def _provider_chips() -> None:
    st.markdown(
        """
        <div class="hmnd-providers">
            <span class="chip claude"><span class="dot"></span>Claude</span>
            <span class="chip chatgpt"><span class="dot"></span>ChatGPT</span>
            <span class="chip cursor"><span class="dot"></span>Cursor</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _bar_list(rows: list[dict], label_key: str, value_key: str, css_class: str,
              max_value: float | None = None, value_formatter=str) -> None:
    if not rows:
        st.caption("No data.")
        return
    if max_value is None:
        max_value = max((r[value_key] or 0) for r in rows) or 1
    html = []
    for r in rows:
        val = r[value_key] or 0
        pct = max(2, min(100, int((val / max_value) * 100)))
        klass = css_class if isinstance(css_class, str) else css_class(r)
        html.append(
            f'<div class="hmnd-bar-row">'
            f'  <div class="name">{r[label_key]}</div>'
            f'  <div class="track"><div class="fill {klass}" style="width:{pct}%"></div></div>'
            f'  <div class="value">{value_formatter(val)}</div>'
            f'</div>'
        )
    st.markdown("\n".join(html), unsafe_allow_html=True)


# ----------------- main render -----------------

hero(
    "AI Tools",
    'AI Tools <span class="accent">Overview</span>',
    "Per-tool view across Claude, ChatGPT and Cursor with cross-provider High Spenders.",
)
_provider_chips()
_freshness_header()

filters = filters_bar()


tab_overview, tab_claude, tab_gpt, tab_cursor, tab_high = st.tabs(
    ["Overview", "Claude Users", "ChatGPT Users", "Cursor", "⚠ High Spenders"]
)


with tab_overview:
    o = get_ai_tools_overview(period_days=5)
    kpi_row([
        {"label": "Claude Chat Users (5d)",  "value": _fmt_dash(o["claude_chat_users"]),
         "delta": None, "note": "Anthropic active users"},
        {"label": "Claude Code Users (5d)", "value": _fmt_dash(o["claude_code_users"]),
         "delta": None, "note": "needs Claude Code telemetry"},
        {"label": "ChatGPT Active Users",   "value": _fmt_dash(o["chatgpt_active_users"]),
         "delta": None, "note": "OpenAI active users"},
        {"label": "Cursor Active Devs",     "value": _fmt_dash(o["cursor_active_devs"]),
         "delta": None, "note": "needs Cursor Teams API"},
    ])

    c1, c2 = st.columns(2)
    with c1:
        section("Claude — Daily Active Users")
        st.caption("Connect Claude Code telemetry for hour-level granularity.")
    with c2:
        section("Claude Code — Daily Lines Added")
        st.caption("Will appear once Claude Code OTel collector is wired up.")


with tab_claude:
    # F-12.1.2 — Claude data comes from the Cursor team CSV exports the user
    # drops into the repo (see backend.services.cursor_analytics). Anthropic's
    # Admin API stays untouched; this tab is purely Cursor-derived so the
    # leaderboard reflects every dev whose Cursor 'favorite model' is Claude.
    from backend.services.cursor_analytics import (
        claude_users as _claude_users,
        load_user_leaderboard as _all_leaders,
    )
    claude_rows = _claude_users()
    all_rows = _all_leaders()

    if not claude_rows:
        st.info(
            "No Claude users in the latest Cursor export. Drop a "
            "User_Leaderboard_*.csv with users whose Favorite Model contains "
            "'claude' to populate this tab."
        )
    else:
        total_ai_lines = sum(r["ai_lines"] for r in claude_rows)
        total_completions = sum(r["agent_completions"] + r["tab_completions"] for r in claude_rows)
        share_pct = (
            len(claude_rows) / max(len(all_rows), 1) * 100 if all_rows else 0.0
        )
        kpi_row([
            {"label": "Claude users",       "value": str(len(claude_rows)),
             "note": f"{share_pct:.0f}% of team"},
            {"label": "Total AI lines",     "value": fmt_int(total_ai_lines)},
            {"label": "Total completions",  "value": fmt_int(total_completions)},
            {"label": "Period",
             "value": claude_rows[0]["period_start"][5:] + " — " + claude_rows[0]["period_end"][5:]},
        ])

        c1, c2 = st.columns(2)
        with c1:
            section("Top 10 by AI Lines")
            top_lines = sorted(claude_rows, key=lambda r: r["ai_lines"], reverse=True)[:10]
            _bar_list(top_lines, label_key="name", value_key="ai_lines",
                      css_class="claude", value_formatter=fmt_int)
        with c2:
            section("Top 10 by Agent Completions")
            top_compl = sorted(claude_rows, key=lambda r: r["agent_completions"], reverse=True)[:10]
            _bar_list(top_compl, label_key="name", value_key="agent_completions",
                      css_class="claude", value_formatter=lambda v: f"{int(v):,}")

        section("All Claude Users")
        df = pd.DataFrame(claude_rows)
        view = df[[
            "name", "favorite_model", "agent_completions", "agent_lines",
            "tab_completions", "tab_lines", "ai_lines",
        ]].rename(columns={
            "name": "Name",
            "favorite_model": "Favorite model",
            "agent_completions": "Agent completions",
            "agent_lines": "Agent lines",
            "tab_completions": "Tab completions",
            "tab_lines": "Tab lines",
            "ai_lines": "AI lines",
        })
        st.markdown(
            view.to_html(escape=False, index=False, classes="hmnd-table"),
            unsafe_allow_html=True,
        )


with tab_gpt:
    rows = get_users_for_provider("openai", period_days=filters.period_days,
                                   api_key_id=filters.api_key_id)
    total_msgs = sum(r["messages"] for r in rows)
    total_spend = sum(r["cost"] for r in rows)
    high = [r for r in rows if r["cost"] >= 200]
    kpi_row([
        {"label": "Active Users",   "value": str(len(rows)), "note": "with API activity"},
        {"label": "Total Messages", "value": _fmt_int(total_msgs)},
        {"label": "Total Spend",    "value": fmt_money(total_spend)},
        {"label": "High Spenders",  "value": str(len(high)), "note": "≥ $200"},
    ])

    section("All ChatGPT Users")
    if rows:
        df = pd.DataFrame(rows).sort_values("messages", ascending=False)
        df["spend_str"] = df["cost"].apply(lambda v: fmt_money(v) if v else "—")
        df["flag_str"] = df["cost"].apply(
            lambda v: badge(chatgpt_flag(v), {"High": "high", "Medium": "medium", "Watch": "review"}.get(chatgpt_flag(v), "low"))
            if chatgpt_flag(v) else ""
        )
        view = df[["user_name", "messages", "spend_str", "flag_str"]].rename(
            columns={"user_name": "Name", "messages": "Messages",
                     "spend_str": "Spend", "flag_str": "Flag"}
        )
        st.markdown(
            view.to_html(escape=False, index=False, classes="hmnd-table"),
            unsafe_allow_html=True,
        )
    else:
        st.info("No OpenAI activity in the period.")


with tab_cursor:
    from backend.services.cursor_analytics import (
        load_contribution_daily, load_team_dau, load_user_leaderboard, model_usage_summary,
    )
    leaders = load_user_leaderboard()
    dau = load_team_dau()
    contrib = load_contribution_daily()
    models = model_usage_summary()

    if not leaders and not dau:
        st.markdown(
            """
            <div style="
                border:1px dashed #fcd34d; border-radius:18px; padding:32px; background:#fffdf6;
                text-align:center; color:#475569;
            ">
                <div style="font-size:13px;color:#f59e0b;letter-spacing:.12em;text-transform:uppercase;font-weight:600">
                    No Cursor exports yet
                </div>
                <div style="font-size:22px;color:#06091c;font-weight:300;margin-top:8px">
                    Drop the CSV exports into the repo
                </div>
                <p style="margin-top:8px">
                    Expected files at repo root (or <code>HMND_CURSOR_EXPORT_DIR</code>):
                    <code>User_Leaderboard_*.csv</code>,
                    <code>Team_DAU_Analytics_*.csv</code>,
                    <code>Contribution_Analytics_*.csv</code>,
                    <code>Analytics_Team_*.csv</code>.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        active_devs = len({r["email"] for r in leaders})
        total_ai_lines = sum(r["ai_lines"] for r in leaders)
        prefer_claude = sum(1 for r in leaders if "claude" in r["favorite_model"].lower())
        prefer_gpt = sum(1 for r in leaders if r["favorite_model"].lower().startswith("gpt"))
        kpi_row([
            {"label": "Active developers", "value": str(active_devs), "note": "in latest period"},
            {"label": "Total AI lines",    "value": fmt_int(total_ai_lines)},
            {"label": "Prefer Claude",     "value": f"{prefer_claude} devs",
             "note": f"vs {prefer_gpt} on GPT"},
            {"label": "Period",
             "value": leaders[0]["period_start"][5:] + " — " + leaders[0]["period_end"][5:]
             if leaders else "—"},
        ])

        c1, c2 = st.columns(2)
        with c1:
            section("Top 10 by AI Lines")
            top10 = leaders[:10]
            max_lines = max((r["ai_lines"] for r in top10), default=1) or 1
            def _row_class(r):
                fm = r["favorite_model"].lower()
                if "claude" in fm:
                    return "claude"
                if fm.startswith("gpt"):
                    return "chatgpt"
                return "cursor"
            _bar_list(
                top10, label_key="name", value_key="ai_lines",
                css_class=_row_class, max_value=max_lines,
                value_formatter=fmt_int,
            )
        with c2:
            if dau:
                section("Daily Active Users")
                df_dau = pd.DataFrame(dau)
                df_dau["date"] = pd.to_datetime(df_dau["date"])
                fig = __import__("plotly.express", fromlist=[""]).bar(
                    df_dau, x="date", y="dau",
                    color_discrete_sequence=["#f59e0b"],
                )
                fig.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                                  margin=dict(l=10, r=10, t=10, b=10),
                                  font=dict(family="Inter", color=NAVY),
                                  xaxis=dict(showgrid=False),
                                  yaxis=dict(gridcolor="#e8edf3"))
                st.plotly_chart(fig, use_container_width=True)

        if models:
            section("Models used by the team")
            df_models = pd.DataFrame(models[:15])
            view = df_models.rename(columns={
                "model": "Model", "requests": "Requests", "user_days": "User-days",
            })
            st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"),
                        unsafe_allow_html=True)

        if contrib:
            section("Daily contribution (composer + tabs)")
            df_c = pd.DataFrame(contrib)
            df_c["date"] = pd.to_datetime(df_c["date"])
            df_long = df_c.melt(
                id_vars=["date"],
                value_vars=["composer_lines_accepted", "tabs_lines_accepted"],
                var_name="kind", value_name="lines",
            )
            df_long["kind"] = df_long["kind"].map({
                "composer_lines_accepted": "Composer accepted",
                "tabs_lines_accepted": "Tabs accepted",
            })
            fig = __import__("plotly.express", fromlist=[""]).bar(
                df_long, x="date", y="lines", color="kind", barmode="stack",
                color_discrete_map={"Composer accepted": "#6366f1", "Tabs accepted": "#f59e0b"},
            )
            fig.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                              margin=dict(l=10, r=10, t=10, b=10),
                              font=dict(family="Inter", color=NAVY),
                              xaxis=dict(showgrid=False),
                              yaxis=dict(gridcolor="#e8edf3"))
            st.plotly_chart(fig, use_container_width=True)


with tab_high:
    spenders = get_high_spenders(period_days=filters.period_days,
                                  threshold_usd=200,
                                  api_key_id=filters.api_key_id)
    combined = sum(r["spend"] for r in spenders)
    top = spenders[0] if spenders else None
    kpi_row([
        {"label": "High Spenders", "value": str(len(spenders)), "note": "≥ $200"},
        {"label": "Combined Spend", "value": fmt_money(combined)},
        {"label": "Top Spender", "value": fmt_money(top["spend"]) if top else "—",
         "note": top["user_name"] if top else "—"},
    ])

    if spenders:
        section("Top 10 High Spenders")
        max_spend = max(r["spend"] for r in spenders)
        _bar_list(
            spenders[:10],
            label_key="user_name", value_key="spend",
            css_class=lambda r: f"risk-{classify_risk(r['spend']) or 'low'}",
            max_value=max_spend,
            value_formatter=lambda v: fmt_money(v),
        )

        section("Detail · Red ≥ $1000 · Amber ≥ $500 · Yellow ≥ $200")
        df = pd.DataFrame(spenders)
        df["spend_str"] = df["spend"].apply(fmt_money)
        df["dpm_str"] = df["dollar_per_msg"].apply(lambda v: f"${v:.2f}" if v is not None else "—")
        df["risk_badge"] = df["risk"].apply(lambda r: badge(r, r))
        view = df[["user_name", "messages", "spend_str", "dpm_str", "risk_badge"]].rename(
            columns={"user_name": "Name", "messages": "Messages",
                     "spend_str": "Spend", "dpm_str": "$/msg", "risk_badge": "Risk"}
        )
        st.markdown(
            view.to_html(escape=False, index=False, classes="hmnd-table"),
            unsafe_allow_html=True,
        )
    else:
        st.info("No users above $200 spend in the last 30 days.")
