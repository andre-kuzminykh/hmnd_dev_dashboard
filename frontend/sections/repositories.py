"""F-05 Repositories & AI Code %."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.config import load_config
from backend.services.repos import get_repos_overview
from frontend.components import badge, filters_bar, hero, section
from frontend.theme import BLUE, NAVY

CFG = load_config()

hero(
    "F-05 · Repositories",
    'Share of <span class="accent">AI code</span> per repo',
    "How much of every repository was written by AI. Visibility into risk on critical components.",
)

if not CFG.github_enabled:
    st.markdown(
        """
        <div style="
            border:1px dashed #c7d2fe; border-radius:18px; padding:32px; background:#fcfdff;
            text-align:center; color:#475569;
        ">
            <div style="font-size:13px;color:#4953d8;letter-spacing:.12em;text-transform:uppercase;font-weight:600">
                Coming soon
            </div>
            <div style="font-size:22px;color:#06091c;font-weight:300;margin-top:8px">
                Connect GitHub to see AI code share
            </div>
            <p style="margin-top:8px">
                Open <b>Settings</b> → add a GitHub Token → enable
                <code>HMND_GITHUB_ENABLED=true</code> → run a sync.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

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
    "repo": "Repo", "is_critical": "Critical",
    "commits": "Commits", "prs": "PRs", "lines_added": "Lines added",
    "ai_lines": "AI lines", "ai_code_pct": "AI %", "risk_badge": "Risk",
})
st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"), unsafe_allow_html=True)

section("AI code share per repo")
fig = px.bar(df, x="repo", y="ai_code_pct", color_discrete_sequence=[BLUE])
fig.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                  margin=dict(l=10, r=10, t=10, b=10),
                  font=dict(family="Inter", color=NAVY),
                  xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#e8edf3", title="AI code %"))
st.plotly_chart(fig, use_container_width=True)
