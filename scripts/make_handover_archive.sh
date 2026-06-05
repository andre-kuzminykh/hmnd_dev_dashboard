#!/usr/bin/env bash
# Build a handover archive for a colleague.
#
# Includes: all code, docs, scripts, tests, AND the live data
#   (data/hmnd.db + sources/*.json/csv + snapshots/) so they can
#   `docker compose up -d --build` and immediately see the dashboard
#   with real numbers.
#
# EXCLUDES (on purpose):
#   .env            — your real OpenAI admin key + GitHub PAT. NEVER ship.
#                     Colleague creates their own from .env.example.
#   .git/           — full history; bulky. (Pass --with-git to include.)
#   __pycache__, *.pyc, .pytest_cache, .venv — build/cache junk.
#   ~/hmnd_backups  — lives outside repo, not touched anyway.
#
# Usage:
#   bash scripts/make_handover_archive.sh              # code + data, no .env
#   bash scripts/make_handover_archive.sh --no-data    # code only (smaller)
#   bash scripts/make_handover_archive.sh --with-git   # include .git history
#
set -euo pipefail

cd "$(dirname "$0")/.."          # repo root
REPO_NAME="$(basename "$(pwd)")"
TS="$(date -u +%Y%m%d)"
OUT="../hmnd_dashboard_handover_${TS}.tar.gz"

INCLUDE_DATA=1
INCLUDE_GIT=0
for arg in "$@"; do
  case "$arg" in
    --no-data)  INCLUDE_DATA=0 ;;
    --with-git) INCLUDE_GIT=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 1 ;;
  esac
done

# Safety: refuse to run if .env is somehow not gitignored (paranoia).
if git check-ignore -q .env 2>/dev/null; then :; else
  echo "WARNING: .env is not gitignored. Aborting to avoid leaking secrets." >&2
  echo "Add '.env' to .gitignore first." >&2
  exit 1
fi

EXCLUDES=(
  --exclude='./.env'
  --exclude='./.env.*'           # .env.local etc (keep .env.example — see below)
  --exclude='*/__pycache__'
  --exclude='*.pyc'
  --exclude='./.pytest_cache'
  --exclude='*/.pytest_cache'
  --exclude='./.venv'
  --exclude='*/node_modules'
  --exclude='*.tar.gz'
)
# Keep .env.example explicitly (it's safe — no secrets).
# tar's --exclude='./.env.*' would catch it, so re-add via a wildcard tweak:
#   we exclude .env.local/.env.prod but NOT .env.example — handle by not
#   matching: change pattern to .env.local-style only.
EXCLUDES=(
  --exclude='./.env'
  --exclude='./.env.local'
  --exclude='./.env.prod'
  --exclude='./.env.production'
  --exclude='*/__pycache__'
  --exclude='*.pyc'
  --exclude='./.pytest_cache'
  --exclude='*/.pytest_cache'
  --exclude='./.venv'
  --exclude='*/node_modules'
  --exclude='*.tar.gz'
)

if [ "$INCLUDE_GIT" -eq 0 ]; then
  EXCLUDES+=( --exclude='./.git' )
fi
if [ "$INCLUDE_DATA" -eq 0 ]; then
  EXCLUDES+=( --exclude='./data/hmnd.db' --exclude='./sources' --exclude='./snapshots' )
fi

echo "Building archive: $OUT"
echo "  include data:    $([ "$INCLUDE_DATA" -eq 1 ] && echo yes || echo no)"
echo "  include .git:    $([ "$INCLUDE_GIT" -eq 1 ] && echo yes || echo no)"
echo "  EXCLUDES .env:    yes (always — contains your API keys)"
echo

tar czf "$OUT" "${EXCLUDES[@]}" -C .. "$REPO_NAME"

echo
echo "✓ Created: $(cd .. && pwd)/$(basename "$OUT")"
echo "  Size:    $(du -h "$OUT" | cut -f1)"
echo
echo "Sanity-check that .env did NOT make it in:"
if tar tzf "$OUT" | grep -E '/\.env$' ; then
  echo "  ✗ DANGER: .env is in the archive! Delete it and investigate." >&2
  exit 1
else
  echo "  ✓ no .env in archive — safe to send"
fi
echo
echo "Tell your colleague:"
echo "  1. tar xzf $(basename "$OUT")"
echo "  2. cd $REPO_NAME && cp .env.example .env && edit .env (see docs/HANDOVER.md § '.env variables')"
echo "  3. docker compose up -d --build"
echo "  4. docker compose exec -T dashboard python -m scripts.audit_etl | tail -25   # expect 17 ✓"
echo "  5. read docs/HANDOVER.md"
