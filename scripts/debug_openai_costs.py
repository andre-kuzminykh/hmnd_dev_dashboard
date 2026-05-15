"""Direct debug of OpenAI /v1/organization/costs vs Platform UI.

Hits the same endpoint our sync uses, and prints:
- one row per day with the dollar amount
- per-line-item breakdown for each day (line_item, project_id, amount)

So you can spot if /costs includes anything the Platform UI hides
(fine-tuning, code interpreter sessions, batch, web search, etc.).
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

# Pick the Artem key out of OPENAI_API_KEYS env (our normal config).
keys_raw = os.environ.get("OPENAI_API_KEYS", "").strip()
keys = json.loads(keys_raw) if keys_raw else []
artem = next((k for k in keys if (k.get("label") or "").lower() == "artem"), None)
if not artem:
    print("No 'Artem' key in OPENAI_API_KEYS env", file=sys.stderr)
    sys.exit(1)
api_key = artem["key"]

# Defaults: last 15 days, same as the Platform UI screenshot.
days = int(sys.argv[1]) if len(sys.argv) > 1 else 15
end_dt = datetime.now(timezone.utc)
start_dt = end_dt - timedelta(days=days)

print(f"Window: {start_dt.date()} → {end_dt.date()}  ({days} days, UTC)\n")

params = {
    "start_time": int(start_dt.timestamp()),
    "end_time": int(end_dt.timestamp()),
    "bucket_width": "1d",
    "limit": 31,
}
r = requests.get(
    "https://api.openai.com/v1/organization/costs",
    headers={"Authorization": f"Bearer {api_key}"},
    params=params,
    timeout=30,
)
r.raise_for_status()
data = r.json()

total = 0.0
by_lineitem: dict[str, float] = defaultdict(float)
by_project: dict[str, float] = defaultdict(float)
by_day: list[tuple[str, float, list[dict]]] = []

for bucket in data.get("data", []):
    ts = bucket.get("start_time")
    day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    day_total = 0.0
    rows = []
    for it in bucket.get("results", []):
        amount = float((it.get("amount") or {}).get("value") or 0)
        day_total += amount
        by_lineitem[it.get("line_item") or "?"] += amount
        by_project[it.get("project_id") or "(no project)"] += amount
        rows.append({
            "amount": round(amount, 4),
            "line_item": it.get("line_item"),
            "project_id": it.get("project_id"),
        })
    total += day_total
    by_day.append((day, day_total, rows))

print(f"{'DAY':<12} {'COST $':>10}")
print("-" * 24)
for day, day_total, _ in by_day:
    print(f"{day:<12} {day_total:>10.4f}")
print("-" * 24)
print(f"{'TOTAL':<12} {total:>10.2f}\n")

print("Breakdown by line_item (what kind of usage):")
for li, amt in sorted(by_lineitem.items(), key=lambda x: -x[1]):
    print(f"  {li or '(null)':<40} ${amt:>10.2f}")
print()

print("Breakdown by project_id:")
for pid, amt in sorted(by_project.items(), key=lambda x: -x[1]):
    print(f"  {pid:<40} ${amt:>10.2f}")
