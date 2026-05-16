#!/usr/bin/env bash
# Safe re-deploy after `git pull` — guarantees that source changes land
# inside the Docker image and that the identity / data integrity audits
# stay green.
#
# Why this script exists:
# Without this, `git pull` updates files on the host but the sync
# sidecar keeps running the OLD image (it's reused across restarts).
# A single missed `--build` re-introduced 20 dual-domain identities on
# 2026-05-16 by running stale loader code for 15 minutes. This script
# makes that mistake impossible.
#
# Usage:
#   bash scripts/redeploy.sh                # normal redeploy
#   bash scripts/redeploy.sh --skip-pull    # rebuild without pulling
#   bash scripts/redeploy.sh --tests-only   # run audits, don't restart
#
# Exit codes:
#   0 — deployed cleanly, all audits green
#   1 — a step failed (build, tests, or audit) — sync NOT restarted
set -euo pipefail

cd "$(dirname "$0")/.."

SKIP_PULL=0
TESTS_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --skip-pull)  SKIP_PULL=1 ;;
    --tests-only) TESTS_ONLY=1 ;;
    *) echo "Unknown arg: $arg"; exit 2 ;;
  esac
done

echo "═══ HMND redeploy ═══"
date -u +"started: %Y-%m-%dT%H:%M:%SZ"

# 1. Stop the sync sidecar so it can't run stale code while we rebuild.
echo
echo "─── 1/6  Stopping sync sidecar ───"
docker compose stop sync 2>/dev/null || echo "(sync was not running — fine)"

# 2. Optional: pull latest source.
if [[ $SKIP_PULL -eq 0 ]]; then
  echo
  echo "─── 2/6  Pulling latest source ───"
  git pull --ff-only
else
  echo
  echo "─── 2/6  Skipping git pull (--skip-pull) ───"
fi

# 3. Rebuild the dashboard image so source changes land inside.
#    Same image is reused by sync + snapshotter sidecars.
echo
echo "─── 3/6  Rebuilding dashboard image ───"
docker compose up -d --build dashboard

# Wait for dashboard healthcheck so `exec` calls below don't race.
echo "   (waiting for dashboard health…)"
for i in {1..30}; do
  if docker compose ps dashboard | grep -q "(healthy)"; then
    echo "   dashboard healthy after ${i}s"
    break
  fi
  sleep 1
done

# 4. Smoke-test the identity loader fix is in the image.
echo
echo "─── 4/6  Running identity-resolution tests ───"
docker compose exec -T dashboard python -m pytest -q tests/test_identity_resolution.py

# 5. Data audits — both must be clean before we re-start sync.
echo
echo "─── 5/6  Data audits ───"
echo
echo "   • Identity collisions:"
COLLISION_OUT=$(docker compose exec -T dashboard python -m scripts.audit_identity_collisions)
echo "$COLLISION_OUT"
if ! echo "$COLLISION_OUT" | grep -q "No dual-domain identity collisions"; then
  echo
  echo "✗ Identity collisions detected — NOT restarting sync."
  echo "  Run merge first:"
  echo "    docker compose exec -T dashboard python -m scripts.merge_dual_domain_identities"
  echo "  Then re-run this script."
  exit 1
fi

echo
echo "   • Full ETL audit (17 checks, ~30s):"
docker compose exec -T dashboard python -m scripts.audit_etl | tail -25

# 6. Restart sync — image is current, regressions cannot occur.
if [[ $TESTS_ONLY -eq 1 ]]; then
  echo
  echo "─── 6/6  Skipping sync restart (--tests-only) ───"
else
  echo
  echo "─── 6/6  Starting sync sidecar ───"
  docker compose start sync
fi

echo
echo "✓ deploy complete"
date -u +"finished: %Y-%m-%dT%H:%M:%SZ"
