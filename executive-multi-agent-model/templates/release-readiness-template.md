<!-- Conforms to schemas/message.schema.yaml (type: release_readiness) + schemas/version.schema.yaml.
     Provenance: Recommended — the source had no release role and no release-process artifact
     (release approval authority was "Not found"); this template gives release-manager's evidence
     bundle a fixed shape built on the extracted "gates over status" and independent-review principles. -->

# Release Readiness Template

`release-manager` assembles this bundle before requesting the human go/no-go. It exists to prove one
thing: the recommendation is built on **independent** evidence, not on the implementer's word.

---

## Full release_readiness fields

```yaml
schema_version: 1
id: <PLACEHOLDER>
project_id: <PLACEHOLDER>
version: <PLACEHOLDER>
prepared_by: release-manager

qa_results:
  source: <PLACEHOLDER — qa-report id, e.g. QA-2026-07-13-09>
  independent: <true — MUST be true; reviewed_by must be qa-engineer, not owner_agent>
  overall_result: <pass|fail|pass_with_conditions>
  blocking_defects_open: <PLACEHOLDER integer>
  summary: <PLACEHOLDER — one line>

security_results:
  source: <PLACEHOLDER — security-report id, e.g. SEC-2026-07-13-05>
  independent: <true — MUST be true; reviewed_by must be security-engineer>
  approval_status: <approved|rejected|approved_with_conditions|vetoed>
  blocking_findings_open: <PLACEHOLDER integer>
  summary: <PLACEHOLDER — one line>

devops_readiness:
  build_status: <pass|fail>
  deploy_mechanism_verified: <true|false>
  rollback_tested: <true|false>
  rollback_procedure_ref: <PLACEHOLDER>
  migration_reversibility:
    migrations_included: <true|false>
    each_migration_reversible: <true|false|not_applicable>
    reversal_tested: <true|false|not_applicable>
  monitoring_in_place: <true|false>

release_notes:
  summary: <PLACEHOLDER — user-facing summary of what changed>
  included_scope: <PLACEHOLDER — features/fixes in this version>
  excluded_scope: <PLACEHOLDER — what was deliberately left out, "do not negotiate back in">
  known_issues: <PLACEHOLDER>

go_no_go_recommendation: <go | no-go | go_with_conditions>
recommendation_rationale: <PLACEHOLDER>

human_approval:
  required: true   # release approval is ALWAYS a mandatory human-approval trigger
  status: <pending|approved|approved_with_conditions|rejected>
  approver: <PLACEHOLDER — "human:<role>">
  conditions: <PLACEHOLDER>
  timestamp: <PLACEHOLDER ISO-8601>

evidence_refs: <PLACEHOLDER>
created_at: <PLACEHOLDER ISO-8601>
```

---

## Explicit rule

> `release-manager` MUST receive independent `qa-engineer` and `security-engineer` results and MUST
> NOT rely only on an implementation agent's handoff summary to fill `qa_results` or
> `security_results`. `independent: true` is a hard requirement — if `reviewed_by` on the source
> report is the same agent as `owner_agent`, this bundle is invalid and must be rejected back to
> whoever assembled it. `release-manager` re-verifies gate evidence; it does not re-litigate the
> gates themselves (it does not re-run QA's judgment, only confirms the evidence is real and
> independent).

## Rules

- `go_no_go_recommendation: go` requires both `qa_results.overall_result` and
  `security_results.approval_status` to be clean (pass / approved, or the conditional variants with
  all conditions non-blocking) AND `rollback_tested: true` for any version touching production
  data paths.
- A `security_results.approval_status: vetoed` is an automatic `no-go` — release-manager cannot
  override a scoped veto, and does not attempt to.
- Human approval is required for every release regardless of how clean the bundle is — this is one
  of the fixed mandatory human-approval triggers, not a judgment call.
- If `migrations_included: true`, `each_migration_reversible` and `reversal_tested` must both be
  `true` before `go_no_go_recommendation` can be `go`.

---

## Filled example

```yaml
schema_version: 1
id: RELEASE-READY-2026-07-13-01
project_id: acme-boards
version: v1.3.0
prepared_by: release-manager

qa_results:
  source: QA-2026-07-13-09
  independent: true
  overall_result: pass_with_conditions
  blocking_defects_open: 0
  summary: "All blocking acceptance criteria met; one non-blocking load-test gap tracked."

security_results:
  source: SEC-2026-07-13-05
  independent: true
  approval_status: approved
  blocking_findings_open: 0
  summary: "Tenant-derivation defect from prior review remediated and re-verified; no open findings."

devops_readiness:
  build_status: pass
  deploy_mechanism_verified: true
  rollback_tested: true
  rollback_procedure_ref: "runbooks/rollback-websocket-gateway.md"
  migration_reversibility:
    migrations_included: false
    each_migration_reversible: not_applicable
    reversal_tested: not_applicable
  monitoring_in_place: true

release_notes:
  summary: "Adds real-time presence indicators to boards (who's viewing/editing right now)."
  included_scope:
    - "WebSocket presence channel (connect/disconnect fanout)"
  excluded_scope:
    - "Typing indicators (deferred to v1.4.0)"
  known_issues:
    - "Load-tested to 50 concurrent clients/board only; see QA-2026-07-13-09 condition."

go_no_go_recommendation: go_with_conditions
recommendation_rationale: >
  Independent QA and Security both clean with no blocking items. Recommend canary rollout at 10%
  for 24h given this is the feature's first production traffic exposure, per orchestrator's
  approval request to the human.

human_approval:
  required: true
  status: pending
  approver: "human:product-owner"
  conditions: "Canary at 10% for 24h before full rollout"
  timestamp: null

evidence_refs:
  - QA-2026-07-13-09
  - SEC-2026-07-13-05
  - "CI run #4021"
created_at: 2026-07-13T18:00:00Z
```
