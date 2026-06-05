# HMND AIOps Dashboard — Reference

Single-file operations reference. Where things are, how they work, how to run them.

---

## TL;DR

- **What:** Streamlit dashboard at `http://localhost:7501` that consolidates AI tool spend (OpenAI / Anthropic / Cursor) × Git activity (3 HMND repos).
- **Storage:** single SQLite file at `data/hmnd.db`. Schema lives in `data/schema.sql`.
- **Refresh:** `sync` sidecar pulls live OpenAI API every 15 min; Anthropic / Cursor / OpenAI-Humanoid come from `sources/*.json` drops (weekly).
- **Audit:** `python -m scripts.audit_etl` re-derives every dashboard number from raw bytes (17 checks).
- **Reports:** `docs/REPORT_I.md` + optional `CEO_BRIEF.html` (phone-friendly mirror).

---

## Quick start on a fresh VM

```bash
# 1. Clone and configure
git clone <repo-url> hmnd_dev_dashboard
cd hmnd_dev_dashboard
git checkout claude/token-monitoring-dashboard-aDaNV
cp .env.example .env && nano .env                      # see ".env variables" below

# 2. Drop the latest JSON exports into sources/ (see "Where to get exports")
#    Anthropics_YYYYMMDD.json
#    Cursor_YYYYMMDD.json
#    OpenAI_YYYYMMDD.json

# 3. Build + start (3 containers: dashboard, sync, snapshotter)
docker compose up -d --build

# 4. Verify
docker compose ps                                       # all 3 (healthy)
docker compose exec -T dashboard python -m scripts.audit_etl | tail -25
# Ends with 17 ✓ in SUMMARY

# 5. Open http://localhost:7501
```

### `.env` variables

| Variable | Purpose | Required for |
|----------|------|--------------|
| `OPENAI_ADMIN_KEY` | OpenAI admin API key (admin scope for `/v1/organization/*`) | OpenAI Artem live sync |
| `ANTHROPIC_API_KEY` | Anthropic API key | currently optional (Anthropic is JSON-drop) |
| `GITHUB_TOKEN` (or `HMND_GITHUB_TOKEN`) | GitHub PAT, `repo:read` scope on `HumanoidTeam/hmnd*` repos | `scripts/extract_git_stats.py`, `scripts/audit_repos_ai_readiness.py --clone` |
| `HMND_GITHUB_ENABLED` | `true`/`false` | Toggle Git-side features in UI |
| `HMND_DB_PATH` | Path to SQLite file (default `/app/data/hmnd.db` in container) | Override only if you move the DB |

Optional:

| Variable | Purpose |
|----------|------|
| `HMND_OPENAI_JSON_ORG_LABEL` | Org label for the JSON drop (default `Humanoid`) |
| `HMND_SOURCES_DIR` | Override `sources/` location |
| `HMND_ANTHROPIC_MOCK` | `true` for mock data (testing only) |
| `HMND_GITHUB_ORG` | GitHub org (default `HumanoidTeam`) |

### Where to get the JSON exports

| File pattern | Source | Frequency |
|--------------|--------|-----------|
| `Anthropics_YYYYMMDD.json` | Anthropic console → org admin → usage export | weekly |
| `Cursor_YYYYMMDD.json` | Cursor team admin → analytics → JSON export | weekly |
| `OpenAI_YYYYMMDD.json` | `openai_admin_dump` tool (pulls `/v1/organization/*` for orgs without a live admin key) | weekly |
| `git_authors_YYYYMMDD.csv` + `git_commit_file_stats_YYYYMMDD.csv` | `scripts/extract_git_stats.py` | monthly |
| `User_Leaderboard_*.csv` (optional) | Cursor team admin CSV export — used by `cursor_to_anthropic.py` | weekly |

Loaders match `Anthropics_*.json` / `Cursor_*.json` / `OpenAI_*.json` literally. Latest-by-date filename wins; older files remain as history.

---

## Architecture

Streamlit frontend reads from SQLite, no separate API layer. Loaders (`data/sources/*.py`, `data/connectors/openai.py`) write to `usage_events` (granular events) + roll up to `daily_costs` and `provider_totals`. Per-user identity collapses cross-domain emails via `data/sources/_identity.py:resolve_canonical_user_id`. Git data comes from `scripts/extract_git_stats.py` → `sources/git_commit_file_stats_*.csv` → `git_commits` + `git_authors` tables. The `sync` sidecar runs `scripts/sync.py` in a 15-min loop. The `snapshotter` sidecar dumps daily `scripts/report_i_data` output to `snapshots/YYYY-MM-DD.txt`.

| Concern | File |
|---------|------|
| Schema | `data/schema.sql` |
| DB connection | `data/db.py` |
| Cross-domain identity | `data/sources/_identity.py` |
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

## Identity matching — `_identity.py`

HMND people are seen across two email domains for the same human: `@thehumanoid.ai` (engineering) and `@skl.vc` (Sycamore corporate).

`data/sources/_identity.py:resolve_canonical_user_id(email, name)` is called by every loader:

1. Lowercase + strip email.
2. Compute `local_part(email)` (before `@`).
3. Find any existing user with the same `LOWER(local_part)` across either domain.
4. If found → return that user_id; update `full_name` if the new one is better (longer, has a space).
5. If not → insert a new user with the lowercased email; return the new id.

All loaders go through this — `anthropic_json.py`, `cursor_json.py`, `openai_json.py`, `cursor_to_anthropic.py`. New domains can be added to the matcher in `_identity.py`; historical splits then cleaned up with `scripts/merge_dual_domain_identities.py`.

To verify the state: `python -m scripts.audit_identity_collisions` returns `"No dual-domain identity collisions"` when clean.

---

## Routine operations

### Daily (automatic)
- `sync` sidecar pulls OpenAI Artem live every 15 min.
- `snapshotter` writes `snapshots/$(date +%F).txt` once per day.
- Streamlit reads DB on every render (no warm cache).

### Weekly (manual — replace JSON drops)

```bash
# Backup
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
docker compose exec -T dashboard python -m scripts.extract_git_stats
docker compose exec -T dashboard python -m scripts.sync
```

---

## Reports

| Artefact | File | Audience |
|----------|------|----------|
| Living spec | `docs/SPEC.md` | engineering |
| Verify runbook | `docs/VERIFY.md` | maintainer |
| Report I — AI Usage / Adoption / Economics | `docs/REPORT_I.md` | leadership |
| CEO-mobile mirror | `CEO_BRIEF.html` | leadership |
| Report II prep | `scripts/audit_repos_ai_readiness.py` | future maintainer |

Regenerate Report I numbers with a fresh 30d window:

```bash
docker compose exec -T dashboard python -m scripts.report_i_data > /tmp/dump.txt
```

---

## Audit (`scripts/audit_etl.py`)

Re-derives every dashboard number from raw provider files. 17 checks in 4 groups:

- **Raw → DB** (5): Anthropic, Cursor, OpenAI/Humanoid, OpenAI/API, Git CSV.
- **Service formulas** (4): Code Quality classification, dashboard math, segment partition, high-spenders cross-tool.
- **Temporal** (1): freshness + date gaps.
- **Integrity** (7): orphan FKs, money conservation (events → daily_costs → provider_totals), value sanity (no negatives / futures / NaN), tokens uncached, high-churn files, user dedup.

```bash
docker compose exec -T dashboard python -m scripts.audit_etl | tail -25
```

Each line is one check; output ends with a 17-line SUMMARY of ✓ / ✗.

---

## Snapshots

The `snapshotter` sidecar writes `snapshots/$(date -u +%F).txt` once per day:

1. Full `report_i_data` dump (10 sections: total spend, per-org, Anthropic-by-purpose, top spenders, top models, ChatGPT outliers, Cursor leaderboard, Claude Code top, Git × AI segments, summary KPIs).
2. `audit_identity_collisions` output.
3. Retention: last 30 days; older files removed by `find -mtime`.

Inspect:

```bash
cat snapshots/2026-05-13.txt
diff snapshots/2026-05-09.txt snapshots/2026-05-16.txt | grep "Top 15"
```

Manual snapshot any time:

```bash
docker compose exec -T dashboard python -m scripts.report_i_data > snapshots/manual.txt
```

---

## Scripts inventory

| Script | Purpose |
|--------|---------|
| `scripts/sync.py` | Refresh DB from all sources (one shot) — sync sidecar runs this every 15 min |
| `scripts/extract_git_stats.py` | Clone 3 repos → `git_commit_file_stats_*.csv` (monthly) |
| `scripts/audit_etl.py` | 17-check audit; re-derives every number |
| `scripts/audit_identity_collisions.py` | List users with > 1 user_id across email domains |
| `scripts/merge_dup_emails.py` | Merge case-only email duplicates (one-shot cleanup) |
| `scripts/merge_dual_domain_identities.py` | Merge `@thehumanoid.ai` ↔ `@skl.vc` people (`_identity.py` does this at insert; this script handles historical rows) |
| `scripts/report_i_data.py` | Dump every 30d KPI as plain text (10 sections) |
| `scripts/audit_repos_ai_readiness.py` | Scan 3 repos for AGENTS.md / tests / CI / docs (Report II prep — needs PAT + repos cloned) |
| `scripts/match_git_authors_llm.py` | LLM-assisted git-author → user matching (deterministic matching usually suffices) |
| `scripts/snapshot_dashboard.py` | Render dashboard text dump |
| `scripts/diagnose.py` | Connection / config sanity |
| `scripts/reset.py` | Wipe DB and re-seed (destructive) |
| `scripts/init_db.py` | Run schema migrations |
| `scripts/make_handover_archive.sh` | Build a `tar.gz` handover archive (excludes `.env`) |

---

## Tests

`docker compose exec -T dashboard python -m pytest` runs everything.

| Test file | Covers | Approx count |
|-----------|--------|-------------|
| `tests/test_git_quality.py` | F-15 Code Quality (Git × AI) — subject regex, team rollup, per-author dedup, $/fix safety, churn rollup | 15 |
| `tests/test_ux_help.py` | F-16 help tooltips — `section()` + `kpi_row()` `help=` param, HTML escape, a11y | 5 |
| `tests/test_ai_tools.py` | F-12 AI Tools tabs — freshness, user shapes, ChatGPT flag, high-spender ranking | ~10 |
| `tests/test_git_correlation.py` | Git × AI segments, bot detection, alias dedup, repo filter | 11 |
| `tests/test_pages_smoke.py` | All Streamlit pages render | ~5 |
| `tests/test_sources_anthropic.py` | Anthropic JSON loader — shape, idempotency, filename pattern | ~5 |
| `tests/test_sources_cursor.py` | Cursor JSON loader — shape, JSON-over-CSV priority | ~3 |
| `tests/test_cursor_to_anthropic.py` | Cursor → Anthropic synth — idempotency, empty CSV | 3 |
| `tests/test_overview.py` | F-01 Overview — KPI keys, zero-user case, perf, delta calc | ~5 |
| `tests/test_filters.py` | F-13 filters — date presets, API-key drill-down, project filter | ~10 |
| `tests/test_costs.py`, `test_devs.py`, `test_seats.py`, `test_models.py`, `test_alerts.py`, `test_repos.py`, `test_pr_quality.py`, `test_insights.py` | Legacy feature suites (F-02 … F-08) | ~30 |
| `tests/test_filters_matrix.py`, `test_e2e_filter_propagation.py` | Filter propagation across all tabs | ~10 |
| `tests/test_sources_etl_real.py` | Hits real source files | ~5 |

Each failing test line names the `FR-XX.Y.Z.N` requirement it covers; the matching ID also exists in `docs/SPEC.md`.

---

## Diagnostics

Common commands when something behaves unexpectedly:

```bash
# Container status
docker compose ps

# Logs (last 50 lines)
docker logs hmnd-dashboard --tail 50
docker logs hmnd-sync --tail 50
docker logs hmnd-snapshotter --tail 50

# Force-rebuild after pulling new code
docker compose up -d --build

# Inspect DB from inside the container (sqlite3 CLI is installed)
docker compose exec dashboard sqlite3 data/hmnd.db
# Or via Python:
docker compose exec -T dashboard python -c "import sqlite3; …"

# Re-run a single sync
docker compose exec -T dashboard python -m scripts.sync

# Force a hard browser refresh after sync if numbers look stale
# (Streamlit per-tab cache)
Ctrl-Shift-R
```

Behaviour cross-reference:

| Behaviour | Where it comes from |
|-----------|---------------------|
| Dashboard shows $0 for "Today" with a specific API key | `usage_events` filtered by `(occurred_at, api_key_id)` returns 0 rows — verify with `audit_identity_collisions` / direct SQL |
| Dashboard at `http://localhost:7501` returns HTML, public HTTPS URL returns `ERR_SSL_PROTOCOL_ERROR` | Dashboard binds plain HTTP on `127.0.0.1:7501`. Public HTTPS is terminated by a separate reverse proxy outside this repo |
| `audit_etl` ends with `✗` for a single provider | The check line names the source and shows `expected=$X actual=$Y Δ=±Z` |
| Container shows `unhealthy` | Healthchecks: dashboard hits `/_stcore/health`; sync checks `mtime` on `/tmp/sync.heartbeat`; snapshotter checks `/tmp/snapshotter.heartbeat` |
| `No module named scripts.xxx` after pulling new code | Image not rebuilt — `docker compose up -d --build dashboard` |
| `cannot attach stdin to a TTY-enabled container` | `docker compose exec` needs `-T` for non-interactive use |
| New JSON dropped but loader didn't pick up | Filename must match `Anthropics_*.json` / `Cursor_*.json` / `OpenAI_*.json` literally; loader takes the most recent by name date |

---

## Branch & spec

- Active branch: `claude/token-monitoring-dashboard-aDaNV`. Pull before pushing.
- Living spec: `docs/SPEC.md` (F-01 through F-16). Each requirement has an ID + ≥ 1 test in `tests/`.
- Git history is the change log — every behavioural change has a commit explaining the motivation.
