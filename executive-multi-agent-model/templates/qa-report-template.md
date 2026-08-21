<!-- Conforms to schemas/review.schema.yaml (review_type: qa) + schemas/quality-gate.schema.yaml.
     Provenance: Recommended — the source's qa-engineer role and "gates over status" principle are
     Extracted, but no report artifact existed to carry that verdict forward; this template gives
     the QA verification a fixed, auditable shape. -->

# QA Report Template

QA's output is a verdict, not a checklist tick. **QA owns gates, not code.** A `qa-engineer` never
fixes the defects it finds — it reports them to the owning agent and holds the gate. A red blocking
gate stops progress; no agent (including `orchestrator` or `cto`) may override it.

---

## Full qa_report fields

```yaml
schema_version: 1
id: <PLACEHOLDER>
task_id: <PLACEHOLDER>
project_id: <PLACEHOLDER>
version: <PLACEHOLDER>
reviewed_by: <PLACEHOLDER canonical_id — must be qa-engineer, independent of owner_agent>
owner_agent: <PLACEHOLDER canonical_id — the implementer being reviewed>

overall_result: <pass | fail | pass_with_conditions>

defects:
  - id: <PLACEHOLDER>
    severity: <critical|high|medium|low>
    description: <PLACEHOLDER>
    reproduction_steps: <PLACEHOLDER — numbered, exact, someone else must be able to follow them>
    regression_impact: <PLACEHOLDER — what else could this break; blast radius>
    owning_agent: <PLACEHOLDER canonical_id — who must fix it>
    blocking: <true|false>

acceptance_criteria_verification:
  - criterion: <PLACEHOLDER — verbatim from PRD/task acceptance_criteria>
    prd_reference: <PLACEHOLDER>
    verified: <met | not_met | partially_met>
    evidence: <PLACEHOLDER — test id, artifact, or observed behavior; never "looks fine">

gate_results:
  - gate_name: <PLACEHOLDER — e.g. requirement-validation, domain-correctness, acceptance-criteria>
    result: <pass|fail>
    blocking: <true|false>
    override_authority: <PLACEHOLDER — must be "none" for any CI-stage gate>

release_recommendation: <go | no-go | go_with_conditions>
conditions: <PLACEHOLDER — required if pass_with_conditions or go_with_conditions>

evidence_refs: <PLACEHOLDER>
created_at: <PLACEHOLDER ISO-8601>
```

---

## Rules

- `overall_result: fail` on any `blocking: true` defect or gate is final at this stage — the task
  returns to `owner_agent` via `rework_required`. QA does not negotiate a red blocking gate down to
  a caveat.
- Every `acceptance_criteria_verification` row must trace to something QA can point at (a test run,
  a reproduced scenario) — "verify, don't tick." An acceptance criterion QA cannot verify is
  `not_met`, not skipped.
- `regression_impact` is mandatory on every defect, even low severity — it is how QA prevents a
  fixed bug from being reintroduced silently.
- QA never edits code, contracts, or the PRD to make a criterion pass. If a criterion is untestable
  as designed, that is escalated as a design defect to `cto`, not silently waived.
- `release_recommendation: go` requires `overall_result: pass` (or `pass_with_conditions` with all
  conditions non-blocking).

---

## Filled example

```yaml
schema_version: 1
id: QA-2026-07-13-09
task_id: TASK-AB-142
project_id: acme-boards
version: v1.3.0
reviewed_by: qa-engineer
owner_agent: backend-engineer

overall_result: pass_with_conditions

defects:
  - id: DEF-2026-07-13-02
    severity: low
    description: "Presence fanout uses a naive broadcast loop; no functional defect observed, but
      no load test exists beyond 50 concurrent clients/board."
    reproduction_steps:
      - "1. Open 51+ WebSocket connections to a single board in a load-test harness."
      - "2. Observe fanout latency and CPU on the presence service."
      - "3. Currently: not attempted — no harness configured for this scenario."
    regression_impact: "If board-size limits are raised later without addressing this, fanout
      latency could silently exceed the 2s acceptance criterion at higher concurrency."
    owning_agent: test-automation-engineer
    blocking: false

acceptance_criteria_verification:
  - criterion: "presence-update within 2s of disconnect"
    prd_reference: "TASK-AB-142 acceptance_criteria #1"
    verified: met
    evidence: "tests/realtime/test_presence_service.py::test_fanout_latency — 12/12 passing, CI run #4021"
  - criterion: "presence state not persisted beyond session"
    prd_reference: "TASK-AB-142 acceptance_criteria #2"
    verified: met
    evidence: "Code review confirms no persistence adapter imported in presence_service.py"

gate_results:
  - gate_name: acceptance-criteria-verification
    result: pass
    blocking: true
    override_authority: none
  - gate_name: unit-tests
    result: pass
    blocking: true
    override_authority: none
  - gate_name: domain-correctness (load-scale)
    result: fail
    blocking: false
    override_authority: none

release_recommendation: go_with_conditions
conditions:
  - "test-automation-engineer to add a load test at >=100 concurrent clients/board before the next
     board-size-limit change is approved."

evidence_refs:
  - "CI run #4021"
  - "handoff HANDOFF-2026-07-13-01"
created_at: 2026-07-13T16:10:00Z
```
