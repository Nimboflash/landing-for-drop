# 12 — Human Approval Model

**Purpose.** Where the human operator stays in the loop for credit-intelligence today, versus where
this project needs to add checkpoints it currently lacks entirely, and the format an approval request
should take so the human can decide from it alone.

> This document applies the human-control framework (`framework/16-human-control-model.md`) to the
> credit-intelligence EVIDENCE. Merge review and pre-build security consultation are Extracted human
> checkpoints; release/deploy/rollback/migration/scope-change/assumption approvals are Recommended —
> the delivery half of this project's lifecycle currently has no human checkpoint at all because it
> has no delivery mechanism at all.

## The 4 decision classes, applied to this project

- **`agent_autonomous`** — for example, `ai-engineer` choosing an internal feature-engineering helper
  function name, or `backend-engineer` writing a unit test for the Decision API. Logged, no human
  needed.
- **`agent_recommendation_with_human_review`** — for example, `data-engineer` proposing a non-breaking
  addition to the `curated` schema; proceeds unless the human objects on a glance.
- **`human_approval_required`** — the class this project depends on most heavily, given the domain: a
  wrong threshold or a wrongly-collected signal is not a cosmetic bug, it is a lending decision or a
  legal exposure. Full list below.
- **`human_action_required`** — for example, granting a design partner's production credential, or
  signing whatever legal agreement underlies a Type-2-licence application in Version 3; only the human
  can do this at all.

## The Extracted human checkpoints

Two checkpoints are real in the source today:

1. **PR merge review.** Every PR requires 1 human review plus green CI before merge to `main`; this is
   the project's only implemented human-in-the-loop mechanism across its entire designed 23-stage
   workflow. It is real, but it is also the *only* implemented one — everything past merge (deploy,
   release, rollback, post-release) has no checkpoint because it has no mechanism. — *Classification:
   Extracted. Evidence: EXT/05-git-devops-release.md, repo:CONTRIBUTING.md. Confidence: high.*
2. **Security consulted BEFORE building, not after.** For any change touching the data-collection or
   sensitive-data boundary, `security-architect`/`security-engineer` reviews at design time, and the
   veto (§ below) has **no override path by design** — this is the one place in the entire system where
   a human saying "ship it anyway" is not an available button. The human owner's role here is to set
   the veto's scope up front (naming the one existential-compliance question for this project — the
   data-collection boundary) and then live inside that boundary once set, not to clear it case by case.
   — *Classification: Extracted (the veto and its timing) / Recommended framing (the "no override path
   by design" as an explicit human-control-model statement). Evidence: EXT/09 (stage 18), EXT/12c
   (escalation-matrix.md), design-spine §16. Confidence: high.*

## The Recommended additions

Every other item on the framework's human-approval-required list is currently unaddressed in this
project because the mechanism it would attach to (release, deployment, migrations, scope process,
assumption tracking) does not exist yet. Recommended checkpoints to add before Version 1 ships:

- **Release approval** — `release-manager` (Recommended role) assembles independent QA + security +
  devops evidence; human approves before `completed` → `released`. Today: no release role exists, so no
  release has ever been approved or denied by anyone.
- **Production deployment** — executed by `devops-engineer`, authorized by the human owner. Today: no
  deployment mechanism exists to authorize.
- **Rollback** — `devops-engineer` recommends, `release-manager` + human decide. Today: rollback is
  doctrine ("test the rollback before you need it") with no rehearsed mechanism and no one designated to
  decide when to pull it.
- **Destructive migration** — any migration that is not purely additive requires human approval before
  merge, on top of the migration-validation gate. Today: no migration exists yet (no Alembic files), so
  this checkpoint should be specified *before* the first one lands, not retrofitted after.
- **Scope change** — any change to Phase 1's included/excluded scope (for example, someone proposing to
  pull Kafka or multi-tenancy back in before its trigger has fired) requires `product-manager` to route
  it to the human owner. Today: the "do not negotiate back in" lists are strong normative language but
  have no enforcement mechanism forcing a human decision if someone tries anyway.
- **High-risk assumptions** — for example, an assumption about a design partner's loan-tape data quality
  or a regulatory interpretation feeding into `domain-policy-architect`'s thresholds — should be
  recorded in an assumption register (currently Missing — the source has "no assumption register";
  assumptions surface only inside ADRs) with explicit human sign-off on the high-risk ones.

*Classification: Recommended for all items above. Evidence: EXT/06 (stages 18–21 score 0), EXT/16
("Missing... release automation"), EXT/09 (stage 4: "no assumption register"), design-spine §3.8 and
§16. Confidence: high.*

## The one place with no human override, restated

The scoped security veto is deliberately **not** a checkpoint the human can push past — it is not in
the `human_approval_required` class at all in the sense of "human can approve an exception." Once the
human owner has set the veto's scope (the data-collection boundary, and nothing else), the veto stands
until the design changes to satisfy it. This is the framework's stated asymmetry, and it maps exactly
onto this project's own founding constraint that unlicensed centralization of certain data is illegal —
a question that can end the company outranks even the human's desire to ship on schedule.

## The approval_request format

Every `human_approval_required` decision above should reach the human as a decision-ready summary, not
a raw agent transcript, carrying: `requested_by, decision_needed, background, options, recommendation,
risks, cost_or_impact, blocking_status, safe_default_action, affected_version, affected_tasks,
evidence_refs, response_required`.

Worked example for this project — a Version-1 release approval:

```
requested_by: release-manager
decision_needed: "Approve release of Decision API v1.0 to the first design partner?"
background: "All CI gates green. Domain gates (leakage/replay/stability/monotonicity) passed on the
  pinned model+policy+code triple. Security review of the ingest data boundary completed with no
  open findings. QA and Security evidence attached independently below."
options: ["Approve for release", "Approve with conditions (name them)", "Hold — reason"]
recommendation: "Approve — all blocking gates green, independent QA and security evidence attached."
risks: ["Design partner cohort is small (n=1); model stability evidence is early."]
cost_or_impact: "First real-world test of the exit gate: does the partner say 'run this on our next
  cohort'?"
blocking_status: "blocking — Version 1 cannot close without this approval."
safe_default_action: "Hold; re-request once condition X is met."
affected_version: "Version 1 — Foundation"
affected_tasks: ["DEC-014", "DEC-019"]
evidence_refs: ["qa-gate-result-2026-xx", "security-review-2026-xx"]
response_required: "approve | approve_with_conditions | hold"
```

This lets the human owner decide from the request alone, without reconstructing the underlying
agent-to-agent discussion. — *Classification: Recommended (schema and worked example; the underlying
principle that approvals must be evidence-backed rather than self-reported is Extracted from this
project's own "gates over status" discipline). Evidence: design-spine §16, EXT/12c
(approval-matrix.md). Confidence: high.*

## Reusable rules (recap)

- Classify every decision in this project as autonomous, recommendation-with-review, approval-required,
  or action-required — most of this project's real risk sits in the approval-required class.
- PR merge review and pre-build security consultation are the only two human checkpoints that exist
  today; every checkpoint past merge (release, deploy, rollback, destructive migration) must be built,
  not assumed.
- Scope changes to the "do not negotiate back in" lists route to the human owner via `product-manager`,
  not silently.
- The security veto has no override path by design; the human's job is to set its scope once, not to
  clear it repeatedly.
- Every approval request is a decision-ready summary — options, recommendation, risks, safe default —
  never a raw transcript.
