"""HMND theme — палитра и CSS-инъекция в Streamlit (NFR-10.1.1.1, NFR-10.1.1.2)."""
from __future__ import annotations

import streamlit as st

NAVY = "#06091c"
BLUE = "#4953d8"
LINE = "#e8edf3"
MUTED = "#64748b"
SOFT = "#f8fafc"
BG_BLUE = "rgba(73,83,216,.05)"
SUCCESS = "#10b981"
WARN = "#f59e0b"
DANGER = "#ef4444"

# Brand-correct provider colors used in charts.
OPENAI = "#10a37f"      # OpenAI teal
ANTHROPIC = "#cc785c"   # Anthropic terracotta
PROVIDER_COLORS = {"openai": OPENAI, "anthropic": ANTHROPIC, "OpenAI": OPENAI, "Anthropic": ANTHROPIC}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [data-testid="stAppViewContainer"] * {
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
}

[data-testid="stAppViewContainer"] {
    background: linear-gradient(180deg, #ffffff 0%, #fcfdff 100%);
    color: #06091c;
}

[data-testid="stSidebar"] {
    background: #ffffff;
    border-right: 1px solid #e8edf3;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] li a span {
    font-weight: 500;
}

/* Headings */
h1, h2, h3 { letter-spacing: -0.03em; font-weight: 400; }
h1 { font-weight: 300; }

/* Brand header in sidebar */
.hmnd-brand {
    display: flex; align-items: center; gap: 10px;
    padding: 6px 4px 18px 4px; border-bottom: 1px solid #e8edf3; margin-bottom: 14px;
}
.hmnd-brand .dot {
    width: 22px; height: 22px; border-radius: 6px;
    background: linear-gradient(135deg, #4953d8 0%, #06091c 100%);
}
.hmnd-brand .title {
    font-size: 12px; letter-spacing: 0.18em; text-transform: uppercase; font-weight: 700; color: #06091c;
}
.hmnd-brand-sub {
    font-size: 13px; color: #475569; margin: -8px 4px 14px 4px;
}

/* KPI card */
.hmnd-kpi {
    border: 1px solid #e8edf3;
    border-radius: 18px;
    padding: 18px 20px;
    background: linear-gradient(180deg,#ffffff 0%,#fcfdff 100%);
    box-shadow: 0 14px 32px -24px rgba(6,9,28,.14);
    height: 100%;
}
.hmnd-kpi .label {
    font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: .12em; margin-bottom: 8px;
}
.hmnd-kpi .value { font-size: 28px; line-height: 1; font-weight: 300; color: #06091c; }
.hmnd-kpi .note  { font-size: 12px; color: #475569; margin-top: 8px; }

.hmnd-delta-up   { color: #10b981; font-weight: 600; }
.hmnd-delta-down { color: #ef4444; font-weight: 600; }
.hmnd-delta-flat { color: #64748b; font-weight: 500; }

/* Chip / badge */
.hmnd-chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: 999px;
    font-size: 11px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase;
    border: 1px solid rgba(73,83,216,.18); color: #4953d8; background: rgba(73,83,216,.05);
}
.hmnd-badge { display:inline-block; padding:3px 9px; border-radius:999px; font-size:11px; font-weight:600; letter-spacing:.04em; text-transform:uppercase; }
.hmnd-badge.ok       { color:#065f46; background:#ecfdf5; border:1px solid #a7f3d0; }
.hmnd-badge.warn     { color:#92400e; background:#fffbeb; border:1px solid #fde68a; }
.hmnd-badge.breach,
.hmnd-badge.high     { color:#991b1b; background:#fee2e2; border:1px solid #fecaca; }
.hmnd-badge.medium   { color:#92400e; background:#fffbeb; border:1px solid #fde68a; }
.hmnd-badge.low      { color:#065f46; background:#ecfdf5; border:1px solid #a7f3d0; }
.hmnd-badge.review   { color:#1e40af; background:#eff6ff; border:1px solid #bfdbfe; }
.hmnd-badge.revoke   { color:#991b1b; background:#fee2e2; border:1px solid #fecaca; }
.hmnd-badge.keep     { color:#065f46; background:#ecfdf5; border:1px solid #a7f3d0; }

/* Hero */
.hmnd-hero {
    border: 1px solid #e8edf3;
    border-radius: 24px;
    padding: 28px 30px;
    background:
        radial-gradient(circle at top left, rgba(73,83,216,.10), transparent 28%),
        radial-gradient(circle at top right, rgba(6,9,28,.05), transparent 24%),
        linear-gradient(180deg, #ffffff 0%, #fcfdff 100%);
    margin-bottom: 18px;
}
.hmnd-hero .eyebrow {
    color:#4953d8; font-size:11px; font-weight:600; letter-spacing:.14em; text-transform:uppercase;
    display:inline-flex; align-items:center; gap:8px;
}
.hmnd-hero .eyebrow::before { content:""; width:24px; height:1px; background:#4953d8; display:inline-block; }
.hmnd-hero h1 { margin: 12px 0 8px; font-size: 38px; line-height: 1.04; }
.hmnd-hero .accent { color: #4953d8; }
.hmnd-hero p.subtitle { color:#475569; font-size:15px; margin: 0; max-width: 700px; }

/* Section header */
.hmnd-section {
    border-top: 1px solid #e8edf3;
    padding-top: 18px;
    margin-top: 14px;
}
.hmnd-section h2 { font-size: 22px; margin: 0 0 12px; }

/* Buttons / filters */
[data-testid="stToolbar"] { display: none; }
[data-testid="stHeader"]  { background: transparent; }

[data-baseweb="select"] > div {
    border-radius: 12px !important;
    border: 1px solid #e8edf3 !important;
}

[data-testid="stMetricValue"] { color: #06091c; }
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def render_brand() -> None:
    st.sidebar.markdown(
        """
        <div class="hmnd-brand">
            <div class="dot"></div>
            <div class="title">HUMANOID</div>
        </div>
        <div style="font-size:13px;color:#475569;margin-bottom:8px">
            AIOps Dashboard
        </div>
        """,
        unsafe_allow_html=True,
    )
