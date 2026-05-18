"""F-12 / F-20 AI Tools — unified Overview + Engineering tabs.

Two-tab page: every chart and table reacts to the single filter bar already
rendered ABOVE this file by overview.py (the `filters` variable is in scope
because main.py exec()s both files into the same globals dict).

Scope rules (driven by filters.provider):
  - 'all'        → cross-tool KPIs (Claude + ChatGPT + Cursor)
  - 'anthropic'  → Claude-only KPIs + Claude Products Breakdown
  - 'openai'     → ChatGPT-only KPIs + Top OpenAI Models
  - 'cursor'     → Cursor-only KPIs + DAU + completions
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.services.ai_tools import (
    chatgpt_flag,
    classify_risk,
    get_anthropic_model_spend_from_json,
    get_anthropic_spend_by_purpose,
    get_cursor_completion_split,
    get_high_spenders,
    get_high_spenders_per_provider,
    get_openai_top_models,
    get_spend_by_model,
    get_users_for_provider,
)
from frontend.components import badge, fmt_int, fmt_money, kpi_row, section
from frontend.theme import NAVY


# ----------------- shared helpers (verbatim from old file) -----------------

def _fmt_int(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)) and v >= 1000:
        return fmt_int(int(v))
    return str(int(v))


def _fmt_dash(v, formatter=str) -> str:
    return "—" if v is None else formatter(v)


def _bar_list(rows: list[dict], label_key: str, value_key: str, css_class,
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


def _hs_note(s: dict[str, Any]) -> str:
    """Heuristic one-liner describing the spend pattern."""
    spend = s["spend"] or 0
    msgs = s["messages"] or 0
    dpm = (spend / msgs) if msgs > 0 else None
    if dpm is not None and dpm >= 100:
        return f"anomalous: ~${dpm:,.0f} per message — possible API/automation"
    if dpm is not None and dpm >= 20:
        return f"high cost/message (${dpm:,.1f}/msg) — likely reasoning model"
    if msgs >= 1000:
        return "high volume, proportionate spend"
    return f"avg ${dpm:,.2f}/msg" if dpm is not None else "non-message billing"


def _hs_findings(high: list[dict[str, Any]]) -> list[str]:
    """Generate up to 4 narrative bullets for the analysis card."""
    bullets: list[str] = []
    if not high:
        return bullets
    top = high[0]
    bullets.append(
        f"<b>{top['user_name']}</b> — {fmt_money(top['spend'])} on "
        f"{top['messages']:,} messages, top single spender."
    )
    anomalies = [s for s in high
                 if s["messages"] and (s["spend"] / s["messages"]) >= 100]
    if anomalies:
        a = anomalies[0]
        dpm = a["spend"] / a["messages"]
        bullets.append(
            f"<b>{a['user_name']}</b> — {fmt_money(a['spend'])} on {a['messages']} messages "
            f"(~${dpm:,.0f}/msg). Likely API/automation, not chat usage."
        )
    volume = sorted(high, key=lambda r: r["messages"] or 0, reverse=True)
    if volume and volume[0]["messages"] >= 1000 and volume[0] != top:
        v = volume[0]
        bullets.append(
            f"<b>{v['user_name']}</b> — {v['messages']:,} messages at "
            f"{fmt_money(v['spend'])}. High volume, normal $/msg."
        )
    if len(high) >= 3:
        top3 = sum(s["spend"] for s in high[:3])
        total = sum(s["spend"] for s in high)
        share = (top3 / total * 100) if total else 0
        bullets.append(f"Top 3 high-spenders = <b>{share:.0f}%</b> of all high spend.")
    return bullets[:4]


# ----------------- main render -----------------
# main.py sources this file into overview.py's globals so `filters` is in
# scope already (filters bar lives above, on Overview).
# F-20 — three tabs, no "AI Tools" caption.

tab_overview, tab_engineering, tab_people = st.tabs(
    ["Overview", "Engineering", "People"]
)


# =============================================================================
# OVERVIEW TAB
# =============================================================================
with tab_overview:
    from data.db import get_conn as _gc
    f = filters  # noqa: F821 — provided by main.py exec scope
    s_iso = f.date_range()[0].strftime("%Y-%m-%d %H:%M:%S")
    e_iso = f.date_range()[1].strftime("%Y-%m-%d %H:%M:%S")
    _scope = (f.provider or "all").lower()
    _show_anthropic = _scope in ("all", "anthropic")
    _show_openai    = _scope in ("all", "openai")
    _show_cursor    = _scope in ("all", "cursor")

    # Organization narrowing for OpenAI sub-orgs (Artem vs Humanoid).
    _org_clause = ""
    _org_params: list = []
    if f.organization and f.organization != "all":
        _org_clause = " AND ue.organization_id IN (SELECT id FROM organizations WHERE label = ?) "
        _org_params = [f.organization]
    _key_clause = ""
    _key_params: list = []
    if f.api_key_id:
        _key_clause = " AND ue.api_key_id = ? "
        _key_params = [f.api_key_id]

    _empty = {"s": 0, "u": 0, "c": 0}
    with _gc() as _conn:
        if _show_anthropic:
            _claude_spend = _conn.execute(
                f"""SELECT COALESCE(SUM(ue.cost_usd), 0) AS s, COUNT(DISTINCT ue.user_id) AS u, COUNT(*) AS c
                   FROM usage_events ue JOIN providers p ON p.id = ue.provider_id
                   WHERE p.name='anthropic' AND ue.occurred_at BETWEEN ? AND ?
                   {_org_clause} {_key_clause}""",
                [s_iso, e_iso] + _org_params + _key_params,
            ).fetchone()
        else:
            _claude_spend = _empty
        if _show_openai:
            _gpt_spend = _conn.execute(
                f"""SELECT COALESCE(SUM(ue.cost_usd), 0) AS s, COUNT(DISTINCT ue.user_id) AS u, COUNT(*) AS c
                   FROM usage_events ue JOIN providers p ON p.id = ue.provider_id
                   WHERE p.name='openai' AND ue.occurred_at BETWEEN ? AND ?
                   {_org_clause} {_key_clause}""",
                [s_iso, e_iso] + _org_params + _key_params,
            ).fetchone()
        else:
            _gpt_spend = _empty

    # Cursor: real spend from usage_events; CSV/JSON leaderboard for activity.
    from backend.services.cursor_analytics import load_user_leaderboard as _llb
    _leaders = _llb() if _show_cursor else []
    _cursor_devs = len(_leaders)
    _cursor_completions = sum(int(r.get("agent_completions", 0) or 0)
                              + int(r.get("tab_completions", 0) or 0) for r in _leaders)
    _cursor_ai_lines = sum(int(r.get("ai_lines", 0) or 0) for r in _leaders)
    if _show_cursor:
        with _gc() as _conn:
            _cursor_spend_row = _conn.execute(
                f"""SELECT COALESCE(SUM(ue.cost_usd), 0) AS s, COUNT(*) AS c
                   FROM usage_events ue JOIN providers p ON p.id = ue.provider_id
                   WHERE p.name='cursor' AND ue.occurred_at BETWEEN ? AND ?
                   {_key_clause}""",
                [s_iso, e_iso] + _key_params,
            ).fetchone()
        _cursor_spend_actual = float(_cursor_spend_row["s"] or 0)
    else:
        _cursor_spend_actual = 0.0

    claude_v = float(_claude_spend["s"] or 0)
    gpt_v = float(_gpt_spend["s"] or 0)
    cursor_v = _cursor_spend_actual
    total_v = claude_v + gpt_v + cursor_v
    cp = (claude_v / total_v * 100) if total_v else 0
    gp = (gpt_v / total_v * 100) if total_v else 0
    crp = (cursor_v / total_v * 100) if total_v else 0

    # -------- 1. Spend Breakdown bar --------
    if total_v > 0:
        st.markdown(
            f"""
            <div style="border:1px solid #e8edf3;border-radius:18px;padding:18px 22px;
                        background:linear-gradient(180deg,#fff 0%,#fcfdff 100%);margin-bottom:14px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                    <div style="font-weight:600;color:#06091c;">Spend Breakdown</div>
                    <div style="color:#64748b;font-size:12px;">Total <b style="color:#06091c">{fmt_money(total_v)}</b></div>
                </div>
                <div style="display:flex;height:36px;border-radius:8px;overflow:hidden;background:#f1f5f9;">
                    <div style="background:#6366f1;width:{cp:.2f}%;display:flex;align-items:center;justify-content:center;
                                color:white;font-weight:600;font-size:13px;">{cp:.1f}%</div>
                    <div style="background:#10a37f;width:{gp:.2f}%;display:flex;align-items:center;justify-content:center;
                                color:white;font-weight:600;font-size:13px;">{gp:.1f}%</div>
                    <div style="background:#f59e0b;width:{crp:.2f}%;display:flex;align-items:center;justify-content:center;
                                color:white;font-weight:600;font-size:13px;">{crp:.1f}%</div>
                </div>
                <div style="display:flex;gap:24px;margin-top:10px;font-size:13px;color:#475569;">
                    <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#6366f1;margin-right:6px;"></span>Claude <b style="color:#06091c">{fmt_money(claude_v)}</b></span>
                    <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#10a37f;margin-right:6px;"></span>ChatGPT <b style="color:#06091c">{fmt_money(gpt_v)}</b></span>
                    <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#f59e0b;margin-right:6px;"></span>Cursor ~<b style="color:#06091c">{fmt_money(cursor_v)}</b></span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # -------- 2. Three tool cards (Claude / ChatGPT / Cursor) --------
    def _tool_card(color: str, label: str, value: str, note: str) -> str:
        return f"""
            <div style="border:1px solid #e8edf3;border-top:3px solid {color};border-radius:18px;
                        padding:18px 20px;background:linear-gradient(180deg,#fff 0%,#fcfdff 100%);
                        box-shadow:0 14px 32px -24px rgba(6,9,28,.14);height:100%;">
                <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.12em;margin-bottom:8px;">{label}</div>
                <div style="font-size:28px;line-height:1;font-weight:300;color:#06091c;">{value}</div>
                <div style="font-size:12px;color:#475569;margin-top:10px;">{note}</div>
            </div>
        """

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(_tool_card(
            "#6366f1", "Claude", fmt_money(claude_v),
            f"{_claude_spend['u']} users · {_claude_spend['c']:,} reqs",
        ), unsafe_allow_html=True)
    with c2:
        st.markdown(_tool_card(
            "#10a37f", "ChatGPT", fmt_money(gpt_v),
            f"{_gpt_spend['u']} users · {_gpt_spend['c']:,} reqs",
        ), unsafe_allow_html=True)
    with c3:
        st.markdown(_tool_card(
            "#f59e0b", "Cursor", fmt_money(cursor_v),
            f"{_cursor_devs} devs · {_cursor_completions:,} completions · {fmt_int(_cursor_ai_lines)} AI lines",
        ), unsafe_allow_html=True)

    # -------- 3. Top Spenders horizontal bars --------
    _title_suffix = {
        "all":       "— All Tools",
        "anthropic": "— Claude",
        "openai":    "— ChatGPT",
        "cursor":    "— Cursor",
    }.get(_scope, "")
    section(
        f"Top Spenders {_title_suffix}".strip(),
        help="Top 10 people by spend in the active Source + Date filter. "
             "Bar colour = risk level: red >= $1k, orange $500-1k, "
             "yellow < $500.",
    )
    if _scope == "all":
        st.caption("Ranks across all tools — adjust the Source filter "
                   "to narrow to one provider.")
    else:
        _label = {"anthropic": "Anthropic (Claude)",
                  "openai":    "OpenAI (ChatGPT)",
                  "cursor":    "Cursor"}.get(_scope, _scope.title())
        st.caption(f"Filtered to **{_label}** "
                   f"({f.period_days}-day window).")
    spenders = get_high_spenders(
        period_days=f.period_days,
        threshold_usd=0,
        api_key_id=f.api_key_id,
        provider=_scope,
        organization=(f.organization or "all"),
        date_from=f.date_from,
        date_to=f.date_to,
    )
    top10 = spenders[:10]
    if top10:
        max_spend = max(r["spend"] for r in top10) or 1
        _bar_list(
            top10, label_key="user_name", value_key="spend",
            css_class=lambda r: f"risk-{classify_risk(r['spend']) or 'low'}",
            max_value=max_spend, value_formatter=fmt_money,
        )
    else:
        st.caption("No spend recorded yet for the active filter.")

    # -------- 4. Claude Products Breakdown — only when Anthropic in scope --
    if _show_anthropic:
        purposes = get_anthropic_spend_by_purpose(period_days=f.period_days)
        if purposes:
            section("Claude Products Breakdown",
                    help="Split of Anthropic spend across Chat / Claude Code "
                         "(Agent) / Cowork + Other.")
            grouped: dict[str, dict] = {"Chat": {}, "Claude Code": {}, "Cowork + Other": {}}
            for p in purposes:
                key = {"Chat": "Chat", "Agent": "Claude Code"}.get(
                    p["purpose"], "Cowork + Other"
                )
                g = grouped.setdefault(key, {"spend": 0.0, "requests": 0, "users": 0})
                g["spend"] = (g.get("spend") or 0) + (p["spend"] or 0)
                g["requests"] = (g.get("requests") or 0) + (p["requests"] or 0)
                g["users"] = max(g.get("users") or 0, p["users"] or 0)
            colors = {"Chat": "#a5b4fc", "Claude Code": "#6366f1",
                      "Cowork + Other": "#c7d2fe"}
            pc1, pc2, pc3 = st.columns(3)
            for col, (label, g) in zip((pc1, pc2, pc3), grouped.items()):
                with col:
                    st.markdown(
                        f"""
                        <div style="border:1px solid #e8edf3;border-top:3px solid {colors[label]};
                                    border-radius:18px;padding:18px 20px;background:#fff;height:100%;">
                            <div style="font-size:11px;color:#64748b;text-transform:uppercase;
                                        letter-spacing:.12em;margin-bottom:8px;">{label}</div>
                            <div style="font-size:24px;font-weight:300;color:#06091c;">
                                {fmt_money(g.get('spend') or 0)}
                            </div>
                            <div style="font-size:12px;color:#475569;margin-top:10px;">
                                {(g.get('users') or 0)} users · {(g.get('requests') or 0):,} reqs
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

    # -------- 5. OpenAI Top Models — only when OpenAI in scope --
    if _show_openai:
        openai_models = get_openai_top_models(period_days=f.period_days)
        if openai_models:
            section("OpenAI Top Models",
                    help="Per-model ChatGPT usage by request count.")
            _bar_list(openai_models[:8], label_key="model",
                      value_key="requests", css_class="chatgpt",
                      value_formatter=fmt_int)

    # -------- 6. Cursor DAU — only when Cursor in scope --
    if _show_cursor:
        from backend.services.cursor_analytics import load_team_dau
        dau = load_team_dau()
        if dau:
            section("Cursor — Daily Active Users",
                    help="Cursor team DAU over the data window. Source: "
                         "Team_DAU_Analytics_*.csv exports.")
            df_dau = pd.DataFrame(dau)
            df_dau["date"] = pd.to_datetime(df_dau["date"])
            fig_dau = px.bar(
                df_dau, x="date", y="dau",
                color_discrete_sequence=["#f59e0b"],
            )
            fig_dau.update_layout(
                plot_bgcolor="white", paper_bgcolor="white",
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(family="Inter", color=NAVY),
                xaxis=dict(showgrid=False),
                yaxis=dict(gridcolor="#e8edf3"),
            )
            st.plotly_chart(fig_dau, use_container_width=True)

        # Cursor completion split — small bonus KPI strip
        compl = get_cursor_completion_split(period_days=f.period_days)
        if compl["total"] > 0:
            st.caption(
                f"Cursor completions in scope: "
                f"**{fmt_int(compl['agent'])}** Agent + "
                f"**{fmt_int(compl['tab'])}** Tab = "
                f"**{fmt_int(compl['total'])}** total."
            )

    # ================ Expanders (tables, collapsed by default) ================

    # ---- All Users — cross-tool ----
    with st.expander("All Users — cross-tool", expanded=False):
        per_provider = get_high_spenders_per_provider(period_days=f.period_days)
        if not per_provider:
            st.caption("No cross-tool user spend in the active window.")
        else:
            # Scope filter — drop rows that have $0 in the active scope.
            def _in_scope(r: dict) -> bool:
                if _scope == "all":
                    return True
                if _scope == "anthropic":
                    return (r.get("cost_anthropic") or 0) > 0
                if _scope == "openai":
                    return (r.get("cost_openai") or 0) > 0
                if _scope == "cursor":
                    return (r.get("cost_cursor") or 0) > 0
                return True
            scoped = [r for r in per_provider if _in_scope(r)]
            if not scoped:
                st.caption(f"No users with spend in scope '{_scope}'.")
            else:
                df_au = pd.DataFrame(scoped)
                df_au = df_au[["user_name", "messages",
                               "cost_openai", "cost_anthropic",
                               "cost_cursor", "cost_total"]].copy()
                for c in ("cost_openai", "cost_anthropic", "cost_cursor", "cost_total"):
                    df_au[c] = df_au[c].apply(
                        lambda v: fmt_money(v) if v else "—"
                    )
                df_au["messages"] = df_au["messages"].apply(
                    lambda v: fmt_int(int(v)) if v else "0"
                )
                view_au = df_au.rename(columns={
                    "user_name": "Name",
                    "messages": "Messages",
                    "cost_openai": "OpenAI",
                    "cost_anthropic": "Anthropic",
                    "cost_cursor": "Cursor",
                    "cost_total": "Total",
                })
                st.markdown(
                    view_au.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True,
                )

    # ---- Claude Users (Cursor leaderboard) ----
    if _show_anthropic or _show_cursor:
        with st.expander("Claude Users (Cursor leaderboard)", expanded=False):
            from backend.services.cursor_analytics import claude_users as _claude_users
            claude_rows = _claude_users()
            if not claude_rows:
                st.caption(
                    "No Claude users in the latest Cursor export. Drop a "
                    "User_Leaderboard_*.csv with users whose Favorite Model "
                    "contains 'claude' to populate this view."
                )
            else:
                active = [
                    r for r in claude_rows
                    if (int(r.get("ai_lines") or 0) > 0
                        or int(r.get("agent_completions") or 0) > 0
                        or int(r.get("tab_completions") or 0) > 0)
                ]
                if not active:
                    st.caption("Claude users found but zero activity in this period.")
                else:
                    df_cu = pd.DataFrame(active)
                    view_cu = df_cu[[
                        "name", "favorite_model", "agent_completions",
                        "agent_lines", "tab_completions", "tab_lines",
                        "ai_lines",
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
                        view_cu.to_html(escape=False, index=False, classes="hmnd-table"),
                        unsafe_allow_html=True,
                    )

    # ---- Claude Code Users ----
    if _show_anthropic:
        with st.expander("Claude Code Users", expanded=False):
            from data.db import get_conn
            from backend.analytics import api_key_clause as _api_key_clause
            s_dt, e_dt = f.date_range()
            k_clause, k_params = _api_key_clause(f.api_key_id, "ue")
            sql_cc = f"""
                SELECT u.full_name AS name,
                       u.email      AS email,
                       COUNT(*)     AS requests,
                       ROUND(SUM(ue.cost_usd), 2) AS spend,
                       SUM(ue.tokens_in)  AS tokens_in,
                       SUM(ue.tokens_out) AS tokens_out
                FROM usage_events ue
                JOIN users u ON u.id = ue.user_id
                JOIN providers p ON p.id = ue.provider_id
                WHERE p.name = 'anthropic'
                  AND ue.purpose = 'Agent'
                  AND ue.occurred_at BETWEEN ? AND ?
                  {k_clause}
                GROUP BY u.id
                ORDER BY spend DESC
            """
            with get_conn() as conn:
                cc_rows = [dict(r) for r in conn.execute(
                    sql_cc,
                    [s_dt.strftime("%Y-%m-%d %H:%M:%S"),
                     e_dt.strftime("%Y-%m-%d %H:%M:%S")] + k_params,
                ).fetchall()]
            if not cc_rows:
                st.caption(
                    "No Claude Code (purpose='Agent') events in this window."
                )
            else:
                total_reqs = sum(r["requests"] for r in cc_rows)
                total_spend = sum(r["spend"] or 0 for r in cc_rows)
                kpi_row([
                    {"label": "CC Requests", "value": _fmt_int(total_reqs)},
                    {"label": "CC Spend",    "value": fmt_money(total_spend)},
                    {"label": "Top spender",
                     "value": fmt_money(cc_rows[0]['spend']) if cc_rows else "—"},
                    {"label": "Avg / user",
                     "value": fmt_money(total_spend / max(len(cc_rows), 1))},
                ])
                df_cc = pd.DataFrame(cc_rows)
                view_cc = df_cc[[
                    "name", "email", "requests", "spend",
                    "tokens_in", "tokens_out",
                ]].copy()
                view_cc["spend"] = view_cc["spend"].apply(
                    lambda v: fmt_money(v) if v else "—"
                )
                view_cc["requests"] = view_cc["requests"].apply(
                    lambda v: fmt_int(int(v)) if v else "0"
                )
                view_cc["tokens_in"] = view_cc["tokens_in"].apply(
                    lambda v: fmt_int(int(v or 0))
                )
                view_cc["tokens_out"] = view_cc["tokens_out"].apply(
                    lambda v: fmt_int(int(v or 0))
                )
                view_cc = view_cc.rename(columns={
                    "name": "Name", "email": "Email",
                    "requests": "Requests", "spend": "Spend",
                    "tokens_in": "Tokens in", "tokens_out": "Tokens out",
                })
                st.markdown(
                    view_cc.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True,
                )

    # ---- ChatGPT Users ----
    if _show_openai:
        with st.expander("ChatGPT Users", expanded=False):
            rows = get_users_for_provider("openai", period_days=f.period_days,
                                          api_key_id=f.api_key_id)
            # Honor organization filter (Artem vs Humanoid) — keep the same
            # rebuild logic the old tab_gpt used so message/cost counts are
            # org-scoped, not just user-list filtered.
            if f.organization and f.organization != "all":
                from data.db import get_conn as _gc_gpt
                with _gc_gpt() as _conn_gpt:
                    org_rows = _conn_gpt.execute(
                        """SELECT u.full_name AS user_name,
                                  COUNT(*)                          AS messages,
                                  ROUND(SUM(ue.cost_usd), 2)        AS cost,
                                  SUM(ue.tokens_in)                 AS tokens_in,
                                  SUM(ue.tokens_out)                AS tokens_out
                           FROM usage_events ue
                           JOIN users u ON u.id = ue.user_id
                           JOIN providers p ON p.id = ue.provider_id
                           JOIN organizations o ON o.id = ue.organization_id
                           WHERE p.name='openai' AND o.label = ?
                             AND ue.occurred_at >= datetime('now', ?)
                           GROUP BY u.id
                           ORDER BY messages DESC""",
                        (f.organization, f"-{f.period_days} days"),
                    ).fetchall()
                rows = [
                    dict(r) | {
                        "sessions": None, "lines_added": None, "commits": None,
                        "tokens_in": int(r["tokens_in"] or 0),
                        "tokens_out": int(r["tokens_out"] or 0),
                        "cost": float(r["cost"] or 0),
                        "messages": int(r["messages"]),
                    }
                    for r in org_rows
                ]
            if not rows:
                st.caption("No OpenAI activity in the active window.")
            else:
                total_msgs = sum(r["messages"] for r in rows)
                total_spend = sum(r["cost"] for r in rows)
                high = [r for r in rows if r["cost"] >= 200]
                kpi_row([
                    {"label": "Active users",   "value": str(len(rows))},
                    {"label": "Total messages", "value": _fmt_int(total_msgs)},
                    {"label": "Total spend",    "value": fmt_money(total_spend)},
                    {"label": "High (>= $200)", "value": str(len(high))},
                ])
                df_gpt = pd.DataFrame(rows).sort_values("messages", ascending=False)
                df_gpt["spend_str"] = df_gpt["cost"].apply(
                    lambda v: fmt_money(v) if v else "—"
                )
                df_gpt["flag_str"] = df_gpt["cost"].apply(
                    lambda v: badge(
                        chatgpt_flag(v),
                        {"High": "high", "Medium": "medium",
                         "Watch": "review"}.get(chatgpt_flag(v), "low"),
                    ) if chatgpt_flag(v) else ""
                )
                view_gpt = df_gpt[["user_name", "messages", "spend_str", "flag_str"]].rename(
                    columns={
                        "user_name": "Name", "messages": "Messages",
                        "spend_str": "Spend", "flag_str": "Flag",
                    }
                )
                st.markdown(
                    view_gpt.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True,
                )

    # ---- Cursor Users (full leaderboard) ----
    if _show_cursor:
        with st.expander("Cursor Users (full leaderboard)", expanded=False):
            from backend.services.cursor_analytics import load_user_leaderboard
            leaders = load_user_leaderboard()
            if not leaders:
                st.caption(
                    "No Cursor leaderboard data. Drop User_Leaderboard_*.csv "
                    "into sources/ to populate."
                )
            else:
                df_lb = pd.DataFrame(leaders)
                view_lb = df_lb[[
                    "name", "email", "favorite_model",
                    "agent_completions", "agent_lines",
                    "tab_completions", "tab_lines", "ai_lines",
                ]].rename(columns={
                    "name": "Name",
                    "email": "Email",
                    "favorite_model": "Favorite model",
                    "agent_completions": "Agent completions",
                    "agent_lines": "Agent lines",
                    "tab_completions": "Tab completions",
                    "tab_lines": "Tab lines",
                    "ai_lines": "AI lines",
                })
                st.markdown(
                    view_lb.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True,
                )

    # ---- High Spenders detail (cards) ----
    with st.expander("High Spenders detail (cards)", expanded=False):
        # Cross-tool view by design — ignore scope so we can rank everyone.
        threshold = st.slider(
            "High-spender threshold ($)", 200, 5000, 1000, 100,
            key="hs_threshold",
        )
        all_spenders = get_high_spenders(
            period_days=f.period_days,
            threshold_usd=0,
            api_key_id=None,
        )
        high = [r for r in all_spenders if r["spend"] >= threshold]
        combined = sum(r["spend"] for r in high)
        top = high[0] if high else None
        total_users = len(all_spenders)
        share_high = (len(high) / total_users * 100) if total_users else 0

        kpi_row([
            {"label": "High spenders",  "value": f"{len(high)} / {total_users}"},
            {"label": "Highest single", "value": fmt_money(top["spend"]) if top else "—"},
            {"label": "Combined spend", "value": fmt_money(combined)},
            {"label": "Share of users", "value": f"{share_high:.0f}%"},
        ])

        if not high:
            st.info(
                f"No users at or above {fmt_money(threshold)} in the period."
            )
        else:
            per_provider_full = get_high_spenders_per_provider(
                period_days=f.period_days
            )
            split_by_user = {r["user_name"]: r for r in per_provider_full}

            section(
                "Notable high spend",
                help="Top 15 high-spenders with per-tool split (GPT + CC + "
                     "Cursor). Border colour = risk level.",
            )
            cards_html = []
            for s in high[:15]:
                spend_v = s["spend"] or 0
                risk = classify_risk(spend_v) or "low"
                border_color = {"high": "#ef4444", "medium": "#f59e0b",
                                "low": "#eab308"}.get(risk, "#94a3b8")
                note = _hs_note(s)
                split = split_by_user.get(s["user_name"])
                split_parts: list[str] = []
                if split:
                    if split.get("cost_openai", 0) > 0:
                        split_parts.append(f"GPT {fmt_money(split['cost_openai'])}")
                    if split.get("cost_anthropic", 0) > 0:
                        split_parts.append(f"CC {fmt_money(split['cost_anthropic'])}")
                    if split.get("cost_cursor", 0) > 0:
                        split_parts.append(f"Cursor {fmt_money(split['cost_cursor'])}")
                split_inline = (
                    f'<div style="color:#94a3b8;font-size:11px;margin-top:4px;">'
                    f'{" + ".join(split_parts)}</div>'
                    if len(split_parts) > 1 else ""
                )
                cards_html.append(
                    f'<div style="border-left:3px solid {border_color};padding:14px 18px;'
                    f'margin-bottom:8px;background:#fcfdff;border-radius:0 12px 12px 0;'
                    f'display:flex;align-items:center;justify-content:space-between;gap:18px;">'
                    f'<div style="min-width:0;">'
                    f'<div style="font-weight:600;color:#06091c;font-size:14px;">{s["user_name"]}</div>'
                    f'<div style="color:#64748b;font-size:12px;margin-top:2px;">'
                    f'{s["messages"]:,} messages · {note}</div>'
                    f'{split_inline}'
                    f'</div>'
                    f'<div style="font-size:18px;font-weight:600;color:{border_color};white-space:nowrap;">'
                    f'{fmt_money(spend_v)}</div>'
                    f'</div>'
                )
            st.markdown("".join(cards_html), unsafe_allow_html=True)

            col_anal, col_rank = st.columns(2)
            with col_anal:
                section("High spend analysis")
                findings = _hs_findings(high)
                if findings:
                    st.markdown(
                        "<ul style='margin:0; padding-left:18px; color:#475569; "
                        "font-size:13px; line-height:1.7'>"
                        + "".join(f"<li>{fnd}</li>" for fnd in findings)
                        + "</ul>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("No notable anomalies detected.")
            with col_rank:
                section("Cross-tool spend ranking")
                ranked = sorted(
                    all_spenders, key=lambda r: r["spend"] or 0, reverse=True
                )[:10]
                if ranked:
                    max_spend_r = max((r["spend"] or 0) for r in ranked) or 1
                    _bar_list(
                        ranked, label_key="user_name", value_key="spend",
                        css_class=lambda r: f"risk-{classify_risk(r['spend']) or 'low'}",
                        max_value=max_spend_r,
                        value_formatter=fmt_money,
                    )

    # ---- Anthropic models — JSON rollup ----
    if _show_anthropic:
        with st.expander("Anthropic models — JSON rollup", expanded=False):
            model_spend = get_anthropic_model_spend_from_json()
            if not model_spend:
                st.caption(
                    "No Anthropic JSON dump on disk — drop a "
                    "sources/Anthropic_*.json file."
                )
            else:
                # Surface the JSON's actual rangeStart/End so users don't
                # think these $-values are filtered by the Period picker.
                _window_note = ""
                try:
                    from data.sources.anthropic_json import latest_anthropic_file as _laf
                    _af = _laf()
                    if _af:
                        import json as _json
                        _meta = _json.loads(
                            _af.path.read_text(encoding="utf-8")
                        ).get("_meta") or {}
                        _start = (_meta.get("rangeStart") or "")[:10]
                        _end = (_meta.get("rangeEnd") or "")[:10]
                        if _start and _end:
                            _window_note = f" Window: {_start} → {_end}."
                except Exception:
                    pass
                st.caption(
                    "Source: `rollups.modelSpend` (all Claude products combined "
                    "— per-product per-model split isn't in the JSON dump)."
                    + _window_note
                )
                df_anm = pd.DataFrame(model_spend)
                df_anm["spend_str"] = df_anm["spend"].apply(fmt_money)
                df_anm["share_str"] = df_anm["share"].apply(lambda v: f"{v:.1f}%")
                view_anm = df_anm[["model", "spend_str", "share_str"]].rename(
                    columns={
                        "model": "Model",
                        "spend_str": "Spend",
                        "share_str": "Share",
                    }
                )
                st.markdown(
                    view_anm.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True,
                )

    # ---- OpenAI top models — full table ----
    if _show_openai:
        with st.expander("OpenAI top models — full table", expanded=False):
            openai_models_full = get_openai_top_models(period_days=f.period_days)
            if not openai_models_full:
                st.caption("No OpenAI events in the window.")
            else:
                df_om = pd.DataFrame(openai_models_full)
                # get_spend_by_model returns {model, spend, requests, users}
                df_om["spend_str"] = df_om["spend"].apply(
                    lambda v: fmt_money(v) if v else "—"
                )
                df_om["requests"] = df_om["requests"].apply(
                    lambda v: fmt_int(int(v))
                )
                view_om = df_om[["model", "requests", "spend_str", "users"]].rename(
                    columns={
                        "model": "Model",
                        "requests": "Requests",
                        "spend_str": "Spend",
                        "users": "Users",
                    }
                )
                st.markdown(
                    view_om.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True,
                )

    # ---- Cursor models ----
    if _show_cursor:
        with st.expander("Cursor models", expanded=False):
            from backend.services.cursor_analytics import model_usage_summary
            cursor_rows = model_usage_summary()
            if not cursor_rows:
                st.caption(
                    "No Cursor model usage. Drop Analytics_Team_*.csv into "
                    "sources/ to populate."
                )
            else:
                df_cm = pd.DataFrame(cursor_rows)
                view_cm = df_cm.rename(columns={
                    "model": "Model",
                    "requests": "Requests",
                    "user_days": "User-days",
                })
                st.markdown(
                    view_cm.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True,
                )

    # ---- Model Landscape (kept at the very bottom by request) ----
    with st.expander("Model Landscape", expanded=False):
        from backend.services.models_svc import get_models_breakdown
        from backend.services.cursor_analytics import model_usage_summary as _mus
        rows_api = get_models_breakdown(f)
        if f.provider and f.provider != "all":
            rows_api = [r for r in rows_api if r["provider"] == f.provider]

        _anth_in_scope = f.provider in ("all", "anthropic")
        anthropic_rollup = (
            get_anthropic_model_spend_from_json() if _anth_in_scope else []
        )
        if anthropic_rollup:
            rows_api = [
                r for r in rows_api
                if not (r["provider"] == "anthropic"
                        and r["model"] == "claude-generic")
            ]
            anth_total_events = next(
                (r["spend"] for r in get_spend_by_model(
                    "anthropic", period_days=f.period_days)
                 if r["model"] == "claude-generic"),
                None,
            )
            rollup_total = sum(m["spend"] for m in anthropic_rollup) or 1
            scale = (anth_total_events / rollup_total) if anth_total_events else 1.0
            for m in anthropic_rollup:
                rows_api.append({
                    "provider": "anthropic",
                    "model": m["model"],
                    "cost": round(m["spend"] * scale, 2),
                    "requests": 0,
                })

        spend_by_provider: dict[str, float] = {}
        for r in rows_api:
            p = r["provider"]
            spend_by_provider[p] = spend_by_provider.get(p, 0) + (r["cost"] or 0)

        _cursor_in_scope = f.provider in ("all", "cursor")
        cursor_rows_ml = _mus() if _cursor_in_scope else []
        cursor_total_reqs = sum(m["requests"] for m in cursor_rows_ml)

        st.caption(
            f"Model landscape — {f.date_range()[0].date()} → "
            f"{f.date_range()[1].date()}. Statuses: DOMINANT (>= 40% of "
            "scope), GROWING (20-40%), ACTIVE (else)."
        )

        items: list[dict[str, Any]] = []
        for r in rows_api:
            share = ((r["cost"] or 0) / spend_by_provider[r["provider"]] * 100
                     if spend_by_provider.get(r["provider"]) else 0)
            tool_label = {
                "anthropic": "Chat + CC",
                "openai":    "ChatGPT",
                "cursor":    "Cursor",
                "github":    "GitHub Copilot",
            }.get(r["provider"], r["provider"].capitalize())
            color_label = {
                "anthropic": "claude",
                "openai":    "chatgpt",
                "cursor":    "cursor",
            }.get(r["provider"], "cursor")
            items.append({
                "_color": color_label,
                "model": r["model"],
                "tool": tool_label,
                "share": share,
                "metric": fmt_money(r["cost"] or 0),
                "metric_note": f"({share:.0f}%)",
                "raw_value": r["cost"] or 0,
            })
        for m in cursor_rows_ml[:10]:
            share = (m["requests"] / cursor_total_reqs * 100) if cursor_total_reqs else 0
            is_claude = "claude" in m["model"].lower()
            items.append({
                "_color": "claude" if is_claude
                          else ("chatgpt" if "gpt" in m["model"].lower() else "cursor"),
                "model": m["model"],
                "tool": "Cursor",
                "share": share,
                "metric": f"{fmt_int(m['requests'])} reqs",
                "metric_note": f"({share:.0f}%)",
                "raw_value": m["requests"],
            })

        def _status(it: dict[str, Any]) -> tuple[str, str]:
            sh = it["share"]
            if sh >= 40:
                return ("DOMINANT", "high")
            if sh >= 20:
                return ("GROWING", "review")
            return ("ACTIVE", "low")

        items.sort(key=lambda x: (-(x["share"] if x["tool"] != "Cursor" else 0),
                                  -x["raw_value"]))

        if not items:
            st.caption("No model activity in the scope.")
        else:
            html_rows = []
            for it in items[:20]:
                status_text, status_kind = _status(it)
                dot_color = {"claude": "#6366f1", "chatgpt": "#10a37f",
                             "cursor": "#f59e0b"}.get(it["_color"], "#94a3b8")
                html_rows.append(
                    f"<tr>"
                    f"<td><span style='display:inline-block;width:8px;height:8px;"
                    f"border-radius:50%;background:{dot_color};margin-right:8px'></span>"
                    f"<code>{it['model']}</code></td>"
                    f"<td>{it['tool']}</td>"
                    f"<td>{badge(status_text, status_kind)}</td>"
                    f"<td><b>{it['metric']}</b> "
                    f"<span style='color:#64748b'>{it['metric_note']}</span></td>"
                    f"</tr>"
                )
            st.markdown(
                f"<table class='hmnd-table'>"
                f"<thead><tr><th>Model</th><th>Tool</th><th>Status</th>"
                f"<th>Spend / Volume</th></tr></thead>"
                f"<tbody>{''.join(html_rows)}</tbody></table>",
                unsafe_allow_html=True,
            )


# =============================================================================
# ENGINEERING TAB (= old tab_devs; tables wrapped in collapsed expanders)
# =============================================================================
with tab_engineering:
    st.caption(
        "Cross-source view — joins each person's git activity with their AI "
        "spend / lines / completions. Source filter is ignored by design."
    )

    from backend.services.git_correlation import (
        get_git_ai_correlation, get_team_ai_share,
    )
    from backend.services.git_quality import (
        get_ai_spend_per_fix, get_high_churn_files, get_quality_per_author,
        get_team_quality,
    )
    from data.sources.git_csv import list_known_repos

    _known_repos = list_known_repos()
    selected_repos: list[str] = []
    if _known_repos:
        selected_repos = st.multiselect(
            "Repositories",
            options=_known_repos,
            default=_known_repos,
            key="devs_repos_filter",
            help="Narrow git-side stats to specific repos. "
                 "Clear all to see only AI activity.",
        )

    # Bots-from-Engineering side-panel: surface who the bots are in this
    # view so it's obvious which segments come from automation.
    devs = get_git_ai_correlation(
        period_days=filters.period_days,
        repos=selected_repos if (selected_repos and _known_repos) else None,
    )
    if devs:
        bots = [r for r in devs if r.get("is_bot")]
        if bots:
            bot_lines = sum(
                int(r.get("git_additions") or 0) for r in bots
            )
            st.markdown(
                f'<div style="border:1px solid #ede9fe;background:#faf5ff;'
                f'border-radius:14px;padding:10px 16px;margin-bottom:10px;'
                f'color:#581c87;font-size:13px;">'
                f'<b>{len(bots)} bot(s) / agents</b> in scope — '
                f'{fmt_int(bot_lines)} lines (100% AI). '
                f'<span style="color:#a78bfa;">'
                f'{", ".join(b["canonical_name"] for b in bots[:6])}'
                f'{"…" if len(bots) > 6 else ""}'
                f'</span></div>',
                unsafe_allow_html=True,
            )

    if not devs:
        st.info(
            "No git authors loaded yet. Drop a `git_authors_YYYYMMDD.csv` into "
            "`sources/` (columns: git_author_name, git_author_emails, repos, "
            "commits, additions, deletions, net_lines, first_commit, last_commit) "
            "or run the extraction script described in docs/."
        )
    else:
        # Top-level KPIs.
        share = get_team_ai_share(
            period_days=filters.period_days,
            repos=selected_repos if (selected_repos and _known_repos) else None,
        )
        counts: dict[str, int] = {}
        for r in devs:
            counts[r["segment"]] = counts.get(r["segment"], 0) + 1
        n_humans = sum(1 for r in devs if not r.get("is_bot"))
        n_bots = sum(1 for r in devs if r.get("is_bot"))

        kpi_row([
            {"label": "Tracked devs",   "value": f"{n_humans} +{n_bots} bots",
             "help": "Unique commit authors found in git this period "
                     "(humans + bots / CI-agents counted separately)."},
            {"label": "Team AI share",  "value": f"{share['ai_share_pct']}%",
             "help": "Share of all new code lines generated by AI. Counts "
                     "every bot commit as 100% AI plus ai_lines from humans "
                     "via Cursor. Healthy AI-first team: 30-60%."},
            {"label": "Bot share",      "value": f"{share['bot_share_pct']}%",
             "help": "Share of total git output written by bots / agents."},
            {"label": "Human AI share", "value": f"{share['human_ai_share_pct']}%",
             "help": "Among HUMAN-only commits, what share of lines came "
                     "via Cursor AI completions."},
        ])
        st.markdown(
            f'<div style="margin:14px 0 4px 0;color:#475569;font-size:13px;">'
            f"AI-generated lines: <b>{fmt_int(share['ai_lines_total'])}</b> of "
            f"<b>{fmt_int(share['total_additions'])}</b> total git additions. "
            f"Bots ({fmt_int(share['bot_additions'])} lines, 100% AI) + Cursor-reported "
            f"AI lines by humans ({fmt_int(min(share['human_ai_lines'], share['human_additions']))} lines). "
            f'<span style="color:#94a3b8;font-style:italic">'
            f"Caveat: human ai_lines is a lifetime total from Cursor "
            f"(not period-filtered); git additions ARE period-filtered."
            f"</span></div>",
            unsafe_allow_html=True,
        )

        # Segment colours + human-readable labels.
        SEGMENT_META = [
            ("HIGH_AI_SPEND_HIGH_GIT_OUTPUT", "High AI · High Output",   "#10b981"),
            ("LOW_AI_SPEND_HIGH_GIT_OUTPUT",  "Low AI · High Output",    "#3b82f6"),
            ("HIGH_AI_LINES_LOW_COMMITS",     "Lots of AI lines, few commits", "#f59e0b"),
            ("HIGH_AI_SPEND_LOW_GIT_OUTPUT",  "High AI · Low Output",    "#ef4444"),
            ("BOT_AUTOMATION",                "Bots / Agents",           "#a855f7"),
            ("AI_ACTIVE_BUT_NO_GIT",          "AI active, no git",       "#94a3b8"),
            ("GIT_ACTIVE_BUT_NO_AI",          "Git active, no AI",       "#cbd5e1"),
            ("NORMAL",                        "Normal",                  "#e2e8f0"),
        ]

        # 1. Stacked-bar segment distribution (chart on top).
        section(
            "Segment distribution",
            help="The team split into 8 buckets by AI spend × git output. "
                 "Ideal: most people in green (High AI · High Output) or "
                 "blue (Low AI · High Output).",
        )
        total_devs = len(devs)
        present = [(s, lbl, c) for s, lbl, c in SEGMENT_META if counts.get(s, 0) > 0]
        bar_segments_html = []
        legend_html = []
        for seg_id, label, color in present:
            n = counts[seg_id]
            pct = n / total_devs * 100 if total_devs else 0
            inside = f'{pct:.0f}%' if pct >= 5 else ''
            bar_segments_html.append(
                f'<div title="{label}: {n} ({pct:.1f}%)" '
                f'style="background:{color};width:{pct:.2f}%;display:flex;'
                f'align-items:center;justify-content:center;color:white;'
                f'font-weight:600;font-size:12px;min-width:0;overflow:hidden;'
                f'white-space:nowrap;">{inside}</div>'
            )
            legend_html.append(
                f'<span style="display:inline-flex;align-items:center;gap:6px;'
                f'margin-right:18px;font-size:13px;color:#475569;">'
                f'<span style="width:10px;height:10px;border-radius:3px;'
                f'background:{color};"></span>'
                f'<span style="color:#06091c;">{label}</span> '
                f'<b style="color:#06091c;">{n}</b> '
                f'<span style="color:#94a3b8;">({pct:.1f}%)</span></span>'
            )
        st.markdown(
            f'<div style="border:1px solid #e8edf3;border-radius:18px;'
            f'padding:18px 22px;background:#fff;margin-bottom:14px;">'
            f'<div style="display:flex;justify-content:space-between;'
            f'align-items:center;margin-bottom:10px;">'
            f'<div style="font-weight:600;color:#06091c;">Distribution</div>'
            f'<div style="color:#64748b;font-size:12px;">Total '
            f'<b style="color:#06091c">{total_devs} devs</b></div>'
            f'</div>'
            f'<div style="display:flex;height:36px;border-radius:8px;'
            f'overflow:hidden;background:#f1f5f9;">{"".join(bar_segments_html)}</div>'
            f'<div style="margin-top:12px;display:flex;flex-wrap:wrap;'
            f'gap:6px 0;">{"".join(legend_html)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ---------------- Code Quality (Git × AI) ----------------
        repo_arg = selected_repos if (selected_repos and _known_repos) else None
        tq = get_team_quality(period_days=filters.period_days, repos=repo_arg)
        section(
            "Code Quality (Git × AI)",
            help="Code health through an AI lens: % of commits that are "
                 "bug-fixes, the gap between human and bot bug-rate, and "
                 "$ per bug-fix.",
        )
        if tq["commits"] == 0:
            scope_msg = (
                f"selected repos ({', '.join(repo_arg)})"
                if repo_arg else "all repos"
            )
            st.info(
                f"No commits in **{scope_msg}** within the last "
                f"**{filters.period_days} days**. "
                f"Either widen the period (try 90 or 365 days) or pick "
                f"different repos."
            )
        if tq["commits"] > 0:
            st.caption(
                "Subject-line regex classification on commit messages "
                "(`fix:`, `Revert \"…\"`, `feat:`, `refactor:`, …). Directional "
                "signal — captures self-declared bug-fixes, not severity."
            )
            kpi_row([
                {"label": "Commits", "value": fmt_int(tq["commits"]),
                 "help": "Total commits across selected repos this period."},
                {"label": "Bug-fix rate",
                 "value": f"{tq['bug_rate_pct']:.1f}%" if tq["bug_rate_pct"] is not None else "—",
                 "help": "Share of commits that are bug-fixes. Healthy: 15-25%."},
                {"label": "Human bug rate",
                 "value": f"{tq['human_bug_rate_pct']:.1f}%"
                          if tq["human_bug_rate_pct"] is not None else "—",
                 "help": "Bug-fix rate among human-authored commits."},
                {"label": "Bot bug rate",
                 "value": f"{tq['bot_bug_rate_pct']:.1f}%"
                          if tq["bot_bug_rate_pct"] is not None else "—",
                 "help": "Bug-fix rate among bot / CI-agent commits."},
            ])

            # Composition strip: features vs fixes vs refactors vs tests vs docs.
            tags_total = (tq["fixes"] + tq["features"] + tq["refactors"]
                          + tq["tests"] + tq["docs"] + tq["reverts"])
            if tags_total > 0:
                parts = [
                    ("Features",  tq["features"],  "#10b981"),
                    ("Bug fixes", tq["fixes"],     "#ef4444"),
                    ("Refactors", tq["refactors"], "#6366f1"),
                    ("Tests",     tq["tests"],     "#f59e0b"),
                    ("Docs",      tq["docs"],      "#94a3b8"),
                    ("Reverts",   tq["reverts"],   "#0f172a"),
                ]
                bar_html_q = []
                legend_html_q = []
                for label, n, color in parts:
                    if n <= 0:
                        continue
                    pct = n / tags_total * 100
                    inside = f"{pct:.0f}%" if pct >= 5 else ""
                    bar_html_q.append(
                        f'<div title="{label}: {n} ({pct:.1f}%)" '
                        f'style="background:{color};width:{pct:.2f}%;display:flex;'
                        f'align-items:center;justify-content:center;color:white;'
                        f'font-weight:600;font-size:12px;min-width:0;overflow:hidden;'
                        f'white-space:nowrap;">{inside}</div>'
                    )
                    legend_html_q.append(
                        f'<span style="display:inline-flex;align-items:center;gap:6px;'
                        f'margin-right:18px;font-size:13px;color:#475569;">'
                        f'<span style="width:10px;height:10px;border-radius:3px;'
                        f'background:{color};"></span>'
                        f'<span style="color:#06091c;">{label}</span> '
                        f'<b style="color:#06091c;">{fmt_int(n)}</b> '
                        f'<span style="color:#94a3b8;">({pct:.1f}%)</span></span>'
                    )
                st.markdown(
                    f'<div style="border:1px solid #e8edf3;border-radius:18px;'
                    f'padding:18px 22px;background:#fff;margin:14px 0;">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center;margin-bottom:10px;">'
                    f'<div style="font-weight:600;color:#06091c;">Commit composition</div>'
                    f'<div style="color:#64748b;font-size:12px;">Tagged '
                    f'<b style="color:#06091c">{fmt_int(tags_total)}</b> of '
                    f'{fmt_int(tq["commits"])} commits (multi-tag possible)</div>'
                    f'</div>'
                    f'<div style="display:flex;height:32px;border-radius:8px;'
                    f'overflow:hidden;background:#f1f5f9;">{"".join(bar_html_q)}</div>'
                    f'<div style="margin-top:12px;display:flex;flex-wrap:wrap;'
                    f'gap:6px 0;">{"".join(legend_html_q)}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # $/fix debt indicator + AI vs human breakdown side-by-side
            col_cost, col_breakdown = st.columns(2)
            with col_cost:
                section(
                    "AI spend per bug-fix",
                    help="$ of AI rent per bug-fix commit (team-wide AI "
                         "spend / team-wide bug-fix commit count). "
                         "Green < $100, orange $100-500, red >= $500.",
                )
                spf = get_ai_spend_per_fix(
                    period_days=min(filters.period_days, 90),
                )
                spend_val = spf["ai_spend_per_fix"]
                spend_txt = fmt_money(spend_val) if spend_val is not None else "—"
                spend_color = (
                    "#ef4444" if spend_val is not None and spend_val >= 500 else
                    "#f59e0b" if spend_val is not None and spend_val >= 100 else
                    "#10b981" if spend_val is not None else
                    "#94a3b8"
                )
                st.markdown(
                    f'<div style="border:1px solid #e8edf3;border-radius:18px;'
                    f'padding:22px;background:#fff;">'
                    f'<div style="font-size:11px;color:#64748b;text-transform:uppercase;'
                    f'letter-spacing:.12em;margin-bottom:8px;">'
                    f'AI $ per bug-fix ({spf["period_days"]}d)</div>'
                    f'<div style="font-size:34px;font-weight:300;color:{spend_color};">'
                    f'{spend_txt}</div>'
                    f'<div style="color:#475569;font-size:13px;margin-top:10px;">'
                    f'{fmt_money(spf["ai_spend"])} AI spend · '
                    f'{fmt_int(spf["fixes"])} bug-fix commits'
                    f'</div>'
                    f'<div style="color:#94a3b8;font-size:12px;margin-top:6px;'
                    f'font-style:italic;">High $/fix => team debugs heavily '
                    f'with AI or AI-generated code needs many fixes.</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with col_breakdown:
                section(
                    "AI vs human bug rate",
                    help="Side-by-side bug-rate for bots/agents vs humans.",
                )
                hrate = tq["human_bug_rate_pct"]
                brate = tq["bot_bug_rate_pct"]
                hmax = max(hrate or 0, brate or 0, 1)

                def _qbar(label: str, val: float | None, color: str, count: int) -> str:
                    if val is None:
                        return (
                            f'<div style="margin-bottom:12px;">'
                            f'<div style="display:flex;justify-content:space-between;'
                            f'font-size:13px;color:#475569;margin-bottom:4px;">'
                            f'<span>{label}</span><span>—</span></div>'
                            f'<div style="background:#f1f5f9;height:14px;'
                            f'border-radius:7px;"></div>'
                            f'<div style="color:#94a3b8;font-size:12px;margin-top:2px;">'
                            f'no commits in window</div></div>'
                        )
                    pct = max(2, (val / hmax) * 100)
                    return (
                        f'<div style="margin-bottom:12px;">'
                        f'<div style="display:flex;justify-content:space-between;'
                        f'font-size:13px;color:#475569;margin-bottom:4px;">'
                        f'<span>{label}</span>'
                        f'<b style="color:#06091c;">{val:.1f}%</b></div>'
                        f'<div style="background:#f1f5f9;height:14px;border-radius:7px;'
                        f'overflow:hidden;">'
                        f'<div style="background:{color};height:100%;width:{pct:.2f}%;'
                        f'border-radius:7px;"></div></div>'
                        f'<div style="color:#94a3b8;font-size:12px;margin-top:2px;">'
                        f'{fmt_int(count)} commits in scope</div></div>'
                    )

                st.markdown(
                    f'<div style="border:1px solid #e8edf3;border-radius:18px;'
                    f'padding:22px;background:#fff;">'
                    + _qbar("Humans", hrate, "#3b82f6", tq["human_commits"])
                    + _qbar("Bots / agents", brate, "#a855f7", tq["bot_commits"])
                    + '</div>',
                    unsafe_allow_html=True,
                )

            # Per-author bug-fix breakdown (table → expander)
            with st.expander("Per-author bug-fix breakdown", expanded=False):
                quality_rows = get_quality_per_author(
                    period_days=filters.period_days, repos=repo_arg, limit=50,
                )
                if not quality_rows:
                    st.caption("No commits in the selected window / repos.")
                else:
                    qdf = pd.DataFrame(quality_rows)

                    def _qpct(v):
                        if v is None or (isinstance(v, float) and v != v):
                            return "—"
                        return f"{v:.1f}%"

                    view_q = pd.DataFrame({
                        "Name":         qdf["canonical_name"],
                        "Kind":         qdf["is_bot"].map(
                            lambda b: "bot" if b else "human"
                        ),
                        "Commits":      qdf["commits"].map(lambda v: fmt_int(int(v))),
                        "Bug-fixes":    qdf["fixes"].map(lambda v: fmt_int(int(v))),
                        "Reverts":      qdf["reverts"].map(lambda v: fmt_int(int(v))),
                        "Features":     qdf["features"].map(lambda v: fmt_int(int(v))),
                        "Refactors":    qdf["refactors"].map(lambda v: fmt_int(int(v))),
                        "Tests":        qdf["tests"].map(lambda v: fmt_int(int(v))),
                        "Bug rate":     qdf["bug_rate_pct"].map(_qpct),
                        "Revert rate":  qdf["revert_rate_pct"].map(_qpct),
                    })
                    st.markdown(
                        view_q.to_html(escape=False, index=False, classes="hmnd-table"),
                        unsafe_allow_html=True,
                    )

            # High-churn files (table → expander)
            churn = get_high_churn_files(
                period_days=filters.period_days, repos=repo_arg, limit=15,
            )
            if churn:
                with st.expander("High-churn files (problem areas)", expanded=False):
                    st.caption(
                        "Files most often touched in the window — proxy for "
                        "hot spots worth refactor attention or extra review."
                    )
                    cdf = pd.DataFrame(churn)
                    view_c = pd.DataFrame({
                        "File":      cdf["file"],
                        "Commits":   cdf["commits"].map(lambda v: fmt_int(int(v))),
                        "+lines":    cdf["additions"].map(lambda v: fmt_int(int(v))),
                        "-lines":    cdf["deletions"].map(lambda v: fmt_int(int(v))),
                        "Repos":     cdf["repos"],
                    })
                    st.markdown(
                        view_c.to_html(escape=False, index=False, classes="hmnd-table"),
                        unsafe_allow_html=True,
                    )

        # ------------- Drill into segments -------------
        section(
            "Drill into segments",
            help="Per-segment detail. Pick segments to render below as "
                 "individual expandable tables.",
        )
        seg_options = [s for s, _, _ in SEGMENT_META if counts.get(s, 0) > 0]
        seg_labels_map = {s: lbl for s, lbl, _ in SEGMENT_META}
        seg_colors_map = {s: c for s, _, c in SEGMENT_META}
        picked_segments = st.multiselect(
            "Show tables for:",
            options=seg_options,
            default=seg_options,
            format_func=lambda s: f"{seg_labels_map[s]}  ({counts.get(s, 0)})",
            key="devs_segments_filter",
            help="Pick one or more segments to render their developers as "
                 "individual tables.",
        )

        def _money(v):
            if v is None or (isinstance(v, float) and v != v):
                return "—"
            return fmt_money(v) if v > 0 else "—"

        def _num(v):
            if v is None or (isinstance(v, float) and v != v):
                return "0"
            return fmt_int(int(v)) if v else "0"

        def _pct(v):
            if v is None or (isinstance(v, float) and v != v):
                return "—"
            return f"{v:.0f}%"

        def _ratio(v):
            if v is None or (isinstance(v, float) and v != v):
                return "—"
            return f"{v:.0f}"

        df_all = pd.DataFrame(devs)
        if df_all.empty or not picked_segments:
            st.caption("No segments selected — pick at least one above.")
        else:
            for seg_id in picked_segments:
                seg_devs = [r for r in devs if r["segment"] == seg_id]
                if not seg_devs:
                    continue
                color = seg_colors_map[seg_id]
                label = seg_labels_map[seg_id]
                with st.expander(
                    f"{label} — {len(seg_devs)} devs "
                    f"({len(seg_devs)/total_devs*100:.1f}% of team)",
                    expanded=False,
                ):
                    # Colored header for context inside the expander.
                    st.markdown(
                        f'<div style="display:flex;align-items:center;gap:10px;'
                        f'margin:0 0 8px 0;border-left:4px solid {color};'
                        f'padding:6px 12px;background:{color}1a;border-radius:0 8px 8px 0;">'
                        f'<span style="font-weight:600;color:#06091c;font-size:15px;">'
                        f'{label}</span></div>',
                        unsafe_allow_html=True,
                    )
                    seg_df = pd.DataFrame(seg_devs)
                    view = pd.DataFrame({
                        "Name":           seg_df["canonical_name"],
                        "AI cost":        seg_df["ai_cost_usd"].map(_money),
                        "AI lines":       seg_df["ai_lines"].map(_num),
                        "Commits":        seg_df["commits"].map(_num),
                        "Git +lines":     seg_df["git_additions"].map(_num),
                        "Git -lines":     seg_df["git_deletions"].map(_num),
                        "AI share %":     seg_df["ai_share_of_additions"].map(_pct),
                        "$/commit":       seg_df["cost_per_commit"].map(_money),
                        "$/1k git adds":  seg_df["cost_per_1000_git_additions"].map(_money),
                        "ailines/commit": seg_df["ai_lines_per_commit"].map(_ratio),
                        "Repos":          seg_df["repos"],
                    })
                    st.markdown(
                        view.to_html(escape=False, index=False, classes="hmnd-table"),
                        unsafe_allow_html=True,
                    )


# =============================================================================
# PEOPLE TAB — per-person profile (F-20)
# =============================================================================
with tab_people:
    from data.db import get_conn as _gc_p
    f = filters  # noqa: F821 — provided by main.py exec scope
    s_iso = f.date_range()[0].strftime("%Y-%m-%d %H:%M:%S")
    e_iso = f.date_range()[1].strftime("%Y-%m-%d %H:%M:%S")

    # ── 1. Dropdown (every user, ordered by lifetime total spend) ──────────
    with _gc_p() as _conn_p:
        people_rows = _conn_p.execute(
            """SELECT u.id, u.full_name, u.email,
                      COALESCE(ROUND(SUM(ue.cost_usd), 2), 0) AS total_spend
               FROM users u
               LEFT JOIN usage_events ue ON ue.user_id = u.id
               GROUP BY u.id
               ORDER BY total_spend DESC, u.full_name"""
        ).fetchall()
    people = [dict(r) for r in people_rows]

    if not people:
        st.info("No users in the database yet. Run sync to populate.")
    else:
        def _label(p: dict) -> str:
            ts = float(p["total_spend"] or 0)
            return f"{p['full_name']} — {fmt_money(ts)}" if ts > 0 else p["full_name"]

        selected_id = st.selectbox(
            "Person",
            options=[p["id"] for p in people],
            format_func=lambda uid: _label(next(p for p in people if p["id"] == uid)),
            key="people_user_id",
        )
        person = next(p for p in people if p["id"] == selected_id)

        # ── 2. Period-scoped queries for this person (Source filter ignored) ─
        with _gc_p() as _conn_p:
            # per-tool split
            tool_rows = _conn_p.execute(
                """SELECT p.name AS provider,
                          COALESCE(ROUND(SUM(ue.cost_usd), 2), 0) AS spend,
                          COUNT(*)                                 AS reqs,
                          COALESCE(SUM(ue.tokens_in), 0)           AS tokens_in,
                          COALESCE(SUM(ue.tokens_out), 0)          AS tokens_out
                   FROM usage_events ue
                   JOIN providers p ON p.id = ue.provider_id
                   WHERE ue.user_id = ? AND ue.occurred_at BETWEEN ? AND ?
                     AND (? IS NULL OR ue.api_key_id = ?)
                   GROUP BY p.name
                   ORDER BY spend DESC""",
                (selected_id, s_iso, e_iso, f.api_key_id, f.api_key_id),
            ).fetchall()
            top_models = _conn_p.execute(
                """SELECT m.name AS model, p.name AS provider,
                          COALESCE(ROUND(SUM(ue.cost_usd), 2), 0) AS spend,
                          COUNT(*) AS reqs
                   FROM usage_events ue
                   JOIN models m   ON m.id = ue.model_id
                   JOIN providers p ON p.id = ue.provider_id
                   WHERE ue.user_id = ? AND ue.occurred_at BETWEEN ? AND ?
                     AND (? IS NULL OR ue.api_key_id = ?)
                   GROUP BY m.id
                   ORDER BY spend DESC
                   LIMIT 10""",
                (selected_id, s_iso, e_iso, f.api_key_id, f.api_key_id),
            ).fetchall()
            daily_rows = _conn_p.execute(
                """SELECT date(ue.occurred_at) AS day, p.name AS provider,
                          COALESCE(ROUND(SUM(ue.cost_usd), 2), 0) AS cost,
                          COUNT(*)                                 AS reqs
                   FROM usage_events ue
                   JOIN providers p ON p.id = ue.provider_id
                   WHERE ue.user_id = ? AND ue.occurred_at BETWEEN ? AND ?
                     AND (? IS NULL OR ue.api_key_id = ?)
                   GROUP BY day, provider
                   ORDER BY day""",
                (selected_id, s_iso, e_iso, f.api_key_id, f.api_key_id),
            ).fetchall()
            purpose_rows = _conn_p.execute(
                """SELECT COALESCE(ue.purpose, '—') AS purpose,
                          COUNT(*) AS reqs,
                          COALESCE(ROUND(SUM(ue.cost_usd), 2), 0) AS spend
                   FROM usage_events ue
                   WHERE ue.user_id = ? AND ue.occurred_at BETWEEN ? AND ?
                     AND (? IS NULL OR ue.api_key_id = ?)
                   GROUP BY purpose
                   ORDER BY reqs DESC""",
                (selected_id, s_iso, e_iso, f.api_key_id, f.api_key_id),
            ).fetchall()
            events_rows = _conn_p.execute(
                """SELECT ue.occurred_at, p.name AS provider, m.name AS model,
                          ue.purpose, ue.tokens_in, ue.tokens_out,
                          ROUND(ue.cost_usd, 4) AS cost
                   FROM usage_events ue
                   JOIN providers p ON p.id = ue.provider_id
                   JOIN models m    ON m.id = ue.model_id
                   WHERE ue.user_id = ? AND ue.occurred_at BETWEEN ? AND ?
                     AND (? IS NULL OR ue.api_key_id = ?)
                   ORDER BY ue.occurred_at DESC
                   LIMIT 100""",
                (selected_id, s_iso, e_iso, f.api_key_id, f.api_key_id),
            ).fetchall()
            team_row = _conn_p.execute(
                "SELECT t.name AS team FROM users u "
                "LEFT JOIN teams t ON t.id = u.team_id WHERE u.id = ?",
                (selected_id,),
            ).fetchone()

        # ── 3. Top-of-page profile card ───────────────────────────────────
        per_tool = {r["provider"]: dict(r) for r in tool_rows}
        period_spend = sum(float(t.get("spend") or 0) for t in per_tool.values())
        period_reqs  = sum(int(t.get("reqs") or 0) for t in per_tool.values())
        days_active  = len({r["day"] for r in daily_rows})
        top_tool_name = max(per_tool.values(), key=lambda r: r["spend"], default={}).get("provider", "—")
        team_name = team_row["team"] if team_row and team_row["team"] else "—"

        st.markdown(
            f"""
            <div style="border:1px solid #e8edf3;border-radius:18px;padding:22px 26px;
                        background:linear-gradient(180deg,#fff 0%,#fcfdff 100%);margin-bottom:14px;">
                <div style="font-size:24px;font-weight:500;color:#06091c;">{person['full_name']}</div>
                <div style="color:#64748b;font-size:13px;margin-top:4px;">
                    {person['email']} · team <b style="color:#06091c">{team_name}</b>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        kpi_row([
            {"label": "Period spend",  "value": fmt_money(period_spend),
             "help": f"This person's AI spend in the active period "
                     f"({f.period_days} d window). All tools combined."},
            {"label": "Period reqs",   "value": _fmt_int(period_reqs),
             "help": "All messages / API requests / completions."},
            {"label": "Top tool",      "value": top_tool_name.title() if top_tool_name != "—" else "—",
             "help": "Provider with the highest spend by this person."},
            {"label": "Active days",   "value": str(days_active),
             "help": "Number of distinct calendar days with ≥1 event."},
        ])

        # 3 sub-cards — Claude / ChatGPT / Cursor share
        def _sub_card(color: str, label: str, p: str) -> str:
            v = per_tool.get(p, {"spend": 0, "reqs": 0})
            share = (v["spend"] / period_spend * 100) if period_spend else 0
            return f"""
                <div style="border:1px solid #e8edf3;border-top:3px solid {color};border-radius:18px;
                            padding:14px 18px;background:#fff;height:100%;">
                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.12em;margin-bottom:6px;">
                        {label}
                    </div>
                    <div style="font-size:22px;line-height:1;font-weight:300;color:#06091c;">
                        {fmt_money(v["spend"])}
                    </div>
                    <div style="font-size:12px;color:#475569;margin-top:8px;">
                        {v["reqs"]:,} reqs · {share:.1f}% of total
                    </div>
                </div>
            """
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(_sub_card("#6366f1", "Claude",  "anthropic"), unsafe_allow_html=True)
        with c2: st.markdown(_sub_card("#10a37f", "ChatGPT", "openai"),    unsafe_allow_html=True)
        with c3: st.markdown(_sub_card("#f59e0b", "Cursor",  "cursor"),    unsafe_allow_html=True)

        # ── 4. Charts ─────────────────────────────────────────────────────
        section(
            "Daily spend",
            help="Per-day spend stacked by provider. Spikes can indicate "
                 "automation kicked in or a one-off heavy task.",
        )
        if daily_rows:
            df_daily = pd.DataFrame([dict(r) for r in daily_rows])
            df_daily["day"] = pd.to_datetime(df_daily["day"])
            color_map = {"anthropic": "#6366f1", "openai": "#10a37f", "cursor": "#f59e0b"}
            fig = px.bar(
                df_daily, x="day", y="cost", color="provider",
                color_discrete_map=color_map, barmode="stack",
            )
            fig.update_layout(
                plot_bgcolor="white", paper_bgcolor="white",
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(family="Inter", color=NAVY),
                xaxis=dict(showgrid=False),
                yaxis=dict(gridcolor="#e8edf3", title="$ per day"),
                legend_title_text="",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No events for this person in the active period.")

        col_models, col_purpose = st.columns(2)
        with col_models:
            section(
                "Top models (this person)",
                help="The models they actually drive — by spend, top 10.",
            )
            if top_models:
                def _model_color(r):
                    p = (r.get("provider") or "").lower()
                    return {"anthropic": "claude", "openai": "chatgpt"}.get(p, "cursor")
                _bar_list(
                    [dict(r) for r in top_models],
                    label_key="model", value_key="spend",
                    css_class=_model_color, value_formatter=fmt_money,
                )
            else:
                st.caption("No model usage in the active period.")
        with col_purpose:
            section(
                "Activity by purpose",
                help="What KIND of work they're doing with AI: Chat / Agent / "
                     "API / Tab / etc. Useful for separating chatbox usage "
                     "from agentic / automated workflows.",
            )
            if purpose_rows:
                _bar_list(
                    [dict(r) for r in purpose_rows],
                    label_key="purpose", value_key="reqs",
                    css_class="cursor", value_formatter=fmt_int,
                )
            else:
                st.caption("No purpose-tagged events in the active period.")

        # ── 5. Expandable tables (collapsed by default) ───────────────────
        with st.expander("All events (last 100)", expanded=False):
            if events_rows:
                df_ev = pd.DataFrame([dict(r) for r in events_rows])
                df_ev["cost"] = df_ev["cost"].apply(lambda v: fmt_money(float(v) if v else 0))
                df_ev = df_ev.rename(columns={
                    "occurred_at": "When", "provider": "Provider",
                    "model": "Model", "purpose": "Purpose",
                    "tokens_in": "Tokens in", "tokens_out": "Tokens out",
                    "cost": "Cost",
                })
                st.markdown(
                    df_ev.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True,
                )
            else:
                st.caption("No events in the active period.")

        with st.expander("Daily activity (per provider)", expanded=False):
            if daily_rows:
                df_d = pd.DataFrame([dict(r) for r in daily_rows])
                df_d["cost"] = df_d["cost"].apply(lambda v: fmt_money(float(v) if v else 0))
                df_d = df_d.rename(columns={
                    "day": "Day", "provider": "Provider",
                    "cost": "Cost", "reqs": "Reqs",
                })
                st.markdown(
                    df_d.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True,
                )
            else:
                st.caption("No daily breakdown.")

        with st.expander("Cursor leaderboard row (lifetime, from CSV/JSON)", expanded=False):
            from backend.services.cursor_analytics import load_user_leaderboard as _llb_p
            ld = next(
                (r for r in _llb_p() if (r.get("email") or "").lower()
                 == (person["email"] or "").lower()),
                None,
            )
            if ld:
                rows_h = [
                    ("Email",             ld.get("email", "—")),
                    ("Favorite model",    ld.get("favorite_model", "—")),
                    ("Agent completions", _fmt_int(ld.get("agent_completions", 0))),
                    ("Agent lines",       _fmt_int(ld.get("agent_lines", 0))),
                    ("Tab completions",   _fmt_int(ld.get("tab_completions", 0))),
                    ("Tab lines",         _fmt_int(ld.get("tab_lines", 0))),
                    ("AI lines total",    _fmt_int(ld.get("ai_lines", 0))),
                ]
                st.markdown(
                    "<table class='hmnd-table'><tbody>"
                    + "".join(
                        f"<tr><td style='color:#475569'>{k}</td>"
                        f"<td style='text-align:right;font-weight:600'>{v}</td></tr>"
                        for k, v in rows_h
                    )
                    + "</tbody></table>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption(
                    "This person is not in the latest Cursor leaderboard "
                    "export. If they use Cursor, drop the latest "
                    "`Cursor_*.json` into `sources/` and re-sync."
                )
