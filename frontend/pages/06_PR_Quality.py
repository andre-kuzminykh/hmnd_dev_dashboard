"""F-06 PR Quality."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from backend.config import load_config
from backend.services.pr_quality import get_pr_quality
from frontend.components import badge, filters_bar, hero, section
from frontend.theme import inject, render_brand


st.set_page_config(page_title="PR Quality · HMND", layout="wide")
inject()
render_brand()

CFG = load_config()

hero(
    "F-06 · PR Quality",
    'Качество <span class="accent">AI-кода</span> через призму PR',
    "Не просто сколько кода от ИИ, а насколько он качественный. Risk score = AI% × critical files × review × bugs.",
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
                Подключи GitHub, чтобы увидеть качество PR
            </div>
            <p style="margin-top:8px">
                Risk score, AI %, ревью-комментарии и rollback'и появятся после подключения
                GitHub Token в <b>Settings</b>.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()


filters = filters_bar()
repo_filter = st.text_input("Filter repository (exact name)", "")
rows = get_pr_quality(filters, repo=repo_filter or None)

if not rows:
    st.warning("No PRs in selected window.")
    st.stop()

df = pd.DataFrame(rows)
df["risk_badge"] = df["risk"].apply(lambda r: badge(r, r))
df["review"] = df["has_human_review"].apply(lambda x: "yes" if x else badge("none", "high"))
df["rolled_back"] = df["rolled_back"].apply(lambda x: badge("rollback", "high") if x else "—")

view = df[[
    "repo", "number", "author", "ai_code_pct", "review_comments",
    "critical_files_changed", "bug_count", "risk_score", "risk_badge", "review", "rolled_back",
]].rename(columns={
    "repo": "Repo",
    "number": "#",
    "author": "Author",
    "ai_code_pct": "AI %",
    "review_comments": "Review comments",
    "critical_files_changed": "Critical files",
    "bug_count": "Bugs after merge",
    "risk_score": "Risk score",
    "risk_badge": "Risk",
    "review": "Human review",
    "rolled_back": "Rollback",
})
st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"), unsafe_allow_html=True)
