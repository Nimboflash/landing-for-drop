# 03 — Communication Architecture

**Purpose.** How the agents form one interconnected organization rather than a pile of disconnected
role prompts. This document is the map; `08` (messages), `09` (handoffs), `10` (blockers/events),
and `07` (state) are the territory.

> **Provenance banner.** Reusable / project-independent. The coordination *substrate* here is
> **Recommended** — the source coordinated through prose documents and structural constraints, not
> structured messages. The escalation edges and interface-as-coordination pattern are **Extracted**.

## The four communication layers

An agent organization that actually works needs four layers, each with its own schema and its own
document:

1. **Messages** (`schemas/message.schema.yaml`, doc `08`) — the request/response traffic between
   agents: assignments, clarifications, reviews, approvals, escalations. Point-to-point, typed,
   acknowledged when consequential.
2. **Handoffs** (`schemas/handoff.schema.yaml`, doc `09`) — the *validated transfer of work* from
   one agent to the next. A handoff is heavier than a message: it carries evidence and is validated,
   not trusted.
3. **Events** (`schemas/event.schema.yaml`, doc `10`) — the notification layer. Something happened
   (`qa_passed`, `security_failed`, `release_ready`); publishers emit, subscribers react, and
   project state updates.
4. **State** (`schemas/project-state.schema.yaml`, doc `07`) — the durable memory that lets any of
   the above resume after an interruption. Messages are transient; state is not.

The source proved you can run a small organization on layers it did not formalize — its
"coordination" was a constitution every agent loaded, ownership lanes, and escalation tables, with a
human sequencing everything. That works at one-human, zero-code scale and fails at the multi-agent,
multi-session scale the source itself aspired to. The four-layer substrate is the Recommended fix,
and it is designed to preserve the source's genuinely good idea: **the interface is the coordination
mechanism** — two agents can work either side of a contract without meeting.

## The correlation thread

A single unit of work threads through all four layers under one `correlation_id`. A
`task_assignment` message opens the thread; `clarification_request`/`information_response` pairs may
branch off it (linked by `reply_to`); a `handoff` closes the implementer's part; a `review_request`/
`review_result` pair gates it; an `approval_request`/`approval_response` pair clears the human
checkpoints; a `completion_notice` ends it. Because every artifact carries `task_id`,
`correlation_id`, and `project_id`, the whole history of a task is reconstructable from the message
and event logs — which is what makes interrupted work resumable and duplicate work detectable.

## Who may talk to whom

Communication is not a free-for-all; it follows the authority and escalation edges fixed in
`04-organization-and-authority.md`. Every active agent has explicit incoming and outgoing rules
(the full per-agent tables live in `08-message-protocol.md`). The shape:

- The **`orchestrator`** is the hub for *scheduling* traffic: it sends `task_assignment` to owners,
  triggers `review_request` to reviewers and gates, and raises `approval_request` to the
  `human-owner`. It receives `handoff`, `blocker_report`, `completion_notice`, and
  `quality_gate_result`. It never sends a message that *decides* scope, architecture, security, or
  release — those originate from their owners.
- **Implementation agents** (`backend-engineer`, `frontend-engineer`, `ml-engineer`, …) receive
  `task_assignment`, send `clarification_request` up the escalation edge, send `dependency_request`
  and `contract_change` sideways to the agents they depend on, and send `handoff` to their
  `handoff_target`. They never approve their own work.
- **`code-reviewer`, `qa-engineer`, `security-engineer`** receive `review_request`, return
  `review_result`/`quality_gate_result`, and — for security — may return a veto. They are addressed
  *because they are independent of the implementer*.
- **`release-manager`** receives independent `quality_gate_result` from QA and security and
  `build_passed` from devops, emits `release_readiness`, and raises the deployment
  `approval_request` to the human.
- The **`human-owner`** receives `approval_request` (as decision-ready summaries, never raw agent
  chatter — see `16`) and returns `approval_response`.

## Mandatory acknowledgement

Most messages are fire-and-proceed. But a message that changes any of the following **must** be
acknowledged by the affected agents before work continues, because silent divergence here is how
parallel agents corrupt each other's assumptions:

- scope
- contracts
- dependencies
- file ownership
- deadlines or execution sequence
- quality requirements
- release status

Acknowledgement is itself a message (`status: acknowledged`); the orchestrator will not advance a
task whose consequential change is unacknowledged. A `contract_change`, in particular, drives the
eight-step procedure in `13-contract-governance.md` and cannot be skipped.

## Failure is a first-class message

The network is designed so that *failure has somewhere to go*. A `rejection` returns incomplete work
to its owner with named reasons; a `blocker_report` names an owner and an escalation path; an
`escalation` climbs the ladder toward a human; an `incident_report` surfaces production problems.
None of these is an exceptional side channel — they are ordinary, schema-conforming messages, which
is what keeps the organization honest under stress. An agent that cannot proceed does not go
silent; it emits.

## Reusable rules (recap)

- Four layers — messages, handoffs, events, state — carry every interaction; each has a schema.
- One `correlation_id` threads a task through all four, making it resumable and auditable.
- Talk along the authority/escalation edges; every active agent has explicit incoming/outgoing rules.
- Consequential changes (scope, contracts, dependencies, ownership, sequence, quality, release) must
  be acknowledged before work continues.
- Failure is a normal, typed message — rejection, blocker, escalation, incident — never silence.
