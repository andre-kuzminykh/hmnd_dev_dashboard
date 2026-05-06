"""F-09 Settings & Connectors."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from data.connectors import AnthropicConnector, GitHubConnector, OpenAIConnector
from data.seed import seed
from frontend.components import hero, section
from frontend.theme import inject, render_brand


st.set_page_config(page_title="Settings · HMND", layout="wide")
inject()
render_brand()

hero(
    "F-09 · Settings",
    'Подключение <span class="accent">источников</span>',
    "Ключи OpenAI/Anthropic/GitHub. Без ключей дашборд работает в mock-режиме на seed-данных.",
)

# FR-09.1.1.2 — секреты живут в session_state и не пишутся в БД
session_keys = st.session_state.setdefault("api_keys", {})

section("Credentials")
c1, c2, c3 = st.columns(3)
with c1:
    session_keys["openai"] = st.text_input(
        "OpenAI API key", session_keys.get("openai", ""), type="password"
    )
    if st.button("Test OpenAI"):
        ok = OpenAIConnector(session_keys["openai"], mock=not session_keys["openai"]).test_connection()
        st.success("connected (mock)" if not session_keys["openai"] else f"connection: {ok}")

with c2:
    session_keys["anthropic"] = st.text_input(
        "Anthropic API key", session_keys.get("anthropic", ""), type="password"
    )
    if st.button("Test Anthropic"):
        ok = AnthropicConnector(session_keys["anthropic"], mock=not session_keys["anthropic"]).test_connection()
        st.success("connected (mock)" if not session_keys["anthropic"] else f"connection: {ok}")

with c3:
    session_keys["github"] = st.text_input(
        "GitHub token", session_keys.get("github", ""), type="password"
    )
    if st.button("Test GitHub"):
        ok = GitHubConnector(session_keys["github"], mock=not session_keys["github"]).test_connection()
        st.success("connected (mock)" if not session_keys["github"] else f"connection: {ok}")

section("Demo data")
if st.button("Reseed database (drops & regenerates demo data)"):
    seed()
    st.success("Database reseeded.")
