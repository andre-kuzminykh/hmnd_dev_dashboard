"""F-09 Settings & Connectors."""
from __future__ import annotations

import streamlit as st

from backend.config import load_config
from backend.services.sync import run_sync
from data.connectors import AnthropicConnector, GitHubConnector, OpenAIConnector
from frontend.components import hero, section

CFG = load_config()

hero(
    "F-09 · Settings",
    'Connect your <span class="accent">sources</span>',
    "Keys come from server env vars or .streamlit/secrets.toml. Never stored in DB.",
)


def _key_status(key: str) -> str:
    if not key:
        return '<span class="hmnd-badge revoke">missing</span>'
    return '<span class="hmnd-badge keep">loaded · ' + f"{key[:7]}…{key[-4:]}" + "</span>"


section("API keys (env / secrets.toml)")
st.markdown(
    f"""
    <div style="font-size:14px;line-height:1.8">
        <b>OPENAI_API_KEY</b> &nbsp;{_key_status(CFG.openai_key)}<br>
        <b>ANTHROPIC_API_KEY</b> &nbsp;{_key_status(CFG.anthropic_key)}
        {" · <span class='hmnd-badge review'>mock mode</span>" if CFG.anthropic_mock else ""}
        <br>
        <b>GITHUB_TOKEN</b> &nbsp;{_key_status(CFG.github_token)} ·
        feature flag <code>HMND_GITHUB_ENABLED</code> = {"on" if CFG.github_enabled else "off"}
    </div>
    """,
    unsafe_allow_html=True,
)

st.caption(
    "Edit keys in `.env` (Docker) or `Environment=` in the systemd unit, "
    "then restart the service: `docker compose up -d` or `sudo systemctl restart hmnd-dashboard`."
)

section("Connection test")
c1, c2, c3 = st.columns(3)
with c1:
    if st.button("Test OpenAI", use_container_width=True):
        c = OpenAIConnector(api_key=CFG.openai_key, mock=not CFG.openai_key)
        ok = c.test_connection()
        if c.mock:
            st.info("mock mode (no key)")
        elif ok:
            st.success("connected")
        else:
            st.error("failed — check key permissions")
with c2:
    if st.button("Test Anthropic", use_container_width=True):
        c = AnthropicConnector(api_key=CFG.anthropic_key, mock=not CFG.anthropic_key)
        ok = c.test_connection()
        if CFG.anthropic_mock:
            st.info("mock mode (HMND_ANTHROPIC_MOCK=true)")
        elif c.mock:
            st.info("mock mode (no key)")
        elif ok:
            st.success("connected")
        else:
            st.error("failed — admin key required")
with c3:
    if st.button("Test GitHub", use_container_width=True, disabled=not CFG.github_enabled):
        c = GitHubConnector(api_key=CFG.github_token, mock=not CFG.github_token)
        ok = c.test_connection()
        if c.mock:
            st.info("mock mode (no token)")
        elif ok:
            st.success("connected")
        else:
            st.error("failed")

section("Sync data")
days = st.slider("Period (days)", 1, 30, 7)
if st.button("Run sync now", type="primary"):
    with st.spinner("Pulling data from connected providers…"):
        result = run_sync(period_days=days)
    st.success(f"Daily costs refreshed: {result.get('daily_costs_refreshed')}")
    st.json(result)

section("Maintenance")
if st.button("Wipe all data (drop tables, recreate schema)"):
    from data.db import init_schema, get_conn
    with get_conn() as conn:
        for t in [
            "ai_code_attribution", "alerts", "pull_requests", "commits",
            "repositories", "daily_costs", "usage_events", "api_keys", "seats",
            "model_prices", "models", "providers", "users", "teams",
        ]:
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
    init_schema()
    st.success("Database wiped.")
