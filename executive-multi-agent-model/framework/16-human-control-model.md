# 16 — Human-Control Model

**Purpose.** Where the human stays in the loop, how decisions are classified by how much autonomy an
agent has, and how an approval request is packaged so the human decides quickly and well.

> **Provenance banner.** Merge review and pre-build security consultation as human checkpoints are
> **Extracted**; the release/deploy/rollback human approvals are **Recommended** (the delivery tail
> was Missing). The decision-classification scheme is a **Recommended** formalization.

## Four decision classes

Every decision the organization makes falls into one of four classes, which fixes how much an agent
may do alone:

- **`agent_autonomous`** — the agent decides and proceeds; the decision is logged but needs no human.
  Example: choosing an internal variable name, writing a unit test.
- **`agent_recommendation_with_human_review`** — the agent proposes and proceeds only after a human
  glances and does not object; used for reversible, low-stakes changes where a human wants visibility.
- **`human_approval_required`** — the agent must stop and get explicit human approval before
  proceeding. This is the class for high-risk actions (below).
- **`human_action_required`** — only a human can perform the act at all (for example, granting a
  production credential, signing a legal document); the agent prepares and waits.

## Actions that require human approval

Human approval is mandatory before any of these proceed:

- product-scope changes
- high-risk assumptions
- major architecture decisions
- new external dependencies
- destructive migrations
- authentication changes
- authorization changes
- sensitive-data changes
- security exceptions
- production deployment
- production rollback
- release approval
- critical quality-gate overrides

These are the points where a wrong autonomous decision is expensive or irreversible, so the framework
routes each to a human. The project profile can add more, but should not remove these without a
recorded, human decision.

## The approval request

A human is asked with a **decision-ready summary**, never a raw transcript of agent chatter. The
request (`schemas/approval.schema.yaml`, rendered from
`templates/human-approval-request-template.md`) carries: `requested_by, decision_needed, background,
options, recommendation, risks, cost_or_impact, blocking_status, safe_default_action,
affected_version, affected_tasks, evidence_refs, response_required`. The orchestrator's job is to
*convert* an internal discussion into this shape — to state the decision, lay out the options with a
recommendation, name the risks and the blocking status, and identify the safe default if the human
does nothing. The human should be able to decide from the request alone.

## The one place with no human override

The scoped security veto (`04`, `14`) is deliberately *not* a human-approval checkpoint that can be
cleared by pushing past it — on its one existential-compliance question, there is **no override
path**, by design. The human owner sets the veto's scope up front (in `project-profile.yaml`); once
set, the veto stands until the design changes to satisfy it. This is the source's deliberate
asymmetry, preserved: a compliance question that outranks even the human's desire to ship, because it
is the question that can end the company.

## Keeping the human effective, not buried

Human control fails in two directions: too little (agents take irreversible actions alone) and too
much (the human is buried in noise and rubber-stamps). The framework guards both: the four classes
keep autonomous work autonomous, and the decision-ready summary keeps the human's attention on
decisions that actually need judgment. Raw internal conversations are not forwarded unless genuinely
necessary; the orchestrator summarizes.

## Reusable rules (recap)

- Classify every decision as autonomous, recommendation-with-review, approval-required, or
  action-required.
- The thirteen high-risk actions always require explicit human approval before proceeding.
- Ask with a decision-ready summary (options, recommendation, risks, safe default), never raw chatter.
- The scoped security veto has no override path by design; the human sets its scope up front.
- Protect the human from both too little control and too much noise.
