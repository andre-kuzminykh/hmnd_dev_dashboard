"""F-08 Alerts."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from backend.services.alerts import evaluate_alert_rules, list_alerts, update_status
from frontend.components import badge, hero, section

hero(
    "Alerts",
    'Signals and <span class="accent">rules</span>',
    "Spend spikes, budget overruns, idle paid seats, risky PRs.",
)

c1, c2, c3 = st.columns([1, 1, 1])
with c1:
    severity = st.selectbox("Severity", ["all", "critical", "high", "medium", "low"])
with c2:
    status = st.selectbox("Status", ["new", "ack", "resolved", "all"])
with c3:
    if st.button("Re-evaluate rules", use_container_width=True):
        n = evaluate_alert_rules()
        st.toast(f"Inserted {n} new alerts")
        st.rerun()

alerts = list_alerts(status=status, severity=severity)
if not alerts:
    st.info("No alerts match the filters.")
    st.stop()

df = pd.DataFrame(alerts)
df["severity_badge"] = df["severity"].apply(lambda s: badge(s, s if s != "critical" else "high"))
view = df[["created_at", "severity_badge", "type", "subject_kind", "subject_id", "message", "status"]].rename(
    columns={
        "created_at": "Created", "severity_badge": "Severity",
        "type": "Type", "subject_kind": "Subject", "subject_id": "Id",
        "message": "Message", "status": "Status",
    }
)
st.markdown(view.to_html(escape=False, index=False, classes="hmnd-table"), unsafe_allow_html=True)

section("Resolve / acknowledge")
sel_id = st.selectbox("Alert ID", [a["id"] for a in alerts])
new_status = st.radio("New status", ["ack", "resolved", "new"], horizontal=True)
if st.button("Apply"):
    update_status(int(sel_id), new_status)
    st.toast(f"Alert {sel_id} → {new_status}")
    st.rerun()
