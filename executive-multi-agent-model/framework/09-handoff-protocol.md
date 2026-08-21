# 09 — Handoff Protocol

**Purpose.** One handoff format for the whole organization, the fifteen checks the receiver runs, and
the five outcomes it may return. A handoff is validated, never trusted.

> **Provenance banner.** The formal handoff artifact is **Recommended** — the source had *no* handoff
> objects; work crossed lanes through shared documents (`EXT/07-collaboration-and-handoffs.md`,
> classified Missing). The validation discipline reflects the source's Extracted "verify, don't tick"
> review culture.

## Why handoffs are heavier than messages

A message asks or tells; a handoff *transfers responsibility for work*. When
`backend-engineer` hands an implemented endpoint to `frontend-engineer`, or `ml-engineer` hands a
model to `qa-engineer`, the receiver is about to build on, gate, or ship that work. If the handoff is
incomplete and the receiver proceeds anyway, the defect propagates silently — the exact failure this
protocol exists to prevent. So a handoff carries evidence, and the receiver validates it before
accepting.

## The handoff record

Every handoff conforms to `schemas/handoff.schema.yaml` and carries: `schema_version, id, from_agent,
to_agent, task_id, project_id, version, milestone, feature, summary, original_requirements,
completed_work, outputs, changed_files, decisions, assumptions, contracts, acceptance_criteria_status,
automated_test_results, manual_test_results, quality_gate_results, known_issues, unresolved_questions,
risks, required_next_action, recommended_next_agent, approval_required, evidence_refs,
proposed_state_changes, created_at`.

## The fifteen validation checks

The receiving agent validates, in order: (1) task identity, (2) scope, (3) required inputs, (4)
acceptance criteria, (5) relevant decisions, (6) dependencies, (7) output locations, (8) contract
versions, (9) changed files, (10) tests, (11) risks, (12) remaining work, (13) approval status, (14)
evidence references, and (15) project-state changes. Each check asks the same underlying question:
*is what I need to proceed actually here and consistent?* A handoff that claims tests passed without
`automated_test_results`, or that changes a contract without a matching `contracts` version, fails
validation.

## The five outcomes

The receiver returns **exactly one** status:

- **`accepted`** — everything validates; the receiver takes ownership and proceeds.
- **`accepted_with_conditions`** — usable, but with named follow-ups the sender still owns; the
  conditions are recorded in state.
- **`rejected_incomplete`** — a required field, artifact, or check failed; the work returns to the
  sender.
- **`blocked_by_dependency`** — the handoff is fine but an external dependency prevents proceeding;
  the dependency becomes a blocker (`10`).
- **`requires_human_decision`** — proceeding needs a human call; an `approval_request` is raised
  (`16`).

## An incomplete handoff is never silently repaired

This is the load-bearing rule. If the receiver could quietly fix a missing test, patch a
contract mismatch, or fill in an absent acceptance-criteria status, the handoff discipline would
collapse — senders would learn they can hand off half-done work and someone downstream will finish
it. So the receiver **must not** repair; it must reject. A `rejected_incomplete` names, precisely:

- the missing field,
- the missing artifact,
- the failed validation,
- the required correction,
- the responsible agent, and
- the blocking status.

The task returns to `rework_required` (see the task state machine in `11`), the reason is written to
`retry_history` in project state, and the sender submits a fresh handoff. Acceptance criteria do not
change during rework unless formally re-approved — a reviewer cannot lower the bar to make a
rejection go away.

## Handoffs and independent review

A handoff into a review or gate state always goes to an agent **independent of the implementer**
(`code-reviewer`, `qa-engineer`, `security-engineer`). This is where the handoff protocol and
separation of duties meet: the implementer may *claim* completion (`in_progress →
implementation_complete`), but only an independent receiver moves the work forward. No agent hands
its own work off to itself for approval.

## Reusable rules (recap)

- One handoff format organization-wide; it carries evidence, not just a summary.
- The receiver runs all fifteen checks and returns exactly one of five statuses.
- An incomplete handoff is rejected with named reasons — never silently repaired.
- Rejection returns the task to its owner and records the reason; acceptance criteria stay fixed.
- Handoffs into review/gate states go to agents independent of the implementer.
