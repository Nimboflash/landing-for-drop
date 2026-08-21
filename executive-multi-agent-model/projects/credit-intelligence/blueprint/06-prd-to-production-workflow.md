# 06 — PRD-to-Production Workflow (credit-intelligence)

**Purpose.** The credit-intelligence PRD-to-production path, first as the source honestly designed it
(strong top, missing middle, missing tail), then as the reusable optimized lifecycle
(`EXT/11-prd-to-production-workflow.md`) applied stage-by-stage to this project.

> This document applies the framework to the **credit-intelligence evidence** — the reference
> example. Part 1 describes only what the source repository actually specified (Extracted where a
> mechanism existed, Missing where only intent existed) — it is a design, never an observed execution,
> since no PRD ever ran and almost no code exists. Part 2 is the framework's Recommended lifecycle
> configured for this project; it should never be read back into Part 1 as something the source did.

## Part 1 — The extracted original workflow

**Honesty preamble (Extracted, `EXT/09-prd-to-product-workflow.md`).** credit-intelligence has never
executed a PRD-to-product cycle: no PRD instance exists, and `src/` is an empty hexagonal skeleton (all
`__init__.py` files are 0 bytes). What exists is fully specified *intent* — every station names an
owner and a definition of done — but the conveyor belt connecting the stations (task objects,
handoffs, orchestration) does not exist. Reading the 23 designed stages honestly:

### The strong top

- **PRD content bar (stage 2, Extracted).** `product-manager` owns a defined bar: problem statement,
  who it's for, why now, the smallest testable thing, QA-executable acceptance criteria, a proving
  metric, and explicit non-goals. The rule exists in full; no PRD has ever been written against it.
- **Phase exit gates (stages 5, 21, Extracted).** `repo:ROADMAP.md` defines three phases, each with
  exactly one falsifiable exit gate (e.g. Phase 1: *"A design partner says: run this on our next
  cohort"*) and an explicit "do not negotiate back in" OUT list per phase. Final validation against
  the PRD (stage 21) runs through this same gate mechanism, jointly owned by `product-manager` and
  `qa-engineer`, and is stated to be outcome-based: "if the gate fails, the version is not done
  regardless of how much shipped."
- **ADRs (stages 8–9, Extracted).** `cto` owns architecture decisions via the `/adr` skill; "a decision
  that is not an ADR does not exist" is a stated repository rule. `repo:ADR/0001-monorepo.md`,
  `0002-ddd.md`, `0003-event-driven.md` exist and cite each other in sequence.

### The missing middle

Stage-by-stage, the source's own gaps (Missing unless noted):

- **Stage 1 — PRD storage/format**: no mechanism defined.
- **Stage 4 — Assumptions**: only recorded via ADRs; no standing assumption register (Partial).
- **Stage 6 — User stories/acceptance criteria**: the rule exists, no instance was ever produced.
- **Stage 10 — Task decomposition**: conversational only ("always propose the next milestone"); no
  task artifacts.
- **Stage 11 — Dependency calculation**: `repo:ROADMAP.md` names exactly one critical-path item per
  phase; the rest is marked parallelizable/cuttable — a partial mechanism, not a graph.
- **Stage 12 — Task assignment**: standing lanes plus runtime trigger-description selection, not
  per-task assignment.
- **Stage 20 — Release approval**: not found; no role owns it.
- **Stage 23 — Missing-requirement detection**: none.

### The missing tail

- **Stage 19 — DevOps deployable output**: specified in `repo:devops-engineer.md` ("deploy is a single
  reproducible command, and rollback is a single command too") but implemented nowhere — no
  Dockerfile, no compose file, no environments, despite Docker Compose being named as the Phase 1
  runtime.
- No release process, release notes, changelog, rollback mechanism, or hotfix path exists anywhere in
  the repository (`EXT/13-git-devops-release.md`).

### Two stages worth naming precisely

- **Stage 13 — FE/BE contract (Extracted).** Co-owned by `backend-engineer` + `credit-architect` +
  `cto`; the frontend client is *generated* from the schema; a breaking change is a new API version.
  This is the one place the middle layer is real, not missing.
- **Stage 18 — Security review (Extracted).** Owned by `security-architect`, explicitly **before
  building**, with veto authority on the data boundary — the source's distinctive asymmetry, intact at
  the workflow level.

### The distinctive design idea, and its automation cost

The source replaces requirements-traceability with two asymmetric safety nets: falsifiable phase exit
gates at the top, and 8 non-negotiables as standing acceptance criteria at the bottom. This is elegant
and it is measurably incomplete: the automation assessment scores the full 21-stage lifecycle at
**≈37% weighted capability (7.75/21)**, with only **1 of 21 stages fully automated — stage 12, test
execution**, via the CI `check` job running on every push and PR (`repo:.github/workflows/ci.yml`).
Five stages (deploy, release, rollback, post-release validation, dependency management) score zero
implementation. The fair summary the source's own evidence supports: an agent-assisted,
human-orchestrated system with a hard-automated quality floor and a completely manual or absent
delivery tail (`EXT/14-automation-assessment.md`, confidence medium, method-dependent).

## Part 2 — The recommended reusable lifecycle applied to this project

Applying `EXT/11-prd-to-production-workflow.md`'s optimized lifecycle to credit-intelligence, keeping
the strong top, filling the missing middle, and building the missing tail:

| Stage | Responsible (this project) | Gate | Human approval? |
|---|---|---|---|
| Requirements audit | product-manager | requirement-validation vs the existing PRD content bar | — |
| Clarification & assumptions | orchestrator + product-manager | — | high-risk assumptions (e.g. any expansion of the sensitive-data boundary) |
| Product-scope approval | product-manager | — | **yes** |
| Release strategy | release-manager *(Recommended role)* | — | — |
| Version planning | product-manager | one falsifiable exit gate + OUT list — reuses `ROADMAP.md`'s existing three-phase structure | — |
| Architecture | cto | architecture-review; human ratifies the ADR set | major decisions |
| Contract definition | backend-engineer + credit-architect + cto (unchanged from the source's real co-ownership) | contract-tests | — |
| Milestone planning | orchestrator + product-manager | — | — |
| Feature & task decomposition | orchestrator | — | — |
| Dependency mapping | orchestrator | — | — |
| Agent assignment | orchestrator | — | — |
| Implementation | backend-engineer / frontend-engineer / ai-engineer / data-engineer, each in their own module lane | edit-time hooks (`domain-purity.sh`, `format-python.sh`) | — |
| Integration | backend-engineer / devops-engineer | build-verification | — |
| Code review | independent reviewer (formalizes the source's `/pr-check` skill + human review) | review gate | — |
| Automated testing | qa-engineer / test-automation | unit / integration / contract tests — extends the existing CI `check` job | — |
| QA | qa-engineer | QA gate, including the four domain-correctness gates (leakage, replay, stability, monotonicity) wired into CI for the first time | — |
| Security review | security-architect | security gate — **the scoped veto**, exercised before this stage completes, not after | exceptions only |
| Release preparation | release-manager *(Recommended role)* | release-readiness, on independent qa + security + devops evidence | — |
| Human approval | human-owner | — | **yes** |
| Deployment | devops-engineer | deployment-verification | **yes** |
| Post-release validation | release-manager + product-manager | post-release gate vs the phase's falsifiable exit gate | — |
| Closure & lessons | orchestrator + product-manager | — | — |

### Two things this project's evidence requires emphasizing

- **Contract-first FE/BE stays exactly as the source designed it.** The source's real pattern — a
  co-owned, versioned API contract landing before the frontend/backend fan-out, with the frontend
  client generated rather than hand-written — is already the correct shape for the reusable lifecycle's
  "contract definition" stage. Nothing here should be redesigned; it should be preserved and simply
  given a task/handoff record it never had.
- **The pre-build security consultation is sequential, not parallel, by design.** The reusable
  lifecycle's general rule — security review before a data collector or new signal is built — is not a
  generic addition here; it is the source's own most load-bearing sequencing rule, tied directly to the
  scoped veto on the sensitive-data / cross-tenant-boundary question. Any configuration of this
  lifecycle for credit-intelligence that allows implementation to proceed in parallel with, rather than
  after, that consultation reopens the exact risk the veto exists to close.

### What closing the middle and tail would do to the automation number

Per the source's own automation assessment, adding the orchestrator + task/state layer (raising
stages 5–7 from 0.25–0.5 to 0.75), wiring the four domain-correctness gates into CI (raising stage 13
to 1.0), and adding a deploy/release pipeline with a human checkpoint (raising stages 18–21 from 0 to
0.5–0.75) would move the weighted score from ≈37% to an estimated **≈55–60% — while adding human
checkpoints, not removing them** (`EXT/14-automation-assessment.md`). This is the concrete, source-
evidenced target the Part 2 lifecycle is built to reach for this project.

## Reusable rules applied here

- Document the original process honestly first: credit-intelligence's top is genuinely strong (PRD
  bar, exit gates, ADRs) and its middle and tail are genuinely absent — neither should be
  overstated or understated to fit a template.
- The 1-of-21-stages fully-automated fact (CI test execution) and the ≈37% weighted score are the
  project's honest baseline; any claim that more is automated must cite a specific mechanism, not the
  documents that merely specify one.
- Contract-first FE/BE coordination and the pre-build security veto consultation are the two stages
  this project already does correctly at the workflow level — the optimized lifecycle formalizes them
  with task/handoff records, it does not redesign them.
- Filling the middle (tasks, handoffs, state) and building the tail (release, deploy, rollback,
  post-release) is the single highest-leverage change available to this project, by the source's own
  automation evidence.
- A red blocking gate stops the line for this project exactly as it did in the source; the only
  legitimate override remains the one documented case (ai-engineer + product-manager jointly, on the
  domain-quality threshold) — it does not extend to any gate in this table.
