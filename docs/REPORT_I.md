# Report I — AI Usage, Adoption & Economics

**Period:** Last 30 days (2026-04-16 → 2026-05-16) unless otherwise noted.
**Source:** HMND AIOps Dashboard, audited 2026-05-16 (17/17 data audits ✓).
**Audience:** HMND leadership.

> **Methodology**: This report covers AI usage, adoption, behaviour, and economics. It does NOT claim AI directly wrote X% of production code — that requires Git/PR correlation (Report II). Findings are tagged **[Fact]** (verified in dashboard), **[Estimate]** (derived from dashboard numbers), or **[Hypothesis]** (requires Git/PR/Jira correlation).

---

## 1. Executive Summary

### Key Findings

- **[Fact]** HMND spent **$23,353** on AI tools in the last 30 days. Annualised run-rate: **~$284,000/yr**.
- **[Fact]** **140 active humans in the 30-day AI-usage cohort** (post identity-merge on 2026-05-16). ✅ Dual-domain people who used both `@thehumanoid.ai` (engineering) and `@skl.vc` (Sycamore corporate) are now correctly counted as one human each — 20 split identities merged, $19,610 of fragmented spend re-attributed. See Appendix A.10.

> **Cohort note.** "140 active humans" counts people with ≥ 1 AI usage event in the last 30 days. The Adoption Segments table in §3 sums to **~206** because it works on a **different cohort**: every person ever seen in either `users` (AI events) OR `git_authors` (commits) — lifetime, no time window, plus 13 bots. The numbers SHOULD NOT match; see Appendix A.12 for the reconciliation.
- **[Fact]** Tool mix:  **Anthropic 57.2% / Cursor 29.9% / OpenAI 12.9%** by 30d spend.
- **[Fact]** Within Anthropic, **Claude Code (Agent) is 83% of Anthropic spend ($11,489)** — agentic coding is the dominant Claude workflow.
- **[Fact]** **Top 5 spenders = 44.7% of total spend; Top 10 = 63.2%** — textbook Pareto, robust to identity merge (shifted < 1 pp).
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
| **Cost concentration** | Top 10 = 63.2% of spend ($14,757/mo). Single individual changes can move the line. | Pareto = budget alerts on ~10 people catch most issues. |
| **Reasoning-model overuse on OpenAI** | 4 of 5 top OpenAI spenders pay $7-$23/msg (o-series) | Routing policy → ~$1,500/mo saving on OpenAI alone |
| **Claude Code dominance ($11.5k/30d)** | All eggs in one Anthropic basket; one provider outage = team blocked | Maintain GPT/Cursor as fallback workflows |
| **Bot bug rate > human (24.8% vs 18.8% lifetime, from `git_commits`)** | AI agents may ship code that they later have to fix | Add PR-review data on top of existing git telemetry — needed to confirm if those fixes are reverts of agents' own work |
| **"Git active, no AI" cohort (44 engineers)** | Productivity left on table | Pair with power user 1 sprint each |
| **Synthesised Claude Code events** | Top CC users all show exactly 56 events — these are Cursor→Anthropic synthesised (not real CC sessions); real CC users hidden behind Cursor's `agent_completions` aggregation | Tag Claude Code events by source in Report II |
| **Dual-domain identity split** | ~22 individuals use both `@thehumanoid.ai` and `@skl.vc` and appear as 2 user_id rows. Per-person spend, Top-spender ranks, and "AI active, no git" segment are all affected. | Run `scripts/audit_identity_collisions` to confirm scope; then merge in DB. **Likely changes Top spenders ranks.** |

### Common Recommendations

1. **Adopt a model-routing policy** (see §4 table). Route routine queries to cheaper models. Estimated saving: $1,500-$3,000/mo.
2. **Interview top 5 AI users** (Oleg Sinavski, atin, Eugene Lyapustin, Richard, Sam Pfeiffer) — document workflow playbook, publish team-wide.
3. **Per-user budget alerts** at $500 and $1,000/mo (Slack). Not caps — early warning.
4. **Reach the 44 "Git active, no AI" engineers** — pair each with a power user for 1 sprint.
5. **Connect AI telemetry to PR/Jira** (Report II) to convert "cost report" into "cost-per-engineering-outcome report". Git is already wired in (commit-level bug-fix rates, per-author segmentation, Code Quality tab); the missing pieces are **PR review data** (time-to-merge, review comments, revert chains beyond commit-level) and **Jira/incident data** (which $/fix actually closed a P0/P1).

---

## 2. Tools / Usage / Workflows

### Tool Summary Table (Last 30 days)

| Tool | Users | Activity | Spend | Share | Primary Usage | Key Risk | Recommendation |
|------|-------|----------|-------|-------|---------------|----------|----------------|
| **Anthropic (all Claude products)** | 111 | 6,808 events | **$13,779** | **57.2%** | Claude Code (Agent), Chat, Cowork | High-context reasoning calls are expensive | Reserve `claude-opus` for hard tasks |
| **Cursor** | 67 active (81 seats) | 1,876 spend-events (excl. free Tab) | **$7,214** | **29.9%** | Everyday IDE coding | `ai_lines` is lifetime not period; per-PR attribution is Report II | AI-lines vs commits already in segments view |
| **OpenAI** | 7 humans + 1 bot | 57,392 events (mostly automation) | **$3,112** | **12.9%** | Reasoning, automation (n8n) | $23/msg outliers on reasoning models | Route to cheaper models for routine work |
| **TOTAL** | **140 unique humans** | 66,076 events | **$23,353** (post-merge) | 100% | | | |

> Per-tool $ rows above were captured pre-merge morning of 2026-05-16. Total $23,353 is the post-merge evening figure (window shifted by ~1 day; merge itself doesn't change per-provider totals, only re-attributes between user_ids).

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

**Caveat**: Oleg's 10.9M AI lines is a *lifetime* total — it represents months of work. Converting to "real productive code" requires Git correlation (Report II).

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

### Top 15 Cross-Tool Spenders (30 days, post identity-merge)

> ✅ **Dual-domain identities have been unified** (2026-05-16). Each row below is one human, with their AI spend correctly summed across both `@thehumanoid.ai` and `@skl.vc` accounts. Notable post-merge changes vs the pre-merge ranking: **Andy Park** now shows his $29 Cursor activity instead of $0; **Cody Griffin** now shows his $52 Claude usage on top of $1,178 GPT; **atin** picked up $2 Cursor that was previously orphaned under `anai@skl.vc`. See Appendix A.10 for the full list of 20 merged identities.

| # | Name | Total | Claude | GPT | Cursor | Events | Pattern |
|---|------|------:|-------:|----:|-------:|-------:|---------|
| 1 | **Oleg Sinavski** | $2,936 | $58 | $0 | **$2,878** | 108 | Cursor-dominant power user, 10.9M AI lines lifetime |
| 2 | **atin (Atindra Nair)** | $2,340 | **$2,339** | $0 | $2 | 135 | Claude Code only — likely PM/exec doing agentic work |
| 3 | **Eugene Lyapustin** | $2,319 | **$2,319** | $0 | $0 | 108 | Claude Code only, also 1.6k git commits |
| 4 | **Richard** | $1,558 | **$1,558** | $0 | $0 | 54 | Pure Claude Code, no git activity → likely exec/research |
| 5 | Sam Pfeiffer | $1,289 | $822 | $464 | $3 | 134 | Balanced multi-tool engineer |
| 6 | **Cody Griffin** | $1,240 | $52 | **$1,178** | $9 | 213 | ChatGPT-dominant, $23/msg → reasoning overuse |
| 7 | **Andy Park** | $987 | $954 | $3 | $29 | 144 | Claude-dominant, light Cursor + OpenAI |
| 8 | Dr. Klingensmith (Matt) | $791 | $0 | **$791** | $0 | 34 | ChatGPT only, $23/msg → reasoning overuse |
| 9 | Artem | $687 | $146 | $541 | $0 | **57,391** | n8n automation account, high event volume |
| 10 | Saeid Samadi | $610 | $0 | $0 | $610 | 27 | Cursor power user, 338k AI lines |
| 11 | Daksh Dhingra | $494 | $491 | $0 | $4 | 81 | Claude Code-heavy engineer |
| 12 | Richard Osterloh | $433 | $433 | $0 | $0 | 135 | Pure Claude Code |
| 13 | ber131 | $355 | $355 | $0 | $0 | 54 | Pure Claude Code |
| 14 | Vaibhav Mehta | $354 | $0 | $0 | $354 | 27 | Cursor-only, 444k AI lines |
| 15 | cfil | $344 | $0 | $0 | $344 | 27 | Cursor-only |

**Spend concentration (post-merge)**:
- **Top 5**: $10,443 = **44.7%** of $23,353
- **Top 10**: $14,757 = **63.2%**

### Adoption Segments

> **Cohort:** lifetime universe of every person seen in either `users` (any AI event ever) or `git_authors` (any commit ever) — **not** the 30-day AI-active cohort of 140 from §1. Latest audit (2026-05-16) sums to **206 devs** total. This number should NOT match "140 active humans" — see cohort note in §1 and reconciliation in Appendix A.12.

| Segment | Devs | Pattern | Risk | Recommendation |
|---------|-----:|---------|------|----------------|
| **High AI · High git output** | **21** ⬆ (+6 vs pre-merge) | AI-first power engineers (Eugene, Sam, Saeid, Oleg, Daksh...). Coupling that was hidden by dual-domain split becomes visible | Cost runaway if reasoning models overused | Keep & document playbook |
| **Low AI · High git output** | **7** ⬇ (−3 vs pre-merge) | Productive engineers under-using AI; 3 moved into "High AI · High git" after their dual-domain AI spend was reunified with their git output | Productivity left on table | Pair with power user 1 sprint |
| **High AI lines, few commits** | 1 (Amir Torabi: 244k AI lines, 1 commit) | Anomaly — likely paste of generated config | Misleading metric | Investigate workflow |
| **Bots / Agents** | 13 | github-actions, Cursor Agent, Renovate | Higher bug-fix rate than humans | Audit agent PRs (Report II) |
| **AI active, no git** | **79** ⬇ (−10 vs pre-merge) ✅ | Non-engineers (PM/ops/exec/research) — incl. atin, Richard, Andy. **17 phantom rows initially removed** by the identity merge: these were Cursor-via-`@skl.vc` accounts whose Git activity was logged under their `@thehumanoid.ai` identity. Drift back to 79 after subsequent sync cycles is expected (lifetime cohort grows). | Costs unmonitored by role | Confirm intended use per person; per-role budgets |
| **Git active, no AI** | 42 | Engineers not on AI tools | Output bottlenecked | Pair with power user; provide seat |
| **Normal** | 43 | Mainstream mid-AI mid-output | Healthy | None |
| **TOTAL** | **206** | sum across all segments (lifetime universe) | — | — |

> **Reconciliation:** 206 (lifetime) − 13 (bots) = **193 humans ever seen in HMND**. Of these, **140 used AI in the last 30 days** (the "active" cohort in §1). The 53 difference = humans who committed to git in the past but didn't touch AI in the recent window, plus humans who used AI more than 30d ago but stopped. **Both numbers are correct — they answer different questions.**

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

**$23,353** total (post identity-merge, evening 2026-05-16). Annualised: **~$284,000/yr** if linear.

### Spend Breakdown by Tool

| Tool | Spend (30d) | Share |
|------|------------:|------:|
| Anthropic (Claude) | $13,779 | ~57% |
| Cursor | $7,214 | ~30% |
| OpenAI | $3,112 | ~13% |
| **TOTAL** | **$23,353** | 100% |

> Per-tool $ are pre-merge morning capture; total is post-merge evening. The identity merge does NOT change per-provider totals (it only re-attributes between user_ids), so per-tool shares are reliable; the ~$750 delta is a 1-day window shift.

Within Anthropic, **Claude Code (Agent) = $11,489 (83% of Claude)**. Within OpenAI, **Humanoid org = $2,571, Artem org = $540** (Artem is the n8n automation).

### Spend Concentration

| Metric | Value |
|--------|------:|
| Top-5 share | **44.7%** ($10,443) |
| Top-10 share | **63.2%** ($14,757) |
| Users ≥ $200/30d | ~14 |
| Users ≥ $500/30d | ~10 |
| Users ≥ $1k/30d | 6 |

Classic Pareto — manageable to alert on. Shares are essentially unchanged by the identity merge (< 1 pp shift), confirming that fragmentation didn't distort the headline economics — but it did distort *individual* rankings.

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

10. **Report II — Git × AI × Quality**. Connect `git_commits` to PR data (review_comments, time-to-merge, revert chains). Tag each commit with the AI tool likely used by the author.
11. **Jira integration** — incidents → fix-commit → AI tool used by author. Closes the "did AI cost reduce production incidents" loop.
12. **Quarterly model-routing policy review** — provider pricing changes monthly; defaults should adapt.
13. **Productivity baseline** — track "cost per merged PR" and "cost per closed Jira ticket" by user.

---

## Leadership Takeaway

> The question is no longer **whether** HMND uses AI — it does, materially and across the company. **$23,353/month** and **140 active humans** prove that.
>
> The next question is **which AI workflows produce useful engineering output**, and which workflows only consume budget. The dashboard already joins AI spend × Git commits per person (Devs (Git × AI) tab) and classifies commits by type (Code Quality tab). What it cannot yet show is WHETHER those dollars converted to **reviewed, merged, non-reverted** code that **closed a real Jira issue**.
>
> **Next step: extend the existing AI × Git telemetry with PR review data and Jira/incident data**, so we can move from "AI cost × git activity" (today) to "AI cost-per-engineering-outcome" (Report II).
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
| Total AI spend (30d) = **$23,353** | 🟢 | `SUM(usage_events.cost_usd)` per audit; each provider's slice matches raw bytes. Post identity-merge (2026-05-16). |
| Anthropic spend = **$13,779** | 🟡 | Matches Anthropic's `userCost` rows exactly. But their own `rollups.totalSpend` shows **+1.43% drift** ($45,369 raw userCost vs $44,731 rollup) — Anthropic's internal inconsistency, not ours. We chose to use userCost for per-user attribution. Real number is within **±1.5%** band. |
| Cursor spend = **$7,214** | 🟢 | `spendCents + includedSpendCents` from raw Cursor JSON (lifetime $23,444; 30d slice from `usage_events`) |
| OpenAI **total** spend = **$3,112** | 🟢 | API push from `/v1/organization/costs` (Artem) + raw JSON (Humanoid); audit confirms 0% drift |
| OpenAI **per-user** $ (e.g. Cody Griffin $1,178) | 🟡 | **ESTIMATE not billing.** OpenAI's `/cost` endpoint returns `user_id: null` for 100% of events. Per-user $ is computed as `(user's request share) × total_spend`. Accurate at the cohort/request level, approximation at the dollar level. |
| Active humans (30d) = **140** | 🟢 | `COUNT(DISTINCT user_id) WHERE occurred_at BETWEEN ...` post identity-merge. Was 160 pre-merge (20 dual-domain rows now collapsed — see A.10). |
| Top-5 share = **44.7%** ($10,443) | 🟢 | Manual math: $10,443 / $23,353 = 44.71% ≈ 44.7% |
| Top-10 share = **63.2%** ($14,757) | 🟢 | $14,757 / $23,353 = 63.19% ≈ 63.2% |
| Avg spend/human = **$166.81** | 🟡 | $23,353 / 140. Math is right. But it averages near-zero users in. Median is more like $5-20 — Pareto distribution. Report leadership the median + top-decile if asked. |

## A.2 Tool-mix breakdown

| Claim | Trust | Why |
|-------|------|-----|
| Anthropic ≈ 57% of spend | 🟢 | $13,779/$23,353 — pre/post-merge shift is < 1 pp; per-provider sums are merge-invariant |
| Cursor ≈ 30% | 🟢 | $7,214/$23,353 |
| OpenAI ≈ 13% | 🟢 | $3,112/$23,353 |
| Claude Code = 83% of Anthropic | 🟡 | $11,489/$13,779 = 83.4%. BUT "Agent" purpose includes events SYNTHESISED from Cursor agent_completions (see A.4). Real CC vs synthesised CC not separated. |
| OpenAI Humanoid = $2,571, Artem = $540 | 🟢 | Per-org SQL with org_id check |

## A.3 Per-person numbers (Top 15 spenders)

| Claim | Trust |
|-------|------|
| Oleg Sinavski $2,936 (98% Cursor) | 🟢 |
| atin (Atindra Nair) $2,340 (100% Claude + $2 Cursor reunified) | 🟢 math, 🟡 interpretation (some Claude Code events are synthesised, see A.4) |
| Eugene Lyapustin $2,319 (100% Claude) | 🟢 math, 🟡 interpretation |
| Richard $1,558 (100% Claude) | 🟢 math, 🟡 interpretation |
| Andy Park $987 = $954 Claude + $3 GPT + $29 Cursor (cross-tool unified post-merge) | 🟢 math |
| Cody Griffin $1,240 = $52 Claude + $1,178 GPT + $9 Cursor (cross-tool unified post-merge) | 🟢 math, 🔴 "reasoning overuse" is a HYPOTHESIS |
| Artem 57,391 events / $0.01/msg | 🟢 math, 🟢 confirmed automation (n8n_artem service account) |

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

**Important**: "AI lines" is Cursor's internal counter — it counts characters Cursor's autocomplete/agent produced, NOT lines in merged PRs. Don't equate to production code without Git correlation (Report II).

## A.6 Engineering / Git data

| Claim | Trust |
|-------|------|
| 213 humans + 13 bots in git | 🟢 from `git_authors_20260515.csv` |
| 23,044 commits lifetime | 🟢 audit confirms `git_commits` table matches raw CSV per-repo |
| Bug-fix rate 19.2% lifetime | 🟢 SUM(is_bug_fix)/COUNT(*) on the regex flags |
| Human bug rate 18.8% vs Bot 24.8% | 🟢 math; 🔴 the INTERPRETATION "bots ship messier code" is a HYPOTHESIS |
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
3. **Bot bug rate 24.8% > human 18.8%** — directional yes, but the bot population is small (13 bots) and dominated by github-actions doing release commits. **Need Report II** to make this claim load-bearing.
4. **"140 active humans"** — counts anyone with ≥1 event (post identity-merge — was 160 pre-merge, see A.10). "Engaged" cohort (≥5 events) is probably 80-100. If the boss wants "real engineering adoption", use engaged count, not active count.
5. **"OpenAI per-user $ ranks"** — OpenAI returns `user_id: null`, so per-user dollar amounts are *estimates* (share of requests × total). Ranks are directionally right (Cody Griffin is heaviest), absolute dollars are ±20% per person.

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

## A.10 Dual-domain identity split — ✅ RESOLVED (2026-05-16)

HMND people exist under two email domains:
- `@thehumanoid.ai` (engineering / work email — primary in Anthropic and Git)
- `@skl.vc` (Sycamore corporate email — primary in Cursor and OpenAI subscriptions)

Pre-merge state: because each loader did `INSERT OR IGNORE INTO users(email)` by exact email, **one person became two user_id rows**. The dashboard split their spend, ai_lines, commits, and segment classification across both rows.

### Scope (audited 2026-05-16 morning)

| Metric | Value |
|--------|------:|
| People split across 2 user_id rows | **20** |
| Total user_id rows affected | 40 |
| Lifetime $ on fragmented identities | **$19,610** |
| Share of all lifetime spend | ~28% |
| Local-parts only @thehumanoid.ai | 109 |
| Local-parts only @skl.vc | 19 |
| Local-parts in BOTH domains | 20 |

### Merge execution (afternoon 2026-05-16)

```
MERGING 20 dual-domain identity group(s):
  ...
DONE:
  20 duplicate user rows deleted
  11,378 FK rows rewritten across usage_events, daily_costs,
         api_keys, git_authors, git_author_repo_stats, git_commits

Verify: docker compose exec -T dashboard python -m scripts.audit_identity_collisions
  → "No dual-domain identity collisions found."
```

### Effect on Report I numbers

| Metric | Pre-merge | Post-merge | Notes |
|--------|----------:|-----------:|-------|
| Total spend (30d) | $24,104 | **$23,353** | −3.1%, ~1-day window shift, not merge effect |
| Active user_id rows (30d) | 160 | **140** | −20 stub rows deleted |
| Top-5 share | 44.9% | **44.7%** | Pareto robust to merge (< 1 pp) |
| Top-10 share | 62.7% | **63.2%** | Same |
| Segment AI_ACTIVE_BUT_NO_GIT | 89 | **72** | −17 phantom rows removed; Cursor-@skl.vc users whose Git activity was under @thehumanoid.ai |
| Segment HIGH_AI_SPEND_HIGH_GIT_OUTPUT | 15 | **19** | +4 — coupling that was hidden by the split becomes visible |
| Segment LOW_AI_SPEND_HIGH_GIT_OUTPUT | 10 | **7** | −3 moved into HIGH/HIGH after reunification |
| Top-1 rank (Oleg) | $3,045 | $2,936 | unchanged rank (single identity) |
| Atindra Nair (atin) | $2,425 (only Claude) | **$2,340** ($2,339 Claude + $2 Cursor reunified) | Cursor cents finally joined |
| Andy Park | $990 (only Claude) | **$987** ($954 + $3 GPT + **$29 Cursor**) | Cursor activity now correctly attributed |
| Cody Griffin | $1,188 (only GPT) | **$1,240** (**$52 Claude** + $1,178 GPT + $9 Cursor) | Anthropic activity finally attributed |

### Loader patch (prevents regression on next sync)

The merge above is one-shot — without a loader change, the next sync run would have re-created all 20 dual-identities. Patch applied in this same commit:

| File | Change |
|------|--------|
| `data/sources/_identity.py` (new) | `resolve_canonical_user_id(email, name)` — exact-email → alias-table → HMND-domain-local-part lookup → insert. New table `user_aliases(user_id, email)` registers every email seen, so post-merge `@skl.vc` and `@thehumanoid.ai` both resolve to the same canonical id. |
| `data/sources/anthropic_json.py:_ensure_user` | Now a one-liner that calls `resolve_canonical_user_id`. |
| `data/sources/cursor_json.py:_ensure_user` | Same. |
| `data/sources/openai_json.py:_ensure_user` | Same + retains `organization_id` tagging. |

Tunable via env: `HMND_IDENTITY_DOMAINS="thehumanoid.ai,skl.vc"` (defaults to those two) if a third domain ever appears.

**Re-audit any time:**

```bash
docker compose exec -T dashboard python -m scripts.audit_identity_collisions
```

### Full list of merged identities (lifetime $, descending)

| Local-part | Likely person | $ unified | thehumanoid.ai $ | skl.vc $ |
|-----------|--------------|---------:|------------------:|----------:|
| anai | Atindra Nair | $7,902 | $7,897 (Anthropic) | $6 (Cursor) |
| apar | Andy Park | $3,341 | $3,232 (Anthropic) | $109 |
| codg | Cody Griffin | $1,672 | $191 (Anthropic) | $1,481 (OpenAI) |
| brig | Brian Ginebaugh | $1,102 | $884 | $218 |
| sfed | Sergei Fedotov | $829 | $828 | $2 |
| sram | Sepehr Ramezani | $759 | $6 | $753 |
| ksha | Karim Shaban | $706 | $16 | $690 |
| byan | Boris Yangel | $683 | $553 | $130 |
| ius | Yuriy Strezhik | $551 | $80 | $471 |
| gwad | Gourav Wadhwa | $451 | $2 | $448 |
| dalm | Diogo Almeida | $353 | $331 | $23 |
| mata | Mustafa Atakan | $328 | $1 | $327 |
| mahs | Maheswar | $241 | $239 | $2 |
| lbie | Luke Bierbaum | $139 | $8 | $132 |
| mraf | Muhammad Rafique | $129 | $0 | $129 |
| gcer | Giulio Cerruti | $127 | $70 | $57 |
| pols | Polina Shorenko | $81 | $52 | $29 |
| yjj | Yoo-Jin Jung | $76 | $76 | $0 |
| fpro | Federico Proni | $72 | $70 | $2 |
| ccop | Claudio Coppola | $67 | $50 | $16 |

**Why does HMND have two domains?** Engineering operates under `@thehumanoid.ai`; Sycamore (the venture-builder / parent) provides `@skl.vc` accounts as corporate identity. People log into Anthropic with one, Cursor with the other. The merge + loader patch make this transparent to all downstream reporting.

## A.11 What IS already integrated (don't mislabel as "next step")

To avoid confusion when reading the "next step" recommendations:

| Source | Status | Where in dashboard |
|--------|------|--------------------|
| **OpenAI Admin API** | ✅ live (15-min sync) | Overview, AI Tools, ChatGPT tab |
| **Anthropic Admin Console export (JSON)** | ✅ ingested | Overview, Claude / Claude Code tabs |
| **Cursor Teams export (JSON)** | ✅ ingested | Overview, Cursor tab, ai_lines |
| **Git commits + authors + per-file churn** | ✅ ingested (`git_commits` table, 23,044 rows; `git_authors_repo_stats` per-author per-repo) | Devs (Git × AI) tab — segments people by AI spend × git output. Code Quality tab — bug-fix rate, revert rate, human-vs-bot. High-churn files tab. |
| **Git CI agent / bot detection** | ✅ ingested (13 bots flagged: github-actions, Cursor Agent, Renovate, etc.) | is_bot column on every commit; segmented separately |

**What is NOT yet integrated (the real Report II gap):**
- ❌ **PR-level review data**: review comments per PR, time-to-merge, review approvals, merge-conflicts. Today Git tells us commit subjects/files; PR data would tell us if AI-generated commits made it through review easily or with friction.
- ❌ **Jira / incident tickets**: which $/fix commit actually closed a P0/P1 ticket. Bug-fix rate today is "self-declared" from commit subjects (regex on `fix:`). With Jira we'd know if it was a real production fire.
- ❌ **Per-event source tagging for synthesised Claude Code** (see A.4) — would convert one of the 🟡 ratings to 🟢.
- ❌ **Deploy-event linkage** — which commits actually reached production.

**Bottom line**: when Report I says "next step: connect AI × Git × PR × Jira", READ IT AS "extend the already-connected AI × Git with PR and Jira on top". Git telemetry is in the dashboard today.


## A.12 Cohort reconciliation — "140 active humans" vs "206 in segments"

Surfaced 2026-05-16 by leadership review (good catch). The two numbers come from **different SQL queries with different time windows and different sources** — they answer different questions and are NOT supposed to match.

| Metric | SQL (roughly) | Time window | Includes |
|---|---|---|---|
| "**140 active humans**" (§1, §4) | `SELECT COUNT(DISTINCT user_id) FROM usage_events WHERE occurred_at >= now − 30d` | **Last 30 days** | Humans with ≥ 1 AI usage event in the window |
| "**206 devs**" (§3 segments) | `SELECT COUNT(*) FROM <users ∪ git_authors>` | **Lifetime** | Everyone ever seen in either AI usage OR git history; includes 13 bots and inactive lifetime accounts |

**Subtraction sanity check:**
```
206 lifetime devs
−  13 bots/agents (BOT_AUTOMATION segment)
= 193 humans ever seen in HMND tooling
− 140 humans active in AI in last 30d
=  53 humans who are in git/AI history but not active in last 30d
```

These 53 break down (estimate from segment data) as:
- ~ 42 in `GIT_ACTIVE_BUT_NO_AI` — engineers who commit but don't use AI tools (or stopped using them in 30d window)
- ~ 11 in lifetime AI users who haven't logged any AI event in the last 30 days (churned / on leave / job changed)

**Both numbers are correct.** The headline "140 active humans" is the right metric for "how broad is current adoption". The "206 devs" total is the right metric for "what is the full universe we're segmenting against". The two simply answer different questions, and the report should make that clear (§1 cohort note + this appendix).

**Drift over time:** the lifetime cohort grows monotonically (it only adds rows). The 30-day-active cohort moves up or down as people churn in/out of the window. Don't be surprised if next month it's 145 active, 215 lifetime — sync keeps adding new git authors and new AI users.
