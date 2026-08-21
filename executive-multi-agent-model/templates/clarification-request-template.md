<!-- Conforms to schemas/message.schema.yaml (type: clarification_request). Provenance:
     Recommended — formalizes the source's cultural rule "challenge the request before satisfying
     it" (evidence-digest §2, stage 3) into a structured, blocking message. -->

# Clarification Request Template

Use when a requirement, contract, or instruction is ambiguous enough that proceeding would risk
building the wrong thing. This is a `clarification_request` specialization of the standard message
envelope (see agent-message-template.md) — all envelope fields still apply; this template focuses
on the fields unique to making the ambiguity actionable.

---

## Envelope basics

```yaml
type: clarification_request
from_agent: <PLACEHOLDER — agent raising the question>
to_agent: <PLACEHOLDER — see "who must answer" below>
task_id: <PLACEHOLDER | null>
priority: <critical|high|medium|low>
blocking: <true|false>
status: open
```

## What is ambiguous

<PLACEHOLDER — state the exact sentence, field, or requirement that is unclear. Quote it. Do not
paraphrase away the ambiguity.>

## Why it blocks

<PLACEHOLDER — explain concretely what cannot proceed, or what would have to be guessed, without
an answer. If it does not actually block work, this should be a `low`-priority, non-blocking
message, not an escalation.>

## Options considered

| Option | Consequence if chosen | Recommended? |
|---|---|---|
| <PLACEHOLDER option A> | <PLACEHOLDER> | <yes/no> |
| <PLACEHOLDER option B> | <PLACEHOLDER> | <yes/no> |
| <PLACEHOLDER option C, if any> | <PLACEHOLDER> | <yes/no> |

> Do not present an empty menu. Even when asking a genuine open question, show what you already
> ruled out and why — this is what separates a real clarification from routed indecision.

## Who must answer

**target_agent / role:** <PLACEHOLDER — use the escalation-matrix routing: the owner of the
decision type this ambiguity touches (e.g. product ambiguity → product-manager; architecture
disagreement → cto; scope change → product-manager → human-owner). Never route to orchestrator —
it holds no decision authority.>

## Blocking status

`blocking: <true|false>` — if `true`, the task named in `task_id` MUST remain in its current state
(not advance) until this message reaches `resolved`.

---

## Filled mini-example

```yaml
type: clarification_request
from_agent: backend-engineer
to_agent: domain-policy-architect
task_id: TASK-CI-071
priority: high
blocking: true
status: open

What is ambiguous: >
  DECISION_ENGINE.md §3 says "binding_cap applies per partner" but the API contract
  (docs/api/decision-api.md) shows binding_cap as a single value per decision request with no
  partner_id field. It is unclear whether binding_cap should be looked up per-partner at request
  time or passed in by the caller.

Why it blocks: >
  Implementing the persistence layer requires knowing whether binding_cap is a computed value
  (requires a partner lookup + join) or a pass-through field (requires only validation). These
  are different schemas and different audit-log shapes; picking wrong means a rework cycle
  through security_review again.

Options considered:
  - option: "Compute binding_cap server-side from partner_id at decision time"
    consequence: "Requires partner lookup service; safer against caller tampering"
    recommended: yes
  - option: "Accept binding_cap as caller-supplied input, validate against a stored ceiling"
    consequence: "Simpler; caller could theoretically pass an out-of-policy value if validation
      has a gap"
    recommended: no

Who must answer: domain-policy-architect (owns domain/business policy semantics per decision-
  spine §4); escalates to cto only if domain-policy-architect and backend-engineer cannot agree
  on the resulting contract shape.

Blocking status: true — TASK-CI-071 stays in `blocked` until resolved.
```
