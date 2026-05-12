"""Projects — read-only inventory pulled with project-scoped OpenAI keys.

Useful when you only have `sk-proj-...` keys for a second organisation and
can't yet pull org-wide usage. Surfaces what each project owns:
models, assistants, files, vector stores, batches, fine-tuning jobs.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from backend.config import load_config
from backend.services.openai_projects import get_project_inventories
from frontend.components import badge, fmt_int, hero, kpi_row, section


hero(
    "Projects",
    'Project-key <span class="accent">inventory</span>',
    "What each OpenAI project owns — pulled with sk-proj keys. No usage data: that needs an Admin key.",
)


CFG = load_config()

if not CFG.openai_project_keys:
    st.markdown(
        """
        <div style="
            border:1px dashed #c7d2fe; border-radius:18px; padding:32px; background:#fcfdff;
            text-align:center; color:#475569;
        ">
            <div style="font-size:13px;color:#4953d8;letter-spacing:.12em;text-transform:uppercase;font-weight:600">
                No project keys configured
            </div>
            <div style="font-size:22px;color:#06091c;font-weight:300;margin-top:8px">
                Add <code>OPENAI_PROJECT_KEYS</code> to <code>.env</code>
            </div>
            <p style="margin-top:8px">
                Format: <code>OPENAI_PROJECT_KEYS='[{"label":"Humanoid","key":"sk-proj-..."}]'</code>
                <br/>Then restart: <code>docker compose up -d</code>
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()


if st.button("Refresh inventory", type="primary"):
    st.cache_data.clear()


@st.cache_data(ttl=300, show_spinner="Probing OpenAI projects…")
def _probe_all():
    return get_project_inventories()


probes = _probe_all()

if not probes:
    st.info("No probe results yet.")
    st.stop()

ok_count = sum(1 for p in probes if p.get("ok"))
total_models = sum(len(p.get("models") or []) for p in probes)
total_assistants = sum(len(p.get("assistants") or []) for p in probes)
total_vector_stores = sum(len(p.get("vector_stores") or []) for p in probes)

kpi_row([
    {"label": "Keys probed",     "value": f"{ok_count}/{len(probes)}",
     "note": "OK / total"},
    {"label": "Total models",    "value": str(total_models),
     "note": "across all projects"},
    {"label": "Assistants",      "value": str(total_assistants)},
    {"label": "Vector stores",   "value": str(total_vector_stores)},
])


for p in probes:
    status_html = (
        badge("connected", "keep") if p.get("ok") else badge("failed", "revoke")
    )
    section(f"{p['label']} · {p['api_key_redacted']}")
    cols = st.columns(4)
    with cols[0]:
        st.markdown(
            f"**Status** {status_html}", unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(f"**Org id**<br/>`{p.get('org_id') or '—'}`", unsafe_allow_html=True)
    with cols[2]:
        st.markdown(f"**Project id**<br/>`{p.get('project_id') or '—'}`", unsafe_allow_html=True)
    with cols[3]:
        files = p.get("files") or {}
        st.markdown(
            f"**Files** {files.get('count', 0)} · "
            f"{fmt_int(files.get('bytes_total', 0))} B",
            unsafe_allow_html=True,
        )

    if not p.get("ok"):
        st.caption("Errors: " + ", ".join(p.get("errors") or ["unknown"]))
        continue

    # Models
    models = p.get("models") or []
    if models:
        with st.expander(f"Models ({len(models)})"):
            st.write(", ".join(models[:200]))

    # Assistants
    assistants = p.get("assistants") or []
    if assistants:
        with st.expander(f"Assistants ({len(assistants)})"):
            df = pd.DataFrame(assistants)
            if "tools" in df.columns:
                df["tools"] = df["tools"].apply(lambda xs: ", ".join(xs or []))
            if "created_at" in df.columns:
                df["created_at"] = pd.to_datetime(df["created_at"], unit="s", errors="coerce")
            st.dataframe(df, use_container_width=True)

    # Vector stores
    vstores = p.get("vector_stores") or []
    if vstores:
        with st.expander(f"Vector stores ({len(vstores)})"):
            st.dataframe(pd.DataFrame(vstores), use_container_width=True)

    # Batches
    batches = p.get("batches") or []
    if batches:
        with st.expander(f"Batches ({len(batches)})"):
            df = pd.DataFrame(batches)
            if "created_at" in df.columns:
                df["created_at"] = pd.to_datetime(df["created_at"], unit="s", errors="coerce")
            st.dataframe(df, use_container_width=True)

    # Fine-tuning jobs
    ft = p.get("fine_tuning_jobs") or []
    if ft:
        with st.expander(f"Fine-tuning jobs ({len(ft)})"):
            df = pd.DataFrame(ft)
            if "created_at" in df.columns:
                df["created_at"] = pd.to_datetime(df["created_at"], unit="s", errors="coerce")
            st.dataframe(df, use_container_width=True)

    if p.get("errors"):
        st.caption("Soft errors: " + ", ".join(p["errors"]))
