-- HMND AI Governance Dashboard schema (SQLite-flavour, Postgres-compatible).
-- Соответствует разделу "Архитектура данных" в SPEC.md.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    monthly_budget_usd REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    full_name   TEXT NOT NULL,
    team_id     INTEGER REFERENCES teams(id),
    role        TEXT,
    monthly_limit_usd REAL DEFAULT 200,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS providers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE  -- 'openai' | 'anthropic'
);

CREATE TABLE IF NOT EXISTS models (
    id          INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    name        TEXT NOT NULL,
    family      TEXT,                  -- gpt-5, claude-4, ...
    UNIQUE(provider_id, name)
);

CREATE TABLE IF NOT EXISTS model_prices (
    id          INTEGER PRIMARY KEY,
    model_id    INTEGER NOT NULL REFERENCES models(id),
    valid_from  TEXT NOT NULL,         -- ISO date
    input_per_1k  REAL NOT NULL,
    output_per_1k REAL NOT NULL,
    cache_read_per_1k REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS seats (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    seat_type   TEXT NOT NULL,         -- 'Claude Team', 'ChatGPT Business' ...
    assigned    INTEGER NOT NULL DEFAULT 1,
    monthly_cost_usd REAL NOT NULL DEFAULT 25,
    assigned_at TEXT,
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    id              INTEGER PRIMARY KEY,
    provider_id     INTEGER NOT NULL REFERENCES providers(id),
    external_id     TEXT NOT NULL,         -- openai 'key_xxx' / anthropic 'apikey_xxx'
    name            TEXT,
    redacted_value  TEXT,                  -- 'sk-...****1234'
    owner_user_id   INTEGER REFERENCES users(id),
    is_admin        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT,
    last_used_at    TEXT,
    UNIQUE(provider_id, external_id)
);

CREATE TABLE IF NOT EXISTS usage_events (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    model_id    INTEGER NOT NULL REFERENCES models(id),
    api_key_id  INTEGER REFERENCES api_keys(id),
    occurred_at TEXT NOT NULL,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    tokens_cached INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL NOT NULL DEFAULT 0,
    latency_ms  INTEGER,
    is_error    INTEGER NOT NULL DEFAULT 0,
    purpose     TEXT                   -- IDE / API / chat / agent ...
);

CREATE INDEX IF NOT EXISTS ix_usage_events_user_time ON usage_events(user_id, occurred_at);
CREATE INDEX IF NOT EXISTS ix_usage_events_provider_time ON usage_events(provider_id, occurred_at);
CREATE INDEX IF NOT EXISTS ix_usage_events_model_time ON usage_events(model_id, occurred_at);

CREATE TABLE IF NOT EXISTS daily_costs (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    day         TEXT NOT NULL,         -- ISO date
    cost_usd    REAL NOT NULL DEFAULT 0,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    requests    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, provider_id, day)
);

CREATE TABLE IF NOT EXISTS repositories (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    full_name   TEXT,                  -- org/name
    is_critical INTEGER NOT NULL DEFAULT 0,
    default_branch TEXT DEFAULT 'main'
);

CREATE TABLE IF NOT EXISTS commits (
    id          INTEGER PRIMARY KEY,
    repo_id     INTEGER NOT NULL REFERENCES repositories(id),
    sha         TEXT NOT NULL,
    author_id   INTEGER REFERENCES users(id),
    authored_at TEXT NOT NULL,
    message     TEXT,
    additions   INTEGER NOT NULL DEFAULT 0,
    deletions   INTEGER NOT NULL DEFAULT 0,
    UNIQUE(repo_id, sha)
);

CREATE TABLE IF NOT EXISTS pull_requests (
    id          INTEGER PRIMARY KEY,
    repo_id     INTEGER NOT NULL REFERENCES repositories(id),
    number      INTEGER NOT NULL,
    title       TEXT,
    author_id   INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL,
    merged_at   TEXT,
    state       TEXT NOT NULL,         -- open|merged|closed
    additions   INTEGER NOT NULL DEFAULT 0,
    deletions   INTEGER NOT NULL DEFAULT 0,
    review_comments INTEGER NOT NULL DEFAULT 0,
    critical_files_changed INTEGER NOT NULL DEFAULT 0,
    bug_count   INTEGER NOT NULL DEFAULT 0,
    rolled_back INTEGER NOT NULL DEFAULT 0,
    has_human_review INTEGER NOT NULL DEFAULT 1,
    UNIQUE(repo_id, number)
);

CREATE TABLE IF NOT EXISTS ai_code_attribution (
    id          INTEGER PRIMARY KEY,
    repo_id     INTEGER NOT NULL REFERENCES repositories(id),
    pr_id       INTEGER REFERENCES pull_requests(id),
    commit_id   INTEGER REFERENCES commits(id),
    user_id     INTEGER REFERENCES users(id),
    ai_lines    INTEGER NOT NULL DEFAULT 0,
    total_lines INTEGER NOT NULL DEFAULT 0,
    source      TEXT NOT NULL,         -- commit_message_marker | pr_template_flag | agent_metadata | heuristic_block_size
    confidence  REAL NOT NULL DEFAULT 1.0,
    detected_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    type        TEXT NOT NULL,         -- spend_spike | budget_exceed | inactive_seat | ai_code_high | pr_no_review | provider_spike
    severity    TEXT NOT NULL,         -- critical | high | medium | low
    subject_kind TEXT,                 -- user | team | repo | seat | pr
    subject_id  INTEGER,
    message     TEXT NOT NULL,
    dedup_key   TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'new',  -- new | ack | resolved
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS ix_alerts_severity ON alerts(severity);

-- Authoritative spend reported by the provider's own billing endpoint
-- (OpenAI /v1/organization/costs, Anthropic /v1/organizations/cost_report).
-- Used on Overview alongside our computed total so any gap from
-- batch/enterprise/cached pricing differences is transparent.
CREATE TABLE IF NOT EXISTS provider_totals (
    id          INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    day         TEXT NOT NULL,
    cost_usd    REAL NOT NULL DEFAULT 0,
    UNIQUE(provider_id, day)
);
CREATE INDEX IF NOT EXISTS ix_provider_totals_day ON provider_totals(day);
