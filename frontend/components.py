"""Shared Streamlit UI components: фильтры, KPI-карточки, бейджи."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from backend.analytics import Filters

PERIODS = {
    "Today": 1,
    "7 days": 7,
    "30 days": 30,
    "90 days": 90,
}

PROVIDERS = ["all", "openai", "anthropic"]
TEAMS = ["all", "Backend", "Frontend", "Data", "Product"]


def filters_bar() -> Filters:
    """Top-level фильтры. NFR-01.1.2.1 — состояние в session_state."""
    s = st.session_state.setdefault(
        "filters", {"period_label": "30 days", "provider": "all", "team": "all"}
    )
    c1, c2, c3 = st.columns([1.2, 1, 1])
    with c1:
        s["period_label"] = st.selectbox(
            "Period", list(PERIODS.keys()),
            index=list(PERIODS.keys()).index(s.get("period_label", "30 days")),
        )
    with c2:
        s["provider"] = st.selectbox(
            "Provider", PROVIDERS,
            index=PROVIDERS.index(s.get("provider", "all")),
            format_func=lambda x: "All providers" if x == "all" else x.capitalize(),
        )
    with c3:
        s["team"] = st.selectbox(
            "Team", TEAMS,
            index=TEAMS.index(s.get("team", "all")),
            format_func=lambda x: "All teams" if x == "all" else x,
        )

    return Filters(
        period_days=PERIODS[s["period_label"]],
        provider=s["provider"],
        team=s["team"],
    )


def _delta_html(delta: float, suffix: str = "%") -> str:
    if delta > 0:
        return f'<span class="hmnd-delta-up">▲ {delta:+.1f}{suffix}</span>'
    if delta < 0:
        return f'<span class="hmnd-delta-down">▼ {delta:.1f}{suffix}</span>'
    return f'<span class="hmnd-delta-flat">— {delta:.1f}{suffix}</span>'


def kpi_card(label: str, value: str, delta: float | None = None, note: str | None = None) -> str:
    delta_html = _delta_html(delta) if delta is not None else ""
    note_html = f'<div class="note">{note}</div>' if note else ""
    return f"""
        <div class="hmnd-kpi">
            <div class="label">{label}</div>
            <div class="value">{value}</div>
            <div class="note">{delta_html} {note_html or ''}</div>
        </div>
    """


def kpi_row(items: list[dict[str, Any]], cols: int = 4) -> None:
    """items: [{label, value, delta?, note?}]"""
    for i in range(0, len(items), cols):
        chunk = items[i:i + cols]
        columns = st.columns(len(chunk))
        for col, item in zip(columns, chunk):
            with col:
                st.markdown(kpi_card(**item), unsafe_allow_html=True)


def badge(text: str, kind: str) -> str:
    """kind: ok|warn|breach|high|medium|low|keep|review|revoke."""
    return f'<span class="hmnd-badge {kind}">{text}</span>'


def hero(eyebrow: str, title_html: str, subtitle: str | None = None) -> None:
    sub = f'<p class="subtitle">{subtitle}</p>' if subtitle else ""
    st.markdown(
        f"""
        <div class="hmnd-hero">
            <span class="eyebrow">{eyebrow}</span>
            <h1>{title_html}</h1>
            {sub}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section(title: str) -> None:
    st.markdown(f'<div class="hmnd-section"><h2>{title}</h2></div>', unsafe_allow_html=True)


def fmt_money(v: float) -> str:
    return f"${v:,.0f}" if v >= 100 else f"${v:,.2f}"


def fmt_int(v: int) -> str:
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v/1000:.1f}k"
    return f"{v}"


def fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.1f}%"


def relative_time(iso_or_dt: str | datetime | None) -> str:
    if not iso_or_dt:
        return "—"
    dt = iso_or_dt if isinstance(iso_or_dt, datetime) else datetime.fromisoformat(iso_or_dt)
    delta = datetime.utcnow() - dt
    s = int(delta.total_seconds())
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"
