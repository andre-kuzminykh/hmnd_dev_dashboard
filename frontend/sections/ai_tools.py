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
    rows = get_users_for_provider("anthropic", period_days=filters.period_days,
                                   api_key_id=filters.api_key_id)
    total_msgs = sum(r["messages"] for r in rows)
    code_users = [r for r in rows if r.get("sessions")]
    cc_lines = sum((r["lines_added"] or 0) for r in rows)
    kpi_row([
        {"label": "Chat Active Users",  "value": str(len(rows))},
        {"label": "Total Messages",     "value": _fmt_int(total_msgs)},
        {"label": "Claude Code Users",  "value": _fmt_dash(len(code_users) if code_users else None)},
        {"label": "CC Lines Added",     "value": _fmt_dash(cc_lines if cc_lines else None, _fmt_int)},
    ])

    c1, c2 = st.columns(2)
    with c1:
        section("Top 10 Chat Users by Messages")
        _bar_list(
            rows[:10],
            label_key="user_name", value_key="messages", css_class="claude",
            value_formatter=lambda v: f"{int(v):,}",
        )
    with c2:
        section("Top 10 Claude Code Users by Lines")
        if any(r.get("lines_added") for r in rows):
            cc_top = sorted(
                [r for r in rows if r.get("lines_added")],
                key=lambda r: r["lines_added"], reverse=True,
            )[:10]
            _bar_list(cc_top, label_key="user_name", value_key="lines_added",
                      css_class="claude", value_formatter=_fmt_int)
        else:
            st.caption(
                "No Claude Code line counts yet — wire up Claude Code telemetry "
                "(CLAUDE_CODE_TELEMETRY env + OTel endpoint) to populate this list."
            )

    section("All Claude Users")
    if rows:
        df = pd.DataFrame(rows)
        view = df[["user_name", "messages", "sessions", "lines_added", "commits"]].rename(
            columns={
                "user_name": "Name", "messages": "Messages",
                "sessions": "CC Sessions", "lines_added": "Lines Added", "commits": "Commits",
            }
        )
        view = view.fillna("—")
        st.markdown(
            view.to_html(escape=False, index=False, classes="hmnd-table"),
            unsafe_allow_html=True,
        )
    else:
        st.info("No Anthropic activity in the period.")


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
    st.markdown(
        """
        <div style="
            border:1px dashed #fcd34d; border-radius:18px; padding:32px; background:#fffdf6;
            text-align:center; color:#475569;
        ">
            <div style="font-size:13px;color:#f59e0b;letter-spacing:.12em;text-transform:uppercase;font-weight:600">
                Coming soon
            </div>
            <div style="font-size:22px;color:#06091c;font-weight:300;margin-top:8px">
                Connect Cursor Teams to see this view
            </div>
            <p style="margin-top:8px">
                Add <code>CURSOR_API_TOKEN</code> + <code>CURSOR_ORG_SLUG</code> to <code>.env</code>
                so the sync can pull <i>active developers</i>, <i>AI lines</i> and <i>tool preference</i>
                (Claude / GPT / Default) from the Cursor Teams admin endpoint.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
