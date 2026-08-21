<!-- Conforms to schemas/review.schema.yaml. Provenance: Partially extracted — mirrors the
     source's verify-don't-tick review discipline (`/pr-check` skill: separates output into
     Fails / Needs-a-human / Passes); the structured findings[] array is a Recommended
     formalization of that separation. -->

# Review Result Template

The reviewer's response to a review-request-template.md message. Every finding names its owning
agent — a review result is never anonymous about who must fix what.

---

## Result fields

```yaml
schema_version: 1
id: <PLACEHOLDER>
review_type: <code|architecture|qa|security|contract|release>
task_id: <PLACEHOLDER>
reviewer_agent: <PLACEHOLDER canonical_id>

findings:
  - severity: <critical|high|medium|low>
    location: <PLACEHOLDER — file path + line, or artifact + section>
    owning_agent: <PLACEHOLDER canonical_id — who must fix this>
    required_correction: <PLACEHOLDER — precise, actionable>
  - severity: <PLACEHOLDER>
    location: <PLACEHOLDER>
    owning_agent: <PLACEHOLDER>
    required_correction: <PLACEHOLDER>

result: <pass|fail|pass_with_conditions>
blocking: <true|false>
evidence_refs: <PLACEHOLDER>
created_at: <PLACEHOLDER ISO-8601>
resolved_at: <PLACEHOLDER ISO-8601 | null>
```

**result** enum meaning:
- `pass` — no findings above `low`, or no findings at all; task may proceed
- `fail` — at least one `blocking: true` finding; task returns to `owner_agent` (state
  `rework_required`)
- `pass_with_conditions` — proceeds, but named low/medium findings must be tracked and resolved
  (often as follow-up tasks, not a re-review gate)

> A `fail` result is not a suggestion. It sets the task's state to `rework_required` and returns
> it to the owning agent — no agent may talk itself past a fail without a new review.

---

## Filled mini-example

```yaml
schema_version: 1
id: REVIEW-RES-2026-07-13-09
review_type: code
task_id: TASK-AB-142
reviewer_agent: code-reviewer

findings:
  - severity: medium
    location: "src/realtime/adapters/ws_presence_gateway.py:47"
    owning_agent: backend-engineer
    required_correction: >
      Broadcast loop iterates all connected clients synchronously; acceptable at current
      50-client cap per CONTRACT-PRESENCE-v1, but flag as tech debt — file a follow-up task for
      test-automation-engineer to load-test before any board-size limit increase.
  - severity: low
    location: "tests/realtime/test_presence_service.py"
    owning_agent: backend-engineer
    required_correction: "Add a docstring explaining why disconnect fanout is tested at 2s, not
      a tighter bound (matches contract, but not obvious from the test alone)."

result: pass_with_conditions
blocking: false
evidence_refs:
  - "PR #214 diff reviewed line-by-line"
  - "CONTRACT-PRESENCE-v1 §2 cross-checked against implementation"
created_at: 2026-07-13T16:10:00Z
resolved_at: 2026-07-13T16:10:00Z
```
