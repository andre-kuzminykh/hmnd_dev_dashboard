"""F-12 AI Tools Dashboard — tool-centric tabs."""
from __future__ import annotations

from typing import Iterable

import pandas as pd
import streamlit as st

from backend.services.ai_tools import (
    chatgpt_flag,
    classify_risk,
    get_ai_tools_overview,
    get_anthropic_model_spend_from_json,
    get_anthropic_spend_by_purpose,
    get_cursor_completion_split,
    get_high_spenders,
    get_high_spenders_per_provider,
    get_openai_top_models,
    get_provider_freshness,
    get_spend_by_model,
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
# This file is now sourced into overview.py's globals via main.py — hero,
# freshness chips and the filters bar are rendered by Overview ABOVE this
# tabbed section, so we don't re-render them. The `filters` variable below
# is the Filters object already set by overview.py.
section("AI Tools")

(tab_overview, tab_claude, tab_cc, tab_gpt, tab_cursor,
 tab_models, tab_devs, tab_high) = st.tabs([
    "Overview", "Claude Users", "Claude Code", "ChatGPT",
    "Cursor", "Models", "Devs (Git × AI)", "⚠ High Spenders",
])


with tab_overview:
    # Spend breakdown across the three tools — respects the Source filter.
    # When Source is narrowed (e.g. 'OpenAI · Artem'), zero out the
    # other-provider stats so the user sees ONLY the scope they picked.
    from data.db import get_conn as _gc
    f = filters
    s_iso = f.date_range()[0].strftime("%Y-%m-%d %H:%M:%S")
    e_iso = f.date_range()[1].strftime("%Y-%m-%d %H:%M:%S")
    _scope = (f.provider or "all").lower()
    _show_anthropic = _scope in ("all", "anthropic")
    _show_openai    = _scope in ("all", "openai")
    _show_cursor    = _scope in ("all", "cursor")
    # Apply org filter to OpenAI as well (scope = 'openai' + organization='Artem')
    _org_clause = ""
    _org_params: list = []
    if f.organization and f.organization != "all":
        _org_clause = " AND ue.organization_id IN (SELECT id FROM organizations WHERE label = ?) "
        _org_params = [f.organization]
    # Also honour the API-key narrowing so 'ceo_brain_prod' on Source=Artem
    # narrows the AI Tools Overview tab to that key, just like the top KPIs.
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

    # Cursor: real spend comes from usage_events (cursor JSON loader writes
    # spendCents + includedSpendCents). Leaderboard is used only for the
    # completion / AI lines counters that don't have an events-equivalent.
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
                                color:white;font-weight:600;font-size:13px;">
                        {cp:.1f}%
                    </div>
                    <div style="background:#10a37f;width:{gp:.2f}%;display:flex;align-items:center;justify-content:center;
                                color:white;font-weight:600;font-size:13px;">
                        {gp:.1f}%
                    </div>
                    <div style="background:#f59e0b;width:{crp:.2f}%;display:flex;align-items:center;justify-content:center;
                                color:white;font-weight:600;font-size:13px;">
                        {crp:.1f}%
                    </div>
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

    # Tool cards with coloured top borders
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

    # Top spenders all tools + Usage summary
    col_top, col_summary = st.columns(2)
    with col_top:
        section("Top Spenders — All Tools")
        if _scope != "all":
            st.caption(
                "ℹ️ Cross-tool ranking — ignores Source filter by design "
                "(ranks people across OpenAI + Anthropic + Cursor together)."
            )
        spenders = get_high_spenders(period_days=f.period_days, threshold_usd=0,
                                     api_key_id=None)
        top10 = spenders[:10]
        if top10:
            max_spend = max(r["spend"] for r in top10) or 1
            _bar_list(
                top10, label_key="user_name", value_key="spend",
                css_class=lambda r: f"risk-{classify_risk(r['spend']) or 'low'}",
                max_value=max_spend, value_formatter=fmt_money,
            )
        else:
            st.caption("No spend recorded yet — run sync from VM.")

    with col_summary:
        section("Usage Summary")
        usage_rows = [
            {"tool": "Claude (all products)",
             "users": _claude_spend["u"],
             "activity": f"{_claude_spend['c']:,} reqs",
             "spend": fmt_money(claude_v)},
            {"tool": "ChatGPT",
             "users": _gpt_spend["u"],
             "activity": f"{_gpt_spend['c']:,} msgs",
             "spend": fmt_money(gpt_v)},
            {"tool": "Cursor",
             "users": _cursor_devs,
             "activity": f"{_cursor_completions:,} completions",
             "spend": fmt_money(cursor_v)},
        ]
        df = pd.DataFrame(usage_rows)
        view = df.rename(columns={
            "tool": "Tool", "users": "Users",
            "activity": "Activity", "spend": "Spend"
        })
        st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True)


with tab_claude:
    if filters.provider not in ("all", "anthropic", "cursor"):
        st.info(
            f"Claude Users tab is sourced from Cursor leaderboard (favorite_model "
            f"contains 'claude'). Source filter '{filters.provider}' doesn't apply "
            f"here — switch to 'All sources' or 'Anthropic' / 'Cursor'."
        )
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
            {"label": "Claude users",       "value": str(len(claude_rows))},
            {"label": "Total AI lines",     "value": fmt_int(total_ai_lines)},
            {"label": "Total completions",  "value": fmt_int(total_completions)},
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

        # Claude Products Breakdown — split Anthropic spend across Chat /
        # Claude Code (Agent) / Cowork+Other.
        purposes = get_anthropic_spend_by_purpose(period_days=filters.period_days)
        if purposes:
            section("Claude Products Breakdown")
            # Group into 3 buckets to match the design:
            #   Chat            -> "Chat"
            #   Agent           -> "Claude Code"
            #   the rest        -> "Cowork + Other"
            grouped: dict[str, dict] = {"Chat": {}, "Claude Code": {}, "Cowork + Other": {}}
            for p in purposes:
                key = {"Chat": "Chat", "Agent": "Claude Code"}.get(
                    p["purpose"], "Cowork + Other"
                )
                g = grouped.setdefault(key, {"spend": 0.0, "requests": 0, "users": 0})
                g["spend"] = (g.get("spend") or 0) + (p["spend"] or 0)
                g["requests"] = (g.get("requests") or 0) + (p["requests"] or 0)
                g["users"] = max(g.get("users") or 0, p["users"] or 0)
            colors = {"Chat": "#a5b4fc", "Claude Code": "#6366f1", "Cowork + Other": "#c7d2fe"}
            cols = st.columns(3)
            for col, (label, g) in zip(cols, grouped.items()):
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

        section("All Claude Users")
        # Drop zero-activity rows — Cursor leaderboard surfaces members who
        # picked Claude as favorite but generated no actual lines/completions
        # this period. Showing them as 0/0/0/0/0 looks like a bug.
        active_claude_rows = [
            r for r in claude_rows
            if (int(r.get("ai_lines") or 0) > 0
                or int(r.get("agent_completions") or 0) > 0
                or int(r.get("tab_completions") or 0) > 0)
        ]
        df = pd.DataFrame(active_claude_rows)
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


with tab_cc:
    if filters.provider not in ("all", "anthropic"):
        st.info(
            f"Claude Code tab shows Anthropic events (purpose='Agent'). "
            f"Source filter '{filters.provider}' has no Claude Code data — "
            f"switch to 'All sources' or 'Anthropic'."
        )
    # Claude Code = Anthropic events with purpose 'Agent' (synthesised from
    # Cursor leaderboard's agent_completions) — see data/cursor_to_anthropic.
    from data.db import get_conn
    from backend.analytics import api_key_clause as _api_key_clause
    f = filters
    s, e = f.date_range()
    k_clause, k_params = _api_key_clause(f.api_key_id, "ue")
    sql = f"""
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
            sql,
            [s.strftime("%Y-%m-%d %H:%M:%S"), e.strftime("%Y-%m-%d %H:%M:%S")] + k_params,
        ).fetchall()]

    total_reqs = sum(r["requests"] for r in cc_rows)
    total_spend = sum(r["spend"] or 0 for r in cc_rows)
    top_spender = cc_rows[0] if cc_rows else None
    # CC share of Anthropic
    with get_conn() as conn:
        all_anthropic_spend = conn.execute(
            """SELECT ROUND(SUM(ue.cost_usd), 2) AS s
               FROM usage_events ue
               JOIN providers p ON p.id = ue.provider_id
               WHERE p.name='anthropic' AND ue.occurred_at BETWEEN ? AND ?""",
            (s.strftime("%Y-%m-%d %H:%M:%S"), e.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchone()["s"] or 0
    cc_share = (total_spend / all_anthropic_spend * 100) if all_anthropic_spend > 0 else 0.0

    kpi_row([
        {"label": "CC Requests", "value": _fmt_int(total_reqs)},
        {"label": "CC Spend", "value": fmt_money(total_spend)},
        {"label": "Top Spender",
         "value": fmt_money(top_spender['spend']) if top_spender else "—"},
        {"label": "Avg / user",
         "value": fmt_money(total_spend / max(len(cc_rows), 1)) if cc_rows else "—"},
    ])

    if cc_rows:
        section("Top Claude Code Users by spend")
        _bar_list(cc_rows[:15], label_key="name", value_key="spend",
                  css_class="claude", value_formatter=fmt_money)
        # 80/20 footer
        top5_spend = sum(r["spend"] or 0 for r in cc_rows[:5])
        share = (top5_spend / total_spend * 100) if total_spend > 0 else 0.0
        st.markdown(
            f"<div style='margin-top:8px;color:#475569;font-size:13px'>"
            f"Top 5 account for <b style='color:#06091c'>{fmt_money(top5_spend)}</b> "
            f"of {fmt_money(total_spend)} CC spend — <b style='color:#6366f1'>"
            f"{share:.1f}%</b>.</div>",
            unsafe_allow_html=True,
        )

        # Spend by Model — pulled DIRECTLY from rollups.modelSpend in the
        # source JSON. usage_events stores Anthropic events under a
        # 'claude-generic' placeholder because the JSON's userCostByProduct
        # rows have model=null; the rollup is the authoritative per-model
        # number. Caveat: rollup is across all Claude products (Chat + CC +
        # Cowork etc.), not CC-only.
        model_spend = get_anthropic_model_spend_from_json()
        if model_spend:
            # Surface the JSON's actual rangeStart/End so the user doesn't
            # think these $-values are filtered by the page's Period picker.
            from data.sources.anthropic_json import latest_anthropic_file as _laf
            _af = _laf()
            _window_note = ""
            if _af:
                try:
                    import json as _json
                    _meta = _json.loads(_af.path.read_text(encoding="utf-8")).get("_meta") or {}
                    _start = (_meta.get("rangeStart") or "")[:10]
                    _end = (_meta.get("rangeEnd") or "")[:10]
                    if _start and _end:
                        _window_note = f" Window: {_start} → {_end}."
                except Exception:
                    pass
            st.caption(
                "Sourced from `rollups.modelSpend` (all Claude products combined — "
                "per-product per-model split isn't in the JSON dump)."
                + _window_note
            )
            cc1, cc2 = st.columns(2)
            with cc1:
                section("Spend by Model")
                _bar_list(model_spend[:10], label_key="model", value_key="spend",
                          css_class="claude", value_formatter=fmt_money)
            with cc2:
                section("Model Share of Spend")
                shares_html = []
                for m in model_spend[:6]:
                    pct = m["share"]
                    shares_html.append(
                        f'<div style="margin-bottom:8px;">'
                        f'<div style="display:flex;justify-content:space-between;'
                        f'font-size:13px;color:#475569;margin-bottom:3px;">'
                        f'<code>{m["model"]}</code><b>{pct:.1f}%</b></div>'
                        f'<div style="background:#f1f5f9;height:6px;border-radius:3px;'
                        f'overflow:hidden;">'
                        f'<div style="background:#6366f1;height:100%;width:{pct:.2f}%;"></div>'
                        f'</div></div>'
                    )
                st.markdown("".join(shares_html), unsafe_allow_html=True)
    else:
        st.info(
            "No Claude Code events yet. Once Anthropic admin API or Cursor "
            "leaderboard exports are loaded, Claude Code traffic shows up here."
        )


with tab_gpt:
    if filters.provider not in ("all", "openai"):
        st.info(
            f"ChatGPT tab shows OpenAI API events. Source filter "
            f"'{filters.provider}' has no OpenAI data — switch to 'All sources' "
            f"or one of 'OpenAI · Artem' / 'OpenAI · Humanoid'."
        )
    rows = get_users_for_provider("openai", period_days=filters.period_days,
                                   api_key_id=filters.api_key_id)
    # Honor the organization filter (Artem vs Humanoid) — get_users_for_provider
    # itself doesn't take it, so post-filter by joining each row to the org.
    if filters.organization and filters.organization != "all":
        from data.db import get_conn as _gc_gpt
        with _gc_gpt() as _conn_gpt:
            _allowed_uids = {
                r[0] for r in _conn_gpt.execute(
                    """SELECT DISTINCT ue.user_id
                       FROM usage_events ue
                       JOIN providers p ON p.id = ue.provider_id
                       JOIN organizations o ON o.id = ue.organization_id
                       WHERE p.name='openai' AND o.label = ?
                         AND ue.occurred_at >= datetime('now', ?)""",
                    (filters.organization, f"-{filters.period_days} days"),
                ).fetchall()
            }
        # Rebuild rows from scratch via SQL filtered by org so message/cost
        # counts are also org-scoped (not just user-list filtering).
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
                (filters.organization, f"-{filters.period_days} days"),
            ).fetchall()
        rows = [dict(r) | {"sessions": None, "lines_added": None, "commits": None,
                            "tokens_in": int(r["tokens_in"] or 0),
                            "tokens_out": int(r["tokens_out"] or 0),
                            "cost": float(r["cost"] or 0),
                            "messages": int(r["messages"])}
                for r in org_rows]
    total_msgs = sum(r["messages"] for r in rows)
    total_spend = sum(r["cost"] for r in rows)
    high = [r for r in rows if r["cost"] >= 200]
    kpi_row([
        {"label": "Active Users",   "value": str(len(rows))},
        {"label": "Total Messages", "value": _fmt_int(total_msgs)},
        {"label": "Total Spend",    "value": fmt_money(total_spend)},
        {"label": "High Spenders",  "value": str(len(high))},
    ])

    if rows:
        # Top 5 by messages + Spend Metrics — side by side
        col_top, col_metrics = st.columns(2)
        with col_top:
            section("Top Users — by messages")
            top_by_msgs = sorted(rows, key=lambda r: r["messages"], reverse=True)[:5]
            _bar_list(top_by_msgs, label_key="user_name", value_key="messages",
                      css_class="chatgpt", value_formatter=fmt_int)
        with col_metrics:
            section("Spend Metrics")
            avg_per_user = total_spend / max(len(rows), 1) if rows else 0
            top_single = max((r["cost"] for r in rows), default=0)
            # Dominant model = OpenAI model with most messages
            openai_models = get_openai_top_models(period_days=filters.period_days)
            dom_model = openai_models[0]["model"] if openai_models else "—"
            dom_share = 0.0
            if openai_models:
                tot_reqs = sum(m["requests"] for m in openai_models) or 1
                dom_share = openai_models[0]["requests"] / tot_reqs * 100
            metrics_rows = [
                ("Total spend",     fmt_money(total_spend)),
                ("Avg per user",    fmt_money(avg_per_user)),
                ("High spenders (≥ $200)", f"{len(high)} users"),
                ("Top single spend",fmt_money(top_single)),
                ("Dominant model",  f"{dom_model} ({dom_share:.0f}%)"),
            ]
            st.markdown(
                "<table class='hmnd-table'><tbody>"
                + "".join(
                    f"<tr><td style='color:#475569'>{k}</td>"
                    f"<td style='text-align:right;font-weight:600'>{v}</td></tr>"
                    for k, v in metrics_rows
                )
                + "</tbody></table>",
                unsafe_allow_html=True,
            )

        # Top Models Used by message count
        if openai_models:
            section("Top Models Used")
            _bar_list(openai_models[:8], label_key="model", value_key="requests",
                      css_class="chatgpt", value_formatter=fmt_int)

        section("All ChatGPT Users")
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
    if filters.provider not in ("all", "cursor"):
        st.info(
            f"Cursor tab shows the Cursor team leaderboard. Source filter "
            f"'{filters.provider}' has no Cursor data — switch to 'All sources' "
            f"or 'Cursor'."
        )
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
        total_agent = sum(int(r.get("agent_completions") or 0) for r in leaders)
        total_tab = sum(int(r.get("tab_completions") or 0) for r in leaders)
        total_completions = total_agent + total_tab
        prefer_claude = sum(1 for r in leaders if "claude" in r["favorite_model"].lower())
        prefer_gpt = sum(1 for r in leaders if r["favorite_model"].lower().startswith("gpt"))
        kpi_row([
            {"label": "Active developers", "value": str(active_devs)},
            {"label": "Completions",       "value": fmt_int(total_completions)},
            {"label": "AI Lines Written",  "value": fmt_int(total_ai_lines)},
            {"label": "Prefer Claude",     "value": str(prefer_claude)},
        ])
        # Second row: completion split + GPT-preferring devs
        kpi_row([
            {"label": "Prefer GPT",        "value": str(prefer_gpt)},
            {"label": "Agent completions", "value": fmt_int(total_agent)},
            {"label": "Tab completions",   "value": fmt_int(total_tab)},
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
            section("Top 10 by Completions")
            by_completions = sorted(
                leaders,
                key=lambda r: (int(r.get("agent_completions") or 0)
                               + int(r.get("tab_completions") or 0)),
                reverse=True,
            )[:10]
            # Synthesize a 'completions' field for the bar
            for r in by_completions:
                r["_completions"] = (int(r.get("agent_completions") or 0)
                                      + int(r.get("tab_completions") or 0))
            _bar_list(
                by_completions, label_key="name", value_key="_completions",
                css_class=_row_class, value_formatter=fmt_int,
            )

        if dau:
            section("Daily Active Users")
            with st.container():
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


with tab_models:
    # Combined model landscape: OpenAI events + Anthropic (cursor-derived)
    # + Cursor leaderboard model usage. Status badge auto-derived from
    # share within tool.
    from backend.services.models_svc import get_models_breakdown
    from backend.services.cursor_analytics import model_usage_summary
    f = filters
    rows_api = get_models_breakdown(f)  # usage_events grouped by model

    # Respect the Source filter — picking a specific provider should narrow
    # the landscape to that provider's models. Without this, picking
    # 'Anthropic' still showed gpt-* rows which looked like a bug.
    if filters.provider and filters.provider != "all":
        rows_api = [r for r in rows_api if r["provider"] == filters.provider]

    # Replace Anthropic's 'claude-generic' placeholder with real per-model
    # spend from the JSON rollup. Total Anthropic spend stays the same; we
    # just attribute it to actual model names so the landscape doesn't
    # collapse to one row.
    # Skip the Anthropic-rollup substitution when Source filter is narrowed
    # to a non-anthropic provider (otherwise picking 'OpenAI · Artem' would
    # still inject Claude rows from rollup into the landscape).
    _anth_in_scope = filters.provider in ("all", "anthropic")
    anthropic_rollup = get_anthropic_model_spend_from_json() if _anth_in_scope else []
    if anthropic_rollup:
        rows_api = [r for r in rows_api if not (
            r["provider"] == "anthropic" and r["model"] == "claude-generic"
        )]
        # rescale rollup to the events-window total so percentages match
        # what the rest of the dashboard shows.
        # NOTE: get_spend_by_model() returns 'spend' (not 'cost') as the
        # money column — different name than get_models_breakdown().
        anth_total_events = next(
            (r["spend"] for r in get_spend_by_model("anthropic", period_days=f.period_days)
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

    # Per-provider total spend → share computation
    spend_by_provider: dict[str, float] = {}
    for r in rows_api:
        p = r["provider"]
        spend_by_provider[p] = spend_by_provider.get(p, 0) + (r["cost"] or 0)

    # Hide Cursor models from the landscape when Source filter is narrowed
    # to a non-cursor provider (otherwise picking 'OpenAI · Artem' still
    # listed claude-* and gpt-* Cursor models).
    _cursor_in_scope = filters.provider in ("all", "cursor")
    cursor_rows = model_usage_summary() if _cursor_in_scope else []
    cursor_total_reqs = sum(m["requests"] for m in cursor_rows)

    section(f"Model landscape — {f.date_range()[0].date()} → {f.date_range()[1].date()}")

    items: list[dict[str, Any]] = []
    # API-side models
    for r in rows_api:
        share = ((r["cost"] or 0) / spend_by_provider[r["provider"]] * 100
                 if spend_by_provider.get(r["provider"]) else 0)
        # Correct tool attribution from the event's actual provider.
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
    # Cursor-side models (requests, not $)
    for m in cursor_rows[:10]:
        share = (m["requests"] / cursor_total_reqs * 100) if cursor_total_reqs else 0
        is_claude = "claude" in m["model"].lower()
        items.append({
            "_color": "claude" if is_claude else ("chatgpt" if "gpt" in m["model"].lower() else "cursor"),
            "model": m["model"],
            "tool": "Cursor",
            "share": share,
            "metric": f"{fmt_int(m['requests'])} reqs",
            "metric_note": f"({share:.0f}%)",
            "raw_value": m["requests"],
        })

    def _status(it: dict[str, Any]) -> tuple[str, str]:
        s = it["share"]
        if s >= 40:
            return ("DOMINANT", "high")
        if s >= 20:
            return ("GROWING", "review")
        if s >= 10:
            return ("ACTIVE", "low")
        return ("ACTIVE", "low")

    # Sort: API by $ desc, then Cursor by requests desc
    items.sort(key=lambda x: (-(x["share"] if x["tool"] != "Cursor" else 0),
                              -x["raw_value"]))

    html_rows = []
    for it in items[:20]:
        status_text, status_kind = _status(it)
        dot_color = {"claude": "#6366f1", "chatgpt": "#10a37f",
                     "cursor": "#f59e0b"}.get(it["_color"], "#94a3b8")
        html_rows.append(
            f"<tr>"
            f"<td><span style='display:inline-block;width:8px;height:8px;border-radius:50%;background:{dot_color};margin-right:8px'></span>"
            f"<code>{it['model']}</code></td>"
            f"<td>{it['tool']}</td>"
            f"<td>{badge(status_text, status_kind)}</td>"
            f"<td><b>{it['metric']}</b> <span style='color:#64748b'>{it['metric_note']}</span></td>"
            f"</tr>"
        )
    st.markdown(
        f"<table class='hmnd-table'>"
        f"<thead><tr><th>Model</th><th>Tool</th><th>Status</th><th>Spend / Volume</th></tr></thead>"
        f"<tbody>{''.join(html_rows)}</tbody></table>",
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns(2)
    with c1:
        section("Claude spend by model")
        claude_models = [r for r in rows_api if r["provider"] == "anthropic"]
        if claude_models:
            _bar_list(claude_models[:10], label_key="model", value_key="cost",
                      css_class="claude", value_formatter=fmt_money)
    with c2:
        section("Cursor top models")
        if cursor_rows:
            def _row_class(r):
                m = r["model"].lower()
                if "claude" in m: return "claude"
                if "gpt" in m: return "chatgpt"
                return "cursor"
            _bar_list(cursor_rows[:10], label_key="model", value_key="requests",
                      css_class=_row_class, value_formatter=fmt_int)


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
    # anomalous $/msg
    anomalies = [s for s in high
                 if s["messages"] and (s["spend"] / s["messages"]) >= 100]
    if anomalies:
        a = anomalies[0]
        dpm = a["spend"] / a["messages"]
        bullets.append(
            f"<b>{a['user_name']}</b> — {fmt_money(a['spend'])} on {a['messages']} messages "
            f"(~${dpm:,.0f}/msg). Likely API/automation, not chat usage."
        )
    # high msg volume
    volume = sorted(high, key=lambda r: r["messages"] or 0, reverse=True)
    if volume and volume[0]["messages"] >= 1000 and volume[0] != top:
        v = volume[0]
        bullets.append(
            f"<b>{v['user_name']}</b> — {v['messages']:,} messages at "
            f"{fmt_money(v['spend'])}. High volume, normal $/msg."
        )
    # concentration
    if len(high) >= 3:
        top3 = sum(s["spend"] for s in high[:3])
        total = sum(s["spend"] for s in high)
        share = (top3 / total * 100) if total else 0
        bullets.append(f"Top 3 high-spenders = <b>{share:.0f}%</b> of all high spend.")
    return bullets[:4]


with tab_devs:
    # Cross-source view (git × ai). Ignores Source filter by design — the
    # whole point of this tab is to join all sources per person.
    st.caption(
        "ℹ️ Cross-source view — joins each person's git activity with their AI "
        "spend / lines / completions. Source filter is ignored by design."
    )

    # Period picker honored — re-uses top filter.
    # Plus a repo multi-select if the user dropped the granular per-commit
    # CSV (`git_commit_file_stats.csv`) and we built per-repo rollups.
    from backend.services.git_correlation import (
        get_git_ai_correlation, get_segment_counts,
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
    devs = get_git_ai_correlation(
        period_days=filters.period_days,
        repos=selected_repos if (selected_repos and _known_repos) else None,
    )
    if not devs:
        st.info(
            "No git authors loaded yet. Drop a `git_authors_YYYYMMDD.csv` into "
            "`sources/` (columns: git_author_name, git_author_emails, repos, "
            "commits, additions, deletions, net_lines, first_commit, last_commit) "
            "or run the extraction script described in docs/."
        )
    else:
        # Top-level KPIs: counts + team-wide AI share (now including bots).
        from backend.services.git_correlation import get_team_ai_share
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
            {"label": "Tracked devs",   "value": f"{n_humans} +{n_bots} bots"},
            {"label": "Team AI share",  "value": f"{share['ai_share_pct']}%"},
            {"label": "Bot share",      "value": f"{share['bot_share_pct']}%"},
            {"label": "Human AI share", "value": f"{share['human_ai_share_pct']}%"},
        ])
        st.caption(
            f"📊 AI-generated lines: **{fmt_int(share['ai_lines_total'])}** of "
            f"**{fmt_int(share['total_additions'])}** total git additions. "
            f"Bots ({fmt_int(share['bot_additions'])} lines, 100% AI) + Cursor-reported "
            f"AI lines by humans ({fmt_int(min(share['human_ai_lines'], share['human_additions']))} lines)."
        )

        # Segment colours + human-readable labels (ordered by "interestingness"
        # so the bar reads left→right from most-positive to most-passive).
        SEGMENT_META = [
            ("HIGH_AI_SPEND_HIGH_GIT_OUTPUT", "High AI · High Output",   "#10b981"),  # green
            ("LOW_AI_SPEND_HIGH_GIT_OUTPUT",  "Low AI · High Output",    "#3b82f6"),  # blue
            ("HIGH_AI_LINES_LOW_COMMITS",     "Lots of AI lines, few commits", "#f59e0b"),  # amber
            ("HIGH_AI_SPEND_LOW_GIT_OUTPUT",  "High AI · Low Output",    "#ef4444"),  # red
            ("BOT_AUTOMATION",                "Bots / Agents",           "#a855f7"),  # purple
            ("AI_ACTIVE_BUT_NO_GIT",          "AI active, no git",       "#94a3b8"),  # gray
            ("GIT_ACTIVE_BUT_NO_AI",          "Git active, no AI",       "#cbd5e1"),  # light gray
            ("NORMAL",                        "Normal",                  "#e2e8f0"),  # near white
        ]

        # 1. Stacked-bar segment distribution (mirrors Spend Breakdown style)
        section("Segment distribution")
        total_devs = len(devs)
        present = [(s, lbl, c) for s, lbl, c in SEGMENT_META if counts.get(s, 0) > 0]
        bar_segments_html = []
        legend_html = []
        for seg_id, label, color in present:
            n = counts[seg_id]
            pct = n / total_devs * 100 if total_devs else 0
            # Show the percentage inside the bar only when there's room for it
            # (very thin segments would just clip the text).
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
                f'<span style="color:#94a3b8;">({pct:.1f}%)</span>'
                f'</span>'
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

        # 2. Multi-select: which segment(s) to show as tables below
        section("Drill into segments")
        seg_options = [s for s, _, _ in SEGMENT_META if counts.get(s, 0) > 0]
        seg_labels_map = {s: lbl for s, lbl, _ in SEGMENT_META}
        seg_colors_map = {s: c for s, _, c in SEGMENT_META}
        picked_segments = st.multiselect(
            "Show tables for:",
            options=seg_options,
            default=seg_options,
            format_func=lambda s: seg_labels_map[s],
            key="devs_segments_filter",
            help="Pick one or more segments to render their developers as "
                 "individual tables.",
        )

        # Centered search bar for filtering rows by name across all selected
        # segments. Empty = show everything.
        _c1, _c2, _c3 = st.columns([1, 2, 1])
        with _c2:
            search_query = st.text_input(
                "🔍 Search by name",
                value="",
                key="devs_search",
                placeholder="type a name…",
                label_visibility="collapsed",
            )

        # 3. Format helpers + per-segment tables
        def _money(v):
            if v is None or (isinstance(v, float) and v != v):  # NaN-safe
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
            search_lower = (search_query or "").strip().lower()
            for seg_id in picked_segments:
                seg_devs = [r for r in devs if r["segment"] == seg_id]
                if search_lower:
                    seg_devs = [
                        r for r in seg_devs
                        if search_lower in (r.get("canonical_name") or "").lower()
                        or search_lower in (r.get("git_author_name") or "").lower()
                        or search_lower in (r.get("git_email") or "").lower()
                    ]
                if not seg_devs:
                    continue
                color = seg_colors_map[seg_id]
                label = seg_labels_map[seg_id]
                # Colored header
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:10px;'
                    f'margin:20px 0 8px 0;border-left:4px solid {color};'
                    f'padding:6px 12px;background:{color}1a;border-radius:0 8px 8px 0;">'
                    f'<span style="font-weight:600;color:#06091c;font-size:15px;">'
                    f'{label}</span>'
                    f'<span style="color:#64748b;font-size:13px;">'
                    f'{len(seg_devs)} devs · '
                    f'{len(seg_devs)/total_devs*100:.1f}% of team</span>'
                    f'</div>',
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


with tab_high:
    if filters.provider != "all":
        st.caption(
            f"ℹ️ Cross-tool view — ignores Source filter "
            f"(currently '{filters.provider}') by design. Ranks people across "
            f"OpenAI + Anthropic + Cursor together."
        )
    # Threshold slider — default $1k per the design screenshot.
    threshold = st.slider("High-spender threshold ($)", 200, 5000, 1000, 100,
                          key="hs_threshold")
    # High Spenders is a cross-tool view by design — it ranks people across
    # OpenAI/Anthropic/Cursor in one list. So we deliberately ignore the
    # Source filter here (otherwise picking 'OpenAI · Artem' would show only
    # users with OpenAI spend, defeating the cross-tool purpose).
    all_spenders = get_high_spenders(period_days=filters.period_days,
                                      threshold_usd=0,
                                      api_key_id=None)
    high = [r for r in all_spenders if r["spend"] >= threshold]
    combined = sum(r["spend"] for r in high)
    top = high[0] if high else None
    total_users = len(all_spenders)
    share_high = (len(high) / total_users * 100) if total_users else 0

    kpi_row([
        {"label": "High Spenders", "value": f"{len(high)} / {total_users}"},
        {"label": "Highest single", "value": fmt_money(top["spend"]) if top else "—"},
        {"label": "Combined spend", "value": fmt_money(combined)},
        {"label": "Share of users", "value": f"{share_high:.0f}%"},
    ])

    if high:
        # Cross-tool per-user spend split so we can show 'Andy Park: GPT $9920
        # + CC $3154 = $13074'. Build a lookup by user_name (since the basic
        # high_spenders list keys on user_name string).
        per_provider = get_high_spenders_per_provider(period_days=filters.period_days)
        split_by_user = {r["user_name"]: r for r in per_provider}

        section("Notable high spend")
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
            # Build inner block as a single line — Streamlit's markdown parser
            # treats blank lines inside HTML as paragraph breaks, which was
            # turning subsequent cards into literal text. Keeping it inline
            # (no embedded newlines) avoids that.
            split_inline = (
                f'<div style="color:#94a3b8;font-size:11px;margin-top:4px;">'
                f'{" + ".join(split_parts)}</div>'
                if len(split_parts) > 1 else ""
            )
            card_html = (
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
            cards_html.append(card_html)
        st.markdown("".join(cards_html), unsafe_allow_html=True)

        # Two-column footer: narrative analysis + cross-tool ranking bars
        col_anal, col_rank = st.columns(2)
        with col_anal:
            section("High spend analysis")
            findings = _hs_findings(high)
            if findings:
                st.markdown(
                    "<ul style='margin:0; padding-left:18px; color:#475569; "
                    "font-size:13px; line-height:1.7'>"
                    + "".join(f"<li>{f}</li>" for f in findings) + "</ul>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("No notable anomalies detected.")
        with col_rank:
            section("Cross-tool spend ranking")
            ranked = sorted(all_spenders, key=lambda r: r["spend"] or 0, reverse=True)[:10]
            max_spend = max((r["spend"] or 0) for r in ranked) or 1
            _bar_list(
                ranked, label_key="user_name", value_key="spend",
                css_class=lambda r: f"risk-{classify_risk(r['spend']) or 'low'}",
                max_value=max_spend,
                value_formatter=fmt_money,
            )
    else:
        st.info(f"No users at or above {fmt_money(threshold)} in the period.")
