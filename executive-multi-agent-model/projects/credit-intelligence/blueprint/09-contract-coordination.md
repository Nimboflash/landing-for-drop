# 09 — Contract Coordination

**Purpose.** How credit-intelligence's front-end, back-end, ML, data, and policy lanes coordinate
through versioned contracts instead of ad-hoc conversation, and what the eight-step change procedure
looks like applied to this project's real seams.

> This document applies the contract-governance framework (`framework/13-contract-governance.md`) to
> the credit-intelligence EVIDENCE. The FE/BE contract-first seam and generated client are Extracted
> real mechanisms; the eight-step procedure is the framework's formalization of what the source's
> looser "co-owned contract" description implies.

## The Extracted contract-first seam

The source's single most complete artifact is the **Decision API** (`POST /v1/decisions`,
`docs/api/decision-api.md`) — the repository's own self-description: "`/v1/` — Phase 1. This is the
product." Two facts make it a genuine contract-first seam rather than just good documentation:

1. **Co-ownership across three lanes before any code exists**: the API contract is jointly owned by
   `backend-engineer` (implementation), `domain-policy-architect` (decision/output semantics — this is
   the renamed `credit-architect`), and `cto` (boundary conformance). None of the three can silently
   redefine it without the others.
2. **The front-end client is generated from the schema, never hand-written.** `frontend-engineer`
   consumes a generated typed client and is explicitly barred from redefining API contracts or output
   semantics — this is how the two lanes build in parallel "without meeting": the interface itself is
   the coordination mechanism, and generation prevents hand-drift.

A breaking change to the Decision API contract is treated as a **new version**, not an in-place edit —
this project's version discipline (`07`) and its contract discipline are the same discipline applied
at two grain sizes. — *Classification: Extracted. Evidence: EXT/09-prd-to-production-workflow.md
(stage 13), EXT/10-real-feature-trace.md, repo:docs/api/decision-api.md. Confidence: high.*

## The 8-step contract-change procedure, applied

Applying the framework's generic procedure to a change on the Decision API (for example, adding a new
`explanation_warning` field):

1. Create a `contract_change` message naming the field and its motivation.
2. Identify affected agents: `frontend-engineer` (client + display), `ai-engineer` (must supply the
   new field's value), `qa-engineer` (test fixtures), `domain-policy-architect` (does this change
   decision semantics?).
3. State the compatibility impact — additive fields are backward-compatible; anything that changes an
   existing field's meaning (for example redefining `binding_cap`) is breaking and requires a new API
   version.
4. Receive acknowledgements from all four affected agents before anyone proceeds — this
   acknowledgement is mandatory precisely because `binding_cap`, `explanation_warning`, and
   `policy_version` are the fields the source's own cross-referenced docs (API contract, decision
   schema, explainability doc) all agree on by name; an un-acknowledged change breaks that agreement
   silently.
5. Bump the contract version.
6. Update project state's `contract_versions` field.
7. Regenerate the front-end's typed client and any QA fixtures/mocks against the new schema.
8. Resume implementation only after approval — for this project, approval requires at minimum `cto`
   (boundary) and `domain-policy-architect` (semantics) sign-off, per the co-ownership above.

## The real coordination pairs

Four coordination pairs carry the actual cross-lane traffic in this project:

- **`ai-engineer` → `domain-policy-architect`: calibrated PD → policy.** `ai-engineer` produces a
  calibrated probability of default (and its stability/feature evidence); `domain-policy-architect`
  converts that probability into a business decision — threshold, limit, terms. This is a hard
  boundary: `ai-engineer` never sets a business threshold, and `domain-policy-architect` never
  re-derives a probability. The pair exchanges calibration evidence outbound and decision-policy
  parameters inbound.
- **`data-engineer` → `ai-engineer`: feature store substrate vs. feature definitions.** `data-engineer`
  owns the data substrate — ingestion, the `raw`→`curated`→`features` schema pipeline, lineage,
  contracts on the data itself. `ai-engineer` owns what a feature *means* (its definition, its
  computation from substrate). The seam is deliberately drawn here so that a pipeline change
  (`data-engineer`'s lane) cannot silently redefine what a feature represents (`ai-engineer`'s lane)
  without a contract-change conversation between them.
- **`backend-engineer` ↔ `frontend-engineer` via the versioned Decision API.** As above — strictly
  through the contract, never informally.
- **Any engineer → `security-architect`/`security-engineer` BEFORE building.** Not a coordination pair
  in the exchange sense so much as a gate every other pair must clear first when a change touches data
  collection, a new signal, or the sensitive-data boundary — this project's veto applies here (see
  `11`), and the timing (before building, not before merging) is the doctrine.

Each pair exchanges the framework's generic set where applicable — for architecture-adjacent pairs,
problem definition / goals / non-goals outbound and feasibility / risk / trade-offs inbound; for
engineering/QA pairs, the feature handoff outbound and pass/fail/defects/release-recommendation inbound
— adapted above to this project's specific vocabulary (PD, calibration, feature definitions, policy
parameters) rather than the generic terms. — *Classification: Extracted for the pair boundaries and
their rationale; Recommended for the formal exchange-contents list (the source states the boundary,
not an enumerated exchange format). Evidence: EXT/01-repository-structure.md (agent roster + "never
touches" columns), repo:ai-engineer.md, repo:credit-architect.md/DECISION_ENGINE.md,
repo:data-engineer.md. Confidence: high (boundaries), medium (exchange enumeration).*

## Release-manager gets independent evidence

`release-manager` (Recommended — the source names no release authority) must receive QA and Security
results **independently** for any Decision API change reaching release-readiness, never relying only
on `backend-engineer`'s or `ai-engineer`'s own summary of their work. Concretely: `qa-engineer`'s
result on leakage/replay/stability/monotonicity checks (once implemented, see `11`) and
`security-engineer`'s result on the data-boundary review must both land in the release-manager's
evidence bundle directly, not filtered through the implementing agent's handoff notes. This
independence is what makes a release decision on a credit-underwriting system trustworthy — the
implementer's self-report is evidence of effort, not of correctness. — *Classification: Recommended
(release-manager role and this independence discipline are both Missing in source; the underlying
principle — QA and Security as independent gate-owners, not code-owners — is Extracted). Evidence:
design-spine §4, EXT/16-reusability-assessment.md (QA governance scored 5/DR). Confidence: high.*

## Reusable rules (recap)

- Fix and version the Decision API contract before front-end/back-end fan out; the front-end always
  consumes a generated client, never a hand-written one.
- A contract change to this project's schema follows all 8 steps, with mandatory acknowledgement from
  every named cross-referencing doc's owning agent.
- The `ai-engineer` → `domain-policy-architect` and `data-engineer` → `ai-engineer` seams are the two
  boundaries most likely to erode under time pressure; treat any blurring of "calibration vs. policy"
  or "substrate vs. definition" as a contract violation, not a convenience.
- Any change touching data collection or the sensitive-data boundary clears `security-engineer` before
  building, independent of every other coordination pair.
- `release-manager` receives QA and Security evidence directly and independently before assembling a
  release-readiness bundle.
