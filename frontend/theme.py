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

# F-12 AI Tools view — by tool, not by provider.
# Claude family stays purple to match the Anthropic console accent;
# ChatGPT picks the OpenAI teal; Cursor uses an amber that matches their
# editor's accent. Keep these in sync with NFR-12.1.1.1.
CLAUDE = "#6366f1"      # purple
CHATGPT = "#10a37f"     # teal
CURSOR = "#f59e0b"      # amber

# F-12 risk palette (NFR-12.1.5.1)
RISK_HIGH = "#ef4444"
RISK_MEDIUM = "#f59e0b"
RISK_LOW = "#eab308"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* Inter on document; let Streamlit's Material Symbols icons keep their own font. */
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #06091c;
}
[data-testid="stAppViewContainer"] :is(p, h1, h2, h3, h4, h5, h6, label, button, input, textarea, select, span, div),
[data-testid="stSidebar"] :is(p, h1, h2, h3, h4, h5, h6, label, button, input, textarea, select) {
    font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}
/* Make sure Material Symbols glyph spans keep their icon font (otherwise the
   icon ligature shows as plain text like "dashboard"). */
[class*="material-symbols"],
[class*="MaterialIcon"],
[data-testid*="Icon"] svg,
i.material-icons,
.st-emotion-cache-eqffof span[class*="material"] {
    font-family: 'Material Symbols Rounded', 'Material Symbols Outlined',
                 'Material Icons', 'Material Icons Outlined' !important;
}

[data-testid="stAppViewContainer"] {
    background: linear-gradient(180deg, #ffffff 0%, #fcfdff 100%);
    color: #06091c;
}

[data-testid="stSidebar"] {
    background: #ffffff;
    border-right: 1px solid #e8edf3;
}

/* Headings */
h1, h2, h3 { letter-spacing: -0.03em; font-weight: 400; }
h1 { font-weight: 300; }

/* Brand header in sidebar (top-left). */
.hmnd-brand {
    display: flex; align-items: center; gap: 10px;
    padding: 6px 4px 14px 4px; border-bottom: 1px solid #e8edf3; margin-bottom: 10px;
}
.hmnd-brand img {
    width: 26px; height: 26px; object-fit: contain;
}
.hmnd-brand .title {
    font-size: 12px; letter-spacing: 0.18em; text-transform: uppercase; font-weight: 700; color: #06091c;
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

/* Window indicator below filter bar — shows the actual UTC range. */
.hmnd-window-info {
    margin: -4px 0 14px 4px; font-size: 12px; color: #475569;
    display: inline-flex; align-items: center; gap: 8px;
    padding: 4px 10px; background: #f1f5f9; border-radius: 999px;
    border: 1px solid #e2e8f0;
}
.hmnd-window-info .label { color:#64748b; text-transform: uppercase; letter-spacing: .08em; font-weight: 600; font-size: 11px; }
.hmnd-window-info .value { color:#06091c; font-weight: 500; font-variant-numeric: tabular-nums; }

/* F-12 AI Tools — provider chips and freshness header */
.hmnd-fresh { font-size:13px; color:#475569; margin: 4px 0 14px 0; display:flex; gap:14px; flex-wrap:wrap; }
.hmnd-fresh .item { display:inline-flex; align-items:center; gap:6px; }
.hmnd-fresh .item .dot { width:8px; height:8px; border-radius:50%; display:inline-block; }
.hmnd-fresh .item.claude .dot   { background:#6366f1; }
.hmnd-fresh .item.chatgpt .dot  { background:#10a37f; }
.hmnd-fresh .item.cursor .dot   { background:#f59e0b; }
.hmnd-fresh .item .label        { font-weight:600; color:#06091c; }
.hmnd-fresh .item .source-real  { color:#10b981; font-weight:600; }
.hmnd-fresh .item.claude .source-real  { color:#6366f1; }
.hmnd-fresh .item.chatgpt .source-real { color:#10a37f; }
.hmnd-fresh .item.cursor .source-real  { color:#f59e0b; }
.hmnd-fresh .item .source-mock  { color:#f59e0b; font-weight:600; font-style:italic; }
.hmnd-fresh .item .source-absent{ color:#94a3b8; font-style:italic; }

.hmnd-providers { display:flex; gap:14px; justify-content:flex-end; margin-top:-32px; font-size:12px; }
.hmnd-providers .chip { display:inline-flex; align-items:center; gap:5px; color:#475569; font-weight:500; }
.hmnd-providers .chip .dot { width:8px; height:8px; border-radius:50%; }
.hmnd-providers .chip.claude .dot  { background:#6366f1; }
.hmnd-providers .chip.chatgpt .dot { background:#10a37f; }
.hmnd-providers .chip.cursor .dot  { background:#f59e0b; }

/* Top-N horizontal bars */
.hmnd-bar-row { display:grid; grid-template-columns: 160px 1fr 70px; gap:12px; align-items:center; padding:6px 0; }
.hmnd-bar-row .name  { font-size:13px; color:#06091c; }
.hmnd-bar-row .value { font-size:13px; color:#475569; text-align:right; font-variant-numeric: tabular-nums; }
.hmnd-bar-row .track { background:#f1f5f9; border-radius:999px; height:10px; overflow:hidden; }
.hmnd-bar-row .fill  { height:100%; border-radius:999px; }
.hmnd-bar-row .fill.claude  { background:#6366f1; }
.hmnd-bar-row .fill.chatgpt { background:#10a37f; }
.hmnd-bar-row .fill.cursor  { background:#f59e0b; }
.hmnd-bar-row .fill.risk-high   { background:#ef4444; }
.hmnd-bar-row .fill.risk-medium { background:#f59e0b; }
.hmnd-bar-row .fill.risk-low    { background:#eab308; }

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
    """Top-left HUMANOID logo + name. No subtitle inside sidebar."""
    st.sidebar.markdown(
        """
        <div class="hmnd-brand">
            <img src="https://i.ibb.co/nsfMVMGM/1.png" alt="HMND" />
            <div class="title">HUMANOID</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
