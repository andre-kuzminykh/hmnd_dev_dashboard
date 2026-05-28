# JSON sources schema

Drop files into `sources/` at the repo root (or set `HMND_SOURCES_DIR`).
Filename encodes the date: `<Provider>_YYYYMMDD.json`. When multiple files
exist for the same provider they are **all loaded, oldest-first**; each is
idempotent over its own `_meta` period, so weekly drops accumulate and a
newer file wins on any days it re-covers (see Discovery rules below).

## Anthropic_YYYYMMDD.json

Filename matches `Anthropic*_YYYYMMDD.json` — typo `Anthropics_*` also OK.

```json
{
  "period_start": "2026-04-01",
  "period_end":   "2026-04-27",
  "summary": {
    "total_users":          106,
    "chat_users":            92,
    "claude_code_users":     51,
    "chat_requests":      6546,
    "claude_code_requests": 183179,
    "total_spend_usd":   22318
  },
  "products": {
    "chat":         { "spend_usd": 2111,  "requests": 6546,   "users": 92 },
    "claude_code":  { "spend_usd": 19019, "requests": 183179, "users": 51 },
    "cowork_other": { "spend_usd": 1188,  "requests": 18387,  "users": 44 }
  },
  "models": [
    { "name": "claude-opus-4-6",   "spend_usd": 10115, "share_pct": 45.3, "trend": "stable"   },
    { "name": "claude-opus-4-7",   "spend_usd": 6464,  "share_pct": 29.0, "trend": "growing"  },
    { "name": "claude-sonnet-4-6", "spend_usd": 5409,  "share_pct": 24.2, "trend": "stable"   },
    { "name": "claude-haiku-4-5",  "spend_usd": 309,   "share_pct": 1.5,  "trend": "declining"}
  ],
  "users": [
    {
      "email":           "berh@hmnd.ai",
      "name":            "berh",
      "chat_requests":   589,
      "chat_spend_usd":  473.7,
      "cc_requests":     0,
      "cc_spend_usd":    0,
      "primary_model":   "claude-opus-4-7"
    },
    {
      "email":           "anai@hmnd.ai",
      "name":            "anai",
      "chat_requests":   0,
      "chat_spend_usd":  0,
      "cc_requests":     18935,
      "cc_spend_usd":    3911,
      "primary_model":   "claude-opus-4-7-thinking-xhigh"
    }
  ]
}
```

Required: `period_start`, `period_end`, `users[]`.
Optional but recommended: `products{}`, `models[]`, `summary{}`.

## Cursor_YYYYMMDD.json

```json
{
  "period_start": "2026-04-30",
  "period_end":   "2026-05-06",
  "summary": {
    "active_devs":          58,
    "total_completions":  23992,
    "total_ai_lines":   6050048
  },
  "models": [
    { "name": "claude-4.6-opus-high-thinking", "requests": 7458, "users": 11 },
    { "name": "claude-opus-4-7-thinking-high", "requests": 2867, "users":  5 },
    { "name": "gpt-5.3-codex",                 "requests": 2650, "users":  4 }
  ],
  "users": [
    {
      "email":             "olsi@thehumanoid.ai",
      "name":              "Oleg Sinavski",
      "agent_completions": 661,
      "agent_lines":       61067,
      "tab_completions":   0,
      "tab_lines":         0,
      "ai_lines":          61067,
      "favorite_model":    "claude-opus-4-7-thinking-xhigh"
    }
  ]
}
```

Required: `period_start`, `period_end`, `users[]`.
Required per user: `email`, `name`, `ai_lines`.

## OpenAI_YYYYMMDD.json (fallback only)

Used **only** if you can't or don't want to put an admin key in the
container. Same shape conventions: users with messages and spend.

```json
{
  "period_start": "2026-04-01",
  "period_end":   "2026-04-27",
  "summary":      { "total_users": 114, "total_messages": 14156, "total_spend_usd": 80993 },
  "models": [
    { "name": "gpt-5.3", "messages": 11453, "share_pct": 81 }
  ],
  "users": [
    { "email": "u@h.ai", "name": "User Name", "messages": 1847, "spend_usd": 1290, "primary_model": "gpt-5.3" }
  ]
}
```

## Discovery rules

1. Files matched by glob `*_YYYYMMDD.json` inside `HMND_SOURCES_DIR` (default `sources/` at repo root and inside the container `/app/sources`).
2. For each provider **all matching files are loaded, oldest-first** (by `YYYYMMDD` in the filename). Combined with rule 3 this means:
   - **Cumulative pulls** (every file starts at the same `_meta.rangeStart`): the newest file supersedes the older ones — drop the new file and you're done.
   - **Incremental / week-only pulls** (each file covers just its own new week): non-overlapping weeks accumulate, so old weeks are preserved and the new week is added. Keep the older files in place.
   - If two files cover the **same** days, the one with the later filename date (loaded last) wins for those days. To avoid wiping a boundary day with an incremental drop, make its `_meta.rangeStart` the day **after** the previous file's `rangeEnd`.
3. JSON loader is **idempotent** — re-loading the same file does not duplicate rows. The loader drops the period it covers (`_meta.rangeStart..rangeEnd`, scoped to the provider — and to the org for OpenAI) and re-inserts.
4. Sync flow: JSON > Cursor-derived > Real API > Mock. First non-empty wins.
