<!-- Conforms to schemas/version.schema.yaml (post_release_validation) + schemas/event.schema.yaml
     (post_release_validation_passed / _failed). Provenance: Recommended — the source's falsifiable
     phase-exit-gate principle is Extracted (each of the 3 roadmap phases carries ONE falsifiable
     exit condition), but no artifact existed to record the post-release check against it; this
     template closes that loop. -->

# Post-Release Report Template

Every version has exactly **one falsifiable exit gate** (`version.schema.yaml: exit_gate`). This
report is how `release-manager` + `product-manager` confirm — after real production exposure —
whether what shipped actually satisfies that gate, not just whether it deployed cleanly.

---

## Full post_release_report fields

```yaml
schema_version: 1
id: <PLACEHOLDER>
project_id: <PLACEHOLDER>
version: <PLACEHOLDER>
prepared_by: <PLACEHOLDER — release-manager + product-manager jointly>
observation_window: <PLACEHOLDER — start/end timestamps or duration>

exit_gate: <PLACEHOLDER — the single falsifiable condition, quoted verbatim from the version record>
exit_gate_result: <met | not_met | partially_met>
exit_gate_evidence: <PLACEHOLDER — the observed fact that proves or disproves the gate; never an
  assertion, always a pointer to a metric, log, or partner statement>

metrics_observed:
  - metric: <PLACEHOLDER>
    expected: <PLACEHOLDER>
    observed: <PLACEHOLDER>
    within_tolerance: <true|false>

acceptance_criteria_results:
  - criterion: <PLACEHOLDER — verbatim from the version/task acceptance criteria>
    result: <pass|fail>
    evidence: <PLACEHOLDER>

incidents:
  - id: <PLACEHOLDER | "none">
    severity: <critical|high|medium|low>
    description: <PLACEHOLDER>
    detected_at: <PLACEHOLDER>
    resolved_at: <PLACEHOLDER | "ongoing">
    root_cause: <PLACEHOLDER | "under investigation">

rollback_decision:
  rollback_occurred: <true|false>
  trigger: <PLACEHOLDER — the specific condition that would trigger/did trigger rollback, quoted
    from the rollback_requirements defined pre-release; "none" if no rollback>
  decided_by: <PLACEHOLDER — devops-engineer recommends; release-manager + human-owner decide>

lessons_carried_forward:
  - lesson: <PLACEHOLDER>
    action: <PLACEHOLDER — what changes in the next version's plan/gates/process as a result>
    owner: <PLACEHOLDER canonical_id>

overall_verdict: <version_complete | version_incomplete_gate_not_met | version_complete_with_followups>

evidence_refs: <PLACEHOLDER>
created_at: <PLACEHOLDER ISO-8601>
```

---

## Rule

> **If the exit gate is not met, the version is not done — regardless of how much shipped.** A
> version with 100% of its planned features deployed but a `not_met` exit gate is
> `version_incomplete_gate_not_met`, full stop. Do not let deployment completion substitute for gate
> satisfaction; they are evaluated independently. `exit_gate_evidence` must be an externally
> observable fact (a partner's stated commitment, a measured metric, a real production outcome) —
> never an internal team assessment of its own work.

## Rules

- `metrics_observed` rows must include both `expected` (set before release) and `observed` — this
  report is not the place to retroactively redefine what "expected" meant.
- Every `incidents` entry needs a `root_cause`, even if it is currently "under investigation" —
  "none" is only valid for the whole list, never as a placeholder inside an entry.
- `rollback_decision.trigger` must be quoted from the rollback requirements defined before release,
  not invented after the fact to justify what happened.
- `lessons_carried_forward` must name an `owner` and an `action` — a lesson with no owner does not
  survive into the next version plan; it just gets repeated.

---

## Filled example

```yaml
schema_version: 1
id: POSTREL-2026-07-20-01
project_id: acme-boards
version: v1.3.0
prepared_by: "release-manager + product-manager"
observation_window: "2026-07-14T00:00:00Z to 2026-07-20T00:00:00Z (7 days post full rollout)"

exit_gate: "Presence indicators are observed live on boards with 3+ active tenants, with fanout
  latency under 2s at p95, and no tenant reports a false-presence incident."
exit_gate_result: met
exit_gate_evidence: "Production metrics dashboard, 7-day window: 14 tenants used presence, p95
  fanout latency 1.1s, zero false-presence support tickets."

metrics_observed:
  - metric: "p95 presence fanout latency"
    expected: "< 2s"
    observed: "1.1s"
    within_tolerance: true
  - metric: "concurrent clients per board (peak observed)"
    expected: "unspecified pre-release; load-tested to 50"
    observed: "38 (peak, single board)"
    within_tolerance: true

acceptance_criteria_results:
  - criterion: "presence-update within 2s of disconnect"
    result: pass
    evidence: "Production p95 = 1.1s, see metrics_observed"
  - criterion: "presence state not persisted beyond session"
    result: pass
    evidence: "No presence rows found in persistence audit, 2026-07-20"

incidents:
  - id: none

rollback_decision:
  rollback_occurred: false
  trigger: "p95 fanout latency > 5s sustained for 15 min, or false-presence rate > 1% of sessions —
    neither condition observed"
  decided_by: "n/a — no rollback triggered"

lessons_carried_forward:
  - lesson: "Load testing stopped at 50 concurrent clients/board pre-release; production peak (38)
    stayed under that ceiling by luck of adoption pace, not by design margin."
    action: "Add a load test at 150 concurrent clients/board (3x observed peak) before the next
      board-size-limit change is approved."
    owner: test-automation-engineer

overall_verdict: version_complete

evidence_refs:
  - "production metrics dashboard export, 2026-07-20"
  - "RELEASE-READY-2026-07-13-01"
created_at: 2026-07-20T09:00:00Z
```
