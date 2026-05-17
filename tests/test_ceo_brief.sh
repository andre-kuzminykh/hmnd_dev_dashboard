#!/usr/bin/env bash
# Executable verification of docs/CEO_BRIEF.html against R-001..R-040.
# Run from repo root: bash tests/test_ceo_brief.sh — expect 40/40 PASS.

set -u
FILE="docs/CEO_BRIEF.html"
PASS=0; FAIL=0; RESULTS=()
if [[ ! -f "$FILE" ]]; then echo "FATAL: $FILE not found"; exit 2; fi

check() {
  local id="$1" desc="$2" cmd="$3"
  if eval "$cmd" >/dev/null 2>&1; then RESULTS+=("PASS $id  $desc"); PASS=$((PASS+1))
  else RESULTS+=("FAIL $id  $desc"); FAIL=$((FAIL+1)); fi
}
gc()  { grep -cF "$1" "$FILE"; }
gpE() { grep -cE "$1" "$FILE"; }
has() { grep -qF "$1" "$FILE"; }
hasE(){ grep -qE "$1" "$FILE"; }

check R-001 "Single self-contained HTML, mobile-first"               'has "<!DOCTYPE html>" && has "cdn.tailwindcss.com" && has "viewport"'
check R-002 "100% English (no Cyrillic)"                             '! grep -P "[\x{0400}-\x{04FF}]" "$FILE" >/dev/null 2>&1'
check R-003 "Nav: Business / Technical / Roadmap"                    'has "Business Analysis" && has "Technical Analysis" && has "Roadmap" && [[ $(gc "nav-link") -ge 3 ]]'
check R-004 "Champion Matrix with names"                             'has "Champion Matrix" && has "Eugene Lyapustin" && has "Oleg Sinavski" && has "Atindra Nair"'
check R-005 "Q2 workflow-review names"                               'has "Richard" && has "Cody Griffin" && has "Matt Klingensmith"'
check R-006 "Q3 coaching names"                                      'has "Anubhav Dogra" && has "Bao Tran" && has "Dmitriy Shingarey"'
check R-007 "Per-module bug-rate bar chart (14 modules)"             'has "35.3%" && [[ $(gc "progress-row") -ge 14 ]]'
check R-008 "Bot vs Human bug rate"                                  'has "24.8%" && has "18.8%"'
check R-009 "Cross-reference table"                                  'has "Top spender" && has "Module bug rate" && has "Bus factor"'
check R-010 "Numerical depth"                                        'has "\$0.001" && has "\$0.37" && has "\$23.11" && has "\$23.25" && has "\$17.85" && has "0.93"'
check R-011 "Visuals: bars, quadrant, Gantt"                         '[[ $(gc "bar-track") -ge 20 ]] && has "quadrant" && has "gantt"'
check R-012 "Numbers vs Reports I + II"                              'has "\$23,353" && has "140" && has "44.7%" && has "63.2%" && has "4.0 / 5" && has "2.0 / 5"'
check R-013 "Mobile-responsive"                                      'has "md:" && has "sm:" && has "lg:" && has "scroll-x"'
check R-014 "Collapsible <details>"                                  '[[ $(gpE "<details") -ge 3 ]]'
check R-015 "Tooltip pattern (.tip)"                                 'has "class=\"tip\"" && has "@media (max-width:640px)"'
check R-016 "Week-1 Jira (7 tickets)"                                'has "HMND-AI-1" && has "HMND-AI-7"'
check R-017 "4-week monthly cycle"                                   'has "Spec" && has "Test &amp; Dev" && has "Refactor" && has "Env &amp; Monitor"'
check R-018 "Gantt · 13 weeks · Env Rollout + L1-L8 Education"       'has "gantt-head" && has "gantt-row" && has "W13" && has ">L1<" && has ">L8<" && has "Environment Rollout" && has "Education"'
check R-019 "ROI metrics defined"                                    'has "closed-Jira" && has "merged-PR" && has "passing-test"'
check R-020 "Cohort reconciliation 140 vs 206"                       'has "140" && has "206" && has "53 humans not in 30d"'
check R-021 "R-ID catalog visible + tests"                           'has "Requirements traceability" && has "R-001" && has "R-040" && [[ -f tests/test_ceo_brief.sh ]]'
check R-022 "Bus factor (4 single-person)"                           'has "hmnd_services" && has "hmnd_agents" && has "hmnd_update" && has "hmnd_infra" && has "Cody Griffin alone"'
check R-023 "Repo scores"                                            'has "4.0 / 5" && has "2.0 / 5" && has "MOSTLY READY" && has "PAUSE AI"'
check R-024 "16 Priority Actions (collapsed in §2.10)"               'has "16 priority actions"'
check R-025 "Cost optimisation \$3-5k/mo"                            'has "\$3–5k"'
check R-026 "Model routing policy"                                   'has "Model-routing policy" && has "Cursor Tab" && has "gpt-4.1-mini"'
check R-027 "Test coverage disparity (401 / 4 / 0)"                  'has "401" && hasE "4 (tests|⚠)" && has "0 tests"'
check R-028 "AGENTS guardrails table"                                'has "guardrails" && has "AGENTS.md" && has "CODEOWNERS" && has ".cursor"'
check R-029 "Adoption segments"                                      'has "HIGH AI · HIGH Git" && has "Git active · no AI"'
check R-030 "Anomalies (Amir + n8n_artem + 6 dupes)"                 'has "Amir Torabi" && has "n8n_artem" && has "6 display-name dupes"'
check R-031 "Vendor lock-in (Claude Code 83% of Anthropic)"          'has "83.4%" && has "Vendor concentration"'
check R-032 "Cursor seat sunset (18 dormant)"                        'has "18 dormant"'
check R-033 "Display-name dupes (6)"                                 'has "6 display-name dupes"'
check R-034 "Annualisation (~\$284k)"                                'has "~\$284k" && has "30–100%"'
check R-035 "Top-5 risk register R1-R5"                              'has ">R1 ·" && has ">R2 ·" && has ">R3 ·" && has ">R4 ·" && has ">R5 ·"'
check R-036 "Open Harness in tool stack"                             'has "Open Harness" && has "OpenCode" && has "ClawCode"'
check R-037 "Dashboard button"                                       'has "https://hmnd.34.62.139.101.nip.io/" && has "Open HMND Dashboard"'
check R-038 "Tooltips replace inline caveats"                        '[[ $(gc "class=\"tip\"") -ge 5 ]]'
check R-039 "Single biggest gap (prompt-regression eval)"            '[[ $(gc "prompt-regression eval") -ge 2 ]]'
check R-040 "Identity merge documented (tooltip + table notes)"      'has "20 dual-domain" && has "11,378" && has "identity-merge"'

echo
printf '%s\n' "${RESULTS[@]}"
echo
TOTAL=$((PASS+FAIL))
echo "─────────────────────────────────────────"
if [[ $FAIL -eq 0 ]]; then
  echo "SUMMARY: ${PASS}/${TOTAL} PASS ✓ all requirements covered"
  exit 0
else
  echo "SUMMARY: ${PASS}/${TOTAL} PASS · ${FAIL} FAIL ✗"
  exit 1
fi
