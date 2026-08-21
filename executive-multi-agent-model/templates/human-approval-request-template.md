<!-- Conforms to schemas/message.schema.yaml (type: approval_request) + schemas/approval.schema.yaml.
     Provenance: Recommended — the source had no orchestrator and no structured approval message;
     human approval happened by direct conversation. This template formalizes the decision-ready
     summary discipline (§Phase-18) so a human is never asked to approve raw agent chatter. -->

# Human Approval Request Template

An `approval_request` is produced by the **orchestrator** to bring a pending decision to the human
in a form a busy person can act on in under a minute. It is a **DECISION-READY SUMMARY** — never a
dump of raw internal agent messages, logs, or chain-of-thought. If the underlying material is messy,
the orchestrator's job is to compress it, not forward it.

---

## Mandatory human-approval triggers

A human approval is REQUIRED (not optional, not delegable) for any of the following. This list is
closed — if a new situation resembles one of these, treat it as one:

1. Product-scope change
2. High-risk assumption
3. Major architecture decision
4. New external dependency
5. Destructive migration
6. Auth(n/z) change
7. Sensitive-data change
8. Security exception
9. Production deployment
10. Production rollback
11. Release approval
12. Critical gate override

---

## Full approval_request fields (schema_version 1)

```yaml
schema_version: 1
id: <PLACEHOLDER>
requested_by: <PLACEHOLDER canonical_id — usually orchestrator, relaying a decision owner's request>

decision_needed: <PLACEHOLDER — one sentence, phrased as a question the human can answer yes/no/conditionally>

background: <PLACEHOLDER — 3-5 sentences max. Why this decision exists, what triggered it, who is
  asking. No raw agent transcript, no internal debate — the compressed "why now">

options:
  - option: <PLACEHOLDER — option A, plain language>
    consequence: <PLACEHOLDER>
  - option: <PLACEHOLDER — option B>
    consequence: <PLACEHOLDER>

recommendation: <PLACEHOLDER — the requesting agent's recommended option + one-line why>

risks: <PLACEHOLDER — what could go wrong under the recommended option, and under inaction>

cost_or_impact: <PLACEHOLDER — time, money, scope, or user-facing impact, whichever is material>

blocking_status: <true|false — does work stop until this is answered?>

safe_default_action: <PLACEHOLDER — what happens if the human does not respond in time; must be the
  conservative option, never "proceed as recommended by default">

affected_version: <PLACEHOLDER>
affected_tasks: <PLACEHOLDER list of task ids>

evidence_refs: <PLACEHOLDER — links/paths to the underlying artifacts (ADR, gate result, contract,
  incident) the human can open if they want more than the summary>

response_required: <PLACEHOLDER — form of answer needed, e.g. "approve | reject | approve with
  conditions" and, if time-sensitive, a due_sequence or deadline>
```

---

## Header note (repeat verbatim in every rendered request)

> This is a decision-ready summary produced by the orchestrator on behalf of the requesting agent.
> It is never raw internal agent chatter. If you need the underlying detail, follow `evidence_refs`.

## Rules

- The orchestrator MAY compress and format; it MUST NOT alter `recommendation`, `risks`, or
  `options` content supplied by the decision owner — only route it.
- `safe_default_action` must never be silently interpreted as approval. No response = no action on
  irreversible triggers (destructive migration, production deployment/rollback, release, security
  exception).
- Every field above must be filled; `null`/`none` is a valid value where genuinely inapplicable
  (e.g. no `options` for a binary approve/reject), but the field must still be present.

---

## Filled example

```yaml
schema_version: 1
id: APPR-2026-07-13-04
requested_by: orchestrator   # relaying release-manager's request

decision_needed: "Approve release v1.3.0 of Acme Boards to production?"

background: >
  Release v1.3.0 (WebSocket presence channel) has cleared independent QA and Security review with
  no blocking findings. Release-manager has assembled the full readiness bundle. This is a
  production deployment, which requires human approval under standing policy regardless of gate
  status.

options:
  - option: "Approve — deploy v1.3.0 now"
    consequence: "Presence feature goes live for all tenants; rollback plan is tested and ready."
  - option: "Approve with conditions — deploy to a 10% canary first"
    consequence: "Slower rollout, lower blast radius if an issue surfaces post-release."
  - option: "Reject — hold release"
    consequence: "Feature stays on main, unreleased; no user-facing change."

recommendation: >
  Approve with conditions (canary at 10% for 24h, then full rollout) — release-manager's evidence
  bundle is clean but this is the feature's first production traffic exposure.

risks: >
  Under full rollout: unverified behavior at production concurrency (load-tested only to 50
  clients/board in staging). Under holding: presence feature continues to slip past its committed
  milestone date.

cost_or_impact: "User-facing feature; no cost impact; ~2h engineering time to monitor canary."

blocking_status: true

safe_default_action: "No deployment. v1.3.0 remains on main, unreleased, pending explicit approval."

affected_version: v1.3.0
affected_tasks:
  - TASK-AB-142

evidence_refs:
  - "release-readiness bundle: RELEASE-READY-2026-07-13-01"
  - "qa-report: QA-2026-07-13-09"
  - "security-report: SEC-2026-07-13-05"

response_required: "approve | approve_with_conditions | reject — due by 2026-07-14T12:00:00Z"
```
