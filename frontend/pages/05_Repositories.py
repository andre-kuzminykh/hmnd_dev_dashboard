"""F-05 Repositories & AI Code %."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.services.repos import get_repos_overview
from frontend.components import badge, filters_bar, hero, section
from frontend.theme import BLUE, NAVY, inject, render_brand


st.set_page_config(page_title="Repositories · HMND", layout="wide")
inject()
render_brand()

hero(
    "F-05 · Repositories",
    'Доля <span class="accent">AI-кода</span> в репозиториях',
    "Сколько % кода в каждом репозитории создано ИИ. Контроль рискованных компонентов.",
)

filters = filters_bar()
rows = get_repos_overview(filters)
if not rows:
    st.warning("No repositories yet.")
    st.stop()

df = pd.DataFrame(rows)
df["risk_badge"] = df["risk"].apply(lambda r: badge(r, r))
df["is_critical"] = df["is_critical"].apply(lambda x: "yes" if x else "no")
view = df[[
    "repo", "is_critical", "commits", "prs", "lines_added",
    "ai_lines", "ai_code_pct", "risk_badge",
]].rename(columns={
    "repo": "Repo",
    "is_critical": "Critical",
    "commits": "Commits",
    "prs": "PRs",
    "lines_added": "Lines added",
    "ai_lines": "AI lines",
    "ai_code_pct": "AI %",
    "risk_badge": "Risk",
})
st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"), unsafe_allow_html=True)

section("AI code share per repo")
fig = px.bar(df, x="repo", y="ai_code_pct", color_discrete_sequence=[BLUE])
fig.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                  margin=dict(l=10, r=10, t=10, b=10),
                  font=dict(family="Inter", color=NAVY),
                  xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#e8edf3", title="AI code %"))
st.plotly_chart(fig, use_container_width=True)
