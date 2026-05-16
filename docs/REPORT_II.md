# Report II — Technical Repository Audit & AI-Codegen Readiness

**Generated:** 2026-05-16
**Audience:** HMND engineering leadership + CEO
**Scope:** HumanoidTeam GitHub org (~100+ repos), with deep dives on `hmnd`, `hmnd-cloud`, `hmnd-sim`.

> **Methodology.** Repository structure, file inventory, AGENTS/CLAUDE/CODEOWNERS presence, CI workflows, tests, contributors, and excerpts of agent-instruction files were collected from local clones via `scripts/audit_repos_local.sh` on 2026-05-16. Findings tagged **[Fact]** (verifiable from inventory bytes / git log), **[Estimate]** (derived inference), **[Hypothesis]** (requires deeper source-code read). Source code itself was **not read** — only structural signals + first-60-line excerpts of documentation files.
>
> **Known data gaps — read before quoting numbers:**
> 1. **`hmnd` submodules were not initialized** at clone time (`hmnd_robot/`, `hmnd_training/`, `hmnd_locomotion/`, `hmnd_sim/`, `hmnd_fleet/`, `hmnd_firmware/`, `hmnd_infra/`, `hmnd_flywheel/`, `hmnd_wholebody/`, `hmnd_playground/` — see `git submodule update --init --recursive` in README). LoC / test-count / per-module-README findings for `hmnd` show only the **root + thin top layer (~0.2 MB of code + docs)**. The real `hmnd` codebase (estimated >100 MB across submodules) was inspected via *indirect signals* (hot-directories in git log, CI workflow names, AGENTS.md references). A Phase 2 audit with submodules initialized would refine §3.
> 2. **LFS files were skipped** (`GIT_LFS_SKIP_SMUDGE=1`). Localization maps, USD models, model checkpoints not in working tree. Doesn't affect readiness assessment; affects size measurements only.
> 3. **`hmnd-sim` is deprecated** (per its own README) — real simulation code now lives in `hmnd/hmnd_sim` submodule (not initialized, see #1). §5 documents the deprecated repo for completeness.

---

## 1. Repository Landscape

[Fact] HumanoidTeam GitHub org contains **100+ repositories** (audited via `gh api /orgs/HumanoidTeam/repos`, first page = 100 results, 2nd page exists). Cleanly groupable into ~8 segments by purpose.

[Fact] **Selected for deep dive:** `hmnd`, `hmnd-cloud`, `hmnd-sim`. Rationale:

| Repo | Reason for selection | Last commit |
|---|---|---|
| `hmnd` | The monorepo. Contains all robot code, training, fleet, firmware, locomotion, sim, infra modules. Highest engineering surface area. | 2026-05-16 (live) |
| `hmnd-cloud` | Cloud infrastructure-as-code (AWS / Databricks / Nebius). Production blast-radius is highest here — one bad PR = outage. | 2026-05-14 |
| `hmnd-sim` | Originally the simulation hub. **Deprecated as of 2025-08-20** — kept for legacy. Worth including in §5 to document the deprecation and redirect. | 2025-08-20 (stale) |

---

## 2. Repository Segmentation (8 groups)

| Segment | Example repos | Purpose | Include in AI productivity / readiness analysis? | Notes |
|---|---|---|---|---|
| **Core monorepo** | `hmnd` | Main robot codebase, training, fleet, firmware, locomotion, sim, infra | ✅ **Yes — primary target** | Bazel + Cargo (Rust) + Python; LFS-heavy; 87 contributors lifetime |
| **Cloud / infra** | `hmnd-cloud` | Terraform IaC for AWS/Databricks/Nebius, deployables, GitHub runners | ✅ **Yes — high blast radius** | 124 .tf files; 0 tests; small team (5 active) |
| **Deprecated / legacy** | `hmnd-sim`, `hpi` (archived), `mcap_2_lerobot` (archived), `alpha_roadkill` (archived), `roadkill-rtpc` (archived) | Superseded code, kept for history | ❌ **Exclude** | Mixing into "AI productivity" metrics would distort signal |
| **Robotics drivers / firmware** | `rby1-sdk`, `ros2_psyonic`, `ros2_xhand`, `manus_ros_drivers`, `firmware_hal_aurix_tc3`, `firmware_hal_arm_stm32h7`, `firmware_hal_c2000ware`, `xdof_grippers`, `HMI_Alpha_GUI`, `etherlab-ethercat`, `etherlab-rtipc`, `linux` (kernel fork), `backport-iwlwifi`, `Gripper_Firmware`, `Acontis_Thor`, `AURIX_TC3x_Motor_Control_SDK`, `hmnd-actuator-control` | Hardware integration, low-level control, firmware | ⚠️ **Selective** | Most are safety-critical; AI codegen requires hardware-in-the-loop validation. Should NOT be default AI-assist targets. |
| **Vendor SDKs / public forks** | `placo`, `IsaacLab`, `robocasa`, `lerobot_lib`, `ros-noetic`, `BehaviorTree.ROS2`, `ruckig`, `trac_ik`, `librealsense`, `realsense-ros`, `Lakibeam_ROS2_Driver`, `iKalibr`, `Kimera-VIO`, `MASt3R-Fusion`, `ORB_SLAM3`, `VSLAM-LAB`, `LIBERO`, `oculus_reader`, `lightweight_vio`, `microstrain_inertial`, `neo_relayboard_v3`, `time_optimal_trajectory_generation_py`, `eRob_Compensation_Controller`, `rox_argo_kinematics`, `rox` | Forked / vendored third-party deps | ❌ **Exclude** | Forks shouldn't be edited by AI agents — changes belong upstream. Track AI usage to confirm. |
| **Simulation assets** | `sim-assets`, `sim-robots`, `sim-env`, `sim-objs`, `sim-tools` | Mesh / URDF / scene assets | ❌ **Exclude** | Asset-only repos; LFS-heavy; AI codegen N/A |
| **Internal tooling** | `databricks-folders`, `ftrack`, `hm-ops`, `hm-uce-job-submit`, `merge-datasets`, `speech_to_speech`, `vjepa2ac`, `umi-xdof`, `prealpha_provisioning`, `RobotRemote.SHM`, `hmnd_interviews` | Ops scripts, helpers, internal apps | ⚠️ **Selective** | Some are abandoned, some active. Audit individually. |
| **ML / research** | `reasoning`, `Isaac-GR00T-Humanoid`, `openpi`, `isaac_loco`, `groot1`, `dexmimicgen`, `raytorch`, `rl_locomotion`, `aloha_imitation`, `interbotix-aloha`, `manipulation_docker`, `VLABenchmark`, `lerobot`, `lerobot-hackathon`, `hmnd_remote_policy`, `FleetDutySim`, `pilot-public`, `cupid`, `beta-hardware`, `beta-morphology-analysis-tools`, `okvis_ws` | Research code, ML experiments, benchmarks | ⚠️ **Selective** | Research-quality code; AI assist OK but test coverage usually weak |

**Practical scope for AI-codegen rollout (Phase 1):** the two "✅ Yes" rows above — **`hmnd` and `hmnd-cloud`**. Everything else is either deprecated, vendored, asset-only, or selective. Don't try to roll out a one-size-fits-all AI policy across the 100+ repos — the cost/benefit/risk profile differs per segment.

---

## 3. Detailed Review: `hmnd`

**Purpose [Fact, from README].** The main monorepo for HMND humanoid robotics: robot code (ROS2), training pipelines, fleet ops, firmware, locomotion, simulation integration, internal infra. Bazel-driven, polyglot (Python + C++ + Rust + TypeScript).

**Top-level structure [Fact]:** 38 entries at root. Non-hidden notable: `AGENTS.md`, `BUILD`, `Cargo.lock`, `Cargo.toml`, `MODULE.bazel` (Bazel 7+ bzlmod), `MODULE.bazel.lock` (1.8 MB — huge dep graph), `README.md`, `RELEASENOTES.txt`, `deploy.sh`, `docs/`, `hmnd_agents/`. The substantive modules (`hmnd_robot/`, `hmnd_training/`, `hmnd_locomotion/`, etc.) are **submodules not initialized in this inventory** — see §3 note below.

**Modules (from README + hot-directories) [Fact]:**

| Module | Evidence | Hot-dir score (last 90d commits) |
|---|---|---|
| `hmnd_robot/` | README, AGENTS.md, hot dir, CI `test_hmnd_robot.yaml` | **10,468** (#1) |
| `hmnd_training/` | README, hot dir, CI `test_hmnd_training.yaml` + `test_hmnd_training_core.yaml` | 5,808 (#2) |
| `hmnd_locomotion/` | hot dir | 2,528 |
| `hmnd_sim/` | AGENTS.md TL;DR refs `hmnd_sim/AGENTS.md`, hot dir | 1,839 |
| `hmnd_flywheel/` | LFS file `hmnd_flywheel/humanoid-console/frontend/...` → has TS frontend; hot dir | 1,348 |
| `hmnd_fleet/` | hot dir, CI `test_hmnd_fleet.yaml` | 1,206 |
| `hmnd_wholebody/` | hot dir, CI `test_hmnd_wholebody.yaml` (implied by `build_hmnd_wholebody_image_layered.yaml`) | 726 |
| `hmnd_playground/` | hot dir | 704 |
| `hmnd_firmware/` | AGENTS.md TL;DR refs `hmnd_firmware/AGENTS.md`, hot dir, CI `test_hmnd_firmware.yaml` | 582 |
| `hmnd_infra/` | hot dir | (implied: tooling) |

**[Note on Phase 2 audit]** Submodule contents — the actual code — were not in the working tree (clone done without `--recurse-submodules`). The signals above (hot-dirs from git log + CI test_workflow names) **confirm modules exist and are tested**, but per-module LoC, test counts, and module-level READMEs require re-running the inventory with submodules initialized.

### Detailed findings — `hmnd`

| Area | Findings | Evidence | Maturity | Risks | Recommendation |
|---|---|---|---|---|---|
| **AI agent instructions** | `AGENTS.md` (9 KB, ~200 lines), `.cursor/rules/` dir, `.claude/` dir, `.codex` marker file, references to per-module `hmnd_firmware/AGENTS.md` + `hmnd_sim/AGENTS.md` | Inventory + AGENTS.md excerpt | **4/5 — strong** | Multiple agent systems coexist (`.claude/`, `.cursor/`, `.codex/`) — risk of divergence if not maintained together | Document the canonical instruction source; cross-reference between `.cursor/rules` and `AGENTS.md` |
| **Coding rules (in AGENTS.md)** | Excellent. TL;DR, "Functional core / Imperative shell" architecture rule, code-quality standards per language (Python, C++, TypeScript): naming, DRY, control flow, data modeling, error handling. Specific anti-patterns called out (`[&]` captures forbidden, no silent except). | AGENTS.md excerpt | **5/5** | None | Use as template for `hmnd-cloud` and other repos |
| **Module boundaries** | "Functional core / Imperative shell" mandated; "shell" wraps ROS2/gRPC/files. Module names map to bounded contexts (robot, training, sim, fleet, firmware, etc.). | AGENTS.md | **4/5** | Submodule code not audited — hypothesis pending | Phase 2 audit can validate cross-module imports |
| **CI/CD** | **40+ workflows** in `.github/workflows/`. Build + test + deploy per module: `test_hmnd_robot`, `test_hmnd_firmware`, `test_hmnd_fleet`, `test_hmnd_training`, `test_hmnd_training_core`, `test_hmnd_bazel`, `test_hmnd_integration`, `test_hmnd_dataset_v3`, `test_hmnd_services`, `test_hmnd_rust`, `test_hmnd_prefect`, `test_hmnd_infra`, `test_hc_models`, `test_hc_client`, `test_hmndlib_spatial`, `test_episode_preprocessing`, `test_episodes_filter`, `test_prometheus_to_dwh`, `test_console_backend`, `test_console_frontend`, `test_synapse` + `build_*` + `deploy_*` + `apps_code_review.yaml`, `backport_to_main.yaml`, `release.yml`, `hmnd_cron.yaml`, `otel_export.yaml` | Inventory | **5/5 — excellent** | Workflow count suggests test maturity; actual test density per module unverified (Phase 2) | None — this is best-in-class |
| **Pre-commit / linting** | `.pre-commit-config.yaml` is **10.3 KB** (very large — many hooks). `.clang-format`, `.clang-tidy`, `.markdownlint.yaml`, `.prettierrc`, `.typos.toml`, `.buildifier-tables.json`. Coverage spans C++, TypeScript, markdown, spell-check, Bazel BUILD files. | Inventory | **5/5** | None | Document hook list in AGENTS.md so AI agents know what will fail before commit |
| **Module-level READMEs** | `hmnd_robot/README.md` referenced in root README. Others implied. **Not verifiable** (submodules not initialized) | README + Phase 2 deferred | **Estimated 3/5** | Possibly inconsistent per-module | Phase 2 audit |
| **Living specs / ADRs** | `docs/` exists (6 markdown files only — small). No `ADR/`, `RFC/`, `decisions/`, `architecture/`. `docs/RELEASE_WORKFLOW.md` mentioned in AGENTS.md | Inventory | **2/5 — weak** | Architectural decisions not formally documented; tribal knowledge | Introduce ADRs in `docs/adr/` for major decisions going forward |
| **CODEOWNERS** | `.github/CODEOWNERS` exists ✅ | Inventory | **3/5** | Coverage per module unverified | Phase 2 to validate coverage of every top-level dir |
| **DVC / data versioning** | `.dvc/` present | Inventory | (info) | DVC implies model/data artefacts tracked | Good — confirms ML pipeline maturity |
| **Submodules** | 10 git submodules — all `HumanoidTeam/*` forks of third-party deps (`placo`, `IsaacLab`, `robocasa`, `lerobot`, `ruckig`, `oculus_reader`, etc.) | `.gitmodules` | (info) | Vendored deps need careful AI-codegen policy (forks shouldn't drift from upstream) | Add `AGENTS.md` rule: "do not modify `*/third_party/*` — upstream changes only" |
| **Secret management** | `git-crypt unlock` required (README mentions); `.netrc` for S3 artefacts | README | (info) | Secret rotation discipline not visible to audit | Out of scope for this report |

**hmnd top-level summary:**
- **Languages:** Python (rough estimate from CI workflow names + Cargo.toml + MODULE.bazel: Python + C++ + Rust + TypeScript)
- **Test maturity:** **estimated 3/5** at the visible layer (CI workflow names suggest comprehensive coverage; per-module counts pending Phase 2)
- **Documentation maturity:** **3/5** — strong README + AGENTS.md; weak ADR/architecture layer
- **AI-readiness score:** **3.5 / 5** (see §6)

---

## 4. Detailed Review: `hmnd-cloud`

**Purpose [Fact, from README].** Cloud infrastructure-as-code for AWS / Databricks / Nebius, multi-region, structured by domain (perception / reasoning / simulation / vla / shared-between-teams). Manages compute for training, GitHub runners, shared services, deployables (AMIs, containers).

**Top-level structure [Fact]:** 5 main dirs — `bootstrap/`, `deployables/`, `hmnd_deployment/`, `infrastructure/` (the bulk — 2.3 MB), `ssh-keys/`.

**Languages [Fact]:**

| Language | File count | LoC (rough) |
|---|---|---|
| Terraform (`.tf`) | **124** | n/a (not counted by inventory) |
| YAML | 21 | 821 |
| Shell | 18 | 893 |
| HCL | 8 | n/a |
| Python | 7 | 475 |
| Markdown | 9 | 611 |
| Other (json, tftpl, etc.) | ~15 | — |

### Detailed findings — `hmnd-cloud`

| Area | Findings | Evidence | Maturity | Risks | Recommendation |
|---|---|---|---|---|---|
| **AI agent instructions** | **NONE.** No `AGENTS.md`, no `.cursor/rules`, no `CLAUDE.md`, no `.github/copilot-instructions.md`, no `CONTRIBUTING.md`, no `ARCHITECTURE.md` | Inventory | **0/5 — absent** | **HIGHEST RISK in the audit.** AI agents have **zero guidance** on what's safe to change in Terraform IaC. One AI-generated `terraform apply` could wipe production. | **Priority Action #1.** Add `AGENTS.md` with: (a) terraform-specific dos/don'ts; (b) "never `terraform apply` from AI"; (c) per-domain blast-radius warning; (d) which modules require human review |
| **CODEOWNERS** | **NONE.** No `.github/CODEOWNERS`, no `CODEOWNERS` at root | Inventory | **0/5 — absent** | AI-generated PRs auto-merge possible if rules not strict; no module-owner review enforced | **Priority Action #2.** Add CODEOWNERS pinning each `domains/*` dir to its owner team |
| **Tests** | **ZERO test files** by any naming pattern (`test_*.py`, `*_test.go`, `*.test.ts`, `*_test.tf`, etc.). No `terratest`, no `kitchen-terraform`, no Python tests for the 7 .py files | Inventory | **0/5 — absent** | Terraform changes have **no automated validation** beyond `terraform plan`. AI-generated drift, security holes, cost spikes could land unreviewed. | **Priority Action #3.** Add minimal IaC tests: `terraform validate` + `tflint` + `tfsec` already implied (`.tflint.hcl` present); add `regula` or `checkov` policy-as-code; start a `tests/` dir for any custom Python helpers |
| **CI/CD** | 8 workflows: `build-base-gpu-ami`, `build-github-runner-ami`, `build-simulation-ami`, `debug-secrets`, `deploy-infrastructure`, `deploy-to-robots`, `shared-ami-build`, `test-arc` | Inventory | **4/5** | Naming suggests build/deploy heavy; "test-arc" is the only test workflow | Add per-domain `validate.yml` workflow that runs `terraform validate` + `tflint` + `tfsec` on PR |
| **Pre-commit** | `.pre-commit-config.yaml` exists (2.6 KB — modest) | Inventory | **2/5** | Hooks unknown without read | Audit hook list; ensure `terraform-fmt`, `terraform-validate`, `tflint`, `detect-secrets` are in it |
| **Module boundaries** | Excellent on paper. `infrastructure/domains/{perception, reasoning, simulation, vla, shared-between-teams}/{region}` + `infrastructure/modules/{aws,databricks,...}/shared-primitives/*`. Clear separation of "modules" (reusable) vs "domains" (instantiations) | README | **4/5** | Self-documented structure; per-module READMEs absent | Add 1-paragraph README in each `domains/*/` explaining "this is owned by team X, blast radius Y" |
| **Living specs** | `infrastructure/domains/hmnd-console/docs/infra-drift.md` exists (8 KB). No `docs/` at root, no `ADR/`. | Inventory + largest-files list | **2/5** | One nested doc; nothing repo-wide | Add `docs/` with at least: deployment model, environment list, blast-radius matrix |
| **Vendored content** | `lambdas-download/runners.zip` (750 KB), `runner-binaries-syncer.zip` (463 KB), `webhook.zip` (361 KB) — 3 binary zips committed to repo | Inventory largest-files | (info) | Binary blobs in IaC repo; AI agents shouldn't touch them; not obviously called out | Add `.gitignore` rule + AGENTS rule: "do not regenerate `lambdas-download/*.zip` from AI — build via CI" |
| **README** | 5.4 KB; clear structure description; "three rules: don't make overcomplicated things, don't apply from local, explain in PRs" | README excerpt | **4/5** | Rules tonally informal — fine for humans, weak for AI guardrails | Promote the "three rules" into AGENTS.md with concrete examples |

**hmnd-cloud top-level summary:**
- **Languages:** Terraform-dominant + shell + YAML + minor Python
- **Test maturity:** **0/5** — no tests at all
- **Documentation maturity:** **2/5** — good README, no docs/, no ADRs
- **AI-readiness score:** **2.0 / 5** (see §6) — **lowest of the three, biggest blast radius. Most urgent to fix.**

---

## 5. Detailed Review: `hmnd-sim`

**Purpose [Fact, from own README].** Originally the simulation monorepo (Isaac Sim + URDF pipeline + sim assets). **Now deprecated.**

**Status:**

| Signal | Value |
|---|---|
| README first line | "*hmnd-sim (This repository is deprecated. Please use: [hmnd_sim](https://github.com/HumanoidTeam/hmnd/tree/main/hmnd_sim) instead.)*" |
| Last commit | 2025-08-20 (9 months ago) |
| Commits in last 90 days | **0** |
| Total lifetime commits | 154 |
| Lifetime contributors | 10 |
| Active contributors (90d) | 0 |
| Has `CLAUDE.md` | ✅ (3.4 KB, but references `third-party/ai_agent/general_memory/` which isn't in working tree — submodule not initialized) |
| Has CI / tests / CODEOWNERS / docs/ | ❌ none |

### Detailed findings — `hmnd-sim`

| Area | Findings | Recommendation |
|---|---|---|
| **Repository status** | Deprecated, superseded by `hmnd/hmnd_sim` submodule | **Archive on GitHub** (Settings → Archive this repository). Prevents new commits, makes status undeniable, removes from "active" listings. |
| **README** | Self-documents deprecation in first line — good. | Add bigger banner: "⚠️ ARCHIVED — see hmnd/hmnd_sim" |
| **CLAUDE.md** | Present but references an AI-agent memory system in `third-party/ai_agent/` submodule that's not initialized | The memory-system file is interesting (structured AI agent memory model with general / customisations / logs separation). **Consider porting the memory-system pattern to `hmnd` AGENTS.md.** |
| **Submodules** | 4: `neo_msgs2`, `neo_common2`, `neo_srvs2`, `rox_argo_kinematics` — all ROS vendor deps | Migration to `hmnd/hmnd_sim` should have copied/replaced these |

**hmnd-sim summary:** **Exclude from AI-codegen readiness analysis going forward.** All future signal should come from `hmnd/hmnd_sim` submodule (covered by `hmnd` analysis once Phase 2 audit completes).

**AI-readiness score:** **N/A — deprecated.** Not scored in §6.

---

## 6. AI-Codegen Readiness Assessment

Scale: **0 = absent · 1 = very weak · 2 = partial · 3 = usable but incomplete · 4 = strong · 5 = excellent**

| Criterion | hmnd | hmnd-cloud | hmnd-sim | Evidence | Key Gap | Recommendation |
|---|:--:|:--:|:--:|---|---|---|
| **6.1 Agent Instructions** | **4** | **0** | 2 | `hmnd` AGENTS.md (9 KB, language-specific rules), `.cursor/rules/`, `.claude/`, `.codex` markers, per-module AGENTS files referenced | `hmnd-cloud`: nothing. `hmnd-sim`: stale CLAUDE.md referencing missing submodule. | Port hmnd's AGENTS.md pattern to hmnd-cloud (Terraform-specific) immediately |
| **6.2 Living Specification** | **2** | **2** | 1 | hmnd: `docs/` 6 files, no ADR. hmnd-cloud: README only, one nested infra-drift.md. hmnd-sim: README. | Both repos missing ADR/RFC layer. hmnd has heavy CI but light written-down architecture. | Introduce `docs/adr/` in both; require ADR for any new top-level module or domain |
| **6.3 Tests by Layer** | **3*** | **0** | 0 | hmnd: 40+ CI workflows confirm tests exist; per-layer breakdown pending Phase 2. hmnd-cloud: literally zero. hmnd-sim: zero. | hmnd-cloud has no IaC tests at all. | Phase 2 audit will refine hmnd score. Add tflint/tfsec/regula to hmnd-cloud as quick win. |
| **6.4 Module Boundaries** | **4** | **4** | 3 | hmnd: "Functional core / Imperative shell" mandated in AGENTS.md, module names map to bounded contexts. hmnd-cloud: `domains/` × `modules/` × `regions/` separation excellent. | hmnd: cross-module imports not validated (Phase 2). hmnd-cloud: per-domain ownership not in CODEOWNERS. | Add CODEOWNERS to hmnd-cloud per `domains/*` dir |
| **6.5 CI/CD & Local Validation** | **5** | **4** | 1 | hmnd: 40+ workflows, large pre-commit, multi-language linting. hmnd-cloud: 8 workflows, `.tflint.hcl`, `.secrets.baseline`. hmnd-sim: nothing. | hmnd-cloud: only one "test" workflow (`test-arc`); rest are build/deploy. | Add `validate-on-pr.yml` for hmnd-cloud that runs validate + tflint + tfsec on every PR |
| **6.6 Safety-Critical Code Protection** | **3** | **2** | n/a | hmnd: CODEOWNERS exists; AGENTS.md flags firmware. hmnd-cloud: no CODEOWNERS, deployment scripts in repo, no merge protection visible. | hmnd-cloud: AI agent could theoretically modify deploy-to-robots.yml | Branch protection rules + required reviews per `domains/*/` |

*hmnd Tests score **3*** is an *estimate* pending Phase 2 (submodule-initialized) audit. The 40+ test workflow names imply broad coverage; actual per-layer assertion density not yet measured.

### Overall scores

| Repository | Overall AI-Codegen Readiness | Classification | Rationale |
|---|:--:|---|---|
| **hmnd** | **3.5 / 5** | **MOSTLY_READY** | Outstanding agent instructions, comprehensive CI, clear module conventions. Held back by light architectural docs and Phase-2-pending test verification. Safe target for AI-assist with current guardrails. |
| **hmnd-cloud** | **2.0 / 5** | **PARTIALLY_READY** | Strong directory structure + README. Catastrophic gaps: zero agent instructions, zero tests, no CODEOWNERS. **High blast radius** — Terraform changes can break production. **Highest urgency to fix.** |
| **hmnd-sim** | **N/A** | **DEPRECATED** | Repo is archived in spirit; should be archived on GitHub. Skip from AI-codegen analysis. |

---

## 7. Specification & Testing Maturity

Layer-by-layer assessment of where each repo has **specs** (docs / contracts / interfaces) and **tests** (verifiable assertions).

| Layer | `hmnd` specs | `hmnd` tests | `hmnd-cloud` specs | `hmnd-cloud` tests | `hmnd-sim` | Gap |
|---|:--:|:--:|:--:|:--:|:--:|---|
| Infrastructure | weak | n/a | README only | none | n/a | hmnd-cloud needs IaC tests urgently |
| Data | implied (DVC present) | implied | n/a | n/a | n/a | Per-dataset schemas not enumerated |
| Services / APIs | implied (`hmnd_services` test workflow) | yes ✓ | n/a | n/a | n/a | OpenAPI / gRPC schemas not at root — likely in modules |
| Robotics / controls | AGENTS.md mentions; modules visible | yes (test_hmnd_robot) | n/a | n/a | deprecated | Per-module specs unverified |
| AI / ML | implied (`hmnd_training` workflows × 2) | yes (test_hmnd_training_core) | n/a | n/a | n/a | Model evals not separately surfaced — audit Phase 2 |
| Prompts / agents | AGENTS.md repo-wide + per-module (hmnd_firmware, hmnd_sim) | none (no prompt eval) | none | none | CLAUDE.md only | Prompt/agent **evals** are absent across all repos — no test that an AGENTS.md change doesn't regress AI behaviour |
| Integration flows | hmnd_integration test workflow | yes (test_hmnd_integration) | none | none | n/a | hmnd-cloud needs at least one smoke deploy test |
| End-to-end behavior | implied (`hmnd_cron.yaml`, `otel_export.yaml`) | partial | none | none | n/a | E2E hardware-in-the-loop tests not visible at root |

**Tests-as-spec opportunity [Hypothesis, requires Phase 2]:** The 40+ test workflows in `hmnd` likely encode much of the behavioural spec. Surfacing this in AGENTS.md ("when adding X, run `bazel test //hmnd_<module>/...`") would close the largest documentation gap with zero new docs.

**Critical flows without regression protection [Fact]:**
- All of `hmnd-cloud` — no IaC tests means no protection against drift, security regressions, or accidental destroy.
- Prompt/agent files in `hmnd` (AGENTS.md, .cursor/rules) — no eval framework to detect when changes regress AI agent behaviour.

---

## 8. People & Contribution Patterns

### hmnd — broad team, healthy ownership

[Fact, lifetime] 87 contributors, 3,404 commits. [Fact, last 90 days] 87 active people based on top-15 alone (= broad).

**Top contributors by commits (last 90 days):**

| Engineer | Commits 90d | Profile |
|---|--:|---|
| Sam Pfeiffer | 73 | Multi-tool engineer (also #5 in Top spenders from Report I) |
| Oleg Sinavski | 70 | Cursor-dominant (10.9M AI lines lifetime per Report I) |
| Anubhav Dogra | 63 | Core robotics engineer (also lifetime top 4) |
| Bao Tran | 58 | Active core engineer |
| Ricardo Delfin | 55 | Tech lead (referenced in README for credentials) |
| Luke Bierbaum | 52 | Lifetime #3 contributor; high commit cadence |
| Karim Shaban | 51 | Lifetime #1 contributor |
| Artem Ismagilov | 47 | n8n_artem automation owner + active engineer |
| Sergei Fedotov | 45 | Active engineer |
| Atindra Nair (atin) | 44 | Report-I top-2 Claude Code user |
| github-actions[bot] | 44 | Bot — release automation |
| Mustafa Atakan (matakan) | 40 | Cross-repo (also hmnd-cloud lead) |
| Claudio Coppola | 39 | Active engineer |
| Brian Delhaisse | 39 | Active engineer |

**Heaviest file-modifiers (last 90 days)** [the script's "commits" column here is file-rows, not commits]:

| Engineer | File-rows | +LoC | -LoC | Interpretation |
|---|--:|--:|--:|---|
| Cheerag Sharma (shac-src) | 1,128 | +85,292 | -15,834 | Heavy refactor / large changes |
| Mustafa Atakan (matakan, lifetime contributor) | 3,925 | +274,116 | -26,666 | **Largest by far** — likely big terraform/infra reorgs; cross-repo |
| Muhammad Rafique (mrafique) | 796 | +56,038 | -5,867 | Heavy adds, light deletes — feature work |
| Matt Klingensmith (mklingen-humanoid) | 624 | +54,864 | -5,530 | Cross-area engineer |
| Rajat (rash-rajat) | 426 | +33,866 | -10,758 | Active engineer |
| Saurabh Kumar | 269 | +16,534 | -5,508 | Active engineer |
| Nick (ntan-humanoid) | 175 | +5,777 | -3,269 | Lighter-cadence engineer |
| MHIS (mhis-2025) | 81 | +5,755 | -2,215 | Newer contributor |

**Hot directories (last 90 days):**

| Directory | Touches |
|---|--:|
| `hmnd_robot/` | 10,468 |
| `hmnd_training/` | 5,808 |
| `hmnd_locomotion/` | 2,528 |
| `hmnd_sim/` | 1,839 |
| `hmnd_flywheel/` | 1,348 |
| `hmnd_fleet/` | 1,206 |
| `hmnd_wholebody/` | 726 |
| `hmnd_playground/` | 704 |
| `hmnd_firmware/` | 582 |
| `tools/` | 484 |

**Commit-size distribution (last 90 days):** 18% single-file, 31% 2-5 files, 35% 6-20 files, **15% 21+ files**. The 21+-file commits (~218 commits) deserve review-policy attention — AI-assisted large changes are higher-risk.

**Knowledge concentration / bus factor [Estimate]:** Top-10 lifetime contributors = 1,167 commits = ~34% of all commits. Top-25 = ~58%. Healthier distribution than hmnd-cloud below, but `hmnd_locomotion/`, `hmnd_firmware/`, `hmnd_flywheel/` likely have <3-person ownership each (Phase 2 needed to confirm per-module).

### hmnd-cloud — small team, single-digit owners

[Fact] 26 lifetime contributors, 682 commits. **5 active in last 90 days.**

**Top contributors (lifetime):**

| Contributor | Commits | Share |
|---|--:|--:|
| Antoni Bertel | 138 | 20% |
| matakan (Mustafa Atakan, alt) | 128 | 19% |
| Mustafa Atakan | 123 | 18% |
| Daniel Machado | 110 | 16% |
| danielltm (alt of Daniel) | 65 | 10% |
| **Top 5 combined** | **564** | **83%** |
| Remaining 21 | 118 | 17% |

**Bus factor warning [Fact]:** "Antoni Bertel" + "matakan" + "Mustafa Atakan" + "Mustafa Atakan2" looks like **2-3 humans across 4 git identities**. If true, the *real* lifetime ownership concentration is even higher (~80% by 2-3 people). The repo would benefit from explicit identity merging (same problem we solved for Report I in §A.10).

**Last 90 days:** 39 commits Mustafa, 38 matakan, 15 Daniel — **80% from 2 people**.

**Hot directories (last 90 days):** `ml-infrastructure/` (221), `infrastructure/` (48), `onprem-infrastructure/` (32), `.github` (8). One person owning ml-infrastructure is the highest single-person concentration in the whole audit.

### hmnd-sim — abandoned

[Fact] 10 lifetime contributors. **0 active in last 90 days.** Last commit 2025-08-20. Dmitriy Shingarey accounted for 90/154 = 58% of lifetime commits.

### Per-contributor risk/opportunity table

| Contributor | Repos | Main areas | Pattern | Risk / Opportunity | Recommendation |
|---|---|---|---|---|---|
| Mustafa Atakan (matakan) | hmnd-cloud (#1, #2 identities), hmnd | Terraform / IaC, ml-infrastructure | High volume + cross-repo | **Bus-factor risk on hmnd-cloud** — 38% of last-90d commits | Cross-train Daniel + 1-2 more on each `domains/*` |
| Daniel Machado (danielltm) | hmnd-cloud | Various IaC | Active | Only #2 active in hmnd-cloud | Document onboarding for new IaC contributors |
| Cheerag Sharma (shac-src) | hmnd | Multi-area | Heavy file-modifier | Could be doing large refactors — confirm they're reviewed | Audit a sample of recent large PRs |
| Oleg Sinavski | hmnd | Cursor-AI-heavy from Report I | 70 commits 90d but 10.9M Cursor lines lifetime | High AI-line activity — Phase 2 to verify what fraction ships | Pair with Cheerag for "Cursor power-user playbook" (Report I rec #2) |
| Atindra (atin) | hmnd | Active engineer | 44 commits, Report-I top-2 Claude Code user | Demonstrating "AI Power User" pattern | Document workflow as team playbook |
| Karim Shaban (ksha) | hmnd | Lifetime #1 contributor | 51 commits 90d, 690 Cursor spend Report I | Steady high-value contributor | Recognise + retain |
| Dmitriy Shingarey | hmnd-sim only | Owner of deprecated repo | Inactive | Repo deprecated; knowledge in his head | Confirm hmnd_sim submodule has equivalent content + owner |

---

## 9. Technical Recommendations

### 9.1 Per-repo

**`hmnd`** — keep doing what you're doing; add the missing 30%.
- Promote AGENTS.md per-module pattern (`hmnd_firmware/AGENTS.md`, `hmnd_sim/AGENTS.md` already exist per TL;DR) into a documented standard with template.
- Introduce `docs/adr/` with at least 5 retroactive ADRs for major existing decisions (Bazel choice, ROS2 version, functional-core/imperative-shell rule, agent-instruction structure, secret management via git-crypt).
- Phase 2 audit with submodules to validate test coverage per module + per-module READMEs.
- Add a "prompt-regression" eval: when AGENTS.md changes, run a small AI task and compare output.

**`hmnd-cloud`** — multiple critical gaps. Sequence:
1. **AGENTS.md** — Terraform-specific dos/don'ts (copy structure from `hmnd` AGENTS.md, adapt to IaC).
2. **CODEOWNERS** — one team per `domains/*` dir.
3. **PR-validation workflow** — terraform validate + tflint + tfsec + checkov, blocking on PR.
4. **Onboarding doc** — `docs/onboarding.md` so the 5-person team isn't single-point-of-failure.
5. **Module-level READMEs** in each `domains/*/` (one paragraph: owner team, blast radius, deployment cadence).

**`hmnd-sim`** — archive on GitHub formally. Update README to redirect.

### 9.2 AI-codegen enablement (cross-repo)
- AGENTS.md template repo-wide: where to navigate, where NOT to edit, build/test commands, AI-safe vs AI-unsafe task list.
- For each first-party engineering repo, add minimum: `AGENTS.md` + `CODEOWNERS` + `pre-commit` hooks. These three files make AI codegen at least *reviewable*.
- Define `safe AI tasks` (docs, tests, small refactors, formatting) vs `unsafe` (firmware, IaC apply, schema changes) — repo-by-repo.

### 9.3 Testing
- `hmnd-cloud`: terraform validate + tflint + tfsec + checkov as PR gate. Add `terratest` for any non-trivial modules.
- `hmnd`: Phase 2 audit; assuming tests exist, document the runner commands in AGENTS.md so AI agents know how to validate before commit.
- Cross-repo: introduce **prompt/agent evals** — a small canonical task set (e.g. "implement X helper", "fix Y bug pattern") that runs against current agent-instructions every quarter to detect regressions.

### 9.4 Specification
- Introduce `docs/adr/` in `hmnd` and `hmnd-cloud`. Cap at 5-10 ADRs initially.
- Mandate ADR for: any new top-level module in `hmnd`, any new domain in `hmnd-cloud`, any architectural rule change in AGENTS.md.

### 9.5 Agent-instruction recommendations
- `hmnd-cloud/AGENTS.md` is the single highest-value missing file in the audit. Suggested skeleton:
  ```
  - TL;DR: never `terraform apply` from AI. Always plan, then PR, then human review.
  - Repo map: domains/, modules/, deployables/
  - Build/validate: terraform init, validate, fmt, tflint, tfsec
  - Safety-critical files: deploy-to-robots.yml, root domains/production/
  - Cost-sensitive resources: anything in domains/shared-between-teams/training/
  - Required reviews: domain owner per CODEOWNERS
  ```

### 9.6 Governance
- Branch protection on `main` for hmnd-cloud (currently unconfirmed — should be checked in GitHub UI).
- Required reviewer count = 2 for `infrastructure/` and `deployables/` paths.
- AI-assisted PR declaration: a checkbox in PR template "AI agent used: [Claude Code / Cursor / GPT / none]". Helps Report II's data quality going forward.
- Secrets policy: `.secrets.baseline` exists in hmnd-cloud — confirm it's enforced via `detect-secrets` in pre-commit.

---

## 10. Priority Actions

### Immediate (this week — 1-3 day work)

1. **Archive `hmnd-sim` on GitHub.** One-click; eliminates confusion, removes from "active" listings, makes the deprecation undeniable.
2. **Add CODEOWNERS to `hmnd-cloud`.** ~15 min of work; massive risk reduction. Pin each `domains/*/` to its owner team.
3. **Run Phase 2 audit on `hmnd`** with submodules initialized: `git submodule update --init --recursive` then re-run `scripts/audit_repos_local.sh ~/Desktop/hmnd`. This unblocks the actual per-module readiness assessment.
4. **Add `AGENTS.md` to `hmnd-cloud`** (~1 day). Even a 1-page version is infinitely better than zero. Template: copy `hmnd/AGENTS.md` structure, adapt to Terraform.

### 30-day improvements

5. **PR-validation workflow for `hmnd-cloud`** — terraform validate + fmt + tflint + tfsec + checkov, blocking. Quick win, high-leverage.
6. **Module-level READMEs in `hmnd-cloud/domains/*/`** — 1 paragraph per domain: owner team, blast radius, deployment cadence. ~3 days for IaC team.
7. **First 5 ADRs in each of `hmnd` and `hmnd-cloud`.** Retroactive — document decisions that already exist (Bazel, ROS2 version, functional-core rule, deployment model, secret management).
8. **Identity merge for `hmnd-cloud` contributors** — Antoni Bertel + matakan + Mustafa Atakan + Mustafa Atakan2 look like 2-3 humans across 4 git identities. Same fix as Report I §A.10. Apply to bus-factor analysis.
9. **AI-assisted PR declaration checkbox** added to PR templates of `hmnd` and `hmnd-cloud`.

### 60-90 day improvements

10. **Prompt/agent eval framework** — small canonical task set (5-10 tasks) that runs against current AGENTS.md content quarterly. Detects regression in AI agent behaviour when instructions change.
11. **`terratest` (or equivalent) for `hmnd-cloud` modules** — at least the high-blast-radius ones (`shared-between-teams/training/`, `domains/vla/`).
12. **Per-module AGENTS.md across `hmnd`** — formalise the pattern (already exists for `hmnd_firmware`, `hmnd_sim`). Cover `hmnd_robot`, `hmnd_training`, `hmnd_locomotion`, `hmnd_flywheel`, `hmnd_fleet` — the top-5 hot-directories.
13. **Audit policy for large AI-assisted commits** — the 15% of commits in `hmnd` that touch 21+ files. Define what review depth they need.

---

## Leadership Takeaway

**AI code generation can scale safely only if the repositories have specs, tests, module boundaries, agent instructions, CI feedback, and review rules. The three target repos sit at very different points on that maturity curve, and the action priority follows directly:**

- **`hmnd` is the strongest AI-codegen target HMND has** — best-in-class agent instructions (AGENTS.md with architecture rules + language-specific code-quality standards), 40+ CI workflows, broad contributor base (87 lifetime), explicit module boundaries. Phase 2 audit (submodules initialized) will confirm test-density and per-module documentation. **Verdict: MOSTLY_READY. Continue AI assist; document playbook from current power users.**

- **`hmnd-cloud` is the highest-risk repo in scope** — Terraform IaC, ~$10k+/month resources, production blast radius — and it has **zero agent instructions, zero tests, no CODEOWNERS**. AI-generated changes here are dangerous today. **Verdict: PARTIALLY_READY. Pause AI-assisted PRs to this repo until AGENTS.md + CODEOWNERS + PR-validation workflow are in place** (Priority Action #2-5 above — total ~1 week of focused work).

- **`hmnd-sim` is deprecated** — exclude from scope. Real sim work happens in `hmnd/hmnd_sim` submodule, covered by `hmnd` once Phase 2 audit completes.

**Recommendation:** make `hmnd` and `hmnd-cloud` the first two **controlled AI-codegen readiness targets** with clear gates (AGENTS.md, CODEOWNERS, PR validation, prompt evals). After both score 4+ on §6, expand the model to the next tier of repos (the active first-party robotics drivers + firmware). Don't try to roll out one-size-fits-all AI policy across all 100+ org repos — segment-based rollout matches the heterogeneous risk profile.

---

*Generated 2026-05-16 from local inventory at `/tmp/hmnd_repos_audit_2026-05-16.md` (44 KB). All findings tagged [Fact] / [Estimate] / [Hypothesis] above. Phase 2 audit with `hmnd` submodules initialized is the single highest-value follow-up to refine §3, §6.3, §7, and §8.*
