# HMND AIOps Dashboard

Streamlit dashboard at `http://localhost:7501` that consolidates AI tool spend (OpenAI / Anthropic / Cursor) and Git activity (3 HMND repositories) into a single leadership view.

> **Start here:** [`docs/HANDOVER.md`](docs/HANDOVER.md) — single-file operations reference (architecture, env vars, weekly refresh, scripts inventory, tests).

---

## Quick start

```bash
# 1. Configure
cp .env.example .env && nano .env

# 2. Drop the latest JSON exports into sources/
#    Anthropics_YYYYMMDD.json
#    Cursor_YYYYMMDD.json
#    OpenAI_YYYYMMDD.json

# 3. Build + start (3 containers: dashboard, sync, snapshotter)
docker compose up -d --build

# 4. Verify
docker compose ps
docker compose exec -T dashboard python -m scripts.audit_etl | tail -25

# 5. Open http://localhost:7501
```

---

## Repository layout

```
frontend/main.py             — entry point; renders Overview + AI Tools
frontend/sections/           — page sections (overview.py, ai_tools.py rendered;
                               others are legacy backends still usable)
frontend/theme.py            — palette + CSS
frontend/components.py       — KPI cards, badges, filters, tooltip helper

backend/services/            — business logic per feature
                               (ai_tools, git_quality, git_correlation,
                                cursor_analytics, overview, sync, …)
backend/config.py            — .env loader
backend/analytics.py         — shared SQL helpers

data/schema.sql              — SQLite DDL
data/db.py                   — connection helper, schema migration
data/sources/                — JSON / CSV loaders + _identity.py
data/connectors/openai.py    — live OpenAI Admin API
data/cursor_to_anthropic.py  — synthesise Anthropic Agent events from Cursor

scripts/sync.py              — refresh DB from all sources (sync sidecar runs this)
scripts/audit_etl.py         — 17-check audit (raw → DB → service formulas)
scripts/audit_identity_collisions.py
scripts/merge_dup_emails.py / merge_dual_domain_identities.py
scripts/report_i_data.py     — dump 30d KPIs as plain text
scripts/extract_git_stats.py — clone 3 repos → git_commit_file_stats_*.csv
scripts/audit_repos_ai_readiness.py
scripts/make_handover_archive.sh — build a colleague-ready tar.gz

tests/                       — pytest suites, ID-aligned with docs/SPEC.md

docs/HANDOVER.md             — operations reference (START HERE)
docs/SPEC.md                 — living spec (F-01 … F-27)
docs/archive/                — archived legacy multi-page feature specs
docs/REPORT_I.md             — leadership report: AI usage / adoption / economics
docs/REPORT_II.md            — leadership report: repo AI-codegen readiness
docs/VERIFY.md               — pre-demo verification runbook
docs/DEPLOY.md               — VM deployment steps
docs/SOURCES_SCHEMA.md       — JSON drop schema reference
CEO_BRIEF.html               — mobile-friendly leadership snapshot

sources/                     — JSON / CSV drops (replace weekly)
data/hmnd.db                 — SQLite database
snapshots/                   — daily auto-snapshots of report_i_data output
```

---

## Tests

```bash
docker compose exec -T dashboard python -m pytest
```

## Pre-demo verification

```bash
docker compose exec -T dashboard python -m scripts.audit_etl | tail -25
```

See [`docs/VERIFY.md`](docs/VERIFY.md) for the full 5-step pre-demo checklist.
