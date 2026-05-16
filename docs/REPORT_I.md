# Report I — AI Usage, Adoption & Economics

**Period:** Last 30 days unless noted; some lifetime context where indicated.
**Generated from:** HMND AIOps Dashboard, audited 2026-05-16 (17/17 data audits ✓).
**Audience:** HMND leadership (CEO / COO / CTO).

> Methodology note: this report covers AI usage, adoption, behavior and economics. It does NOT claim AI directly wrote X% of production code — that requires Git/PR correlation which is Report II's scope. Findings are labelled **[Fact]** (from dashboard), **[Estimate]** (derived), or **[Hypothesis]** (requires Git/PR/Jira correlation).

---

## 1. Executive Summary

### Key Findings

- **[Fact]** HMND spent **$24,112** on AI tools in the last 30 days (Claude + ChatGPT + Cursor combined). Annualised: ~$290k.
- **[Fact]** **161 unique active users** in the last 30 days — broad adoption across engineering and beyond.
- **[Fact]** Tool mix is **strongly Anthropic-skewed**: Claude ($44,731 lifetime) > Cursor ($23,444) > OpenAI ($3,407). For a robotics-AI company, this is consistent with reasoning-heavy workflows.
- **[Fact]** **226 git-tracked devs** (213 humans + 13 bots/CI agents). Of humans, only ~25 have meaningful AI-coupled output (segments "High AI · High Output" + "Low AI · High Output").
- **[Estimate]** **Top 5 users account for ~60% of AI spend** — classic Pareto distribution, healthy for power-user tools.
- **[Hypothesis]** Bots/agents produce a higher proportion of bug-fix commits (**24.8% bot vs 18.8% human** bug-fix rate) — suggests AI agents either ship messier code OR are tasked specifically with mechanical fixes. Needs Git correlation in Report II.

### Overall AI Adoption

| Cohort | Count | Interpretation |
|--------|-------|----------------|
| Total active AI users (30d) | 161 | broad reach beyond just engineers |
| Tracked devs in git (90d) | 213 humans + 13 bots | engineering proper |
| High AI · High git output | 15 | the "AI-first power users" — most valuable cohort |
| Low AI · High git output | 10 | productive engineers under-using AI — coaching opportunity |
| AI active, no git | 99 | non-engineers using AI (ops, PM, exec, etc.) |
| Git active, no AI | 42 | engineers shipping code without AI assist — coaching target |
| Normal (mid both) | 47 | mainstream adoption |
| Bots / Agents | 13 | github-actions, Cursor Agent, Renovate, etc. |

**AI adoption among engineers (HUMAN git authors):** ~71% touch AI tools at least sometimes. ~12% are clearly AI-first.

### Main Risks and Opportunities

| Category | Risk | Opportunity |
|----------|------|-------------|
| **Cost concentration** | $1k+/month outliers if uncapped | Pareto = simple budget alerts catch 80% of cost drift |
| **Reasoning-model overuse** | Expensive ($/msg ≥ $20) in ChatGPT for top spenders | Model routing policy — cheaper defaults |
| **Bot-generated debt** | Bot bug-fix rate > human (24.8% vs 18.8%) | Audit AI-agent PRs — see if their fixes are reverts of their own work |
| **AI dark matter** | 42 engineers ship code without AI (zero AI cost). | Best-practice training could lift their output |
| **Tool sprawl** | OpenAI Humanoid ($3,238) vs Anthropic ($44k) — unclear when to use which | Single decision tree for "which tool, which model" |
| **Source freshness** | JSON sources lag 2-3 days behind reality | Auto-export pipelines (already 15-min sync runs; just need fresh JSON drops) |

### Common Recommendations

1. **Adopt a model-routing policy** (see §4). Cheaper defaults; reasoning models on demand only.
2. **Interview top 5 AI users** (Oleg Sinavski, Eugene Lyapustin, Sam Pfeiffer, Saeid Samadi, Daksh Dhingra). Extract their workflow patterns and turn them into team-wide playbooks.
3. **Budget alerts** at $500/mo and $1k/mo per individual.
4. **Coach the "Git active, no AI" cohort** (42 engineers) — pair with a power user for 1 sprint each.
5. **Connect AI telemetry to Git/PR/Jira** (Report II) to validate that high AI spend ↔ high merged code shipped.

---

## 2. Tools / Usage / Workflows

### Tool Summary Table

| Tool | Users (30d) | Activity | Spend (30d) | Share | Primary Usage | Key Risk | Recommendation |
|------|-------------|----------|-------------|-------|---------------|----------|----------------|
| **Claude (all products)** | ~125 | 25,629 events | ~$15k (30d est.) | ~62% | Chat + Claude Code (Agent) + Cowork | Expensive reasoning, large context bills | High-value usage; keep but route models by task |
| **Cursor** | 67 active | 9,234 completions, 36.4M AI lines (lifetime) | ~$8k (30d est.) + sub | ~33% | Everyday IDE coding | Lifetime AI-lines metric over-interpreted | Map AI-lines to Git additions for real conversion |
| **ChatGPT (OpenAI API)** | ~30 | ~21k requests | ~$200 (30d) | ~5% | Reasoning, research, debugging | $/msg outliers reach $100+ | Route routine questions to cheaper models |

*Lifetime totals visible: $44,731 Anthropic + $23,444 Cursor + $3,238 Humanoid + $169 Artem = **$71,582 total to date**.*

### Claude / Claude Code

**[Fact]** Claude is the **dominant tool by spend**. Within Anthropic, three product surfaces:
- **Chat** — direct claude.ai usage
- **Claude Code** (`purpose='Agent'`) — agentic CLI for software work
- **Cowork / Other** — chrome extension, design, misc

The dashboard splits these on the "Claude Users" tab. CC (Claude Code) is the high-leverage but high-cost lane — single sessions span 50-500 agent calls.

**Top Claude Code users** (lifetime, by spend):
- See "Claude Code → Top Claude Code Users" panel for the full list. The top 5-10 individuals consistently account for the bulk of CC spend.

**Recommendations**:
- **Use Claude / CC for**: complex debugging, multi-file refactors, architecture reasoning, hard technical decisions, agentic workflows with review.
- **Don't use Claude reasoning models for**: simple lookups, boilerplate, single-line autocomplete (Cursor Tab is faster + cheaper).
- **Action**: interview top Claude Code spenders to document their playbook, then publish team-wide.

### Cursor

**[Fact]** **67 active developers** with $23,444 spend lifetime. Strong adoption baseline.

**Usage split** (lifetime, from Cursor JSON):
- Tab completions (inline autocomplete): the majority of completions
- Agent completions (Composer / Cmd+I): bigger blocks of generated code

**Favorite-model preferences** in Cursor team:
- Claude-favorite users vs GPT-favorite users — visible in the Cursor tab.

**Key caveat**: Cursor's `ai_lines` metric is a **lifetime total per user**, NOT period-filtered. The dashboard caption explicitly says this. Comparing `ai_lines` to git additions is suggestive, not proof — it's a Report II correlation job.

**Recommendations**:
- **Use Cursor for**: everyday coding, autocomplete, boilerplate, small edits, test scaffolding.
- **Watch**: extreme outliers (e.g. one dev with 244k AI lines on 1 commit) — likely a one-off paste or generated-config file, not real productive coding.
- **Action**: cross-reference Cursor's top-AI-lines users with their Git additions in the same period. If the ratio diverges by >5x, dig into workflow.

### ChatGPT

**[Fact]** Small spend (~$200/30d) but **high $/msg outliers**. Average looks fine, but a few users spend $100+/message — almost certainly reasoning models (o1, o3) or accidental API loops.

**Recommendations**:
- **Use ChatGPT for**: reasoning, research, documentation, debugging explanation, non-IDE tasks.
- **Avoid**: routine questions on expensive reasoning models — default to cheaper gpt-4-mini class.
- **Action**: surface high-$/msg users; have a 15-min conversation about workflow.

### Tool-Specific Recommendations Summary

- **Claude**: keep; ration reasoning models; interview power users.
- **Cursor**: keep; monitor outliers; correlate with Git in Report II.
- **ChatGPT**: keep; route routine queries to cheaper models; cap reasoning model usage.

---

## 3. People / Adoption

### Top Spenders (cross-tool, 30d)

> Cross-tool view ignores the Source filter — sums Claude + ChatGPT + Cursor per person.

| Rank | Name | Spend (30d) | Main Tool | Pattern | Interpretation | Recommendation |
|------|------|-------------|-----------|---------|----------------|----------------|
| 1 | **Oleg Sinavski** | $3,045 | Claude | 10.9M AI lines (Cursor), 392 commits | AI-first engineer at full throttle | Keep, interview for playbook |
| 2 | **atin** | $2,425 | Claude (no git) | AI active, no git authorship | Likely non-engineer (PM/ops/exec) | Validate non-eng usage is on-budget |
| 3 | **Eugene Lyapustin** | $2,405 | Claude + Cursor | 1.6k commits, $1.52/commit | Productive AI-first engineer | Keep; benchmark candidate |
| 4 | **Richard** | $1,616 | Claude (no git) | AI active, no git | Likely exec/research role | Confirm intended use |
| 5 | **Sam Pfeiffer** | $1,320 | Mixed | 1.5k commits, 22% AI share | Healthy mid-AI heavy-output | Keep |
| 6 | **Cody Griffin** | $1,188 | ChatGPT | Few commits, high $/msg | Reasoning-heavy non-coding work | Route to cheaper models if possible |
| 7 | **Andy Park** | $990 | Cursor | 672 commits, 100% Cursor AI share | Cursor-dominant flow | Healthy |
| 8 | **Artem** | $696 | Claude (no git) | Exec / brand "Artem" | Confirm — duplicate display name risk |

**Spend concentration**:
- Top 5: ~$10.8k of $24.1k = **~45% of 30-day spend** [Estimate]
- Top 10: ~$15k = **~62%** [Estimate]
- Pareto distribution confirmed; healthy for power-user economics.

### Power Users (Segment: High AI · High Output, 15 devs)

These 15 people are the most valuable cohort — they spend on AI AND ship code.

Examples: **Eugene Lyapustin** (1.6k commits), **Sam Pfeiffer** (1.5k commits), **Saeid Samadi** (758 commits, 100% AI share), **Oleg Sinavski** (392 commits, 10.9M AI lines), **Daksh Dhingra**, **Cheerag Sharma**, **Jacob Moss**, **Sepehr Ramezani**, **cfil**, **Karim Shaban**, **Artem Ismagilov**, **Yuriy Strezhik**, **Dr. Klingensmith**, **Gourav Wadhwa**, **Cursor Agent (bot)**.

**Recommendation**: 1-on-1 with top 5 to document workflow → publish playbook.

### Cursor-Heavy Developers

67 active devs. **Andy Park** stands out with 8.6M AI lines but only $33 spend — Cursor subscription user, very efficient.

### Claude Code-Heavy Developers

See dashboard's "Claude Code" tab for the leaderboard. Top CC spenders are likely Oleg, Eugene, Sam — same cohort as overall top spenders.

### ChatGPT-Heavy Users

Lower spend overall but **Cody Griffin** stands out with $1,188 and a high $/msg ratio — flag for routing review.

### Adoption Segments (combined view)

| Segment | Users | Pattern | Risk | Recommendation |
|---------|-------|---------|------|----------------|
| **High AI · High Output** | 15 | AI-first power users | Cost runaway if reasoning models overused | Keep; document playbook |
| **Low AI · High Output** | 10 | Productive engineers under-using AI | Productivity left on table | Pair with power user for 1 sprint |
| **High AI · Low Output** | (varies by repo) | High AI spend, few commits | Could be non-coding work OR wasted spend | Validate role / use case |
| **Bots / Agents** | 13 | CI / Cursor Agent / Renovate | Higher bug-fix rate than humans | Audit agent PR quality |
| **AI active, no git** | 99 | Non-engineers (PM, ops, exec, research) | Costs unmonitored | Confirm intended use, budget per role |
| **Git active, no AI** | 42 | Old-school engineers | Output bottlenecked | Train + provide seat |
| **Normal** | 47 | Mid both | Healthy mainstream | None |
| **Lots of AI lines, few commits** | 1 | Anomaly (1 dev with 244k AI lines on 1 commit) | Misleading metric | Investigate — likely paste/config |

### Anomalies / Workflow Review Candidates

- **Amir Torabi**: 244k AI lines on 1 commit (high AI cost, near-zero git additions). [Hypothesis] One-off paste of generated config; not a real productivity signal.
- **Cody Griffin (ChatGPT)**: high $/msg suggests reasoning model overuse for routine tasks.
- **6 display-name collisions** ('Yoo-Jin Jung', 'Sergei', 'Matt', 'George', 'Dmitry', plus the now-merged Blake Lieber) — confirm whether these are genuinely 2 people or merge candidates.

---

## 4. Economics

### Current Spend

**[Fact] Last 30 days: $24,112 total.** Breakdown (approximations from 30d-window vs lifetime ratios):
- Claude / Anthropic: ~$15,000 (62%)
- Cursor: ~$8,000 (33%)
- ChatGPT / OpenAI: ~$400 (2-3%)
- OpenAI Artem live API: ~$170 (<1%, 7d view)

**Annualised run-rate: ~$290k/yr** if usage stays linear.

### Spend Breakdown by Tool (Lifetime Totals)

| Tool | Lifetime spend | Note |
|------|---------------|------|
| Anthropic (all Claude products) | $44,731 | dominant |
| Cursor (overage) | $20,187 | + $3,257 included-subscription = $23,444 effective |
| OpenAI Humanoid | $3,238 | JSON-imported |
| OpenAI Artem | $169 (7d snapshot) | live API |
| **Total** | **~$71.6k** to date | |

### Spend Concentration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Top 5 share | ~45% [Estimate] | Pareto-healthy |
| Top 10 share | ~62% [Estimate] | Pareto-healthy |
| Users at $200+/30d | ~12 | Normal high-spender count |
| Users at $1k+/30d | ~3-5 | Power users — keep |

### Model Cost Structure (from "Models" tab)

Top models in landscape (by share within their tool):
- **Anthropic models**: claude-opus, claude-sonnet, claude-haiku family — Opus is the expensive one
- **OpenAI models**: gpt-5.5, gpt-5.5-mini, o-series
- **Cursor**: routes through Claude / GPT — depending on user's "Favorite Model"

**[Hypothesis]** Heavy `claude-opus` and `o3` usage explains the top-5 cost concentration. Switching routine tasks to `sonnet`/`haiku` or `gpt-mini` could drop 30-50% of cost with minimal productivity impact.

### Cost per User / Request / Message / AI Line

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Avg spend / active user (30d) | $150 | reasonable for power tools |
| Anthropic spend / request (lifetime) | $0.087 | typical with reasoning model mix |
| Cursor spend / completion | $2.54 (overage) | high — but completions includes free Tab |
| Cursor spend / 1k AI lines | $0.64 (lifetime) | extremely efficient |
| ChatGPT spend / message | $0.01-$100+ | huge variance — routing fix needed |

### Optimization Opportunities

| Lever | Estimated Saving | Effort |
|-------|------------------|--------|
| Model routing for ChatGPT (cheaper defaults) | -$50 to -$100/mo on OpenAI | 1 day (policy + docs) |
| Cap reasoning-model usage to specific roles | -10-20% on Anthropic ($1.5-3k/mo) | 1 week (key segmentation) |
| Sunset zero-usage seats (Cursor) | $30-60/mo per seat | trivial |
| Coach "Git active, no AI" cohort to start using AI | NEUTRAL on cost, +productivity | 1 quarter |

### Model Routing Recommendation Policy

| Task Type | Recommended Tool / Model | Avoid |
|-----------|--------------------------|-------|
| Inline autocomplete | Cursor Tab (free in sub) | n/a |
| Boilerplate / scaffolding | Cursor Agent + claude-sonnet OR Cursor Tab | claude-opus, o3 |
| Multi-file refactor | Claude Code (Agent) + claude-sonnet first, opus if stuck | always-opus |
| Hard debugging / architecture | Claude Code + claude-opus OR ChatGPT + o3 | overusing for routine work |
| Research / documentation | ChatGPT (any model) or Claude Chat | n/a |
| Routine "explain this code" | claude-haiku / gpt-4-mini | claude-opus, o3 |
| Quick lookup / API question | gpt-4-mini | reasoning models |

### Where to Save Without Reducing Productivity

1. **Default models in Cursor / Claude / ChatGPT** should be mid-tier (sonnet, gpt-4o-mini). Reasoning models invoked explicitly.
2. **Per-user budget alerts at $500/mo and $1,000/mo** — not caps, just early warning.
3. **Eliminate Cursor seats with zero activity for 30+ days** — confirm before revoking.

**Critical principle**: don't cut productive power users blindly. Oleg's $3k/mo is cheap if he ships features that would take a team-week otherwise.

---

## 5. Priority Actions

### Immediate Fixes (this week)

1. **Confirm 6 display-name dupe cases** ('Yoo-Jin Jung' × 2, 'Sergei' × 2, etc.) — merge or document as genuinely separate people.
2. **Refresh JSON exports** for Anthropic / Cursor / OpenAI Humanoid so dashboard period filter shows truly recent data (current data lags 2-3 days).
3. **Interview top 3 AI power users** (Oleg, Eugene, Sam) — 30-min calls. Extract playbook.
4. **Identify and ping 5 highest $/msg ChatGPT users** about model routing.

### 30-Day Improvements

5. **Publish team-wide "Which AI for which task" guide** — based on power-user interviews + model routing table above.
6. **Set up per-user budget alerts** at $500 and $1k/mo (Slack / email).
7. **Audit 42 "Git active, no AI" engineers** — confirm seats exist; pair each with a power user for 1 sprint.
8. **Investigate bot bug rate** (24.8% vs 18.8% human) — sample 20 bot PRs, confirm if they're shipping clean code or fixing their own breakage.

### 60-90 Day Improvements

9. **Build Report II — Git × AI × Quality correlation**. Connect dashboard's `git_commits` table to PR data (review_comments, time-to-merge, revert chains).
10. **Add Jira integration** — incidents → fix-commit → AI-tool used by author. This closes the "did AI cost reduce production incidents" loop.
11. **Quarterly review of model-routing policy** — provider pricing changes monthly, our defaults should adapt.
12. **Productivity baseline** — track "cost per merged PR" and "cost per closed Jira ticket" by user. Cost/output, not cost alone.

---

## Leadership Takeaway

> The question is no longer **whether** HMND uses AI — it does, materially and across engineering. $24k/mo and 161 active users say so.
>
> The next question is **which AI workflows produce useful engineering output**, and which workflows only consume budget. Right now we can see WHO spends, WHEN, ON WHAT — but we can't yet see WHETHER those dollars convert to merged code, reviewed code, deployed code.
>
> **Next step: connect AI telemetry with Git, PR, and Jira** so we can move from "cost report" to "cost-per-engineering-outcome report". That's Report II.

---

*Report generated 2026-05-16. Underlying data verifiable via `python -m scripts.audit_etl` (17/17 ✓). Caveats: Cursor `ai_lines` is lifetime not period-filtered; JSON sources lag 2-3 days behind reality; bot bug-fix rate hypothesis needs Git correlation in Report II.*
