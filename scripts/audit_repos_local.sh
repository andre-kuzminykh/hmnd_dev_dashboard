#!/usr/bin/env bash
# Inventory script for Report II — Technical Repository Audit & AI-Codegen Readiness.
#
# Run on a host where hmnd, hmnd-cloud, hmnd-sim are already cloned. The script
# walks each repo, captures the structural and contributor signals we need to
# answer "are these repos ready to safely absorb AI-generated changes?", and
# writes a single markdown file you paste back into the chat.
#
# Usage:
#   bash scripts/audit_repos_local.sh /path/to/hmnd /path/to/hmnd-cloud /path/to/hmnd-sim
#   bash scripts/audit_repos_local.sh                           # auto-search common locations
#
# Output:
#   /tmp/hmnd_repos_audit_<date>.md   — single self-contained markdown digest
#   (typically 20-60 KB — small enough to paste)
#
# Privacy / safety:
#   - Read-only. Does not modify any repo.
#   - Captures file paths, counts, README excerpts, git contributor metadata.
#   - Does NOT capture source code contents (only structural signals).
#   - Does NOT capture .env / secrets / credentials / private file contents.
set -euo pipefail

OUT="/tmp/hmnd_repos_audit_$(date -u +%Y-%m-%d).md"
> "$OUT"

# ---------------------------------------------------------------------------
# Locate repos
# ---------------------------------------------------------------------------
REPOS=()
if [[ $# -gt 0 ]]; then
  REPOS=("$@")
else
  # Common locations to probe
  for base in "$HOME" "$HOME/repos" "$HOME/code" "$HOME/work" "$HOME/HumanoidTeam" \
              "$HOME/src" "$HOME/dev" "/opt" "/srv" "/workspace"; do
    for name in hmnd hmnd-cloud hmnd-sim; do
      if [[ -d "$base/$name/.git" ]]; then
        REPOS+=("$base/$name")
      fi
    done
  done
fi

if [[ ${#REPOS[@]} -eq 0 ]]; then
  echo "ERROR: no repos found. Pass paths explicitly:"
  echo "  bash scripts/audit_repos_local.sh /path/to/hmnd /path/to/hmnd-cloud /path/to/hmnd-sim"
  exit 1
fi

# Make unique
REPOS=($(printf "%s\n" "${REPOS[@]}" | awk '!seen[$0]++'))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
section() { printf "\n\n## %s\n\n" "$1" >> "$OUT"; }
sub()     { printf "\n### %s\n\n" "$1" >> "$OUT"; }
code()    { printf "\n\`\`\`%s\n" "${1:-}" >> "$OUT"; }
end_code(){ printf "\`\`\`\n" >> "$OUT"; }
hr()      { printf "\n---\n" >> "$OUT"; }

count_files() {
  local repo="$1" pattern="$2"
  find "$repo" -type f -name "$pattern" -not -path '*/\.git/*' 2>/dev/null | wc -l
}

count_files_in() {
  local repo="$1" subdir="$2" pattern="$3"
  [[ -d "$repo/$subdir" ]] || { echo 0; return; }
  find "$repo/$subdir" -type f -name "$pattern" -not -path '*/\.git/*' 2>/dev/null | wc -l
}

exists() {
  local repo="$1" path="$2"
  if [[ -e "$repo/$path" ]]; then echo "✅"; else echo "❌"; fi
}

first_lines() {
  local file="$1" n="${2:-30}"
  [[ -f "$file" ]] || return
  head -n "$n" "$file" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
{
  echo "# HMND repos audit (local inventory for Report II)"
  echo ""
  echo "**Generated:** $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  echo "**Host:** $(hostname)"
  echo "**Script:** scripts/audit_repos_local.sh"
  echo "**Repos found:** ${#REPOS[@]}"
  for r in "${REPOS[@]}"; do
    echo "  - $r"
  done
} >> "$OUT"

# ---------------------------------------------------------------------------
# Per-repo deep dive
# ---------------------------------------------------------------------------
for repo in "${REPOS[@]}"; do
  name=$(basename "$repo")
  hr
  section "Repo: \`$name\`"
  printf "**Path:** \`%s\`\n" "$repo" >> "$OUT"

  # --- Git basics ---
  sub "Git basics"
  pushd "$repo" >/dev/null
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
  default_branch=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo "?")
  total_commits=$(git rev-list --count HEAD 2>/dev/null || echo 0)
  first_commit=$(git log --reverse --format='%aI' HEAD 2>/dev/null | head -1 || echo "?")
  last_commit=$(git log -1 --format='%aI' HEAD 2>/dev/null || echo "?")
  contributors_total=$(git shortlog -s -n HEAD 2>/dev/null | wc -l)
  {
    echo "| | |"
    echo "|---|---|"
    echo "| Current branch | \`$branch\` |"
    echo "| Default branch | \`$default_branch\` |"
    echo "| Total commits | $total_commits |"
    echo "| First commit | $first_commit |"
    echo "| Last commit | $last_commit |"
    echo "| Total contributors | $contributors_total |"
  } >> "$OUT"

  # --- Top-level structure ---
  sub "Top-level structure (depth 2)"
  code text
  ls -la "$repo" | grep -v '^total' >> "$OUT" 2>/dev/null || true
  end_code

  # --- Subdir tree depth 2 (sizes) ---
  sub "Directories at depth 1-2 (sizes)"
  code text
  if command -v du >/dev/null 2>&1; then
    du -sh "$repo"/*/ 2>/dev/null | sort -hr | head -30 >> "$OUT" || true
  fi
  end_code

  # --- File-count by extension ---
  sub "File counts by language/extension (top 15)"
  code text
  find "$repo" -type f -not -path '*/\.git/*' 2>/dev/null | \
    sed -n 's/.*\.\([a-zA-Z0-9]*\)$/\1/p' | sort | uniq -c | sort -rn | head -15 >> "$OUT"
  end_code

  # --- Total LoC by extension (rough) ---
  sub "Lines of code (top languages, excluding .git)"
  code text
  for ext in py cpp c h hpp cu cuh ts tsx js jsx rs go java kt swift rb sh yaml yml md proto sql; do
    total=$(find "$repo" -type f -name "*.$ext" -not -path '*/\.git/*' -not -path '*/node_modules/*' -not -path '*/build/*' -not -path '*/dist/*' -exec cat {} + 2>/dev/null | wc -l)
    if [[ $total -gt 0 ]]; then
      printf "  %-6s  %10d\n" "$ext" "$total" >> "$OUT"
    fi
  done
  end_code

  # --- AI agent / instruction files ---
  sub "AI-codegen instruction files (presence)"
  {
    echo "| File | Exists |"
    echo "|------|:------:|"
    for f in "AGENTS.md" "CLAUDE.md" "AGENT.md" "COPILOT.md" "AI.md" "agents.md" "claude.md" \
             ".cursor/rules" ".cursorrules" ".github/copilot-instructions.md" \
             ".github/CODEOWNERS" "CODEOWNERS" "CONTRIBUTING.md" "ARCHITECTURE.md" \
             "docs/ai/" "docs/agents/" "docs/AGENTS.md"; do
      echo "| \`$f\` | $(exists "$repo" "$f") |"
    done
  } >> "$OUT"

  # --- Build / config / entry files ---
  sub "Build / config / entry files (presence)"
  {
    echo "| File | Exists |"
    echo "|------|:------:|"
    for f in "README.md" "README.rst" "README.txt" \
             "pyproject.toml" "setup.py" "setup.cfg" "requirements.txt" "Pipfile" "poetry.lock" \
             "package.json" "yarn.lock" "pnpm-lock.yaml" \
             "Cargo.toml" "go.mod" "build.gradle" "pom.xml" \
             "CMakeLists.txt" "Makefile" "Bazel.WORKSPACE" "BUILD.bazel" \
             "Dockerfile" "docker-compose.yml" ".devcontainer/devcontainer.json" \
             ".env.example" ".python-version" ".nvmrc" ".tool-versions" \
             "tox.ini" "pytest.ini" "ruff.toml" "mypy.ini" ".pre-commit-config.yaml" \
             "package.xml" "colcon.meta" "CMakeLists.txt" "rosdep.yaml"; do
      echo "| \`$f\` | $(exists "$repo" "$f") |"
    done
  } >> "$OUT"

  # --- CI/CD ---
  sub "CI/CD"
  {
    echo "| Workflow dir | Exists |"
    echo "|------|:------:|"
    for f in ".github/workflows/" ".gitlab-ci.yml" ".circleci/" ".buildkite/" "Jenkinsfile" \
             ".pre-commit-config.yaml"; do
      echo "| \`$f\` | $(exists "$repo" "$f") |"
    done
  } >> "$OUT"
  if [[ -d "$repo/.github/workflows" ]]; then
    echo "" >> "$OUT"
    echo "**Workflows found:**" >> "$OUT"
    code text
    ls -1 "$repo/.github/workflows/" 2>/dev/null >> "$OUT" || true
    end_code
  fi

  # --- Tests ---
  sub "Tests"
  {
    echo "| Path / pattern | Count |"
    echo "|------|------:|"
    echo "| Directories named tests/ or test/ | $(find "$repo" -type d \( -name tests -o -name test -o -name __tests__ -o -name spec -o -name specs \) -not -path '*/\.git/*' 2>/dev/null | wc -l) |"
    echo "| Files matching test_*.py | $(count_files "$repo" "test_*.py") |"
    echo "| Files matching *_test.py | $(count_files "$repo" "*_test.py") |"
    echo "| Files matching *_test.go | $(count_files "$repo" "*_test.go") |"
    echo "| Files matching *.test.ts | $(count_files "$repo" "*.test.ts") |"
    echo "| Files matching *.test.tsx | $(count_files "$repo" "*.test.tsx") |"
    echo "| Files matching *.spec.ts | $(count_files "$repo" "*.spec.ts") |"
    echo "| Files matching *_test.cpp | $(count_files "$repo" "*_test.cpp") |"
    echo "| Files matching test_*.cpp | $(count_files "$repo" "test_*.cpp") |"
    echo "| Files matching *.test.cpp | $(count_files "$repo" "*.test.cpp") |"
    echo "| conftest.py files | $(count_files "$repo" "conftest.py") |"
  } >> "$OUT"

  # --- Docs ---
  sub "Documentation"
  {
    echo "| Path | Exists | Markdown file count |"
    echo "|------|:------:|------:|"
    for d in "docs" "doc" "Documentation" "architecture" "ARCHITECTURE" \
             "design" "specs" "spec" "ADR" "adr" "RFC" "rfc" "rfcs" "decisions"; do
      e=$(exists "$repo" "$d")
      n=$(count_files_in "$repo" "$d" "*.md")
      echo "| \`$d/\` | $e | $n |"
    done
    echo "| Root README* files | $(find "$repo" -maxdepth 1 -name 'README*' 2>/dev/null | wc -l) | - |"
    echo "| Root *.md files | $(find "$repo" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l) | - |"
    echo "| All .md files in repo | - | $(count_files "$repo" "*.md") |"
  } >> "$OUT"

  # --- Per-module README presence (depth-1 dirs that have README inside) ---
  sub "Module-level READMEs (depth-1 dirs with README*)"
  code text
  for d in "$repo"/*/; do
    [[ -d "$d" ]] || continue
    dn=$(basename "$d")
    if ls "$d"README* >/dev/null 2>&1; then
      echo "  ✅ $dn"
    fi
  done >> "$OUT" 2>/dev/null
  end_code

  # --- README excerpt ---
  if [[ -f "$repo/README.md" ]]; then
    sub "README.md — first 60 lines"
    code markdown
    first_lines "$repo/README.md" 60 >> "$OUT"
    end_code
  fi

  # --- Architecture / agents excerpts if present ---
  for f in AGENTS.md CLAUDE.md ARCHITECTURE.md CONTRIBUTING.md docs/architecture.md docs/AGENTS.md .cursor/rules .cursorrules .github/copilot-instructions.md; do
    if [[ -f "$repo/$f" ]]; then
      sub "\`$f\` — first 60 lines"
      code text
      first_lines "$repo/$f" 60 >> "$OUT"
      end_code
    fi
  done

  # --- Contributors (lifetime + last 90 days) ---
  sub "Top contributors — lifetime (commits)"
  code text
  git shortlog -s -n HEAD 2>/dev/null | head -15 >> "$OUT" || true
  end_code

  sub "Top contributors — last 90 days (commits)"
  code text
  since_date=$(date -u -d '90 days ago' +%F 2>/dev/null || date -u -v-90d +%F 2>/dev/null)
  if [[ -n "$since_date" ]]; then
    git shortlog -s -n --since="$since_date" HEAD 2>/dev/null | head -15 >> "$OUT" || true
  fi
  end_code

  sub "Author additions/deletions — last 90 days (top 10)"
  code text
  if [[ -n "$since_date" ]]; then
    git log --since="$since_date" --pretty=format:'%aN' --numstat 2>/dev/null | \
      awk 'NF==1 { author=$0; next }
           NF==3 { adds[author]+=$1; dels[author]+=$2; commits[author]++; }
           END {
             for (a in commits) printf "%-30s commits=%5d  +%-9d -%d\n", a, commits[a], adds[a], dels[a]
           }' | sort -k3 -rn -t= | head -10 >> "$OUT" || true
  fi
  end_code

  # --- Per-directory commit counts (last 90 days) ---
  sub "Directories most touched — last 90 days (top 10)"
  code text
  if [[ -n "$since_date" ]]; then
    git log --since="$since_date" --name-only --pretty=format: HEAD 2>/dev/null | \
      grep -v '^$' | \
      awk -F/ '{ if (NF>=2) print $1; else print "(root)" }' | \
      sort | uniq -c | sort -rn | head -10 >> "$OUT" || true
  fi
  end_code

  # --- Commit-size distribution (last 90 days) ---
  sub "Commit-size distribution — last 90 days"
  code text
  if [[ -n "$since_date" ]]; then
    git log --since="$since_date" --pretty=format: --shortstat HEAD 2>/dev/null | \
      awk '/files? changed/ {
        adds += $4 + $6; dels += $6 + $8;
        f = $1;
        if (f <= 1) b["1 file"]++; else if (f <= 5) b["2-5 files"]++; else if (f <= 20) b["6-20 files"]++; else b["21+ files"]++;
        n++
      }
      END {
        printf "  total commits with changes: %d\n", n;
        for (k in b) printf "  %-12s %5d  (%.0f%%)\n", k, b[k], b[k]*100/n
      }' >> "$OUT" || true
  fi
  end_code

  # --- Largest files (excl. .git) ---
  sub "Largest tracked files (top 15)"
  code text
  git ls-tree -r -l HEAD 2>/dev/null | \
    sort -k4 -rn | head -15 | \
    awk '{ printf "  %12s  %s\n", $4, $5 }' >> "$OUT" || true
  end_code

  # --- Vendored / generated dir indicators ---
  sub "Vendored / generated content indicators"
  {
    echo "| Indicator | Found |"
    echo "|------|:------:|"
    for d in "vendor" "third_party" "thirdparty" "external" "deps" "node_modules" \
             "generated" "gen" "_generated" "auto-generated" "build" "dist" \
             "submodules" "subprojects" ".cache" "__pycache__"; do
      n=$(find "$repo" -type d -name "$d" -not -path '*/\.git/*' 2>/dev/null | wc -l)
      [[ $n -gt 0 ]] && echo "| \`$d/\` | $n dir(s) |"
    done
  } >> "$OUT"

  # --- Submodules ---
  if [[ -f "$repo/.gitmodules" ]]; then
    sub "Git submodules"
    code text
    cat "$repo/.gitmodules" >> "$OUT"
    end_code
  fi

  popd >/dev/null
done

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
hr
{
  echo "_End of inventory. Paste this entire file (or upload as attachment) into the chat for Report II._"
  echo "_File size:_ \`$(du -h "$OUT" | cut -f1)\`"
  echo ""
  echo "**Privacy check:** this file contains:"
  echo "- repo paths, file names, directory names"
  echo "- counts and sizes"
  echo "- commit author names, commit counts, +/- line totals"
  echo "- excerpts of README / AGENTS / ARCHITECTURE / CLAUDE / CONTRIBUTING / .cursor/rules (first 60 lines each)"
  echo ""
  echo "**It does NOT contain:** source code contents, .env / secrets, private file contents beyond the documented excerpts."
} >> "$OUT"

echo ""
echo "✓ Done."
echo "  Output: $OUT"
echo "  Size:   $(du -h "$OUT" | cut -f1)"
echo "  Lines:  $(wc -l < "$OUT")"
echo ""
echo "Next step — review and paste in chat:"
echo "  less $OUT          # eyeball it; redact anything you don't want shared"
echo "  cat  $OUT          # paste full contents"
