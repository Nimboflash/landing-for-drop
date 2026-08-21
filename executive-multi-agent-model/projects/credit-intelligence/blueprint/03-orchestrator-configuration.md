# 03 — Orchestrator Configuration (credit-intelligence)

**Purpose.** What actually coordinated credit-intelligence (no orchestrator agent), and how the
reusable orchestrator (`EXT/05-orchestrator-specification.md`) would be configured if this project
adopted it.

> This document applies the framework to the **credit-intelligence evidence** — the reference
> example. The first section describes real repository facts (Extracted / Missing). The
> configuration section is a framework **Recommendation**: it was never built, staffed, or run in the
> source. Nothing in this document should be read as "credit-intelligence had an orchestrator."

## Original coordination: no orchestrator (Missing)

**Missing, confidence high** — searched for, not found (`EXT/06-orchestrator-analysis.md`,
`EXT/19-evidence-index.md` finding #6). credit-intelligence had no scheduling agent, no task board, no
dispatch mechanism, and no dynamic coordination layer of any kind. What existed instead were four
structural mechanisms, three documentary and one human:

1. **The constitution** (`repo:PROMPT.md`) — loaded by every agent at session start via
   `repo:CLAUDE.md`. It fixed the mission, the four constraining facts, the eight non-negotiables, the
   Phase 1 / Target split, and the 10-agent roster. It coordinated by *constraining*, never by
   *scheduling*. **Extracted.**
2. **The roadmap** (`repo:ROADMAP.md`) — the only plan artifact in the repository. Three phases, each
   with one falsifiable exit gate; Phase 1 named exactly one critical-path item ("the loan tape") with
   the remaining six items marked "parallelizable and, if necessary, cuttable." Sequenced by risk to
   company survival, not by task list or dependency graph. **Extracted.**
3. **Per-agent trigger descriptions** — each of the 10 agent files carried a one-line "use proactively
   for…" clause that the Claude Code runtime used to select which subagent to delegate to. This is the
   closest thing to automated task *assignment* the repository had — and it is a delegation heuristic,
   not a scheduler. **Extracted.**
4. **The human operator** — initiated every piece of work (no scheduler existed to do it
   automatically), merged every PR, and would have approved every release, had one occurred
   (`EXT/14-automation-assessment.md`: "every piece of work human-initiated… everything post-merge
   human/unassisted/undefined"). **Extracted by elimination.**

The verdict the source evidence supports: **strong static coordination, zero dynamic orchestration.**
The repository substituted structure (lanes, gates, a constitution) for scheduling, and that
substitution held up remarkably well for a pre-code, single-human-operator project. It has no answer
for multi-agent, multi-session work: no task object recorded who was assigned what; no handoff
artifact existed to hand work between agents; no state file let a new session resume cold; nothing
tracked a retry. This is precisely the gap doc `EXT/09-prd-to-product-workflow.md` calls "the missing
middle," and it is the reason the orchestrator is Recommended rather than optional.

## Configuring the orchestrator for this project (Recommended)

If credit-intelligence adopted the reusable orchestrator, it would be configured as follows.

### What it would intake

- **`repo:ROADMAP.md`**, as-is — its three-phase structure, one critical-path item per phase, and
  falsifiable exit gates map directly onto the orchestrator's `version` / `milestone` intake without
  modification. The orchestrator would not replace the roadmap; it would parse it into
  `active_version` / `active_milestone` state and track the critical-path item as the primary
  dependency chain.
- **A real PRD** — none was ever written against the PM's defined content bar (problem / who / why-now
  / smallest-testable-thing / QA-executable acceptance criteria / proving metric / explicit non-goals;
  `EXT/09-prd-to-product-workflow.md` stage 2). The orchestrator's first act on this project would be
  to receive that PRD, validate it against the bar the `product-manager` already owns, and — only if
  it clears — begin decomposition. An orchestrator that decomposes a PRD that hasn't cleared the bar
  reproduces the gap it's meant to close.

### Which agents it activates

credit-intelligence matches the framework's **`data_or_ai` profile with `high_risk` / `regulated`
overlays** (real-money lending decisions, sensitive partner data, an unlicensed-centralization legal
constraint). Under that profile the orchestrator would activate:

- Always-on core: `orchestrator`, `product-manager`, `cto`, `backend-engineer`, `qa-engineer`,
  `security-architect` (canonical `security-engineer`), `human-owner`.
- `data_or_ai` additions: `ai-engineer` (canonical `ml-engineer`), `data-engineer`.
- `high_risk` / `regulated` additions: `release-manager` (Recommended — the source had none),
  `documentation-engineer` (Recommended — doc governance existed as rules, not as a role), elevated
  `security-architect` involvement, and the full domain-correctness gate suite (leakage, replay,
  stability, monotonicity) wired into CI rather than left as paper gates.
- `frontend-engineer` and `devops-engineer` activate as standard implementation lanes (both existed in
  the real roster).
- `credit-architect` (canonical `domain-policy-architect`) activates as the domain-policy owner —
  distinct from `ai-engineer`, since the source's own lane split separates model outputs (probability)
  from business decisions (threshold, limit, term).

### Its charter on this project

Applying `EXT/05-orchestrator-specification.md` verbatim: the orchestrator would receive the PRD,
detect missing requirements against the PM's bar, coordinate clarification, select and activate the
agents above, create the version/milestone/task objects the roadmap never had, map the one named
critical-path dependency plus the six parallelizable items, enforce file/schema ownership per module
(`ingest`, `features`, `decision`, `explain`), validate handoffs between agents, trigger the
independent reviewer and the qa/security gates, and update only its own coordination fields in
`project-state.yaml` (see `05-project-state-configuration.md`). It would summarize internal
disagreements for the `human-owner` as decision-ready requests rather than resolving them itself.

### Its restrictions on this project

The orchestrator may not, under any configuration: approve its own scheduling work as complete;
reprioritize the `product-manager`'s scope (e.g. decide Phase 2 starts early); approve or draft
architecture in place of `cto`; override a failed CI-class gate (secret-scan, layering test, or any of
the four domain-correctness gates once wired into CI); clear a `security-architect` exception or the
scoped veto; approve production deployment (undesigned in the source, but if built, this stays with
`human-owner` + `devops-engineer` execution); or mark an `implementation_complete` task `completed`
without qa/security gate evidence attached. These restrictions are not new to this project — they are
the framework's absolute guardrails, restated here because this project's stakes (lending decisions,
sensitive partner data) make an orchestrator overreach especially costly.

### Boundary against the real authority holders

- **vs `credit-architect` / `domain-policy-architect`** — the orchestrator schedules domain-policy
  tasks (e.g. "define the new limit-adjustment rule") and records the resulting ADR into state; it
  never sets the threshold, limit, or term itself. That judgment belongs to `credit-architect` alone.
- **vs `cto`** — the orchestrator schedules architecture-track tasks (ADR drafting, migration-trigger
  review) and tracks which triggers have fired; it never approves an ADR or changes a bounded-context
  boundary. Only `cto` may do that (`repo:DOMAINS.md`).
- **vs `security-architect`** — the orchestrator routes the mandatory pre-build security consultation
  and records the veto decision (with its required alternative) into the decision log; it has no
  power to clear, waive, or narrow the veto. The veto is scoped to exactly one question
  (sensitive-data / cross-tenant-boundary) and the orchestrator's role is limited to making sure that
  consultation happens *before* the relevant work starts, never after.
- **vs `qa-engineer`** — the orchestrator triggers the merge/promotion gates and the four domain-
  correctness checks; it never overrides a red result or edits a gate's recorded outcome. Gates stay
  non-overridable exactly as they were in the source.

## Reusable rules applied here

- credit-intelligence is the cleanest available evidence that structure can substitute for scheduling
  at small scale — and the clearest evidence of where that substitution runs out (multi-agent,
  multi-session work with no state, no handoffs, no retries).
- Configuring the orchestrator for this project means intaking the roadmap as-is and a PRD that
  clears the PM's existing bar — not inventing a new plan artifact.
- The `data_or_ai` + `high_risk`/`regulated` profile activates `ai-engineer`, `data-engineer`,
  `release-manager`, and `documentation-engineer` on top of the always-on core; a project this size
  and risk profile must not run on the `minimal` profile.
- The orchestrator's charter and restrictions are unmodified by this project's stakes; if anything,
  the restrictions matter more here because the domain is real-money lending.
- The orchestrator never touches the scoped veto, the domain-policy threshold, or the architecture
  boundary — those three remain exactly where the source evidence puts them.
