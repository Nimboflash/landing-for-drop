# 10 — Blocker, Escalation, and Retry

**Purpose.** What happens when work cannot proceed, disagreements cannot be resolved in-lane, or
reviewed work fails. Every blocker has an owner and a path; every failure returns to the right agent;
every retry is recorded.

> **Provenance banner.** Escalation-by-question-type is **Extracted** (the source's per-agent
> escalation tables, `EXT/05-organization-and-authority.md`). Structured blocker objects and a retry
> ledger are **Recommended** — the source had escalation *routing* but no blocker record or retry
> tracking (both Missing).

## Blockers

A blocker is recorded as `schemas/blocker.schema.yaml`: `id, blocking_task, blocked_tasks,
reported_by, cause, impact, responsible_owner, required_resolution, severity, suggested_action,
escalation_sequence, human_decision_required, evidence_refs, status, created_at, resolved_at`.
`severity` is `critical | high | medium | low`. Two properties matter most: every blocker names a
`responsible_owner` (a blocker with no owner is an organizational bug), and every blocker carries an
`escalation_sequence` so it cannot sit unresolved indefinitely. Blockers live in `blocked_tasks` in
project state until `resolved_at` is set.

## Escalation ladders

Escalation routes by *question type*, not up a management chain, and every ladder ends at a human:

- **Product ambiguity** → `product-manager` → `human-owner`.
- **Scope change** → `product-manager` → `human-owner` (human approval required).
- **Architecture disagreement** → `software-architect` → `cto` (final arbiter) → `human-owner`.
- **API/contract conflict** → contract owner (`backend-engineer`) / `cto`.
- **File-ownership conflict** → `orchestrator` (surfaces it) / `cto` (decides).
- **Failed implementation review** → responsible implementation agent.
- **Failed QA** → responsible implementation agent (and `software-architect`/`cto` if the design is
  the defect).
- **Critical security issue** → `security-engineer` → `cto` → `human-owner`.
- **Failed deployment** → `devops-engineer` → `release-manager` → `human-owner`.
- **Release disagreement** → `release-manager` → `human-owner`.
- **"Untestable as designed"** → `cto` — treated as a design defect, not a QA problem.
- **"A document disagrees with the constitution"** → fix the document.

The rule that makes the ladder trustworthy: **a question pattern with no owner is an organizational
bug** — discovering one is itself a finding to resolve, not a reason to guess.

## Retry and rework

When reviewed work fails, the loop is deterministic:

1. The reviewer creates a structured **rejection** (`rejected_incomplete`, per `09`) with named
   reasons.
2. The task returns to its `owner_agent` in state `rework_required`.
3. The failure reason is stored in `retry_history` in project state.
4. Acceptance criteria **remain unchanged** unless formally re-approved — the bar does not move to
   make a failure pass.
5. The implementation agent submits a **new handoff**, not a patch to the old one.
6. An **independent reviewer** validates the revised work (the same separation-of-duties rule).
7. `retry_count` and the result are recorded.

## Configurable escalation thresholds

Repeated failure is a signal, not just a nuisance. The project profile sets `retry.max_review_retries`
(default 2); when a task exceeds it, the orchestrator escalates rather than looping forever. The
escalation chain for chronic rework climbs: `software-architect` → `cto` → `product-manager` →
`human-owner`. Chronic rework on one task usually means the design or the acceptance criteria are
wrong — which is a decision for an authority, not another attempt by the implementer.

## Blockers, retries, and resumption

Because blockers and retries are recorded in project state (`07`), a session that resumes cold sees
exactly what is blocked, why, who owns it, and how many times it has been attempted. This is what
turns "the work stalled" from an invisible loss into a tracked, recoverable condition.

## Reusable rules (recap)

- Every blocker names a responsible owner and an escalation sequence; an ownerless blocker is a bug.
- Escalate by question type; every ladder ends at a human.
- On failed review: structured rejection → return to owner → record reason → unchanged criteria →
  new handoff → independent re-review → record retry.
- Repeated failure trips a configurable threshold and escalates to an authority, not another retry.
- Blockers and retries live in project state so stalls are tracked and resumable.
