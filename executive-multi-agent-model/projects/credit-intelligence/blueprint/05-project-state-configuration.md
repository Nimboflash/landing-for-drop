# 05 — Project State Configuration (credit-intelligence)

**Purpose.** The source had no project-state mechanism at all; this document specifies the
Recommended state configuration (`EXT/07-project-state-model.md`) for this project, illustrated
against `state/project-state.yaml`.

> This document applies the framework to the **credit-intelligence evidence** — the reference
> example. Every field, ownership rule, and instance value below is a framework **Recommendation**.
> None of it existed in the source repository; the entire project-state layer is classified Missing.
> Nothing here should be read as "credit-intelligence tracked state this way."

## Why this is entirely Missing, and why it matters most here

**Missing, confidence high, `EXT/08-task-and-state-management.md`.** The source had no state file, no
task board, no status field anywhere in the repository. Work was proposed conversationally — "always
propose the next milestone" — and left no artifact once proposed. `EXT/19-evidence-index.md`'s
search-negative attestations confirm this by full-tree listing: no `tasks/`, no `state/`, no
`handoffs/`, no `reports/` directories exist. For a zero-code, single-human-operator, pre-execution
repository, this cost nothing observable. It is also the single gap the automation assessment
identifies as most consequential to close: stages 5–7 (task decomposition, dependency management,
agent assignment) score 0.25–0.5 out of a possible 0.75 largely *because* there is no state layer to
carry a task's context between sessions (`EXT/14-automation-assessment.md`). credit-intelligence is
exactly the kind of multi-agent, multi-session, high-stakes project this gap will bite hardest — real
money, sensitive data, 10 agents, three phases, and (by design) no execution has happened yet, so
this is the ideal point to introduce state before the gap compounds.

## The recommended state configuration

`projects/credit-intelligence/state/project-state.yaml` (illustrative instance, conforming to
`schemas/project-state.schema.yaml`) would hold the framework's fixed field set:

```yaml
project_state:
  schema_version: 1
  project_id: credit-intelligence
  project_name: "Credit Intelligence — AI Credit-Underwriting Engine"
  current_phase: "Phase 1 — Foundation"
  active_version: "v0.1.0-phase1"
  active_milestone: "M1 — decision-api-loan-tape"
  active_tasks: []          # none yet — pre-execution repository
  completed_tasks: []
  blocked_tasks: []
  deferred_tasks: []        # Target-section items: Kafka, K8s, ClickHouse, federated learning, consortium — carried with their migration triggers, not dropped
  active_agents:
    - cto
    - credit-architect
    - product-manager
    - ai-engineer
    - data-engineer
    - backend-engineer
    - frontend-engineer
    - devops-engineer
    - security-architect
    - qa-engineer
  pending_handoffs: []
  pending_reviews: []
  quality_gate_status: {}   # populated once the 4 domain-correctness gates are wired into CI
  human_approvals: {}
  release_status: "unreleased"   # package version 0.1.0, never shipped
  known_risks:
    - "unlicensed cross-tenant data centralization (the scoped veto question)"
    - "Docker Compose + Alembic named as Phase 1 stack, neither exists yet"
  open_decisions: []        # mirrors ADR/0001-0003 plus any new ADR
  contract_versions:
    decision-api: "v1"
  retry_history: []
  incidents: []
  next_actions:
    - "write the first PRD against the product-manager's content bar"
  last_updated_at: "2026-07-13T00:00:00Z"
  last_updated_by: orchestrator
```

This is illustrative, not prescriptive of exact values — the point is the *shape*, populated with this
project's real known facts (the 10-agent roster, the three-phase roadmap, the zero-shipped-version
status, the named risk that maps to the scoped veto).

## Field-level ownership for this project

The guardrail the framework insists on — the orchestrator coordinates state, but does not own the
fields that record approvals and results — applies to credit-intelligence exactly as specified,
mapped onto the real authority holders identified in `02-organization-and-authority.md`:

| Field(s) | Owner | Why (per this project's authority map) |
|---|---|---|
| `active_tasks`, `completed_tasks`, `blocked_tasks`, `deferred_tasks`, `pending_handoffs`, `pending_reviews`, `next_actions`, `current_phase`, `active_agents`, `last_updated_*` | `orchestrator` | Coordination-only fields; scheduling is the orchestrator's entire charter here. |
| `human_approvals` | The relevant approval authority (never `orchestrator`) | E.g. a scope-change approval is written by whoever holds that approval, with `human-owner` as the actual approver of record — the orchestrator only requests it. |
| `quality_gate_status` | `qa-engineer` (merge/promotion, domain-correctness gates), `security-architect` (security gate/veto), `devops-engineer` (build-verification, once it exists) | Mirrors this project's real gate ownership exactly — `qa-engineer`'s gates were already non-overridable in the source; that property must survive into the state file. |
| `release_status` | `release-manager` (Recommended role — see `02-organization-and-authority.md`) | The source had no release role and zero shipped versions; this field's owner is entirely new to the project. |
| `open_decisions` | `cto` (architecture), `credit-architect` (domain policy), `security-architect` (security), each for their own decisions | Mirrors the real `ADR/` authorship pattern from `04-shared-context-configuration.md`. |
| `contract_versions` | Contract owners jointly (`backend-engineer` + `credit-architect` + `cto`) | Matches the real co-ownership of `docs/api/decision-api.md`. |
| Task-level `completion_evidence` | The owning agent for that task | Owning agents write their own evidence; the orchestrator references it, never invents it. |

The orchestrator moving a task's status field (e.g. `in_progress` → `implementation_complete`) is a
scheduling act, not a certification — exactly as the framework specifies. On a project where a bug
"lends someone the wrong amount of money" (the source's own stated stakes, `repo:CONTRIBUTING.md`),
this separation is not a formality: a `completed` status with no attached qa/security gate evidence
must be treated as invalid regardless of who wrote the status field.

## What this configuration enables for this project

- **Resumption.** credit-intelligence's own automation assessment already identifies its human
  operator as the sole holder of continuity — "every piece of work human-initiated"
  (`EXT/14-automation-assessment.md`). A state file lets any of the 10 agents, or a new session, read
  `active_tasks` and `next_actions` and resume without the human re-deriving context from documents
  scattered across `ROADMAP.md`, `ADR/`, and 10 agent files each time.
- **Duplicate-work prevention.** With `active_tasks` and `completed_tasks` populated, an agent checks
  before starting whether a lane's work (e.g. the decision API contract) already exists or is in
  flight — a real risk once more than one implementation agent works the same module concurrently.
- **Retry tracking.** `retry_history` gives the project a record the source never had for its own
  stated review priority order (boundaries → hidden business rules → replayability → PII → test level
  → style) — repeated failures on, say, the replayability check would trip an escalation the source
  had no mechanism to detect.
- **Deferred-work transfer with intact triggers.** The project's own **Target-section pattern** — the
  source's genuinely novel invention (`EXT/23-requirement-decomposition.md`) of writing deferred work
  into the same document with a named migration trigger — maps directly onto `deferred_tasks`. Kafka,
  Kubernetes, ClickHouse, and federated learning are not lost work; they are `deferred_tasks` entries
  each carrying the exact trigger that would fire them (2nd consumer; >3 compose units; OLTP p99
  degradation; Type 2 licence), preserving the source's best planning idea inside the new state layer
  rather than discarding it.

## Reusable rules applied here

- credit-intelligence's project state is entirely Recommended — there is no Extracted state to
  configure around, only real facts (roster, roadmap, ADRs, zero-ship status) to seed illustrative
  values with.
- Field-level ownership mirrors this project's real authority holders exactly: `qa-engineer`'s gates
  stay non-overridable, `security-architect`'s veto-bearing decisions stay outside the orchestrator's
  reach, and the new `release-manager` owns the one field (`release_status`) nothing else in the
  source ever tracked.
- The Target-section pattern — this project's own best planning idea — is the natural fit for
  `deferred_tasks`; the state model should absorb it rather than compete with it.
- Because this is a real-money lending system, "state never outranks gates" is not a stylistic
  preference here — a status flip with no gate evidence is a production risk, not a paperwork gap.
