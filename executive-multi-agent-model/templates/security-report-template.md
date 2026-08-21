<!-- Conforms to schemas/review.schema.yaml (review_type: security) + schemas/approval.schema.yaml
     (veto block). Provenance: Extracted (the security veto itself, and security-as-authority, are
     Explicit repository fact) — this template is the Recommended structured shape that carries
     that authority forward as an artifact instead of a conversation. -->

# Security Report Template

Security's output is an authority verdict: approval, rejection, or a veto. `security-engineer`
holds the **one scoped veto** in this framework — narrower and stronger than an ordinary review.

---

## Full security_report fields

```yaml
schema_version: 1
id: <PLACEHOLDER>
task_id: <PLACEHOLDER>
project_id: <PLACEHOLDER>
version: <PLACEHOLDER>
reviewed_by: security-engineer
owner_agent: <PLACEHOLDER canonical_id — the implementer whose work is under review>

findings:
  - id: <PLACEHOLDER>
    severity: <critical|high|medium|low>
    location: <PLACEHOLDER — file, endpoint, contract, or data-flow path>
    description: <PLACEHOLDER>
    blocking_status: <true|false>
    required_remediation: <PLACEHOLDER — precise, actionable; owning agent must be able to act on it>
    owning_agent: <PLACEHOLDER canonical_id>

approval_status: <approved | rejected | approved_with_conditions | vetoed>
conditions: <PLACEHOLDER — required if approved_with_conditions>

scoped_veto:
  vetoed: <true|false>
  question_in_scope: <PLACEHOLDER — the ONE existential-compliance question this veto covers,
    stated precisely; a veto never covers more than this>
  rationale: <PLACEHOLDER — why this crosses the line, in terms of the constitution / regulation /
    irreversible harm>
  offered_alternative: <PLACEHOLDER — REQUIRED whenever vetoed:true. A veto with no alternative is
    invalid and must be sent back for rework before it is recorded>

evidence_refs: <PLACEHOLDER>
created_at: <PLACEHOLDER ISO-8601>
```

---

## Invariant note

> A veto MUST carry an alternative — `offered_alternative` cannot be empty when `vetoed: true`.
> The `cto` and `orchestrator` cannot overrule a scoped veto; it outranks the roadmap on that one
> question. Every veto is recorded as a decision (ADR), citing this report as `evidence_refs`, with
> `fired_migration_trigger` left empty (adoption of the vetoed path is rejected by construction).
> The veto is scoped to exactly the one question named in `question_in_scope` — it is not a general
> hold over the task, the feature, or the agent's other work.

## Rules

- `blocking_status: true` findings behave like a red gate: the task does not advance past
  `security_review` until remediated and re-reviewed.
- `security-engineer` never implements the remediation itself — it names `owning_agent` and hands
  back, same as QA.
- A veto is not a severity level; it is a distinct authority act. Do not use `severity: critical` as
  a substitute for `scoped_veto.vetoed: true` when the question is genuinely the one defined
  existential-compliance boundary for this domain.
- `approval_status: vetoed` requires `scoped_veto.vetoed: true` and a non-empty
  `offered_alternative`; the two fields must agree.

---

## Filled example

```yaml
schema_version: 1
id: SEC-2026-07-13-05
task_id: TASK-AB-150
project_id: acme-boards
version: v1.3.0
reviewed_by: security-engineer
owner_agent: backend-engineer

findings:
  - id: FIND-2026-07-13-01
    severity: high
    location: "src/realtime/adapters/ws_presence_gateway.py — tenant_id resolution"
    description: >
      tenant_id for a presence subscription is read from a client-supplied WebSocket query
      parameter rather than derived from the authenticated bearer token, contradicting the
      standing rule that tenant is always derived from credential, never a request field.
    blocking_status: true
    required_remediation: "Derive tenant_id exclusively from the validated auth token on connection;
      reject any connection where a client-supplied tenant_id parameter is present and mismatched."
    owning_agent: backend-engineer

approval_status: rejected
conditions: null

scoped_veto:
  vetoed: false
  question_in_scope: null
  rationale: null
  offered_alternative: null

evidence_refs:
  - "SECURITY.md — tenant-derivation rule"
  - "handoff HANDOFF-2026-07-13-03"
created_at: 2026-07-13T17:05:00Z
```

### Illustrative veto instance (separate task, shown to demonstrate the block)

```yaml
scoped_veto:
  vetoed: true
  question_in_scope: "May raw loan-tape records leave the originating partner's legal boundary for
    any form of cross-partner model training?"
  rationale: "Unlicensed centralization of this data across partners is illegal under the
    applicable regulatory regime absent a Type 2 licence; no engineering mitigation changes the
    legal fact."
  offered_alternative: "Train per-partner models locally and share only gradient updates or
    model deltas under differential privacy, with raw records never leaving the partner boundary,
    until a Type 2 licence is granted."
approval_status: vetoed
# Recorded as ADR-0012, fired_migration_trigger left empty — path rejected until licence granted.
```
