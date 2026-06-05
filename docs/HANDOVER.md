# HMND AIOps Dashboard — Handover

> Single-file onboarding for the next maintainer. If you read only this file, you can run the dashboard, refresh data, run audits, present to leadership, and debug the common failure modes.

---

## TL;DR (60 seconds)

- **What:** Streamlit dashboard at `http://localhost:7501` that consolidates AI tool spend (OpenAI / Anthropic / Cursor) × Git activity (3 HMND repos) for HMND leadership.
- **Storage:** single SQLite file at `data/hmnd.db`. Schema lives in `data/schema.sql`.
- **Refresh:** `sync` sidecar pulls live OpenAI API every 15 min; Anthropic / Cursor / OpenAI-Humanoid come from `sources/*.json` drops (manual every week).
- **Trust:** `python -m scripts.audit_etl` re-derives every number from raw bytes (17 checks, all must be ✓).
- **Reports:** `docs/REPORT_I.md` (leadership-facing, with `Appendix A` trust assessment). Optional `CEO_BRIEF.html` mobile mirror.

---

## Quick start on a fresh VM (15 minutes)

```bash
# 1. Clone and configure
git clone <repo-url> hmnd_dev_dashboard
cd hmnd_dev_dashboard
git checkout claude/token-monitoring-dashboard-aDaNV   # current main work branch
cp .env.example .env && nano .env                      # see ".env variables" below

# 2. Drop the latest JSON exports into sources/ (see "Where to get exports")
#    Anthropics_YYYYMMDD.json
#    Cursor_YYYYMMDD.json
#    OpenAI_YYYYMMDD.json

# 3. Build + start (3 containers: dashboard, sync, snapshotter)
docker compose up -d --build

# 4. Verify everything works
docker compose ps                                       # all 3 (healthy)
docker compose exec -T dashboard python -m scripts.audit_etl | tail -25
# Expect: 17 ✓ in SUMMARY

# 5. Open http://localhost:7501 (or via reverse proxy)
```

### `.env` variables

Required for the dashboard / sync / snapshotter to work:

| Variable | What | Required for |
|----------|------|--------------|
| `OPENAI_ADMIN_KEY` | OpenAI admin API key (NOT a user key — admin scope for `/v1/organization/*` endpoints) | OpenAI Artem live sync. Get from [platform.openai.com → Settings → Organization → Admin Keys](https://platform.openai.com/settings/organization/admin-keys) |
| `ANTHROPIC_API_KEY` | Anthropic API key | (currently optional — Anthropic is JSON-drop only) |
| `GITHUB_TOKEN` (or `HMND_GITHUB_TOKEN`) | GitHub PAT, **`repo:read` scope** on `HumanoidTeam/hmnd*` repos | `scripts/extract_git_stats.py`, `scripts/audit_repos_ai_readiness.py --clone` |
| `HMND_GITHUB_ENABLED` | `true`/`false` | Toggle Git-side features in UI |
| `HMND_DB_PATH` | Path to SQLite file (default `/app/data/hmnd.db` in container) | Override only if you move the DB |

Optional / advanced:

| Variable | What |
|----------|------|
| `HMND_OPENAI_JSON_ORG_LABEL` | Org label for the JSON drop (default `Humanoid`); use if you ingest a JSON for a different org |
| `HMND_SOURCES_DIR` | Override `sources/` location |
| `HMND_ANTHROPIC_MOCK` | `true` for mock data (testing only — keep `false` in prod) |
| `HMND_GITHUB_ORG` | GitHub org (default `HumanoidTeam`) |

### Where to get the JSON exports

| File pattern | Source | Frequency |
|--------------|--------|-----------|
| `Anthropics_YYYYMMDD.json` | Anthropic console → org admin → usage export (or internal `anthropic_admin_dump` tool if you've built one) | weekly |
| `Cursor_YYYYMMDD.json` | Cursor team admin → analytics → JSON export (or use their Team API) | weekly |
| `OpenAI_YYYYMMDD.json` | Internal `openai_admin_dump` tool — pulls `/v1/organization/*` for the Humanoid org (the one we don't have a live admin key for) | weekly |
| `git_authors_YYYYMMDD.csv` + `git_commit_file_stats_YYYYMMDD.csv` | `scripts/extract_git_stats.py` — clones 3 repos via PAT | monthly |
| `User_Leaderboard_*.csv` (optional) | Cursor team admin CSV export — used by `cursor_to_anthropic.py` to synthesise Claude Code events | weekly |

**Pattern matters**: loaders match `Anthropics_*.json` / `Cursor_*.json` / `OpenAI_*.json` literally. Latest-by-date filename wins. Old files stay as history (don't delete — `audit_etl` may reference earlier dates).

---

## Architecture (one-paragraph + map)

Streamlit frontend reads from SQLite, no separate API layer. Loaders (`data/sources/*.py`, `data/connectors/openai.py`) write to `usage_events` (granular events) + roll up to `daily_costs` and `provider_totals`. Per-user identity collapses cross-domain emails via `data/sources/_identity.py:resolve_canonical_user_id` (handles `@thehumanoid.ai` ↔ `@skl.vc`). Git data comes from `scripts/extract_git_stats.py` → `sources/git_commit_file_stats_*.csv` → `git_commits` + `git_authors` tables. The `sync` sidecar wraps `scripts/sync.py` in a 15-min `while true; do …; sleep 900; done` loop. The `snapshotter` sidecar dumps daily `scripts/report_i_data` output to `snapshots/YYYY-MM-DD.txt` for audit trail.

| Concern | File |
|---------|------|
| Schema | `data/schema.sql` |
| DB connection | `data/db.py` |
| Cross-domain identity | `data/sources/_identity.py` (parallel-session work) |
| OpenAI API loader | `data/connectors/openai.py` |
| OpenAI JSON loader (Humanoid) | `data/sources/openai_json.py` |
| Anthropic JSON loader | `data/sources/anthropic_json.py` |
| Cursor JSON loader | `data/sources/cursor_json.py` |
| Cursor → Anthropic synth | `data/cursor_to_anthropic.py` |
| Git CSV loader | `data/sources/git_csv.py` |
| Sync entrypoint | `backend/services/sync.py` + `scripts/sync.py` |
| AI-tools service | `backend/services/ai_tools.py` |
| Code-quality service | `backend/services/git_quality.py` |
| Git × AI correlation | `backend/services/git_correlation.py` |
| Streamlit pages | `frontend/main.py` → `frontend/sections/*.py` |
| Theme / components | `frontend/theme.py`, `frontend/components.py` |
| Living spec | `docs/SPEC.md` (F-01 … F-16) |

---

## Cross-domain identity: `_identity.py`

HMND people use **two email domains** for the same human:
- `@thehumanoid.ai` — engineering work email (primary in Anthropic, Git, OpenAI)
- `@skl.vc` — Sycamore corporate email (primary in Cursor sometimes)

Without help, `INSERT INTO users(email) VALUES('atin@thehumanoid.ai')` and another `INSERT … VALUES('atin@skl.vc')` make **two user_id rows** for the same person. Per-spender ranks, segment classification, and Top spenders all break.

`data/sources/_identity.py:resolve_canonical_user_id(email, name)` solves this **at insert time**:
1. Lowercase + strip email.
2. Compute `local_part(email)` (before `@`).
3. Find any existing user with the same `LOWER(local_part)` across either domain.
4. If found → return that user_id, optionally update `full_name` if the new name is better (longer, has a space).
5. If not → insert a new user with the lowercased email; return new id.

All loaders (`anthropic_json.py`, `cursor_json.py`, `openai_json.py`, `cursor_to_anthropic.py`) go through this. So weekly JSON drops can't re-introduce dual-domain splits.

If you ever change the domain list (e.g. add a third corporate domain), update the matcher in `_identity.py` and re-run `scripts/merge_dual_domain_identities.py` to clean up historical splits.

**Verify it's working**: `audit_identity_collisions` must return `"No dual-domain identity collisions"` after every sync.

---

## Test inventory

`docker compose exec -T dashboard python -m pytest` runs everything. Target: ≥ 50 green.

| Test file | What it covers | Count |
|-----------|----------------|-------|
| `tests/test_git_quality.py` | F-15 Code Quality (Git × AI) — subject regex, team rollup, per-author dedup, $/fix safety, churn rollup | 15 |
| `tests/test_ux_help.py` | F-16 help tooltips — section() + kpi_row() help= param, HTML escape, a11y | 5 |
| `tests/test_ai_tools.py` | F-12 AI Tools tabs — freshness, user shapes, ChatGPT flag, high-spender ranking | ~10 |
| `tests/test_git_correlation.py` | Git × AI segments, bot detection, alias dedup, repo filter | 11 |
| `tests/test_pages_smoke.py` | All Streamlit pages render without crashing | ~5 |
| `tests/test_sources_anthropic.py` | Anthropic JSON loader — shape, idempotency, filename pattern | ~5 |
| `tests/test_sources_cursor.py` | Cursor JSON loader — shape, JSON-over-CSV priority | ~3 |
| `tests/test_cursor_to_anthropic.py` | Cursor → Anthropic synth — idempotency, empty CSV case | 3 |
| `tests/test_overview.py` | F-01 Overview — KPI keys, zero-user case, perf, delta calc | ~5 |
| `tests/test_filters.py` | F-13 filters — date presets, API-key drill-down, project filter | ~10 |
| `tests/test_costs.py`, `test_devs.py`, `test_seats.py`, `test_models.py`, `test_alerts.py`, `test_repos.py`, `test_pr_quality.py`, `test_insights.py` | Legacy feature suites (F-02 … F-08) | ~30 |
| `tests/test_filters_matrix.py`, `test_e2e_filter_propagation.py` | Filter propagation across all tabs | ~10 |
| `tests/test_sources_etl_real.py` | Hits real source files (smoke test for production data) | ~5 |

If any test goes red after changes, the failing line tells you which `FR-XX.Y.Z.N` requirement broke — that ID also exists in `docs/SPEC.md` so you can read the original spec.

---

## Snapshots — using the daily audit trail

The `snapshotter` sidecar writes `snapshots/$(date -u +%F).txt` once per day:
1. Full `report_i_data` dump (10 sections: total spend, per-org, Anthropic-by-purpose, top spenders, top models, ChatGPT outliers, Cursor leaderboard, Claude Code top, Git × AI segments, summary KPIs).
2. `audit_identity_collisions` output (catch any regression where loaders missed a cross-domain merge).
3. Retention: last 30 days, older files auto-deleted by `find -mtime`.

**When to use:**
- "Did we have these numbers 3 days ago?" → `cat snapshots/2026-05-13.txt`
- "Did our Top 5 spenders change this week?" → `diff snapshots/2026-05-09.txt snapshots/2026-05-16.txt | grep "Top 15"`
- "Did a new dual-domain person sneak in?" → tail any recent snapshot for `audit_identity_collisions` block

**If snapshotter is unhealthy:**
- `docker logs hmnd-snapshotter --tail 50` — usually a sync failure or schema drift
- Manual snapshot any time: `docker compose exec -T dashboard python -m scripts.report_i_data > snapshots/manual.txt`

---

## Routine operations

### Daily (automatic — nothing to do)
- `sync` sidecar pulls OpenAI Artem live every 15 min.
- `snapshotter` sidecar writes `snapshots/$(date +%F).txt` once per day for audit trail.
- Streamlit reads DB on every page render (no warm cache to invalidate).

### Weekly (manual — replace the JSON drops)
Full runbook in chat history, here's the gist:

```bash
# Backup first
TS=$(date -u +%Y%m%d_%H%M%S)
mkdir -p ~/hmnd_backups/$TS
cp data/hmnd.db ~/hmnd_backups/$TS/
cp -r sources ~/hmnd_backups/$TS/

# Stop services while swapping
docker compose stop dashboard sync snapshotter

# Drop new JSON files into sources/ with new date in filename
# (loader picks latest-by-date; old files stay as history)

# Restart + sync
docker compose up -d
docker compose exec -T dashboard python -m scripts.sync

# Verify
docker compose exec -T dashboard python -m scripts.audit_etl | tail -25
docker compose exec -T dashboard python -m scripts.audit_identity_collisions
```

### Monthly (refresh Git data)
```bash
# Re-clone + extract — this overwrites sources/git_commit_file_stats_*.csv
docker compose exec -T dashboard python -m scripts.extract_git_stats
docker compose exec -T dashboard python -m scripts.sync     # re-loads git CSV
```

---

## The reports

| Artefact | File | Audience |
|----------|------|----------|
| Living spec | `docs/SPEC.md` | engineering |
| Verify runbook | `docs/VERIFY.md` | maintainer (pre-demo checklist) |
| **Report I — AI Usage / Adoption / Economics** | `docs/REPORT_I.md` | leadership (CEO/COO/CTO) |
| → Trust assessment (each claim 🟢 / 🟡 / 🔴) | `docs/REPORT_I.md` § Appendix A | maintainer + leadership |
| → Dual-identity disclosure | `docs/REPORT_I.md` § Appendix A.10 | leadership |
| CEO-mobile mirror | `CEO_BRIEF.html` | leadership (phone-friendly) |
| Report II prep notes | `scripts/audit_repos_ai_readiness.py` + README | future maintainer |

**To regenerate the Report I numbers** with fresh 30d window:
```bash
docker compose exec -T dashboard python -m scripts.report_i_data > /tmp/dump.txt
# Paste sections A-J back to a Claude session and ask it to refresh REPORT_I.md.
```

---

## Trust framework

Every number on the dashboard is auditable from raw bytes. The 17 checks live in `scripts/audit_etl.py`:

**A. Raw → DB** (5): Anthropic, Cursor, OpenAI/Humanoid, OpenAI/API, Git CSV.
**B. Service formulas** (4): Code Quality classification, dashboard math, segment partition, high-spenders cross-tool.
**C. Temporal** (1): freshness + date gaps.
**D. Integrity** (7): orphan FKs, money conservation (events → daily_costs → provider_totals), value sanity (no negatives / futures / NaN), tokens uncached, high-churn files, user dedup.

**Run before any demo:**
```bash
docker compose exec -T dashboard python -m scripts.audit_etl | tail -25
# Must end with 17 ✓
```

If any row shows ✗: the line gives `expected=$X actual=$Y Δ=±Z` — investigate the failing source first.

---

## Scripts inventory

| Script | Purpose | When |
|--------|---------|------|
| `scripts/sync.py` | Refresh DB from all sources (one shot) | Sync sidecar runs it every 15 min |
| `scripts/extract_git_stats.py` | Clone 3 repos → `git_commit_file_stats_*.csv` | Monthly / when repos change |
| `scripts/audit_etl.py` | 17-check audit; re-derives every number | **Before every demo** |
| `scripts/audit_identity_collisions.py` | List people with > 1 user_id across email domains | After any sync |
| `scripts/merge_dup_emails.py` | Merge case-only email duplicates | One-shot cleanup |
| `scripts/merge_dual_domain_identities.py` | Merge `@thehumanoid.ai` ↔ `@skl.vc` people | Mostly obsolete — `_identity.py` now does this at insert. Useful for legacy DB |
| `scripts/report_i_data.py` | Dump every 30d KPI as plain text (10 sections) | When you want to refresh Report I numbers |
| `scripts/audit_repos_ai_readiness.py` | Scan 3 repos for AGENTS.md / tests / CI / docs | Report II prep — needs PAT + repos cloned |
| `scripts/match_git_authors_llm.py` | LLM-assisted git-author → user matching | Optional; deterministic matching usually suffices |
| `scripts/snapshot_dashboard.py` | Render dashboard text dump | Spot-check vs UI |
| `scripts/diagnose.py` | Connection / config sanity | When things look broken |
| `scripts/reset.py` | Wipe DB and re-seed (DESTRUCTIVE) | Last-resort recovery |
| `scripts/init_db.py` | Run schema migrations | After schema changes |

---

## Known caveats (disclose proactively to leadership)

1. **"Anthropic Agent" purpose mixes real CC + synthesised events.** Top CC users all show exactly 56 events — that's a synthesis quantum from `cursor_to_anthropic.py` (8 days × 7 = 56). Real Claude Code spend is somewhere between 60% and 83% of Anthropic. Report I § Appendix A.4.
2. **Cursor `ai_lines` is lifetime, not period-filtered.** Cursor exports total per user; we surface it as-is. Don't equate to "lines of merged code". Report I § Appendix A.5.
3. **Optimization $-savings are directional estimates**, not promises. The $1.5-3k/mo opportunity assumes ~50% reduction in reasoning-model usage by 3 outliers. Report I § Appendix A.7.
4. **OpenAI per-user $ is an estimate**, not billed. `/v1/organization/costs` returns `user_id: null`; per-user $ comes from request share × total. Ranks are right, absolute dollars ±20% per person. Report I § Appendix A.1.
5. **Anthropic's own rollup vs userCost has +1.43% internal drift.** Our DB matches userCost (per-user attribution); rollup is $44,731, userCost sums to $45,369. Within ±1.5% — Anthropic's bookkeeping, not ours.

When the boss asks "are these numbers right?": **show them `docs/VERIFY.md` § 1** (the 17-✓ audit) and disclose the 5 caveats above before they find them.

---

## Common issues & debugging

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `audit_etl` shows ✗ on Anthropic | new JSON drop has malformed `_meta.rangeStart` | inspect raw JSON, re-export from console |
| `audit_etl` shows ✗ on money conservation | A sync was interrupted mid-write | Re-run `python -m scripts.sync` |
| `audit_identity_collisions` shows new collisions | Someone signed up under both domains | `_identity.py` should catch this on next sync — verify it's installed |
| Dashboard shows $0 for "Today" | API has 1-4h reporting lag (normal) OR specific API key wasn't used today | Pick "Last 7 days" period to confirm |
| `hmnd-sync` container is `unhealthy` | Healthcheck looks for `/tmp/sync.heartbeat` mtime — sync loop crashed | `docker logs hmnd-sync --tail 50` |
| Page shows stale data after sync | Streamlit caches per-tab — try hard refresh (Ctrl-Shift-R) | Or `docker compose restart dashboard` |
| `No module named scripts.xxx` | Container running old image | `docker compose up -d --build dashboard` |
| `cannot attach stdin to a TTY-enabled container` | Forgot `-T` flag on `exec` | `docker compose exec -T dashboard ...` |
| `sqlite3: executable file not found` | Use Python instead | `docker compose exec -T dashboard python -c "import sqlite3; …"` |
| HTTPS / `ERR_SSL_PROTOCOL_ERROR` on public URL | Dashboard only serves HTTP 7501 — reverse proxy issue | Check Caddy / nginx / Traefik config (separate from this repo) |
| New JSON dropped but dashboard didn't pick up | Filename pattern wrong — must match `Anthropics_*.json` / `Cursor_*.json` / `OpenAI_*.json` | Rename per pattern |

---

## What's NOT done (handover backlog)

1. **Report II — Technical Repository Audit & AI-Codegen Readiness.** Prep script (`scripts/audit_repos_ai_readiness.py`) exists but needs the 3 repos cloned + PAT to run. Output then feeds a Claude session to write `docs/REPORT_II.md`.
2. **PR-level data.** Currently we have commit subjects (regex-classified into bug-fix / feature / refactor). Adding GitHub PR data (review comments, time-to-merge, revert chains) would let us answer "did AI-generated code make it through review easily?".
3. **Jira / incident integration.** Today bug-fix rate is self-declared in commit messages. With Jira we'd know if a fix closed a P0/P1.
4. **Separate real vs synthesised Claude Code events.** Add a column to `usage_events` tagging synthesis source; convert the 🟡 in Report I § A.4 to 🟢.
5. **Median + top-decile per-user $ on Overview.** Current "avg spend/user $150" averages near-zero users in. Median ≈ $5-20.
6. **Automate JSON drops.** Currently manual weekly drop. Anthropic Admin API + Cursor Teams API could be polled.

---

## Two-sentence pitch for the leadership demo

> "Every dollar HMND spends on AI is now traceable — we know who, on what tool, on what model, and for what commit. The dashboard re-derives every number from raw provider exports and a 17-check audit makes that verifiable in 60 seconds; the dual-identity issue that fragmented people across `@thehumanoid.ai` and `@skl.vc` has been merged and is now prevented at insert time."

---

## Contact / context

- This branch (`claude/token-monitoring-dashboard-aDaNV`) is the active main work branch.
- Two Claude sessions have been collaborating on it concurrently — pull before pushing.
- Living spec is `docs/SPEC.md` (F-01 through F-16). Each requirement has an ID and ≥ 1 test in `tests/`.
- Test suite: `docker compose exec -T dashboard python -m pytest`. Target: ≥ 50 green; `test_cursor_to_anthropic` should be green after the test-isolation fix.
- Git history is the audit trail — every behavioural change has a commit explaining why.
