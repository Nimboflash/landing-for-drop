<!-- Conforms to schemas/message.schema.yaml (type: escalation). Provenance: Extracted —
     escalation-matrix.md is the one fully-extracted organization matrix from the source: routing
     by question TYPE, not hierarchy, with a named owner and ladder for every pattern. This
     template operationalizes that real routing table as a sendable message. -->

# Escalation Template

Escalation routes by **question pattern**, never by hierarchy. Before writing one, identify which
canonical question pattern this is — a question pattern with no owner is an organizational bug,
not a reason to guess who to ask.

---

## Question pattern (pick the closest match, or name a new one and flag it)

| question_pattern | ladder (owner → … → human) |
|---|---|
| Product ambiguity | `product-manager` → `human-owner` |
| Scope change | `product-manager` → `human-owner` |
| Architecture disagreement | `software-architect` → `cto` → `human-owner` |
| API/contract conflict | contract owner (`backend-engineer`) → `cto` |
| File-ownership conflict | `orchestrator` (form only) → `cto` (authority) |
| Failed implementation review | responsible implementation agent |
| Failed QA | responsible implementation agent (+ `software-architect`/`cto` if design defect) |
| Critical security issue | `security-engineer` → `cto` → `human-owner` |
| Failed deployment | `devops-engineer` → `release-manager` → `human-owner` |
| Release disagreement | `release-manager` → `human-owner` |
| "Untestable as designed" | `cto` (treat as a design defect, not a QA failure) |
| "Doc disagrees with constitution" | fix the doc — the constitution always wins |

---

## Fields

```yaml
type: escalation
question_pattern: <PLACEHOLDER — from the table above, or a new named pattern>
from_agent: <PLACEHOLDER canonical_id>
to_agent: <PLACEHOLDER — first rung of the ladder for this pattern>
task_id: <PLACEHOLDER | null>

question: <PLACEHOLDER — the actual disagreement or unresolved question, stated precisely>
evidence: <PLACEHOLDER — what has already been tried/considered; do not escalate a question that
  hasn't been worked first>
requested_decision: <PLACEHOLDER — the specific decision being asked for, not just "please help">
blocking_status: <true|false>
priority: <critical|high|medium|low>
status: open
created_at: <PLACEHOLDER ISO-8601>
```

---

## Filled mini-example

```yaml
type: escalation
question_pattern: "Architecture disagreement"
from_agent: backend-engineer
to_agent: software-architect
task_id: TASK-AB-146

question: >
  Should presence events cross module boundaries via an in-process port call (current pattern)
  or via a domain event, now that the notifications module also needs to react to presence
  changes? This is the second consumer of a presence signal.
evidence: >
  ADR-0003 states "in-process dispatch until a 2nd consumer" and specifies "only the transport
  changes" when that trigger fires. The notifications module becoming a second consumer appears
  to be exactly that fired trigger, but I want architecture sign-off before restructuring the
  presence_service internals.
requested_decision: >
  Confirm whether the 2nd-consumer trigger in ADR-0003 has fired, and if so, approve migrating
  presence-change dispatch from a direct port call to a domain event.
blocking_status: true
priority: high
status: open
created_at: 2026-07-13T16:35:00Z
```

Ladder for this escalation: `software-architect` → `cto` (if software-architect and
backend-engineer disagree on whether the trigger fired) → `human-owner` (only if cto's ruling is
itself disputed, which should be rare — cto is the arbiter).
