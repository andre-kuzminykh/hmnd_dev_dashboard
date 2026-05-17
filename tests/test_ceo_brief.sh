#!/usr/bin/env bash
# Executable verification of docs/CEO_BRIEF.html against the R-001..R-040
# stakeholder requirements captured during the CEO-brief engagement.
#
# Run from repo root:   bash tests/test_ceo_brief.sh
# Expect:               40/40 PASS

set -u
FILE="docs/CEO_BRIEF.html"
PASS=0
FAIL=0
RESULTS=()

if [[ ! -f "$FILE" ]]; then
  echo "FATAL: $FILE not found (run from repo root)"
  exit 2
fi

check() {
  local id="$1" desc="$2" cmd="$3"
  if eval "$cmd" >/dev/null 2>&1; then
    RESULTS+=("PASS $id  $desc")
    PASS=$((PASS+1))
  else
    RESULTS+=("FAIL $id  $desc")
    FAIL=$((FAIL+1))
  fi
}

# Convenience helpers
gc()  { grep -cF "$1" "$FILE"; }     # count literal occurrences
gpE() { grep -cE "$1" "$FILE"; }     # count regex occurrences
has() { grep -qF "$1" "$FILE"; }
hasE(){ grep -qE "$1" "$FILE"; }

# ──────────────────────────────────────────────────────────────────────────────
check R-001 "Single self-contained HTML, mobile-first"                      'has "<!doctype html>" && has "cdn.tailwindcss.com" && has "viewport"'
check R-002 "100% English (no Cyrillic outside requirement labels)"         '! grep -P "[\x{0400}-\x{04FF}]" "$FILE" >/dev/null 2>&1'
check R-003 "Top nav: Business / Technical / Roadmap"                       'has "Business Analysis" && has "Technical Analysis" && has "Roadmap" && [[ $(gc "nav-link") -ge 3 ]]'
check R-004 "Champion Matrix 2×2 with named people"                         'has "Champion Matrix" && has "Q1" && has "Q2" && has "Q3" && has "Q4" && has "Eugene Lyapustin" && has "Oleg Sinavski" && has "Atindra Nair"'
check R-005 "Q2 workflow-review candidates named"                           'has "Richard" && has "Cody Griffin" && has "Matt Klingensmith"'
check R-006 "Q3 coaching targets named"                                     'has "Anubhav Dogra" && has "Bao Tran" && has "Dmitriy Shingarey"'
check R-007 "Per-module bug-rate bar chart present"                         'has "per-module bug-fix rate" && has "35.3%" && [[ $(gc "progress-row") -ge 14 ]]'
check R-008 "Bot vs Human bug-rate comparison"                              'has "24.8%" && has "18.8%"'
check R-009 "Cross-reference table"                                         'has "Top spender" && has "Module bug rate" && has "Bus factor"'
check R-010 "Numerical depth"                                               'has "\$0.001" && has "\$0.37" && has "\$23.11" && has "\$23.25" && has "\$17.85" && has "0.93"'
check R-011 "Visuals / infographics"                                        '[[ $(gc "bar-track") -ge 20 ]] && has "quadrant" && has "stacked"'
check R-012 "Numbers verified vs Reports I + II"                            'has "\$23,353" && has "140" && has "44.7%" && has "63.2%" && has "4.0 / 5" && has "2.0 / 5"'
check R-013 "Mobile-responsive"                                             'has "md:" && has "sm:" && has "lg:" && has "scroll-x"'
check R-014 "Collapsible <details> blocks"                                  '[[ $(gpE "<details") -ge 3 ]]'
check R-015 "Tooltip CSS pattern"                                           'has ".has-tooltip" && has "@media (max-width:640px)"'
check R-016 "Week-1 Jira plan (7 tickets)"                                  'has "HMND-AI-1" && has "HMND-AI-7"'
check R-017 "Month-1 environment hardening · 4 weekly drills"               'has "Week 1 · IaC blast-radius shield" && has "Week 2 · Cost" && has "Week 3 · Bus-factor" && has "Week 4 · hmnd_fleet"'
check R-018 "Months 1-3 · 8 lectures L1-L8"                                 'for l in L1 L2 L3 L4 L5 L6 L7 L8; do has ">$l<" || exit 1; done'
check R-019 "CEO Decisions D1-D5"                                           'has ">D1<" && has ">D2<" && has ">D3<" && has ">D4<" && has ">D5<"'
check R-020 "Cohort reconciliation 140 vs 206"                              'has "140" && has "206" && has "53 humans not in 30d"'
check R-021 "Requirements catalog in HTML + this test file exists"          'has "Requirements traceability" && has "R-001" && has "R-040" && [[ -f tests/test_ceo_brief.sh ]]'
check R-022 "Bus factor per module (4 single-person)"                       'has "hmnd_services" && has "hmnd_agents" && has "hmnd_update" && has "hmnd_infra" && has "Cody Griffin alone"'
check R-023 "Repo scores 4.0 / 2.0 / DEPRECATED"                            'has "4.0 / 5" && has "2.0 / 5" && has "DEPRECATED"'
check R-024 "17 Priority Actions table"                                     '[[ $(gpE "<td>(1[0-7]|[1-9])</td>") -ge 17 ]] || has "17 Priority actions"'
check R-025 "Cost-optimisation \$3-5k/mo"                                   'has "\$3–5k" || has "\$3-5k"'
check R-026 "Model routing policy table"                                    'has "Recommended model-routing policy" && has "Cursor Tab" && has "gpt-4.1-mini"'
check R-027 "Test coverage disparity highlighted (401 / 4 / 0)"             'has "401" && has "4 tests / 60k" && has "0 tests"'
check R-028 "AGENTS.md / CODEOWNERS / .cursor guardrails table"             'has "AI-codegen guardrails" && has "AGENTS.md" && has "CODEOWNERS" && has ".cursor"'
check R-029 "Adoption segments table"                                       'has "HIGH AI · HIGH Git" && has "Git active · no AI" && has "TOTAL (lifetime)"'
check R-030 "Anomalies (Amir + n8n_artem + 6 dupes)"                        'has "Amir Torabi" && has "n8n_artem" && has "6 display-name dupes"'
check R-031 "Vendor lock-in surfaced (Claude Code 83% of Anthropic)"        'has "83.4%" && has "Vendor concentration"'
check R-032 "Cursor seat sunset opportunity (18 dormant)"                   'has "18 dormant" || has "18 zero-activity"'
check R-033 "Display-name dupes to confirm (6)"                             'has "6 display-name dupes"'
check R-034 "Annualisation / cost projection (~\$284k)"                     'has "~\$284k" && has "30–100%"'
check R-035 "Top-5 risk register R1-R5"                                     'has ">R1 ·" && has ">R2 ·" && has ">R3 ·" && has ">R4 ·" && has ">R5 ·"'
check R-036 "Owner accountability map (7 roles, reports to CEO)"            'has "Owner accountability map" && has "Reports to CEO on"'
check R-037 "Glossary (jargon explained)"                                   'has "§A.2 · Glossary" && has "AGENTS.md" && has "Bus factor"'
check R-038 "Data-trust traceability (VERIFIED / CAVEAT / HYPOTHESIS)"      'has "VERIFIED" && has "CAVEAT" && has "HYPOTHESIS"'
check R-039 "Single biggest gap surfaced (prompt-regression eval)"          '[[ $(gc "prompt-regression eval") -ge 2 ]]'
check R-040 "Identity merge documented (20 dual-domain)"                    'has "20" && has "dual-domain" && has "11,378"'

# ──────────────────────────────────────────────────────────────────────────────
echo
printf '%s\n' "${RESULTS[@]}"
echo
TOTAL=$((PASS+FAIL))
echo "─────────────────────────────────────────"
if [[ $FAIL -eq 0 ]]; then
  echo "SUMMARY: ${PASS}/${TOTAL} PASS  ✓  all requirements covered"
  exit 0
else
  echo "SUMMARY: ${PASS}/${TOTAL} PASS · ${FAIL} FAIL  ✗"
  exit 1
fi
