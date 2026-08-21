<!-- Conforms to schemas/message.schema.yaml. Provenance: Recommended — the source coordinated
     through documents and standing lanes, not a structured message envelope. This template
     formalizes the coordination layer the reusable framework needs. -->

# Agent Message Template

The universal envelope for all inter-agent and agent-to-human communication. `schema_version: 1`.
Every one of the 19 message types below uses this SAME envelope shape — only which fields are
populated (and the `type` value) changes.

## The 19 supported types

`task_assignment`, `clarification_request`, `information_response`, `dependency_request`,
`contract_change`, `review_request`, `review_result`, `handoff`, `rejection`, `blocker_report`,
`escalation`, `approval_request`, `approval_response`, `quality_gate_result`, `release_readiness`,
`incident_report`, `state_change_request`, `state_change_result`, `completion_notice`.

## Envelope fields (fixed order — do not reorder)

```yaml
schema_version: 1
id: <PLACEHOLDER>                  # unique message id
correlation_id: <PLACEHOLDER>      # ties a thread of related messages together
reply_to: <PLACEHOLDER | null>     # id of the message this one replies to, if any
type: <PLACEHOLDER>                # one of the 19 types above
from_agent: <PLACEHOLDER>          # canonical_id or "human:<role>"
to_agent: <PLACEHOLDER>            # canonical_id or "human:<role>"
task_id: <PLACEHOLDER | null>
project_id: <PLACEHOLDER>
project_version: <PLACEHOLDER>
milestone: <PLACEHOLDER | null>
feature: <PLACEHOLDER | null>
subject: <PLACEHOLDER>             # one-line summary
context: <PLACEHOLDER>             # background needed to act on this message
requested_action: <PLACEHOLDER>    # what the recipient must do
required_inputs: <PLACEHOLDER | []>
expected_output: <PLACEHOLDER>
priority: <critical|high|medium|low>
due_sequence: <PLACEHOLDER | null> # ordering hint, not a calendar date
dependencies: <PLACEHOLDER | []>
blocking: <true|false>
approval_required: <true|false>
evidence_refs: <PLACEHOLDER | []>
artifact_refs: <PLACEHOLDER | []>
proposed_state_changes: <PLACEHOLDER | []>   # project-state fields this message asks to change
status: <open|acknowledged|in_progress|resolved|rejected|cancelled>
created_at: <PLACEHOLDER ISO-8601>
acknowledged_at: <PLACEHOLDER ISO-8601 | null>
resolved_at: <PLACEHOLDER ISO-8601 | null>
```

**priority** enum: `critical | high | medium | low`.
**status** enum: `open | acknowledged | in_progress | resolved | rejected | cancelled`.

**Acknowledgement is REQUIRED** whenever a message changes: scope, contracts, dependencies, file
ownership, deadlines/sequence, quality requirements, or release status. Silence is not acceptance.

---

## Filled example — `task_assignment`

```yaml
schema_version: 1
id: MSG-2026-07-13-014
correlation_id: THREAD-AB-142
reply_to: null
type: task_assignment
from_agent: orchestrator
to_agent: backend-engineer
task_id: TASK-AB-142
project_id: acme-boards
project_version: v1.0
milestone: M2-realtime-collaboration
feature: websocket-presence-channel
subject: Implement WebSocket presence channel per approved contract
context: >
  Contract CONTRACT-PRESENCE-v1 was approved by cto and backend-engineer on 2026-07-11.
  Frontend client generation is blocked on this implementation landing.
requested_action: >
  Implement the presence channel service per CONTRACT-PRESENCE-v1, within allowed_files for
  this task, and hand off to code-reviewer when implementation_complete.
required_inputs:
  - contract: CONTRACT-PRESENCE-v1
  - architecture_boundary: ADR-0004
expected_output: >
  Working service code, passing unit + integration tests, updated audit log entries, a handoff
  message to code-reviewer.
priority: high
due_sequence: after TASK-AB-138
dependencies:
  - TASK-AB-138
blocking: true
approval_required: false
evidence_refs:
  - ADR-0004
artifact_refs: []
proposed_state_changes:
  - field: active_tasks
    change: add TASK-AB-142
status: open
created_at: 2026-07-13T14:02:00Z
acknowledged_at: null
resolved_at: null
```
