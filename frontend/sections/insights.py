"""Insights — management metrics for AI ops.

Three primary lenses:
  1. Concentration risk — top 5 spenders share of total AI spend
  2. Idle paid seats — money burned on seats with no activity in 30 days
  3. Per-developer ROI — AI lines × dev-rate / spend
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from backend.services.insights import (
    concentration_risk_label,
    get_developer_roi,
    get_idle_paid_seats,
    get_top_n_concentration,
)
from frontend.components import badge, filters_bar, fmt_int, fmt_money, hero, kpi_row, section


hero(
    "Insights",
    'Management <span class="accent">decisions</span>',
    "Where AI spend is concentrated, what paid seats waste money, and ROI per developer.",
)

filters = filters_bar()
period_days = filters.period_days


tab_conc, tab_seats, tab_roi = st.tabs([
    "⚠ Concentration risk",
    "💺 Idle paid seats",
    "📈 Per-developer ROI",
])


# ---- Concentration risk ----------------------------------------------------

with tab_conc:
    top_n = st.slider("Top N spenders", min_value=3, max_value=20, value=5)
    data = get_top_n_concentration(top_n=top_n, period_days=period_days)
    risk = concentration_risk_label(data["concentration_pct"])

    kpi_row([
        {"label": f"Top-{top_n} share",
         "value": f"{data['concentration_pct']:.1f}%",
         "note": f"of {fmt_money(data['total_spend'])} total spend"},
        {"label": "Top-N combined spend",
         "value": fmt_money(data["top_n_spend"])},
        {"label": "All spenders",
         "value": str(data["total_users"]),
         "note": f"with activity in {period_days}d"},
        {"label": "Risk level",
         "value": risk.upper(),
         "note": "high = >60%, medium = 30–60%, low = <30%"},
    ])

    if data["top_n"]:
        section(f"Top {top_n} spenders")
        df = pd.DataFrame(data["top_n"])
        df["spend_str"] = df["spend_usd"].apply(fmt_money)
        df["share_pct"] = (df["spend_usd"] / data["total_spend"] * 100).round(1).astype(str) + "%"
        view = df[["user_name", "email", "spend_str", "share_pct"]].rename(
            columns={"user_name": "User", "email": "Email",
                     "spend_str": "Spend", "share_pct": "Share of total"}
        )
        st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True)

        st.markdown(
            f"""
            <div style="margin-top:14px;padding:14px 18px;border-radius:14px;
                        background:#fef3f2;border:1px solid #fecaca;color:#991b1b;
                        font-size:14px;line-height:1.5;">
                <b>What this means:</b> if any single person in the top {top_n}
                leaves the team, you lose visibility into / responsibility for
                up to <b>{data['concentration_pct']:.1f}%</b> of your AI spend
                pattern. Consider rotating ownership of expensive workflows or
                documenting agent/automation configs.
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("No spend recorded in this period.")


# ---- Idle paid seats -------------------------------------------------------

with tab_seats:
    threshold = st.slider("Idle threshold (days)", min_value=7, max_value=90, value=30)
    seats = get_idle_paid_seats(threshold_days=threshold)

    kpi_row([
        {"label": "Idle paid seats",
         "value": str(seats["idle_count"]),
         "note": f"no activity in {threshold} days"},
        {"label": "Wasted / month",
         "value": fmt_money(seats["wasted_monthly_usd"])},
        {"label": "Wasted / year",
         "value": fmt_money(seats["wasted_annual_usd"]),
         "note": "if pattern continues"},
        {"label": "Threshold",
         "value": f"{threshold}d",
         "note": "configurable"},
    ])

    if seats["rows"]:
        section("Seats to review")
        df = pd.DataFrame(seats["rows"])
        df["last_used_at"] = df["last_used_at"].fillna("never")
        df["cost_str"] = df["monthly_cost_usd"].apply(
            lambda v: fmt_money(v) if v else "—"
        )
        df["days_idle_str"] = df["days_idle"].apply(
            lambda d: f"{d}d" if d < 9999 else "never used"
        )
        df["recommendation"] = df["recommendation"].apply(lambda r: badge(r, r))
        view = df[["user_name", "seat_type", "provider", "cost_str",
                   "last_used_at", "days_idle_str", "recommendation"]].rename(
            columns={"user_name": "Owner", "seat_type": "Seat type",
                     "provider": "Provider", "cost_str": "$/mo",
                     "last_used_at": "Last used", "days_idle_str": "Idle",
                     "recommendation": "Action"}
        )
        st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True)
        st.markdown(
            f"""
            <div style="margin-top:14px;padding:14px 18px;border-radius:14px;
                        background:#fef3c7;border:1px solid #fcd34d;color:#92400e;
                        font-size:14px;line-height:1.5;">
                <b>Action:</b> revoking these seats would save
                <b>{fmt_money(seats['wasted_monthly_usd'])}</b> per month
                (<b>{fmt_money(seats['wasted_annual_usd'])}</b> per year).
                For each, check with the owner first — they may be on leave.
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.success(f"Every paid seat had activity in the last {threshold} days. Nothing wasted.")


# ---- Per-developer ROI -----------------------------------------------------

with tab_roi:
    c1, c2 = st.columns(2)
    with c1:
        dev_rate = st.number_input(
            "Developer rate, $/hour", min_value=20, max_value=300, value=80, step=10,
            help="Used to convert hours saved → dollar value",
        )
    with c2:
        lph = st.number_input(
            "Lines/hour without AI", min_value=10, max_value=200, value=50, step=5,
            help="Baseline coding speed assumption; 50 LOC/hour is typical for senior devs",
        )

    roi = get_developer_roi(
        dev_rate_usd_per_hour=float(dev_rate),
        lines_per_hour=float(lph),
        period_days=period_days,
    )
    team = roi["team"]

    kpi_row([
        {"label": "Team AI lines",
         "value": fmt_int(team["total_ai_lines"]),
         "note": f"{team['total_developers']} developers"},
        {"label": "Team AI spend",
         "value": fmt_money(team["total_spend_usd"])},
        {"label": "Hours saved (est.)",
         "value": f"{team['total_hours_saved']:,.0f}h",
         "note": f"@ {lph} LOC/h baseline"},
        {"label": "Team ROI",
         "value": (f"{team['team_roi_multiple']}×"
                   if team["team_roi_multiple"] is not None else "—"),
         "note": f"value / spend @ ${dev_rate}/h"},
    ])

    if roi["rows"]:
        section("Per-developer ROI")
        df = pd.DataFrame(roi["rows"])
        df["spend_str"] = df["spend_usd"].apply(
            lambda v: fmt_money(v) if v else "—"
        )
        df["lines_str"] = df["ai_lines"].apply(fmt_int)
        df["hours_str"] = df["hours_saved"].apply(lambda h: f"{h:.0f}h")
        df["value_str"] = df["value_saved_usd"].apply(fmt_money)
        df["roi_str"] = df["roi_multiple"].apply(
            lambda r: f"{r}×" if r is not None else "—"
        )
        view = df[["name", "favorite_model", "lines_str", "hours_str",
                   "value_str", "spend_str", "roi_str"]].rename(
            columns={"name": "Developer", "favorite_model": "Favorite",
                     "lines_str": "AI lines", "hours_str": "Hours saved",
                     "value_str": "Value saved", "spend_str": "AI spend",
                     "roi_str": "ROI"}
        )
        st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"),
                    unsafe_allow_html=True)
        st.caption(
            "Hours saved = AI lines / baseline_LOC_per_hour. "
            "Value saved = hours × developer rate. "
            "ROI multiple = value / actual AI spend. "
            "Developers with '—' ROI have no tracked spend in this period — they "
            "use Cursor under team subscription, so individual spend can't be "
            "split without per-developer Cursor billing."
        )
    else:
        st.info(
            "No Cursor leaderboard data found. Drop a User_Leaderboard_*.csv "
            "(or *.json) into the sources/ folder."
        )
