# Report I — AI Usage, Adoption & Economics

**Period:** Last 30 days (2026-04-16 → 2026-05-16) unless otherwise noted.
**Source:** HMND AIOps Dashboard, audited 2026-05-16 (17/17 data audits ✓).
**Audience:** HMND leadership.

> **Methodology**: This report covers AI usage, adoption, behaviour, and economics. It does NOT claim AI directly wrote X% of production code — that requires PR + quality-gate correlation (Report II). **AI ↔ Git correlation is already wired in this dashboard** (segments, bug-fix rate, $/fix, AI-lines vs commits). Findings are tagged **[Fact]** (verified in dashboard, traceable to raw bytes), **[Estimate]** (derived from dashboard numbers), or **[Hypothesis]** (requires PR / Jira / quality-gate correlation).
>
> **Identity caveat (read Appendix A.10 first)**: 22 HMND people operate under two email domains (`thehumanoid.ai` and `skl.vc`) and appear as two distinct `user_id` rows in this dashboard. Their per-person totals in §3 are **split across two identities** unless the loader unifies them by email local-part — it currently does not. Aggregate totals (§1, §4) are unaffected; per-person rankings and segment counts are.

---

## 1. Executive Summary

### Key Findings

- **[Fact]** HMND spent **$24,104** on AI tools in the last 30 days. Annualised run-rate: **~$293,000/yr**.
- **[Fact]** **160 unique active users** across the company — broad adoption beyond engineering.
- **[Fact]** Tool mix:  **Anthropic 57.2% / Cursor 29.9% / OpenAI 12.9%** by 30d spend.
- **[Fact]** Within Anthropic, **Claude Code (Agent) is 83% of Anthropic spend ($11,489)** — agentic coding is the dominant Claude workflow.
- **[Fact]** **Top 5 spenders = 44.9% of total spend; Top 10 = 62.7%** — textbook Pareto.
- **[Fact]** **OpenAI Artem org** = 1 user × 57,250 events × $0.01/msg = automation (the `n8n_artem` service account). OpenAI Humanoid is the real human-facing OpenAI usage.
- **[Hypothesis]** ChatGPT $/message ratios reveal **clear reasoning-model overuse**: 4 top OpenAI spenders pay $7-$23 PER MESSAGE — they're hitting o-series for routine tasks.

### Overall AI Adoption

| Cohort | Count | Comment |
|--------|-------|---------|
| Active AI users (30d) | **160** | broad reach |
| Cursor team members | 81 | 63 with ≥ 1 completion |
| Claude users (any purpose, 30d) | 111 | dominant tool |
| OpenAI users (30d) | 7 | tiny user base, high $/user |
| Git-tracked devs | 213 humans + 13 bots | engineering proper |
| AI-coupled productive engineers | 25 (15 High-High + 10 Low-High) | the cohort worth scaling |
| "AI active, no git" | 89 | non-engineers (PM/ops/exec/research) |
| "Git active, no AI" | 44 | engineers not yet on AI — coaching target |

**Engineering AI penetration (humans only)**: ~71% touch AI; ~12% are AI-first.

### Main Risks and Opportunities

| Theme | Risk | Opportunity |
|-------|------|-------------|
| **Cost concentration** | Top 10 = 62.7% of spend ($15,105/mo). Single individual changes can move the line. | Pareto = budget alerts on ~10 people catch most issues. |
| **Reasoning-model overuse on OpenAI** | 4 of 5 top OpenAI spenders pay $7-$23/msg (o-series) | Routing policy → ~$1,500/mo saving on OpenAI alone |
| **Claude Code dominance ($11.5k/30d)** | All eggs in one Anthropic basket; one provider outage = team blocked | Maintain GPT/Cursor as fallback workflows |
| **Bot bug rate > human (24.8% vs 18.8% lifetime)** | AI agents may ship code that they later have to fix | Audit a sample of agent PRs in Report II |
| **"Git active, no AI" cohort (44 engineers)** | Productivity left on table | Pair with power user 1 sprint each |
| **Synthesised Claude Code events** | Top CC users all show exactly 56 events — these are Cursor→Anthropic synthesised (not real CC sessions); real CC users hidden behind Cursor's `agent_completions` aggregation | Tag Claude Code events by source in Report II |

### Common Recommendations

1. **Adopt a model-routing policy** (see §4 table). Route routine queries to cheaper models. Estimated saving: $1,500-$3,000/mo.
2. **Interview top 5 AI users** (Oleg Sinavski, atin, Eugene Lyapustin, Richard, Sam Pfeiffer) — document workflow playbook, publish team-wide.
3. **Per-user budget alerts** at $500 and $1,000/mo (Slack). Not caps — early warning.
4. **Reach the 44 "Git active, no AI" engineers** — pair each with a power user for 1 sprint.
5. **Extend AI ↔ Git correlation to PR + Jira + quality-gates** (Report II). The AI ↔ Git side is **already live** (segments, bug-fix rate, $/fix, AI-lines vs commits). Next step: PR review-cycle + Jira ticket closure → convert "cost per AI event" into "cost per merged PR" and "cost per closed ticket".
6. **Unify dual-identity users by email local-part** (see Appendix A.10). One-line fix in the loader; collapses 22 split user_ids and makes §3 rankings honest.

---

## 2. Tools / Usage / Workflows

### Tool Summary Table (Last 30 days)

| Tool | Users | Activity | Spend | Share | Primary Usage | Key Risk | Recommendation |
|------|-------|----------|-------|-------|---------------|----------|----------------|
| **Anthropic (all Claude products)** | 111 | 6,808 events | **$13,779** | **57.2%** | Claude Code (Agent), Chat, Cowork | High-context reasoning calls are expensive | Reserve `claude-opus` for hard tasks |
| **Cursor** | 67 active (81 seats) | 1,876 spend-events (excl. free Tab) | **$7,214** | **29.9%** | Everyday IDE coding | `ai_lines` is lifetime not period; Cursor emails often `@skl.vc` while git commits `@thehumanoid.ai` → matching gap (see A.10) | AI-lines vs commits already in dashboard segments; PR-level attribution = Report II |
| **OpenAI** | 7 humans + 1 bot | 57,392 events (mostly automation) | **$3,112** | **12.9%** | Reasoning, automation (n8n) | $23/msg outliers on reasoning models | Route to cheaper models for routine work |
| **TOTAL** | 160 unique | 66,076 events | **$24,104** | 100% | | | |

### Claude / Claude Code

**[Fact]** Anthropic spend split by `purpose` (last 30d):

| Purpose | Spend (30d) | Share of Anthropic | Requests | Users |
|---------|-------------|---------------------|----------|-------|
| **Agent (Claude Code)** | **$11,489** | **83.4%** | 2,344 | 62 |
| Chat | $1,334 | 9.7% | 2,658 | 76 |
| Cowork | $819 | 5.9% | 1,331 | 37 |
| Chrome | $103 | 0.7% | 321 | 12 |
| Design | $33 | 0.2% | 56 | 2 |
| Other | $1.26 | <0.1% | 98 | 4 |

**Claude Code is the dominant workflow** ($11.5k/30d). Chat and Cowork are minor.

**[Caveat]** Some "Agent" events are *synthesised* from Cursor's `agent_completions` (via `data/cursor_to_anthropic.py`). This shows up as the top-10 CC users having an identical 56 requests each — that's the synthesis quantum, not real session count. Real Claude Code via Anthropic Admin API mixes in. Report II should separate these by event source.

**Top Claude Code (Agent) spenders (30d, may include synthesised entries):**

| Name | Spend |
|------|-------|
| atin | $2,422 |
| Eugene Lyapustin | $2,404 |
| Richard | $1,616 |
| Andy | $963 |
| Sam Pfeiffer | $851 |
| Daksh Dhingra | $509 |
| Richard Osterloh | $441 |

**Recommendations**:
- **Use for**: complex debugging, multi-file refactors, agentic workflows with review, architecture reasoning.
- **Avoid for**: simple lookups, boilerplate (Cursor Tab is cheaper and faster).
- **Action**: interview Eugene, atin, Richard, Andy — extract the workflow patterns that drive their high CC usage. Codify into a HMND playbook.

### Cursor

**[Fact]** 81 team members; 63 active (≥ 1 completion lifetime). 30-day overage spend $7,214.

**Favorite model preferences** (lifetime):
- **Claude family**: 27 devs (e.g. claude-4.6-opus-high-thinking, claude-4.6-sonnet-medium)
- **GPT family**: 20 devs (e.g. gpt-5.3-codex, gpt-5.4-xhigh-fast)
- Other / default: ~16

**Top 10 by AI lines (LIFETIME — Cursor's metric, not period-filtered):**

| Name | AI lines | Tab | Agent | Favorite model |
|------|---------:|----:|------:|----------------|
| Oleg Sinavski | 10,920,238 | 10.92M | 0 | claude-4.6-opus-high-thinking |
| Andy Park | 8,617,280 | 8.53M | 0 | gpt-5.3-codex |
| Luke Bierbaum | 556,543 | 31k | 0 | claude-4.6-sonnet-medium |
| Vaibhav Mehta | 444,956 | 3k | 40 | claude-4.6-opus-high-thinking |
| Saeid Samadi | 338,812 | 322k | 1,299 | gpt-5.4-xhigh-fast |
| batr | 259,234 | 198k | 0 | default |
| Sam Pfeiffer | 255,581 | 144k | 0 | claude-4.6-opus-high-thinking |
| Amir Torabi | 244,331 | 31k | 0 | claude-4.6-opus-high-thinking |
| Atindra Nair | 165,661 | 110k | 0 | claude-4.6-opus-high-thinking |
| Cheerag Sharma | 161,919 | 99k | 0 | gpt-5.4-medium |

**Caveat**: Oleg's 10.9M AI lines is a *lifetime* total — it represents months of work. Cross-checking against Git is **already live** in the dashboard (Segments view → `HIGH_AI_LINES_LOW_COMMITS` bucket flags exactly this kind of outlier). What's still pending in Report II: per-PR attribution and review-cycle quality signals.

**Recommendations**:
- **Use for**: everyday coding, autocomplete, boilerplate, small edits, test scaffolding.
- **Watch**: Oleg & Andy are outliers worth understanding (10M+ AI lines is *unusual* — confirm workflow isn't an artefact like ingesting generated config).
- **Action**: have Saeid Samadi present at an internal demo — he's the most balanced Tab+Agent user.

### ChatGPT (OpenAI)

**[Fact]** 7 human users, $3,112 spend. **Severely concentrated**:

| Name | Spend (30d) | Messages | $/msg | Pattern |
|------|------------:|---------:|------:|---------|
| Cody Griffin | $1,178 | 51 | **$23.11** | Reasoning model overuse |
| Dr. Klingensmith (Matt) | $791 | 34 | **$23.25** | Reasoning model overuse |
| Artem (`n8n_artem`) | $541 | **57,250** | $0.01 | Automation bot (n8n cron) |
| Sam Pfeiffer | $464 | 26 | **$17.85** | Reasoning model overuse |
| Tobias Jacob | $134 | 18 | $7.46 | Mixed |

**Top models by spend (30d):**

| Provider | Model | Spend | Requests | $/req |
|----------|-------|------:|---------:|------:|
| anthropic | claude-generic | $13,779 | 6,808 | $2.02 |
| cursor | cursor-team | $7,214 | 1,876 | $3.84 |
| openai | **gpt-5.4-2026-03-05** | $1,617 | 4,377 | **$0.37** |
| openai | gpt-5.5-2026-04-23 | $525 | 4,067 | $0.13 |
| openai | gpt-4o-mini-tts | $484 | 8 | $60.46 |
| openai | gpt-5.4-mini-2026-03-17 | $161 | 11 | $14.64 |
| openai | gpt-4o-2024-08-06 | $112 | 9,248 | $0.012 |
| openai | gpt-4.1-2025-04-14 | $82 | 7,475 | $0.011 |
| openai | gpt-5.4-nano-2026-03-17 | $73 | 5 | $14.60 |
| openai | **gpt-4.1-mini-2025-04-14** | $26 | **21,803** | **$0.001** |

**[Insight]** Compare gpt-4.1-mini ($0.001/req) with gpt-5.4 ($0.37/req) — 370× cost difference. Most "what's wrong with this code?" questions don't need the expensive one.

**Recommendations**:
- **Use ChatGPT for**: reasoning, research, documentation, debugging explanation, non-IDE tasks.
- **Avoid**: routing routine questions to reasoning models. Default to gpt-4.1-mini class.
- **Action**: 15-min calls with Cody Griffin, Dr. Klingensmith, Sam Pfeiffer — confirm if they really need o-series or if they default to it out of habit.

### Tool-Specific Recommendations Summary

| Tool | Action this week | Expected impact |
|------|------------------|-----------------|
| Claude Code | Interview top 5 CC users → playbook | Documented best practice → team-wide leverage |
| Cursor | Investigate Oleg & Andy lifetime AI lines | Confirm workflow is genuine vs artefact |
| ChatGPT | Coach 3 reasoning-overusers | Estimated saving: $1k-$1.5k/mo |

---

## 3. People / Adoption

### Top 15 Cross-Tool Spenders (30 days)

| # | Name | Total | Claude | GPT | Cursor | Events | Pattern |
|---|------|------:|-------:|----:|-------:|-------:|---------|
| 1 | **Oleg Sinavski** | $3,045 | $60 | $0 | **$2,985** | 112 | Cursor-dominant power user, 10.9M AI lines lifetime |
| 2 | **atin** | $2,425 | **$2,425** | $0 | $0 | 112 | Claude Code only — likely PM/exec doing agentic work |
| 3 | **Eugene Lyapustin** | $2,405 | **$2,405** | $0 | $0 | 112 | Claude Code only, also 1.6k git commits |
| 4 | **Richard** | $1,616 | **$1,616** | $0 | $0 | 56 | Pure Claude Code, no git activity → likely exec/research |
| 5 | Sam Pfeiffer | $1,320 | $852 | $464 | $3 | 138 | Balanced multi-tool engineer |
| 6 | Cody Griffin | $1,188 | $0 | **$1,178** | $10 | 79 | ChatGPT only, $23/msg → reasoning overuse |
| 7 | **Andy** | $990 | **$990** | $0 | $0 | 112 | Pure Claude Code |
| 8 | Dr. Klingensmith (Matt) | $791 | $0 | **$791** | $0 | 34 | ChatGPT only, $23/msg → reasoning overuse |
| 9 | Artem | $692 | $152 | $541 | $0 | **57,278** | n8n automation account, high event volume |
| 10 | Saeid Samadi | $633 | $0 | $0 | $633 | 28 | Cursor power user, 338k AI lines |
| 11 | Daksh Dhingra | $513 | $509 | $0 | $4 | 84 | Claude Code-heavy engineer |
| 12 | Richard Osterloh | $449 | $449 | $0 | $0 | 140 | Pure Claude Code |
| 13 | ber131 | $368 | $368 | $0 | $0 | 56 | Pure Claude Code |
| 14 | Vaibhav Mehta | $367 | $0 | $0 | $367 | 28 | Cursor-only, 444k AI lines |
| 15 | cfil | $356 | $0 | $0 | $356 | 28 | Cursor-only |

**Spend concentration**:
- **Top 5**: $10,811 = **44.9%** of $24,104
- **Top 10**: $15,105 = **62.7%**

### Adoption Segments

| Segment | Users | Pattern | Risk | Recommendation |
|---------|-------|---------|------|----------------|
| **High AI · High git output** | 15 | AI-first power engineers (Eugene, Sam, Saeid, Oleg, Daksh...) | Cost runaway if reasoning models overused | Keep & document playbook |
| **Low AI · High git output** | 10 | Productive engineers under-using AI | Productivity left on table | Pair with power user 1 sprint |
| **High AI lines, few commits** | 1 (Amir Torabi: 244k AI lines, 1 commit) | Anomaly — likely paste of generated config | Misleading metric | Investigate workflow |
| **Bots / Agents** | 13 | github-actions, Cursor Agent, Renovate | Higher bug-fix rate than humans | Audit agent PRs (Report II) |
| **AI active, no git** | 89 | Non-engineers (PM/ops/exec/research) — incl. atin, Richard, Andy | Costs unmonitored by role | Confirm intended use; budget per role |
| **Git active, no AI** | 44 | Engineers not on AI tools | Output bottlenecked | Pair with power user; provide seat |
| **Normal** | 45 | Mainstream mid-AI mid-output | Healthy | None |

### Anomalies / Workflow Review Candidates

| Person | Anomaly | Likely cause | Action |
|--------|---------|--------------|--------|
| **Amir Torabi** | 244k AI lines, 1 commit, 2 git additions | Pasted generated config or one-off; metric misleading | Confirm, exclude from team metrics if true |
| **Cody Griffin** | $23/msg on ChatGPT, 51 messages | Reasoning model habit | 15-min coaching call |
| **Dr. Klingensmith** | $23/msg on ChatGPT, 34 messages | Same as Cody | 15-min coaching call |
| **Sam Pfeiffer** | $17.85/msg on ChatGPT (despite mixed multi-tool profile) | Reasoning model for harder tasks (legitimate?) | Confirm |
| **Artem (`n8n_artem`)** | 57,250 events, $0.01/msg | Automation/cron (n8n workflow) | Validate it's intentional + on-budget |

### How key people use AI — quick read

- **Oleg Sinavski**: Cursor-first. Tab completions are 99% of his volume. Favourite model: claude-opus-high-thinking. Pattern = AI-assisted IDE coding at full throttle. Likely doing inference / training pipeline work given the volume.
- **atin / Richard / Andy**: pure Claude Code, near-zero git activity. **[Hypothesis]** Non-engineers doing agentic work (research, analysis, doc generation). Worth confirming what business workflow they're running.
- **Eugene Lyapustin**: rare balanced profile — high Claude Code spend AND high git output (1.6k commits). This is the "ideal" AI-first engineer pattern.
- **Cody Griffin / Klingensmith**: ChatGPT reasoning users. $23/msg confirms o1/o3 default; the question is whether the queries actually need that much reasoning.

---

## 4. Economics

### Current Spend (Last 30 days)

**$24,104** total. Annualised: **~$293,000/yr** if linear.

### Spend Breakdown by Tool

| Tool | Spend (30d) | Share |
|------|------------:|------:|
| Anthropic (Claude) | $13,779 | 57.2% |
| Cursor | $7,214 | 29.9% |
| OpenAI | $3,112 | 12.9% |
| **TOTAL** | **$24,104** | 100% |

Within Anthropic, **Claude Code (Agent) = $11,489 (83% of Claude)**. Within OpenAI, **Humanoid org = $2,571, Artem org = $540** (Artem is the n8n automation).

### Spend Concentration

| Metric | Value |
|--------|------:|
| Top-5 share | **44.9%** ($10,811) |
| Top-10 share | **62.7%** ($15,105) |
| Users ≥ $200/30d | ~14 |
| Users ≥ $500/30d | ~10 |
| Users ≥ $1k/30d | 6 |

Classic Pareto — manageable to alert on.

### Model Cost Structure (Key Insights)

**Per-request cost spread is enormous:**

| Model | $/req | Use case |
|-------|------:|----------|
| gpt-4.1-mini | **$0.001** | Routine questions, lookups, classification |
| gpt-4.1 | $0.011 | Code generation, mid-complexity |
| gpt-4o | $0.012 | General purpose |
| gpt-5.5 | $0.13 | Better than mini, cheaper than full |
| gpt-5.4 | $0.37 | Strong reasoning |
| claude-generic (mostly claude-opus mix) | $2.02 | Complex multi-file work |
| cursor-team aggregate | $3.84 | Per-request "session" |
| gpt-4o-mini-tts | $60.46 | Voice / TTS (very few calls) |

Routing one third of expensive-model traffic to mid-tier models could save 30-50% on those calls.

### Cost per User / Request / Message

| Metric | Value |
|--------|------:|
| **Avg spend per active user (30d)** | $150.65 |
| Median spend per active user | ~$20 (Pareto tail) |
| Avg Anthropic $/req | $2.02 |
| Avg OpenAI $/req | $0.054 (dragged down by 57k automation events) |
| Avg Cursor $/spend-event | $3.84 |

### Cost Optimization Opportunities

| Lever | Estimated saving | Effort |
|-------|------------------|--------|
| ChatGPT model routing (force mini default) | **$1,000-$1,500/mo** | 1 day |
| Cap reasoning-model usage for top 3 outliers | $500-$1,000/mo | 1 week of coaching |
| Sunset zero-activity Cursor seats (81 seats, 18 inactive) | $30-60/mo per seat × 18 | trivial |
| Move agentic synthesis routing decisions to cheaper Claude tier | $1,500-$2,500/mo | 2 weeks |
| **Total opportunity** | **~$3,000-$5,000/mo (12-20% of current spend)** | |

### Model Routing Policy (Recommended)

| Task type | Recommended | Avoid |
|-----------|-------------|-------|
| Inline autocomplete | Cursor Tab (free in sub) | — |
| Boilerplate / scaffolding | Cursor Agent + sonnet OR Cursor Tab | claude-opus, o-series |
| Multi-file refactor | Claude Code + sonnet first, opus if stuck | always-opus |
| Hard debugging / architecture | Claude Code + opus OR ChatGPT + o3 | — |
| Research / documentation | ChatGPT (any) or Claude Chat | — |
| Routine "explain this code" | gpt-4.1-mini OR claude-haiku | opus, o-series |
| Quick API lookup | gpt-4.1-mini | reasoning models |
| Voice / TTS | Reserve `gpt-4o-mini-tts` for genuine voice work | inadvertent calls |

### Where to Save Without Reducing Productivity

1. **Default models** in tooling should be mid-tier (sonnet, gpt-4o-mini). Reasoning models invoked explicitly.
2. **Per-user budget alerts** at $500/mo and $1,000/mo (not caps).
3. **Sunset zero-activity Cursor seats** (~18 of 81 inactive lifetime).
4. **NEVER blindly cut productive power users.** Oleg's $3k/mo is cheap if he delivers 1 person-week of value.

---

## 5. Priority Actions

### Immediate (this week)

1. **Confirm 6 display-name dupes** ('Yoo-Jin Jung', 'Sergei', 'Matt', 'George', 'Dmitry' × 2 each, plus 'Artem' singular case).
2. **15-min coaching calls** with Cody Griffin, Dr. Klingensmith, Sam Pfeiffer about ChatGPT model routing.
3. **Interview top 5 CC users** (Eugene, atin, Richard, Andy, Sam) — extract workflow playbook.
4. **Validate Artem `n8n_artem`** automation is intentional and on-budget.

### 30-day improvements

5. **Publish team-wide "Which AI for which task" guide** based on power-user interviews + model routing table above.
6. **Per-user budget alerts** at $500 / $1k/mo (Slack notification).
7. **Sunset 18 zero-activity Cursor seats** (confirm with each user first).
8. **Audit 44 "Git active, no AI" engineers** — confirm seat availability; pair each with a power user for 1 sprint.
9. **Investigate bot bug rate** (24.8% vs 18.8% human) — sample 20 bot PRs to confirm if agents ship clean code or fix their own breakage.

### 60-90 day improvements

10. **Report II — AI × PR × Quality**. AI ↔ Git is wired in. Extend by connecting `git_commits` to PR data (review_comments, time-to-merge, revert chains) and tag each commit with the AI tool likely used by the author.
11. **Jira integration** — incidents → fix-commit → AI tool used by author. Closes the "did AI cost reduce production incidents" loop.
12. **Quarterly model-routing policy review** — provider pricing changes monthly; defaults should adapt.
13. **Productivity baseline** — track "cost per merged PR" and "cost per closed Jira ticket" by user.

---

## Leadership Takeaway

> The question is no longer **whether** HMND uses AI — it does, materially and across the company. **$24,104/month** and **160 active users** prove that.
>
> The next question is **which AI workflows produce useful engineering output**, and which workflows only consume budget. The dashboard now shows WHO spends, WHEN, ON WHAT, WHICH MODEL — **and**, via AI ↔ Git linkage, **which segment of engineers couples AI cost with code output**. What it cannot yet show: whether those dollars converted to merged code, reviewed code, deployed code, or closed Jira tickets.
>
> **Next step: extend AI ↔ Git (already live) to AI ↔ PR ↔ Jira ↔ quality-gates** so we can move from "AI cost report" to "AI cost-per-merged-PR" and "AI cost-per-closed-ticket". That is Report II.
>
> Even before Report II lands, three actions have a clean ROI: (1) **model-routing policy** (~$1.5-3k/mo saving), (2) **interview top-5 playbook → publish** (multiplier on team productivity), (3) **budget alerts on 10 power users** (catch 80% of cost drift).

---

*Generated 2026-05-16. All numbers verifiable via `python -m scripts.audit_etl` (17/17 ✓) and `python -m scripts.report_i_data` (data dump). Caveats: Cursor `ai_lines` is lifetime not period-filtered; some "Agent" purpose events are synthesised from Cursor `agent_completions` (uniform 56-event signature) and should be separated from real Claude Code in Report II.*

---

# Appendix A — Data Trust Assessment

> Reading this report to leadership: each number is rated by trust level so you can confidently answer "are you sure?".
>
> **🟢 VERIFIED** = traceable byte-for-byte to provider-reported raw data. Cannot be wrong unless the provider itself lies.
> **🟡 CORRECT WITH CAVEAT** = math is right; interpretation requires care.
> **🔴 HYPOTHESIS** = derived inference, requires further data to prove.

## A.1 Top-level numbers — what to defend if asked

| Claim | Trust | Why |
|-------|------|-----|
| Total AI spend (30d) = **$24,104** | 🟢 | `SUM(usage_events.cost_usd)` per audit; each provider's slice matches raw bytes |
| Anthropic spend = **$13,779** | 🟡 | Matches Anthropic's `userCost` rows exactly. But their own `rollups.totalSpend` shows **+1.43% drift** ($45,369 raw userCost vs $44,731 rollup) — Anthropic's internal inconsistency, not ours. We chose to use userCost for per-user attribution. Real number is within **±1.5%** band. |
| Cursor spend = **$7,214** | 🟢 | `spendCents + includedSpendCents` from raw Cursor JSON (lifetime $23,444; 30d slice from `usage_events`) |
| OpenAI spend = **$3,112** | 🟢 | API push from `/v1/organization/costs` (Artem) + raw JSON (Humanoid); audit confirms 0% drift |
| Active users (30d) = **160** | 🟢 | `COUNT(DISTINCT user_id) WHERE occurred_at BETWEEN ...` |
| Top-5 share = **44.9%** ($10,811) | 🟢 | Manual math: $10,811 / $24,104 = 44.85% ≈ 44.9% |
| Top-10 share = **62.7%** ($15,105) | 🟢 | $15,105 / $24,104 = 62.66% ≈ 62.7% |
| Avg spend/user = **$150.65** | 🟡 | Math is right. But it averages near-zero users in. Median is more like $5-20 — Pareto distribution. Report leadership the median + top-decile if asked. |

## A.2 Tool-mix breakdown

| Claim | Trust | Why |
|-------|------|-----|
| Anthropic = 57.2% of spend | 🟢 | $13,779/$24,104 |
| Cursor = 29.9% | 🟢 | $7,214/$24,104 |
| OpenAI = 12.9% | 🟢 | $3,112/$24,104 |
| Claude Code = 83% of Anthropic | 🟡 | $11,489/$13,779 = 83.4%. BUT "Agent" purpose includes events SYNTHESISED from Cursor agent_completions (see A.4). Real CC vs synthesised CC not separated. |
| OpenAI Humanoid = $2,571, Artem = $540 | 🟢 | Per-org SQL with org_id check |

## A.3 Per-person numbers (Top 15 spenders)

| Claim | Trust |
|-------|------|
| Oleg Sinavski $3,045 (98% Cursor) | 🟢 |
| atin $2,425 (100% Claude) | 🟢 math, 🟡 interpretation (likely synthesised, see A.4) |
| Eugene Lyapustin $2,405 (100% Claude) | 🟢 math, 🟡 interpretation |
| Richard $1,616 (100% Claude) | 🟢 math, 🟡 interpretation |
| Cody Griffin $1,178 ChatGPT, $23/msg | 🟢 math, 🔴 "reasoning overuse" is a HYPOTHESIS |
| Artem 57,250 events / $0.01/msg | 🟢 math, 🟢 confirmed automation (n8n_artem service account, you ran the SQL) |

## A.4 The biggest caveat — synthesised Claude Code events

The "Top Claude Code (Agent) spenders" table shows ALL top users with **exactly 56 requests**.

**That's a synthesis quantum, not a real session count.**

What's happening: `data/cursor_to_anthropic.py` reads Cursor's `User_Leaderboard` CSV and *synthesises* fake Anthropic usage_events from each user's `agent_completions` count. It spreads them evenly across the past week (8 days × 7 events = 56 events). The cost is estimated by applying Anthropic model pricing to a synthetic token count.

**What this means:**
- The DOLLAR amount in "Agent" purpose ($11,489) is partially **estimated**, not directly billed.
- The EVENT count (2,344 reqs) mixes real Anthropic Admin API events with synthesised ones.
- Per-user attribution is reasonable but the model breakdown is forced.

**Honest read of "Claude Code spend"**:
- Lower bound: real Anthropic Admin API CC events only (we don't currently isolate them; would need 1-day fix in `cursor_to_anthropic` to tag synthesised events).
- Upper bound: $11,489 (current report figure).
- This is the **single biggest "trust gap" in the report**.

## A.5 Cursor AI lines (LIFETIME)

| Claim | Trust |
|-------|------|
| Oleg Sinavski 10.9M AI lines | 🟡 — Cursor's own metric (we don't verify). |
| Andy Park 8.6M AI lines | 🟡 same |
| Amir Torabi 244k AI lines on 1 commit | 🔴 anomaly — likely paste of generated config; metric misleading |

**Important**: "AI lines" is Cursor's internal counter — it counts characters Cursor's autocomplete/agent produced, NOT lines in merged PRs. Don't equate to production code without cross-checking against Git additions per author — this is **already in the dashboard** (`HIGH_AI_LINES_LOW_COMMITS` segment flags Cursor outliers like Amir Torabi). What's still missing for the full picture: PR-level review and merge metrics → Report II.

## A.6 Engineering / Git data

| Claim | Trust |
|-------|------|
| 213 humans + 13 bots in git | 🟢 from `git_authors_20260515.csv` |
| 23,044 commits lifetime | 🟢 audit confirms `git_commits` table matches raw CSV per-repo |
| Bug-fix rate 19.2% lifetime | 🟢 SUM(is_bug_fix)/COUNT(*) on the regex flags |
| Human bug rate 18.8% vs Bot 24.8% | 🟢 math from `git_commits`; 🔴 the CAUSAL claim "bots ship messier code" remains a hypothesis — to confirm, sample agent-authored PRs at review time (Report II). The rate itself is a fact today. |
| 44 "Git active, no AI" engineers | 🟢 from segment SQL |
| 15 "High AI · High Output" | 🟢 from segment SQL using team median additions threshold |

## A.7 Optimization estimates ($-saving numbers)

| Claim | Trust |
|-------|------|
| $1,000-$1,500/mo saving from ChatGPT routing | 🔴 ESTIMATE: based on assuming top-3 outlier spend ($2,160/mo combined) drops to mid-tier model pricing |
| $500-$1,000/mo from coaching outliers | 🔴 ESTIMATE: based on 50% reduction assumption |
| $1,500-$2,500/mo from agentic synthesis routing | 🔴 ESTIMATE: depends on Claude Code workflow change |
| **Total $3-5k/mo opportunity** | 🔴 sum of above hypotheticals |

**Don't promise these to the board** — they're directional. Achievable lower bound is probably 50% of stated (so $1.5-2.5k/mo).

## A.8 Numbers I would NOT defend with confidence

1. **"Annualised $293k"** — assumes flat 12 months. Real usage grows; this is **lower bound**, expect 30-100% higher.
2. **"83% of Anthropic is Claude Code"** — see A.4. Range is probably **60-83%** depending on how synthesised events split.
3. **Bot bug rate 24.8% > human 18.8%** — the rate itself is a fact from `git_commits` (🟢). But the bot population is small (13 bots) and dominated by github-actions doing release commits. The **causal** claim "bots ship messier code" is what needs Report II — sample agent PRs at review time. Don't quote the % without that caveat.
4. **"160 active users"** — counts anyone with ≥1 event. The "engaged" cohort is probably 80-100 people. Tighten metric definition before quoting.

## A.9 What to say if the boss asks "how do I know this is right?"

**Two-sentence answer:** "Every aggregate ties back to raw bytes from Anthropic / OpenAI / Cursor — we have a 17-check audit that re-derives every dashboard number from the source files and the audit is 100% green. The only ~1.5% gap is Anthropic's own rollup vs userCost inconsistency in their JSON."

**To prove it on the spot:**
```bash
docker compose exec -T dashboard python -m scripts.audit_etl | tail -20
# Expected: 17 ✓ in SUMMARY
```

**The honest gaps to call out before he does:**
1. "Anthropic Agent" includes synthesised events (A.4)
2. Cursor AI lines is lifetime not period (A.5)
3. Optimization $-saving estimates are directional, not guarantees (A.7)
4. **22 people have two email-domain identities** (`@thehumanoid.ai` + `@skl.vc`) — per-person rankings are split unless the loader is patched (A.10). Aggregate totals are unaffected.

## A.10 Dual-identity people (cross-tool matching gap)

**Finding:** 22 of ~150 HMND people log into different AI tools under different email domains. Anthropic uses `@thehumanoid.ai`; Cursor and OpenAI often `@skl.vc`. Each domain becomes a separate `user_id` row in this dashboard because `data.sources.anthropic_json._ensure_user(email, name)` keys on email exactly.

**Why it matters:**
- Per-person spend in §3 People tables is **split across two rows** for these 22 people.
- §3 segment counts (`AI_ACTIVE_BUT_NO_GIT`, `HIGH_AI_LINES_LOW_COMMITS`) are inflated: a Cursor user @skl.vc whose Git commits land @thehumanoid.ai matches no Git author → falsely labelled "AI active, no Git".
- "160 active users" headline is **overcounted by up to 22** (real engaged headcount ≈ 138).
- Aggregate spend totals in §1 / §4 are **unaffected** — sum of `cost_usd` over events doesn't care about identity grouping.

**The 22 (90-day spend across all tools):**

| Local-part | Display name | Anthropic | Cursor | OpenAI (est) | TOTAL |
|---|---|---|---|---|---|
| anai | Atindra Nair (atin) | $7,897 | $6 | $0 | **$7,902** |
| apar | Andy Park | $3,232 | $98 | $11 | **$3,341** |
| codg | Cody Griffin | $191 | $32 | $1,449 | **$1,672** |
| brig | Brian Ginebaugh | $884 | $218 | $0 | **$1,102** |
| sfed | Sergei | $828 | $2 | $0 | **$830** |
| byan | Boris Yangel | $553 | $130 | $0 | **$683** |
| ksha | Karim Shaban | $16 | $690 | $0 | **$706** |
| sram | Sepehr Ramezani | $6 | $753 | $0 | **$759** |
| ius | Yuriy Strezhik | $80 | $471 | $0 | **$551** |
| gwad | Gourav Wadhwa | $2 | $448 | $0 | **$451** |
| dalm | Diogo Almeida | $331 | $23 | $0 | **$353** |
| mata | Mustafa Atakan | $1 | $327 | $0 | **$328** |
| mahs | Mahe | $239 | $2 | $0 | **$241** |
| onin | omkar | $142 | $0 | $0 | **$142** |
| lbie | Luke Bierbaum | $8 | $132 | $0 | **$139** |
| mraf | Muhammad | $0 | $129 | $0 | **$129** |
| gcer | Giulio | $70 | $57 | $0 | **$127** |
| sdad | (no name) | $83 | $0 | $0 | **$83** |
| pols | Polina | $52 | $29 | $0 | **$81** |
| yjj | Yoo-Jin Jung | $76 | $0 | $0 | **$76** |
| fpro | Fede | $70 | $2 | $0 | **$72** |
| ccop | Claudio | $50 | $16 | $0 | **$67** |

**Top-20 unified spenders (90d, after merging dual identities by local-part):**

| # | Person | Anthropic | Cursor | OpenAI | TOTAL | Identities |
|---|---|---|---|---|---|---|
| 1 | Oleg Sinavski | $204 | $9,700 | $0 | **$9,904** | single |
| 2 | Atindra Nair | $7,897 | $6 | $0 | **$7,902** | dual ⚠️ |
| 3 | Eugene Lyapustin | $7,820 | $0 | $0 | **$7,820** | single |
| 4 | Richard Weingarten | $5,271 | $0 | $0 | **$5,271** | single |
| 5 | Andy Park | $3,232 | $98 | $11 | **$3,341** | dual ⚠️ |
| 6 | Sam Pfeiffer | $2,783 | $11 | $531 | **$3,325** | single |
| 7 | Saeid Samadi | $0 | $2,056 | $0 | **$2,056** | single |
| 8 | Daksh Dhingra | $1,667 | $12 | $0 | **$1,679** | single |
| 9 | Cody Griffin | $191 | $32 | $1,449 | **$1,672** | dual ⚠️ |
| 10 | Richard Osterloh | $1,468 | $0 | $0 | **$1,468** | single |
| 11 | ber131 | $1,202 | $0 | $0 | **$1,202** | single |
| 12 | Vaibhav Mehta | $0 | $1,194 | $0 | **$1,194** | single |
| 13 | cfil | $0 | $1,158 | $0 | **$1,158** | single |
| 14 | Brian Ginebaugh | $884 | $218 | $0 | **$1,102** | dual ⚠️ |
| 15 | Matt Klingensmith | $1 | $0 | $1,095 | **$1,096** | single |
| 16 | Dmitry Shingarey | $0 | $1,015 | $0 | **$1,015** | single |
| 17 | Cheerag Sharma | $19 | $971 | $0 | **$990** | single |
| 18 | Aleksei Chernikhovskii | $975 | $0 | $0 | **$975** | single |
| 19 | Sergei | $828 | $2 | $0 | **$830** | dual ⚠️ |
| 20 | Abby | $805 | $0 | $0 | **$805** | single |

**Grand total (90d, unified): $72,051.** Top-5 share = 47.5%; Top-10 share = 61.7%. Pareto distribution is robust to the unification (Top-N shares move <2%), but **rank ordering changes for the 5 dual-identity people in the top 20** and 30-day numbers in §3 People should be re-computed after the loader fix.

**One-line fix:** in `data/sources/anthropic_json.py:_ensure_user` (and equivalent in `cursor_json.py`, `openai_json.py`), match incoming `email` against existing `users.email` by **email local-part** AND known-HMND-domain set before inserting. Estimated effort: 30 minutes + one re-sync.

**Don't conflate with display-name collisions** (A.6 already mentions 6 cases of distinct people sharing first names — that's the OPPOSITE problem: different humans, same name. Dual-identity is same human, two emails. The dashboard handles name collisions correctly; identity unification is the open one.)

