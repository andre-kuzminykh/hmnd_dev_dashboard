# Verify dashboard data — 100% confidence runbook

A 5-minute checklist for proving every number on the dashboard is
correct. Run this **after every sync** when you need to trust the data
(monthly review, demo to a board, etc.).

## 1. Re-derive every number from raw bytes

Single command, runs in under a minute, exits non-zero on any
discrepancy:

```bash
docker compose exec dashboard python -m scripts.audit_etl
```

What it checks (each as a `✓` / `✗` line in the output):

### A. Raw → DB (data ingestion correctness)

| Source | Ground truth → what we verify |
|--------|-------------------------------|
| **Anthropic** | `sum(report.results[].cost.amount)` from raw `Anthropics_*.json` ↔ `SUM(usage_events.cost_usd) WHERE provider='anthropic'` ↔ loader's reported total |
| **Cursor** | `sum(spendCents + includedSpendCents) / 100` from raw `Cursor_*.json` ↔ `SUM(cost_usd) WHERE provider='cursor'` |
| **OpenAI · Humanoid** | `sum(daily_spend.amount)` from raw `OpenAI_*.json` ↔ DB sum |
| **OpenAI · API push** | `provider_totals` per-day == `SUM(usage_events.cost_usd)` per-day for the API-pushed source; every event tagged with `organization_id` |
| **Tokens (uncached)** | input + output sum across all events matches loader's report |
| **Git authors** | Σ commits / additions / deletions from raw `git_authors.csv` ↔ DB |
| **Code Quality** | For each unique `(repo, sha)` in `git_commit_file_stats.csv`: re-run `_classify_subject` on subject line; sum flags per repo; compare with `git_commits` table AND with `get_team_quality(repos=[r])` service output |

### B. Service-layer formulas (dashboard math correctness)

| Check | What it verifies |
|-------|------------------|
| **Dashboard math** | `bug_rate_pct == fixes / commits * 100` (rounding-exact); same for revert_rate and human_bug_rate. `human_commits + bot_commits == total_commits` (no orphan `is_bot=NULL`). Per-author rows count = unique `COALESCE(user_id, author_name)` keys (alias dedup). |
| **Segment partition** | Every dev gets ≥ 1 segment label AND the label is one of the spec'd 8 (`HIGH_AI_SPEND_HIGH_GIT_OUTPUT`, etc). Σ devs across segments == total devs. |
| **High Spenders math** | For every cross-tool spender row, `spend == cost_openai + cost_anthropic + cost_cursor` within $0.05. Catches double-count bugs in the cross-provider rollup. |
| **High-churn files** | Top-15 files from `get_high_churn_files(period_days=0)` is byte-identical to a fresh top-15 computed directly from raw CSV. |

**Pass criteria:** all rows show `✓`, exit code 0.
**On failure:** the failing row shows `expected=$X actual=$Y Δ=±Z` —
investigate that one source.

## 2. Spot-check one number against provider UI

Total spend per provider should match within rounding (~5%):

| Provider | Where to check |
|----------|---------------|
| **OpenAI** | https://platform.openai.com/settings/organization/usage → period filter to last 30d |
| **Anthropic** | https://console.anthropic.com → Usage → period filter |
| **Cursor** | https://www.cursor.com/team → Settings → Billing |

Differences > 5% almost always mean: provider includes batch/cached
discounts we don't model, or our period boundary is off by a day.

## 3. Spot-check Code Quality against `git log`

Pick any one repo and verify the bug-fix count matches a direct git
query:

```bash
# how many "fix" commits in hmnd over last 30d, by raw git
cd /path/to/your/hmnd-repo
git log --since='30 days ago' --pretty=format:'%s' | \
  grep -iE '\b(fix|fixes|fixed|bug|bugfix|hotfix|patch)\b|^fix[:(!]' | wc -l
```

Compare with the `Bug-fix rate × Commits` shown on the **Devs (Git × AI)
→ Code Quality** section, single-repo filter.

## 4. Cross-check `$/fix` math

Two numbers on the dashboard must satisfy:

```
ai_spend_per_fix == ai_spend / fixes
```

Where:
- `ai_spend` = team-wide AI spend in the same period (Total spend KPI)
- `fixes`    = bug-fix commits in the same period (Code Quality → Commits × Bug-fix rate)

Both shown as separate numbers under the `$/fix` card. If they don't
divide cleanly, file an issue — it's a bug.

## 5. Verify the `git_commits` table is fresh

```bash
docker compose exec dashboard sqlite3 data/hmnd.db \
  "SELECT MIN(author_date), MAX(author_date), COUNT(*) FROM git_commits;"
```

`MAX(author_date)` should be within 24h of the most recent commit you
made. If it's days old, your `git_commit_file_stats_*.csv` is stale —
re-run `python -m scripts.extract_git_stats`.

## What to do when numbers feel "off"

1. **Re-run sync** first — `docker compose exec dashboard python -m scripts.sync`.
   The dashboard reads from a snapshot DB; a fresh CSV needs a sync.
2. **Run the audit** (step 1 above). Any `✗` row points at the failing
   ETL stage.
3. **Check the period filter** — many KPIs change radically between
   "Last 7 days" and "Last 90 days". Make sure your mental model
   matches what's set in the top filter.
4. **Read the `?` tooltip** on the metric — most non-obvious behavior
   (e.g. `$/fix` ignoring repo filter, AI lines being lifetime) is
   spelled out there.

---

## Pre-demo checklist (10 minutes, before showing to leadership)

Run **in this order** the morning of your demo:

```bash
# 1. Refresh source data (extract → drop into sources/)
docker compose exec dashboard python -m scripts.extract_git_stats

# 2. Re-sync the DB from current sources/
docker compose exec dashboard python -m scripts.sync

# 3. Run the audit — must end with all 11 ✓
docker compose exec dashboard python -m scripts.audit_etl
#    Expected SUMMARY:
#      ✓ Anthropic
#      ✓ Cursor
#      ✓ OpenAI / Humanoid
#      ✓ OpenAI / API push
#      ✓ Tokens (uncached)
#      ✓ Git CSV
#      ✓ Code Quality
#      ✓ Dashboard math
#      ✓ Segment partition
#      ✓ High Spenders math
#      ✓ High-churn files

# 4. Confirm dashboard is up and freshness chips read "live" or "1d old"
curl -s http://localhost:8501 | grep -q "AIOps" && echo "dashboard responding"

# 5. Run the unit-test suite (≈ 2 min)
docker compose exec dashboard python -m pytest -q
```

If any of 1-5 fail, **don't demo**. Fix the issue or wait for next
sync window.
