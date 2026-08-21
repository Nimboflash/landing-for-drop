<!-- Conforms to schemas/task.schema.yaml. Provenance: Recommended — the source had no task
     artifacts; decomposition below the lane level was conversational and left no record. This
     template supplies the missing middle layer between phase-level exit gates and lane ownership. -->

# Task Assignment Template

One file per task instance. A task is the atomic unit of assigned, trackable work. It is never
marked `completed` on self-report — only on attached gate evidence (design-spine §6, invariant 6).

---

## Identity & lineage

```yaml
schema_version: 1
id: <PLACEHOLDER>                    # e.g. TASK-<project>-<number>
title: <PLACEHOLDER>
project_id: <PLACEHOLDER>
parent_version: <PLACEHOLDER>
parent_milestone: <PLACEHOLDER>
parent_epic: <PLACEHOLDER | null>
parent_feature: <PLACEHOLDER | null>
task_type: <feature|fix|docs|chore|spike|refactor|security|release|review|validation>
```

## Ownership

```yaml
owner_agent: <PLACEHOLDER canonical_id>       # implements the task
reviewer_agent: <PLACEHOLDER canonical_id>    # MUST be independent of owner_agent
approver: <PLACEHOLDER canonical_id or "human:<role>" | null>
priority: <critical|high|medium|low>
status: <PLACEHOLDER — one of the 19 canonical task states, see below>
```

**Canonical task states (19, exact spelling):** `proposed, requirements_analysis,
architecture_required, ready, assigned, in_progress, blocked, implementation_complete,
implementation_review, rework_required, integration, qa, security_review, release_ready,
completed, released, deferred, cancelled, archived`.

Reminder: no agent may move its own implementation task from `in_progress` into any
approval/`completed` state. `in_progress` → `implementation_complete` by the owning agent is a
CLAIM, not an approval — the actual approval states require an independent role.

## Dependencies & blockers

```yaml
dependencies: <PLACEHOLDER list of task ids this depends on>
blockers: <PLACEHOLDER list of active blocker ids, or []>
```

## Inputs & outputs

```yaml
inputs: <PLACEHOLDER — contracts, specs, prior handoffs this task consumes>
expected_outputs: <PLACEHOLDER — concrete artifacts this task must produce>
```

## File ownership grants

```yaml
allowed_files:
  - <PLACEHOLDER glob or path — files this task MAY modify>
restricted_files:
  - <PLACEHOLDER glob or path — files this task MUST NOT touch, even if the owning agent's
     standing lane would otherwise permit it>
```
> A per-task grant may narrow a standing agent lane; it may never widen it.

## Acceptance & quality

```yaml
acceptance_criteria:
  - <PLACEHOLDER — QA-executable, traces to PRD/contract>
test_requirements: <PLACEHOLDER>
security_requirements: <PLACEHOLDER | "none">
documentation_requirements: <PLACEHOLDER | "none">
contract_versions: <PLACEHOLDER — pinned contract_version(s) this task was built against>
```

## Handoff & completion

```yaml
handoff_target: <PLACEHOLDER canonical_id — who receives the handoff.schema.yaml message next>
completion_evidence: <PLACEHOLDER — filled only once available; links to test results, gate
  results, review results>
quality_gate_results: <PLACEHOLDER — filled by gate owners, never by the orchestrator>
retry_count: <PLACEHOLDER integer, default 0>
```

## Timestamps

```yaml
created_at: <PLACEHOLDER ISO-8601>
updated_at: <PLACEHOLDER ISO-8601>
```

---

## Definition of done (task-level, in addition to schema fields)

- [ ] All `acceptance_criteria` traced to evidence, not asserted
- [ ] `reviewer_agent` is independent of `owner_agent` and has returned `pass`
- [ ] All blocking quality gates attached in `quality_gate_results` are green
- [ ] `handoff_target` has been notified via a `handoff` message (see agent-handoff-template.md)
- [ ] Status only reaches `completed` with gate evidence attached — status never outranks gates

---

## Filled mini-example

```yaml
schema_version: 1
id: TASK-AB-142
title: Add WebSocket presence channel
project_id: acme-boards
parent_version: v1.0
parent_milestone: M2-realtime-collaboration
parent_epic: EPIC-realtime-presence
parent_feature: websocket-presence-channel
task_type: feature

owner_agent: backend-engineer
reviewer_agent: code-reviewer
approver: qa-engineer
priority: high
status: in_progress

dependencies: [TASK-AB-138]
blockers: []

inputs: [CONTRACT-PRESENCE-v1, ADR-0004]
expected_outputs:
  - WebSocket presence service implementation
  - Passing unit + integration tests
  - Updated audit log entries

allowed_files:
  - src/realtime/application/**
  - src/realtime/adapters/**
  - tests/realtime/**
restricted_files:
  - src/realtime/domain/**       # domain rules owned by domain-policy-architect, not this task

acceptance_criteria:
  - "Given two connected clients, when client A goes offline, client B receives a presence-update
     event within 2s"
  - "Presence state is not persisted beyond the active session"
test_requirements: Unit tests for connection lifecycle; integration test for multi-client fanout
security_requirements: No PII in presence payload
documentation_requirements: Update docs/api/presence-contract.md
contract_versions: [CONTRACT-PRESENCE-v1]

handoff_target: code-reviewer
completion_evidence: null
quality_gate_results: null
retry_count: 0

created_at: 2026-07-11T09:00:00Z
updated_at: 2026-07-13T14:02:00Z
```
