"""Shared Streamlit UI components: фильтры, KPI-карточки, бейджи."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from backend.analytics import Filters, preset_range
from data.db import get_conn

PRESETS = [
    "Today",
    "Yesterday",
    "Week to date",
    "Month to date",
    "Last 7 days",
    "Last 14 days",
    "Last 30 days",
    "Last 90 days",
    "Custom",
]
DEFAULT_PRESET = "Last 30 days"

def _available_providers() -> list[str]:
    """Providers that have at least one usage event. Built from the DB so new
    sources (cursor, github) show up without code changes.
    """
    sql = """
        SELECT DISTINCT p.name
        FROM providers p
        WHERE EXISTS (
            SELECT 1 FROM usage_events ue WHERE ue.provider_id = p.id
        )
        ORDER BY p.name
    """
    try:
        with get_conn() as conn:
            return ["all"] + [r["name"] for r in conn.execute(sql).fetchall()]
    except Exception:
        return ["all"]


def _available_organizations() -> list[str]:
    """Org labels for providers that have rows tagged with organization_id.
    Example output: ['all', 'Artem', 'Humanoid'].
    """
    sql = """
        SELECT DISTINCT o.label
        FROM organizations o
        WHERE EXISTS (
            SELECT 1 FROM usage_events ue WHERE ue.organization_id = o.id
        )
        ORDER BY o.label
    """
    try:
        with get_conn() as conn:
            return ["all"] + [r["label"] for r in conn.execute(sql).fetchall()]
    except Exception:
        return ["all"]


def _api_keys_for_provider(provider: str) -> list[dict[str, Any]]:
    sql = """
        SELECT ak.id, ak.name, ak.redacted_value, ak.last_used_at, p.name AS provider
        FROM api_keys ak
        JOIN providers p ON p.id = ak.provider_id
        WHERE 1=1
    """
    params: list[Any] = []
    if provider != "all":
        sql += " AND p.name = ?"
        params.append(provider)
    sql += " ORDER BY (ak.last_used_at IS NULL), ak.last_used_at DESC, ak.name"
    try:
        with get_conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception:
        return []


def filters_bar() -> Filters:
    """FR-13.1.* / FR-13.2.* — provider, period (preset or custom), team, API key.

    Layout: a single row of four selectboxes; an inline date_input appears
    below only when the period preset is set to 'Custom'.
    """
    st.session_state.setdefault("preset", DEFAULT_PRESET)
    st.session_state.setdefault("provider", "all")
    st.session_state.setdefault("organization", "all")
    st.session_state.setdefault("custom_range", (datetime.utcnow().date(), datetime.utcnow().date()))
    st.session_state.setdefault("api_key_id", None)

    providers = _available_providers()
    organizations = _available_organizations()

    # Drop stale selections that no longer exist in the DB so we don't filter
    # on something that won't return any rows.
    if st.session_state.provider not in providers:
        st.session_state.provider = "all"
    if st.session_state.organization not in organizations:
        st.session_state.organization = "all"

    keys = _api_keys_for_provider(st.session_state.provider)
    options = [None] + [k["id"] for k in keys]
    labels = {None: "All keys"}
    for k in keys:
        labels[k["id"]] = k["name"] or k["provider"]

    c1, c2, c3, c4 = st.columns([1, 1.2, 1, 1])
    with c1:
        st.selectbox(
            "Provider", providers, key="provider",
            format_func=lambda x: "All providers" if x == "all" else x.capitalize(),
        )
    with c2:
        st.selectbox("Period", PRESETS, key="preset")
    with c3:
        st.selectbox(
            "Organization", organizations, key="organization",
            format_func=lambda x: "All orgs" if x == "all" else x,
            help="OpenAI sub-org: Artem (admin API) or Humanoid (JSON drop).",
        )
    with c4:
        # If the active provider doesn't include the previously-selected key,
        # reset to "All keys" so we never silently filter on a key that's no
        # longer in the dropdown.
        if st.session_state.api_key_id is not None and st.session_state.api_key_id not in options:
            st.session_state.api_key_id = None
        st.selectbox(
            "API key", options, key="api_key_id",
            format_func=lambda v: labels.get(v, "All keys"),
        )

    date_from = date_to = None
    if st.session_state.preset == "Custom":
        rng = st.date_input(
            "Custom date range",
            value=st.session_state.custom_range,
            key="custom_range_input",
        )
        if isinstance(rng, tuple) and len(rng) == 2 and all(rng):
            st.session_state.custom_range = rng
            date_from = datetime.combine(rng[0], datetime.min.time())
            date_to = datetime.combine(rng[1], datetime.min.time())
    else:
        s, e = preset_range(st.session_state.preset)
        date_from, date_to = s, e

    if date_from and date_to:
        period_days = max((date_to.date() - date_from.date()).days, 1)
    else:
        period_days = 30

    return Filters(
        period_days=period_days,
        provider=st.session_state.provider,
        team="all",  # legacy field (people-team), no UI surface for it any more
        organization=st.session_state.organization,
        date_from=date_from,
        date_to=date_to,
        api_key_id=st.session_state.api_key_id,
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
    """Render KPIs in fixed-width columns (default 4) so rows align across the
    page even when the number of items in the row is less than `cols`.
    Empty trailing slots are kept as blank columns so each card has the same
    width as in the row above/below.
    """
    for i in range(0, len(items), cols):
        chunk = items[i:i + cols]
        columns = st.columns(cols)
        for col, item in zip(columns, chunk):
            with col:
                st.markdown(kpi_card(**item), unsafe_allow_html=True)
        # Empty padding columns are already created by st.columns(cols)
        # — nothing to render in them.


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
    return f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}"


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
