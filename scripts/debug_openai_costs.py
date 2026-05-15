"""Direct debug of OpenAI /v1/organization/costs vs Platform UI.

Probes the same endpoint our sync uses with 3 different group_by modes:
  1) no group_by  — what our sync actually consumes
  2) group_by=line_item  — break out the categories (which the Platform
     UI splits as 'Responses', 'Audio', 'Fine-tuning', etc.)
  3) group_by=project_id — confirm 1 vs many projects

Then dumps one full raw bucket so we can see every field the API returns
(line_item is often null at the org-cost level; the real category may
live in a different field like 'description' or 'cost_type').
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


def _fetch(extra_params: dict) -> dict:
    p = {
        "start_time": int(start_dt.timestamp()),
        "end_time": int(end_dt.timestamp()),
        "bucket_width": "1d",
        "limit": 31,
    }
    p.update(extra_params)
    r = requests.get(
        "https://api.openai.com/v1/organization/costs",
        headers={"Authorization": f"Bearer {api_key}"},
        params=p,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# 1) Plain call — what our sync actually does
print("=" * 70)
print("CALL 1: no group_by (same as sync)")
print("=" * 70)
data = _fetch({})
total = 0.0
for bucket in data.get("data", []):
    ts = bucket.get("start_time")
    day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    day_total = sum(
        float((it.get("amount") or {}).get("value") or 0)
        for it in bucket.get("results", [])
    )
    total += day_total
print(f"TOTAL (no group_by): ${total:.2f}\n")

# 2) Group by line_item — does API split by category when asked?
print("=" * 70)
print("CALL 2: group_by=line_item")
print("=" * 70)
try:
    data_li = _fetch({"group_by[]": "line_item"})
    by_li: dict[str, float] = defaultdict(float)
    total_li = 0.0
    for bucket in data_li.get("data", []):
        for it in bucket.get("results", []):
            amt = float((it.get("amount") or {}).get("value") or 0)
            li = it.get("line_item") or "(null)"
            by_li[li] += amt
            total_li += amt
    for li, amt in sorted(by_li.items(), key=lambda x: -x[1]):
        print(f"  {li:<55} ${amt:>10.2f}")
    print(f"  {'TOTAL':<55} ${total_li:>10.2f}")
except requests.HTTPError as e:
    print(f"  group_by=line_item failed: {e}")
print()

# 3) Group by project_id
print("=" * 70)
print("CALL 3: group_by=project_id")
print("=" * 70)
try:
    data_p = _fetch({"group_by[]": "project_id"})
    by_p: dict[str, float] = defaultdict(float)
    for bucket in data_p.get("data", []):
        for it in bucket.get("results", []):
            amt = float((it.get("amount") or {}).get("value") or 0)
            pid = it.get("project_id") or "(null)"
            by_p[pid] += amt
    for pid, amt in sorted(by_p.items(), key=lambda x: -x[1]):
        print(f"  {pid:<55} ${amt:>10.2f}")
except requests.HTTPError as e:
    print(f"  group_by=project_id failed: {e}")
print()

# 4) Dump one full bucket so we can see all available fields
print("=" * 70)
print("CALL 4: first non-empty bucket from CALL 1, RAW JSON")
print("=" * 70)
for bucket in data.get("data", []):
    if bucket.get("results"):
        print(json.dumps(bucket, indent=2))
        break
