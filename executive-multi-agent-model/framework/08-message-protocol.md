# 08 — Message Protocol

**Purpose.** The standard, machine-readable message every agent sends and receives, the nineteen
message types, and the per-agent rules that turn a roster into a network.

> **Provenance banner.** The structured message layer is **Recommended** — the source passed context
> through shared documents, not typed messages (`EXT/07-collaboration-and-handoffs.md`). The
> escalation and clarification *behaviors* the messages encode are **Extracted**.

## The message envelope

Every message conforms to `schemas/message.schema.yaml`, `schema_version: 1`, with fields in this
fixed order: `schema_version, id, correlation_id, reply_to, type, from_agent, to_agent, task_id,
project_id, project_version, milestone, feature, subject, context, requested_action, required_inputs,
expected_output, priority, due_sequence, dependencies, blocking, approval_required, evidence_refs,
artifact_refs, proposed_state_changes, status, created_at, acknowledged_at, resolved_at`.

`priority` is `critical | high | medium | low`. `status` is `open | acknowledged | in_progress |
resolved | rejected | cancelled`. `correlation_id` threads a whole unit of work; `reply_to` links a
response to its request. `proposed_state_changes` lets a message *propose* a state edit that the
field's owner (per `07`) must apply — an implementation agent proposes its evidence; it does not
write approval fields itself.

## The nineteen message types

| type | from → to | what it does |
|---|---|---|
| `task_assignment` | orchestrator → owner | assigns a task with its lane, inputs, acceptance criteria |
| `clarification_request` | any → owner of the answer | asks a blocking question before proceeding |
| `information_response` | responder → asker | answers a clarification (linked by `reply_to`) |
| `dependency_request` | agent → dependency owner | asks for an artifact/decision another agent owns |
| `contract_change` | contract owner → affected agents | proposes a change to a shared contract (drives `13`) |
| `review_request` | orchestrator → independent reviewer | requests code/QA/security/contract review |
| `review_result` | reviewer → requester | returns pass / fail / pass_with_conditions + findings |
| `handoff` | owner → next agent | transfers validated work (drives `09`) |
| `rejection` | reviewer/receiver → owner | returns incomplete work with named reasons |
| `blocker_report` | any → orchestrator + owner | reports a blocker with an escalation path (`10`) |
| `escalation` | any → next up the ladder | climbs the escalation matrix toward a human |
| `approval_request` | orchestrator/owner → approver | requests a decision (human as decision-ready summary) |
| `approval_response` | approver → requester | grants / conditions / rejects / vetoes |
| `quality_gate_result` | gate owner → orchestrator | records a gate pass/fail |
| `release_readiness` | release-manager → human-owner | presents the independent evidence bundle |
| `incident_report` | any → orchestrator + owners | surfaces a production or process incident |
| `state_change_request` | any → field owner | proposes a change to an owned state field |
| `state_change_result` | field owner → requester | applies or rejects a proposed state change |
| `completion_notice` | owner → orchestrator | signals a task's work is finished and evidence attached |

## Per-agent communication rules

Every active agent's definition (`schemas/agent.schema.yaml`) fixes its communication surface, so the
network is explicit, not emergent. For each agent, the definition states: who may send work to it
(`receives_work_from`); who it may send work to (`sends_work_to`); the message types it accepts
(`supported_message_types`); the artifacts an incoming message must carry (`handoff_requirements`,
`required_inputs`); the responses it must produce; how it validates a response; how it reports
failure; how it asks for clarification; how it escalates; and what evidence it attaches on
completion. A message addressed to an agent that does not accept that type, or that omits a required
artifact, is rejected — the same discipline as handoff validation (`09`), applied to ordinary
traffic.

The escalation and clarification *behaviors* these fields encode are Extracted from the source's per-
agent escalation tables (question pattern → named agent) and its cultural rule to "challenge the
request before satisfying it." The message layer makes those behaviors executable and logged.

## Mandatory acknowledgement

A message that changes scope, contracts, dependencies, file ownership, deadlines or execution
sequence, quality requirements, or release status **must be acknowledged** by the affected agents
before work continues (`acknowledged_at` set, `status: acknowledged`). The orchestrator will not
advance a task whose consequential change is unacknowledged. This is the mechanism that stops two
parallel agents from silently building against different versions of the same assumption.

## Reusable rules (recap)

- One typed envelope for all traffic; nineteen message types cover the full lifecycle.
- Each agent's definition fixes who it hears from, who it speaks to, and which types it accepts.
- A message may *propose* a state change; only the field's owner applies it.
- Consequential-change messages must be acknowledged before work continues.
- A malformed or unauthorized message is rejected, not silently accepted.
