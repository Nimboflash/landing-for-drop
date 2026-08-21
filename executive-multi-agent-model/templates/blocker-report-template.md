<!-- Conforms to schemas/blocker.schema.yaml. Provenance: Recommended — the source had no
     structured blocker artifact (dependency management scored 0/1.0 in the automation
     assessment, evidence-digest §6); this template gives blocking conditions a trackable,
     escalatable shape. -->

# Blocker Report Template

Raise this whenever a task cannot proceed. A blocker is not the same as a `clarification_request`
— a blocker names a concrete obstruction (a dependency, a failed gate, a missing resource), not an
ambiguous requirement.

---

## Fields

```yaml
schema_version: 1
id: <PLACEHOLDER>
blocking_task: <PLACEHOLDER task_id — the task that cannot proceed>
blocked_tasks: <PLACEHOLDER list of task_ids downstream of blocking_task, if any>
reported_by: <PLACEHOLDER canonical_id>

cause: <PLACEHOLDER — what is actually blocking, stated concretely>
impact: <PLACEHOLDER — what cannot happen, and what is at risk if unresolved (deadline, gate,
  downstream lane)>
responsible_owner: <PLACEHOLDER canonical_id — who can actually resolve this>
required_resolution: <PLACEHOLDER — precisely what needs to happen for the blocker to clear>

severity: <critical|high|medium|low>
suggested_action: <PLACEHOLDER>

escalation_sequence:
  - <PLACEHOLDER canonical_id or "human-owner"> # ordered ladder; see escalation-template.md
  - <PLACEHOLDER>

human_decision_required: <true|false>
evidence_refs: <PLACEHOLDER>
status: <open|acknowledged|in_progress|resolved|rejected|cancelled>
created_at: <PLACEHOLDER ISO-8601>
resolved_at: <PLACEHOLDER ISO-8601 | null>
```

---

## Filled mini-example

```yaml
schema_version: 1
id: BLOCKER-2026-07-13-03
blocking_task: TASK-AB-143
blocked_tasks: [TASK-AB-144, TASK-AB-145]
reported_by: frontend-engineer

cause: >
  The typed client generated from CONTRACT-PRESENCE-v1 does not include a `lastSeenAt` field
  that the frontend presence indicator requires; the contract itself is missing the field.
impact: >
  Frontend cannot implement the "last seen 2 minutes ago" UI state without this field. Two
  downstream frontend tasks (TASK-AB-144, TASK-AB-145) are also blocked since they build on the
  same generated client.
responsible_owner: backend-engineer   # contract owner for CONTRACT-PRESENCE-v1
required_resolution: >
  Add `lastSeenAt` (ISO-8601 timestamp) to the presence payload schema, bump contract_version,
  regenerate the typed client, notify frontend-engineer.

severity: high
suggested_action: "Run the contract-change procedure (see contract-change-template.md) to add the
  field without a breaking change."

escalation_sequence:
  - backend-engineer
  - cto
  - human-owner

human_decision_required: false
evidence_refs:
  - "CONTRACT-PRESENCE-v1 current schema"
  - "Frontend mock showing lastSeenAt usage"
status: open
created_at: 2026-07-13T16:20:00Z
resolved_at: null
```
