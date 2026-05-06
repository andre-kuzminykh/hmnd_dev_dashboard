"""F-03 Seats & Licenses."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from backend.services.seats import get_seats_summary, get_seats_table
from frontend.components import badge, fmt_money, hero, kpi_row, section
from frontend.theme import inject, render_brand


st.set_page_config(page_title="Seats · HMND", layout="wide")
inject()
render_brand()

hero(
    "F-03 · Seats & Licenses",
    'Кто <span class="accent">занимает</span> платное место',
    "Видим, какие сидения куплены и кто их реально использует. Подсвечиваем кандидатов на отзыв.",
)

s = get_seats_summary()
kpi_row([
    {"label": "Bought seats", "value": str(s["bought"]), "delta": None},
    {"label": "Assigned",     "value": str(s["assigned"]), "delta": None},
    {"label": "Active 30d",   "value": str(s["active_30d"]), "delta": None},
    {"label": "Inactive paid", "value": str(s["inactive_paid"]), "delta": None,
     "note": "no usage in 30d"},
])
st.markdown(
    f"""
    <div style="margin-top:8px;font-size:13px;color:#475569">
        Potential waste: <b style="color:#06091c">{fmt_money(s['potential_waste_usd'])}</b> / month
    </div>
    """,
    unsafe_allow_html=True,
)

section("All seats")
rows = get_seats_table()
if rows:
    df = pd.DataFrame(rows)
    df["recommendation"] = df["recommendation"].apply(lambda r: badge(r, r))
    df["assigned"] = df["assigned"].apply(lambda x: "yes" if x else "no")
    df["last_used_at"] = df["last_used_at"].fillna("—")
    view = df[[
        "user_name", "seat_type", "provider", "assigned",
        "last_used_at", "usage_30d", "monthly_cost_usd", "recommendation",
    ]].rename(columns={
        "user_name": "User",
        "seat_type": "Seat type",
        "provider": "Provider",
        "assigned": "Assigned",
        "last_used_at": "Last used",
        "usage_30d": "Usage 30d $",
        "monthly_cost_usd": "Cost $/mo",
        "recommendation": "Recommendation",
    })
    st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"), unsafe_allow_html=True)
else:
    st.info("No seats yet.")
