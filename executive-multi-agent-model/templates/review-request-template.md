<!-- Conforms to schemas/review.schema.yaml. Provenance: Partially extracted — the review
     mechanism itself (fixed priority order, `/pr-check` verify-don't-tick discipline, PR template)
     is real source behavior; packaging it as a standing structured request/result pair is a
     Recommended formalization. -->

# Review Request Template

Use this to request any of the six review types. The reviewer MUST be independent of the task
owner — this is non-negotiable (design-spine §3, invariant 3: implementation and final approval
are different roles).

---

## Request fields

```yaml
schema_version: 1
id: <PLACEHOLDER>
review_type: <code|architecture|qa|security|contract|release>
task_id: <PLACEHOLDER>
requested_by: <PLACEHOLDER canonical_id>
reviewer_agent: <PLACEHOLDER canonical_id — MUST NOT equal owner_agent of task_id>
inputs: <PLACEHOLDER — what the reviewer needs: diff/artifact links, contract version, prior ADRs>
checklist: <PLACEHOLDER — see below>
blocking: <true|false>
evidence_refs: <PLACEHOLDER>
created_at: <PLACEHOLDER ISO-8601>
```

## Checklist (populate per review_type)

Use a fixed priority order so attention lands on invisible failures first, not surface style.
Suggested order (adapt per `review_type`, but do not invert the priority — boundaries and hidden
business rules before style):

1. Boundary / architecture conformance — does this cross a lane it shouldn't?
2. Hidden business-rule correctness — not just "does it run" but "is the rule right"
3. Replayability / determinism where applicable
4. Data sensitivity / PII handling
5. Test coverage and level (unit vs integration vs e2e) appropriate to the change
6. Contract conformance (if `review_type: contract`)
7. Style / formatting (lowest priority — often auto-fixed, never blocking on its own)

```yaml
checklist:
  - item: <PLACEHOLDER>
    checked: <true|false>
  - item: <PLACEHOLDER>
    checked: <true|false>
```

> Verify, don't tick. For each applicable box: look. Grep, read, check. An unverified tick is
> worse than an admitted gap.

---

## Filled mini-example

```yaml
schema_version: 1
id: REVIEW-REQ-2026-07-13-09
review_type: code
task_id: TASK-AB-142
requested_by: backend-engineer
reviewer_agent: code-reviewer     # independent of backend-engineer, the task owner
inputs:
  - diff: "PR #214"
  - contract: CONTRACT-PRESENCE-v1
  - coding_standards: CODING_STANDARDS.md
checklist:
  - item: "No shared internal state crossed between modules (only ports)"
    checked: false
  - item: "Business rule for max-clients-per-board matches CONTRACT-PRESENCE-v1 §2"
    checked: false
  - item: "No PII present in presence payload"
    checked: false
  - item: "Test level matches change (integration test present for fanout, not just unit)"
    checked: false
  - item: "Formatting passes ruff (informational only, non-blocking)"
    checked: false
blocking: true
evidence_refs:
  - "PR #214 diff"
created_at: 2026-07-13T15:45:00Z
```
