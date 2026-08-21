# 07 — Project State Model

**Purpose.** The persistent, machine-readable memory that lets interrupted work resume, prevents
duplicate work, tracks retries, and keeps an auditable history — without letting the coordinator own
what it should not.

> **Provenance banner.** The project-state layer is **Recommended** — the source had none
> (`EXT/08-task-and-state-management.md`, classified Missing). The design principle it embodies —
> *completion is defined by gates, not by flipping a status field* — is **Extracted**.

## Why state, and why the source lacked it

The reference repository had no task or project-state system at all: no state file, no task board, no
status fields anywhere. Work was proposed conversationally and left no trace; "docs are the memory."
That is survivable at zero-code, one-human scale and fails at exactly the multi-agent, multi-session
scale the repository aspired to — nothing recorded who did what, what remained, or what had already
been attempted. The Recommended fix is a single, resumable, machine-readable state file, plus
append-only history for consequential changes.

Crucially, the state model preserves the source's best idea rather than replacing it: **a task
reaches `completed` only with gate evidence attached.** State fields never outrank gates. The state
file records that the evidence exists; it does not *become* the evidence.

## The state record

`projects/<slug>/state/project-state.yaml` (conforms to `schemas/project-state.schema.yaml`) holds:

```yaml
project_state:
  schema_version:      # fixed per framework generation
  project_id:
  project_name:
  current_phase:
  active_version:
  active_milestone:
  active_tasks:        # ids + status
  completed_tasks:
  blocked_tasks:
  deferred_tasks:
  active_agents:
  pending_handoffs:
  pending_reviews:
  quality_gate_status: # gate id -> pass/fail/pending
  human_approvals:     # approval id -> status
  release_status:
  known_risks:
  open_decisions:
  contract_versions:
  retry_history:
  incidents:
  next_actions:
  last_updated_at:
  last_updated_by:
```

## Field-level ownership (the guardrail)

The orchestrator may *coordinate* state updates, but it must **not** have unrestricted authority over
the fields that record approvals and results. Ownership is therefore assigned per field:

- **Orchestrator writes** the coordination fields: `active_tasks`, `completed_tasks`,
  `blocked_tasks`, `deferred_tasks`, `pending_handoffs`, `pending_reviews`, `next_actions`,
  `current_phase`, `active_agents`, `last_updated_at`, `last_updated_by`.
- **Approval authorities write** `human_approvals` (never the orchestrator).
- **Gate owners write** `quality_gate_status` (`qa-engineer`, `security-engineer`, `devops-engineer`
  for their gates).
- **`release-manager` writes** `release_status`.
- **Decision and contract owners write** `open_decisions` and `contract_versions`.
- **Owning agents write** their own task `completion_evidence` (referenced from the task, not
  invented by the coordinator).

The orchestrator moving a task's *status* field is a scheduling act; it does not certify the
underlying result. A `completed` status with no matching gate evidence is invalid regardless of who
wrote it.

## Append-only history

Consequential changes — approvals, gate results, security decisions, version transitions, retries —
are recorded append-only. `retry_history`, `human_approvals`, `quality_gate_status`, and `incidents`
grow; they are not overwritten. This is the source's reproducibility doctrine ("any historical
decision attributable to an exact set of pinned artifacts") applied to the agents' own actions, and
it is what makes an audit possible after the fact.

## What the state enables

- **Interrupted-session recovery** — a new session reads `project-state.yaml`, finds `active_tasks`,
  `pending_handoffs`, and `next_actions`, and resumes without re-deriving everything.
- **Task resumption** — each task carries enough context (inputs, allowed files, acceptance criteria)
  to continue.
- **Duplicate-work prevention** — before starting, an agent checks whether a task already exists in
  `active_tasks`/`completed_tasks`.
- **Blocked-task recovery** — `blocked_tasks` plus the blocker records (`10`) make it clear what must
  clear before work resumes.
- **Retry tracking** — `retry_history` records each rework loop and its reason; repeated failures
  trip the escalation threshold in the profile.
- **Deferred-work transfer** — `deferred_tasks` carry work into a later version with its forcing
  condition intact (the Target-section pattern; see `12`).
- **Version transitions and audit/approval/gate history** — the append-only fields make each
  transition and approval reconstructable.

## Staleness

`last_updated_at` is the health signal. State older than one working day past a known change is
suspect: it usually means an agent proceeded without writing back, which the orchestrator treats as a
process fault to investigate, not as ground truth.

## Reusable rules (recap)

- Keep one resumable, machine-readable state file; the source's lack of one was its highest-impact
  gap.
- Assign every field an owner; the orchestrator owns coordination fields only, never approvals,
  gates, security, or release results.
- Completion requires attached gate evidence — state never outranks gates.
- Record consequential changes append-only; supersede, never overwrite.
- Treat stale state as a process fault, not as truth.
