# 08 — Task and Handoff Model

**Purpose.** Specify the task, state, and handoff layer credit-intelligence needs but never built,
using the framework's 19-state task machine and handoff protocol, adapted to this project's real
escalation surfaces (credit thresholds, data-collection legality, untestable design).

> This document applies the task/handoff/state framework to the credit-intelligence EVIDENCE. The
> source has **no task objects, no handoff artifacts, no state file** — `EXT/09-prd-to-production-workflow.md`
> and `EXT/19-evidence-index.md` (#6) record this as a direct search-negative: "no task artifacts," "no
> orchestrator artifact." Everything below is therefore the framework's **Recommended** specification
> for this project, not a reconstruction of something that existed.

## Why this is entirely Recommended

`credit-intelligence` is "docs-first / pre-code": every station in its 23-stage designed workflow has
an owner and a definition of done, but "the conveyor belt between stations (task objects, handoffs,
orchestration) does not exist." Work would be assigned to standing agent **lanes**, not per-task, and
progress would be tracked conversationally ("always propose the next milestone"), leaving no artifact.
This document specifies what should exist before Version 1 work starts, so that the framework's other
guarantees (gates over status, no self-approval, independent review) have something to attach to. —
*Classification: Missing (source) / Recommended (this spec). Evidence: EXT/09, EXT/19 #6, EXT/22
(story/task row: "Not found" across every column). Confidence: high.*

## The 19-state task machine, applied

Every unit of work for this project moves through exactly these states: `proposed,
requirements_analysis, architecture_required, ready, assigned, in_progress, blocked,
implementation_complete, implementation_review, rework_required, integration, qa, security_review,
release_ready, completed, released, deferred, cancelled, archived`.

Who moves each state, mapped onto credit-intelligence's real roles:

- **`proposed` → `ready` → `assigned`**: the `orchestrator` (Recommended role — the source has none)
  schedules these transitions. It does not decide *what* gets proposed (that is `product-manager`'s
  call per the roadmap) or *whether the architecture is sound* (that is `cto`'s call) — it only
  sequences and dispatches, matching this project's own principle that coordination is structural, not
  a decision-making layer.
- **`assigned` → `in_progress`**: the owning agent claims it — for example `backend-engineer` claiming
  a Decision API task, or `data-engineer` claiming an ingestion task.
- **`in_progress` → `implementation_complete`**: the **owning agent self-moves this transition**. This
  is a claim, not an approval — the constitution-level rule (design-spine §8) is explicit that this
  self-move is allowed because nothing downstream trusts it as done; it only unlocks review.
- **`implementation_complete` → `implementation_review`**: triggered by the orchestrator, routed to an
  **independent `code-reviewer`** (a Recommended standing role, formalized from the source's real
  `/pr-check` skill and PR template — the mechanism existed, the standing role is new). The reviewer
  must differ from the implementer; this project's own domain gives that rule teeth: "in a system
  where a bug lends someone the wrong amount of money, that distinction matters" (repo:CONTRIBUTING.md).
- **Review pass → `qa`**: moved by `qa-engineer`, an Extracted role — real in the source, and its gates
  are non-overridable by design.
- **`qa` → `security_review`**: moved by `security-engineer` (renamed from `security-architect`) when
  conditions are met — specifically, any task touching the data-collection or sensitive-data boundary
  must reach security **before** anything is built on top of it, not just before merge.
- **`security_review` → `release_ready` → `completed`**: requires attached gate evidence plus required
  approvals; no agent moves its own implementation task into `completed`.
- **`completed` → `released`**: moved by `release-manager` (Recommended — the source names no release
  authority at all) after human approval.
- **`rework_required`**: set by any reviewer on failure, at any of the review/qa/security checkpoints,
  and returns the task to `owner_agent` — never silently repaired by the reviewer.

**No agent may move its own implementation task from `in_progress` to any approval or `completed`
state.** This is the separation-of-duties rule this project most needs, given that `qa-engineer`'s
gates and `security-engineer`'s veto are exactly the checks a self-approving flow would bypass.

## The handoff format

A handoff (`schemas/handoff.schema.yaml`) records: `from_agent, to_agent, task_id, summary,
original_requirements, completed_work, outputs, changed_files, decisions, assumptions, contracts,
acceptance_criteria_status, automated_test_results, manual_test_results, quality_gate_results,
known_issues, unresolved_questions, risks, required_next_action, recommended_next_agent,
approval_required, evidence_refs, proposed_state_changes`.

**The receiver validates 15 items** before accepting: task identity, scope, required inputs,
acceptance criteria, decisions, dependencies, output locations, contract versions, changed files,
tests, risks, remaining work, approval status, evidence refs, and project-state changes.

**Exactly one of 5 statuses** is returned: `accepted | accepted_with_conditions |
rejected_incomplete | blocked_by_dependency | requires_human_decision`. An incomplete handoff is
**never silently repaired** by the receiver — for example, if `ai-engineer` hands `domain-policy-architect`
a calibrated PD without the calibration evidence attached, `domain-policy-architect` returns
`rejected_incomplete` naming the missing evidence, rather than proceeding on trust or backfilling it
themselves.

## Blocker and escalation ladders, credit-specific

The generic escalation ladder (design-spine §4) resolves to these named paths for
credit-intelligence's actual risk surfaces:

- **Threshold / limit disagreement** → owner `domain-policy-architect` (renamed `credit-architect`) →
  `cto` if unresolved → `human-owner`. This is *the* domain-policy escalation: thresholds, binding
  caps, and terms are `domain-policy-architect`'s call, converting `ai-engineer`'s calibrated
  probabilities into business decisions — `backend-engineer` implements the policy but never authors
  it.
- **"May we collect/use this data" → `security-engineer` BEFORE building.** This is the project's
  single most consequential escalation path, because it is the one place a wrong answer is
  irreversible after the fact: if a signal should never have been collected, the remedy is deleting
  the feature **and everything derived from it**, not adjusting policy after the fact. Every task whose
  `inputs` touch a new data source or signal must route through `security_review` before
  `in_progress`, not merely before `release_ready`.
- **"Untestable as designed"** → treated as a design defect, escalated to `cto` — not silently
  descoped by QA or reworked by the implementer without an architecture-level look.
- **Failed QA** → returns to the responsible implementation agent; escalates to `software-architect`/
  `cto` only if the failure indicates a design defect rather than an implementation bug.
- **Critical security issue** → `security-engineer` → `cto` → `human-owner`, per the standard ladder —
  `cto` cannot overrule the veto itself, only escalate to the human on everything else the finding
  touches.

A question pattern with no owner in this ladder is treated as an organizational bug and gets a named
owner added, not left to float.

## Retry loop and persistence

Failed transitions (a rejected handoff, a failed gate, a `rework_required`) increment `retry_count` on
the task and return it to the owning agent with the rejection's named missing field, missing artifact,
or failed validation attached — never a bare "try again." Project state
(`schemas/project-state.schema.yaml`) persists `active_tasks, blocked_tasks, deferred_tasks,
pending_handoffs, pending_reviews, retry_history` so that a session interruption (this project's
work is agent-driven; a session can end mid-task) resumes cold: the orchestrator reads
`project-state.yaml`, finds active tasks and open handoffs, and continues without re-deciding what was
already decided. Field-level ownership matches the constitution: the orchestrator writes only its own
coordination fields; `quality_gate_status`, `human_approvals`, and `release_status` are written by
their respective authorities, never by the orchestrator.

## Reusable rules (recap)

- The 19-state machine and its transition-authority rules apply unmodified; this project adds no new
  states, only named owners.
- Self-claim into `in_progress`→`implementation_complete` is allowed; self-move into any approval or
  `completed` state is not.
- A handoff is validated on 15 items and answered with exactly one of 5 statuses; incomplete handoffs
  are rejected, never repaired by the receiver.
- Data-collection legality routes to `security-engineer` before building, not before merging — this is
  the credit-specific case where "before" has to mean before code exists, not before a PR opens.
- State persists at the field level so an interrupted session resumes without re-litigating settled
  work.
