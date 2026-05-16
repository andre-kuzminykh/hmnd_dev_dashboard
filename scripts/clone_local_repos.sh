#!/usr/bin/env bash
# Clone (or update) all repos listed in sources/git_repos.txt to a local
# directory — for offline audit / Report II inventory work on the MacBook.
#
# 1-to-1 with what the dashboard tracks (sources/git_repos.txt is the
# single source of truth on both sides).
#
# Usage:
#   bash scripts/clone_local_repos.sh                  # → ~/Desktop/hmnd_repos/
#   bash scripts/clone_local_repos.sh /custom/path     # → /custom/path/
#
# Notes:
#   - LFS files are SKIPPED (GIT_LFS_SKIP_SMUDGE=1). Saves ~70% disk space
#     and avoids needing git-lfs installed. Source code + structure are
#     fully present; only large binary assets (USD models, posegraph maps,
#     ML checkpoints) become 1-line pointer files.
#   - Submodules are NOT initialized by default (keeps total size small).
#     To init submodules in a specific repo afterwards:
#         cd <repo> && GIT_LFS_SKIP_SMUDGE=1 git submodule update --init --recursive
#   - Existing clones are FETCHED (not re-cloned). Safe to re-run any time.
#   - LFS filter is disabled inline (`-c filter.lfs.*`) so checkout completes
#     even when git-lfs isn't installed.
set -euo pipefail

TARGET="${1:-$HOME/Desktop/hmnd_repos}"
LIST_FILE="$(dirname "$0")/../sources/git_repos.txt"

if [[ ! -f "$LIST_FILE" ]]; then
  echo "ERROR: $LIST_FILE not found. Run from inside hmnd_dev_dashboard checkout." >&2
  exit 1
fi

mkdir -p "$TARGET"
cd "$TARGET"

# Parse repo list (skip comments + blanks).
REPOS=()
while IFS= read -r raw; do
  line="${raw%%#*}"
  line="${line//[[:space:]]/}"
  [[ -n "$line" ]] && REPOS+=("$line")
done < "$LIST_FILE"

echo "═══ Cloning ${#REPOS[@]} repos to $TARGET ═══"
echo

# No-LFS git config flags applied inline — works without git-lfs installed.
GIT_NO_LFS=(
  -c filter.lfs.smudge=
  -c filter.lfs.process=
  -c filter.lfs.required=false
)

OK=0
FAIL=0
SKIPPED=()
for full in "${REPOS[@]}"; do
  name="${full##*/}"
  echo "─── $full ───"
  if [[ -d "$name/.git" ]]; then
    echo "  (exists — fetching updates)"
    if GIT_LFS_SKIP_SMUDGE=1 git "${GIT_NO_LFS[@]}" -C "$name" fetch --all --prune --quiet 2>&1 | head -3; then
      OK=$((OK+1))
    else
      FAIL=$((FAIL+1))
      SKIPPED+=("$full (fetch failed)")
    fi
  else
    echo "  (cloning shallow with --depth=50 and LFS skip)"
    if GIT_LFS_SKIP_SMUDGE=1 git "${GIT_NO_LFS[@]}" clone --depth=50 \
         "https://github.com/${full}.git" "$name" 2>&1 | tail -5; then
      OK=$((OK+1))
    else
      FAIL=$((FAIL+1))
      SKIPPED+=("$full (clone failed)")
      rm -rf "$name" 2>/dev/null || true
    fi
  fi
  echo
done

echo "═══ Summary ═══"
echo "  ✓ Successful: $OK"
echo "  ✗ Failed:     $FAIL"
if [[ $FAIL -gt 0 ]]; then
  for f in "${SKIPPED[@]}"; do
    echo "      - $f"
  done
fi
echo
echo "Disk usage:"
du -sh "$TARGET" 2>/dev/null
echo
echo "Per-repo sizes:"
du -sh "$TARGET"/*/ 2>/dev/null | sort -hr | head -20
echo
echo "Next steps:"
echo "  - Audit structure across all of them:"
echo "      bash scripts/audit_repos_local.sh $TARGET/*"
echo "  - Or audit just the core 3 (matches Report II §3-5):"
echo "      bash scripts/audit_repos_local.sh $TARGET/hmnd $TARGET/hmnd-cloud $TARGET/hmnd-sim"
