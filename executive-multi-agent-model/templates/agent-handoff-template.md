<!-- Conforms to schemas/handoff.schema.yaml. Provenance: Recommended — the source coordinated
     lane-to-lane transfer of work informally (no task/handoff/state layer existed); the receiver-
     validation discipline and 5-status contract below formalize the "an incomplete handoff is
     never silently repaired" principle so it is enforceable rather than aspirational. -->

# Agent Handoff Template

A handoff is how completed work moves from one agent to the next. It is NOT a status update — it
is a structured artifact the receiving agent validates before accepting responsibility.

---

## Full handoff fields (schema_version 1)

```yaml
schema_version: 1
id: <PLACEHOLDER>
from_agent: <PLACEHOLDER canonical_id>
to_agent: <PLACEHOLDER canonical_id>
task_id: <PLACEHOLDER>
project_id: <PLACEHOLDER>
version: <PLACEHOLDER>
milestone: <PLACEHOLDER>
feature: <PLACEHOLDER | null>

summary: <PLACEHOLDER — one paragraph, what was done and why it matters>
original_requirements: <PLACEHOLDER — link or restate what this task was asked to deliver>
completed_work: <PLACEHOLDER — enumerate what was actually built/changed>
outputs: <PLACEHOLDER — concrete artifacts produced>
changed_files: <PLACEHOLDER list of file paths>
decisions: <PLACEHOLDER — any decisions made during the work, with rationale; link ADRs if any>
assumptions: <PLACEHOLDER — anything assumed rather than confirmed>
contracts: <PLACEHOLDER — contract ids + versions this work was built against or changed>
acceptance_criteria_status: <PLACEHOLDER — each acceptance criterion + met/not-met>
automated_test_results: <PLACEHOLDER — link or summary + pass/fail>
manual_test_results: <PLACEHOLDER — if any, or "none performed">
quality_gate_results: <PLACEHOLDER — gate name + result, populated only by the gate owner>
known_issues: <PLACEHOLDER — anything left imperfect, named explicitly>
unresolved_questions: <PLACEHOLDER — open clarification_requests, if any>
risks: <PLACEHOLDER — anything the next agent should be alert to>
required_next_action: <PLACEHOLDER — what the receiving agent must do first>
recommended_next_agent: <PLACEHOLDER canonical_id>
approval_required: <true|false>
evidence_refs: <PLACEHOLDER>
proposed_state_changes: <PLACEHOLDER — project-state fields this handoff proposes to change>
created_at: <PLACEHOLDER ISO-8601>
```

---

## Receiver validation (15 checks)

The receiving agent MUST check all 15 before accepting. This is not optional and not a formality —
"verify, don't tick."

1. Task identity matches (`task_id`, `project_id`, `version` line up with what receiver expects)
2. Scope matches what was assigned — no silent scope drift
3. All `required inputs` for the next stage are actually present, not just named
4. `acceptance_criteria_status` is complete and each item is evidenced, not asserted
5. `decisions` are recorded with rationale, not just stated as fact
6. `dependencies` this task had are actually resolved
7. Output locations match where the receiver will actually look
8. `contracts` versions match what the receiver is building against
9. `changed_files` list is complete and matches actual diff
10. Test results are present and readable (not "tests pass" with no artifact)
11. `risks` section is populated or explicitly states "none identified"
12. `known_issues` / remaining work is enumerated, not implied
13. `approval_required` is correctly set and, if true, approval is attached or pending
14. `evidence_refs` resolve to real artifacts
15. `proposed_state_changes` are consistent with current `project-state.yaml`

## Return statuses (return EXACTLY ONE)

- `accepted` — all 15 checks pass; receiver takes ownership
- `accepted_with_conditions` — receiver takes ownership but records named conditions that must be
  resolved alongside the next stage of work
- `rejected_incomplete` — one or more checks failed; work returns to `from_agent`
- `blocked_by_dependency` — checks may pass but an external dependency (another task, a pending
  approval) prevents proceeding
- `requires_human_decision` — the gap found is not something any agent can resolve alone

> An incomplete handoff is never silently repaired by the receiver. If something is missing, it
> goes back with a named gap — the receiver does not fill it in and proceed as if it had arrived
> complete.

## Rejection block (required when status is `rejected_incomplete`)

```yaml
rejection:
  missing_field: <PLACEHOLDER — exact field name, or "none">
  missing_artifact: <PLACEHOLDER — exact artifact, or "none">
  failed_validation: <PLACEHOLDER — which of the 15 checks failed and how>
  required_correction: <PLACEHOLDER — precisely what from_agent must do>
  responsible_agent: <PLACEHOLDER canonical_id — who must fix it, usually from_agent>
  blocking_status: <true|false>
```

---

## Filled example

```yaml
schema_version: 1
id: HANDOFF-2026-07-13-01
from_agent: backend-engineer
to_agent: code-reviewer
task_id: TASK-AB-142
project_id: acme-boards
version: v1.0
milestone: M2-realtime-collaboration
feature: websocket-presence-channel

summary: >
  Implemented the WebSocket presence channel per CONTRACT-PRESENCE-v1. Presence updates fan out
  to all connected clients in a board within 2 seconds of a connect/disconnect event.
original_requirements: TASK-AB-142 acceptance criteria (see task record)
completed_work:
  - Presence service (connect/disconnect lifecycle, fanout)
  - Integration with existing board WebSocket gateway
  - Audit log entries for presence state changes
outputs:
  - src/realtime/application/presence_service.py
  - src/realtime/adapters/ws_presence_gateway.py
changed_files:
  - src/realtime/application/presence_service.py
  - src/realtime/adapters/ws_presence_gateway.py
  - tests/realtime/test_presence_service.py
decisions:
  - "Presence state is held in-memory per board, not persisted — matches CONTRACT-PRESENCE-v1
     §2 explicitly."
assumptions:
  - "Assumed max 50 concurrent clients per board based on existing board-size contract; not yet
     load-tested beyond that."
contracts:
  - CONTRACT-PRESENCE-v1
acceptance_criteria_status:
  - criterion: "presence-update within 2s of disconnect"
    status: met
    evidence: tests/realtime/test_presence_service.py::test_fanout_latency
  - criterion: "presence state not persisted beyond session"
    status: met
    evidence: code review of presence_service.py (no persistence adapter imported)
automated_test_results: "12/12 passing — see CI run attached in evidence_refs"
manual_test_results: "none performed"
quality_gate_results: null   # not yet run — pending code-reviewer, then qa-engineer
known_issues:
  - "No load test yet beyond 50 concurrent clients"
unresolved_questions: []
risks:
  - "Fanout implementation uses a naive broadcast loop; may need optimization if board size
     limits are raised later"
required_next_action: "Independent code review against CONTRACT-PRESENCE-v1 and CODING_STANDARDS"
recommended_next_agent: code-reviewer
approval_required: false
evidence_refs:
  - "CI run #4021"
proposed_state_changes:
  - field: pending_reviews
    change: "add TASK-AB-142 → code-reviewer"
created_at: 2026-07-13T15:40:00Z
```

**Receiver (code-reviewer) response:** `accepted_with_conditions` — all 15 checks pass; condition
recorded: "flag the naive broadcast loop as a tech-debt note for test-automation-engineer to load-
test before the board-size limit changes." No rejection block needed.
