# 04 — Organization and Authority

**Purpose.** Who owns which decision, who reviews it, who approves it, and who may never approve it.
This is the organization — not a headcount chart, but a map of authority over question types.

> **Provenance banner.** Reusable / project-independent. The authority model, the scoped veto, and
> "authority over question types, not hierarchy" are **Extracted**; the release/deploy/rollback
> authorities are **Recommended** (the source had no release role); the orchestrator's coordination
> authority is **Recommended**.

## The source had authority, not hierarchy (Extracted)

The reference repository defined **no reporting relationships** — no agent "reported to" another.
What it defined was *authority over specific kinds of question*, and a constitution that outranked
every agent and document. This is the model the framework generalizes: an organization is a map of
who decides what, not a tree of who manages whom. Four facts from the source anchor it: the `cto`
was architecture authority and final arbiter between agents; the `security-engineer`
(source: `security-architect`) held a scoped veto the CTO could not overrule; the `product-manager`
owned scope; and the `qa-engineer` owned what blocks a merge and a promotion, non-overridably. The
`human-owner` supplied all sequencing, every merge, and would supply release.

## Answers to the fifteen authority questions

- **Who communicates with the human owner?** The `orchestrator` (as decision-ready summaries) and,
  for domain matters, the relevant owner.
- **Who receives the PRD?** The `orchestrator` intakes it; the `product-manager` owns its content
  bar.
- **Who owns product scope?** `product-manager` (execution split to `product-owner` at scale).
- **Who owns architecture?** `cto` (drafted by `software-architect` when split).
- **Who owns task decomposition?** `orchestrator` (form only — scope stays with PM, architecture
  with CTO).
- **Who assigns tasks?** `orchestrator`.
- **Who monitors project state?** `orchestrator` (coordination fields only).
- **Who resolves product ambiguity?** `product-manager`, escalating to the `human-owner`.
- **Who resolves technical disagreement?** `software-architect` → `cto` (final arbiter) → human.
- **Who approves contracts?** The contract owners jointly (`backend-engineer` for implementation,
  `domain-policy-architect` for semantics, `cto` for boundaries).
- **Who approves implementation quality?** An independent `code-reviewer`, then `qa-engineer` at the
  gate — never the implementer.
- **Who approves security?** `security-engineer` (terminal on the data boundary; veto).
- **Who approves release readiness?** `release-manager` on independent evidence, then the
  `human-owner`.
- **Who authorizes production deployment?** The `human-owner`; executed by `devops-engineer`; never
  an implementation agent, never the orchestrator.
- **Who owns rollback decisions?** `devops-engineer` recommends; `release-manager` and `human-owner`
  decide.

## The decision block

Every important decision is specified in this shape, so ownership and separation of duties are
explicit and machine-checkable:

```yaml
decision:
  decision_type:          # e.g. product_scope, architecture, release_approval
  owner:                  # the single accountable role
  required_reviewers:     # who must be consulted before it is made
  required_approver:      # who signs off (may be human:<role>)
  prohibited_approvers:   # who may NEVER approve it (e.g. the owner, the orchestrator)
  human_approval_required: # true | false
  evidence_required:      # what evidence must be attached
```

Worked examples (abbreviated):

| decision_type | owner | required_reviewers | required_approver | prohibited_approvers | human? |
|---|---|---|---|---|---|
| product_scope | product-manager | cto, security-engineer | human-owner | orchestrator | yes (changes) |
| architecture | cto | affected agents | cto + human ratifies ADR | orchestrator, impl agents | yes (major) |
| domain_policy | domain-policy-architect | ml-engineer, product-manager | domain-policy-architect | orchestrator | no |
| api_contract | backend-engineer | frontend-engineer, cto | cto (boundaries) | — | no |
| merge/promotion | qa-engineer | — | qa-engineer (gate) | anyone overriding | no |
| security | security-engineer | cto | security-engineer (veto) | cto, orchestrator | yes (exceptions) |
| release_approval | release-manager | qa-engineer, security-engineer, devops-engineer | human-owner | impl agents | yes |
| production_deploy | devops-engineer (exec) | release-manager | human-owner | impl agents, orchestrator | yes |
| rollback | devops-engineer | release-manager | human-owner | — | yes |

## The five matrices

The full tables live in the project blueprint (`projects/<slug>/blueprint/02-...`), configured per
project; the framework fixes their shape:

- **Responsibility matrix (RACI-style).** For each artifact type: who is Responsible, Accountable,
  Consulted, and what Gate/Veto applies. Note that *Consulted means before, not after* — the source's
  hardest-won rule (security is consulted *before* a collector is built, not after).
- **Decision-authority matrix.** The decision blocks above, one row per decision type.
- **Approval matrix.** What each change type requires: any change → independent review + green CI;
  boundary crossing → + CTO; sensitive-data/PII/new signal → + security, consulted *before* building;
  infrastructure adoption → + a named migration trigger that has *actually fired*; model promotion →
  every gate passing with a named enforcing agent; release → human approval on the evidence bundle.
- **Escalation matrix.** Question pattern → named owner → … → human. A question pattern with no owner
  is an organizational bug.
- **Separation-of-duties matrix.** For each task, `owner ≠ reviewer ≠ approver`; the orchestrator
  never approves; no agent approves its own work.

## The scoped veto (Extracted — the distinctive asymmetry)

The `security-engineer` holds a veto on exactly one existential-compliance question for the project
(in the source: any design that centralizes raw partner data across a tenant boundary). The
`cto`/arbiter **cannot overrule it**; it "outranks the roadmap"; it must be delivered **with an
alternative** ("a veto without an alternative is just an obstacle"); and it is recorded as a
decision/ADR. It is deliberately scoped to that *one* question and nothing else — narrow enough to be
respected, absolute where it matters. This is the single most distinctive governance idea the source
contributed, and the framework preserves it exactly. Naming that one question is a required step in
every project profile (`scoped_veto` in `project-profile.yaml`); if no such question exists, say so
rather than inventing one.

## The one documented override

The source permitted exactly one override of a gate, and only jointly: the explanation-stability
threshold could be overridden by two named roles together (`ml-engineer` + `product-manager`),
recorded in the artifact. The framework generalizes this as the *only* legitimate override shape — a
domain-quality threshold, two named authorities jointly, recorded — and forbids overriding CI-class
blocking gates entirely.

## Reusable rules (recap)

- Organize by authority over question types, not by hierarchy; the constitution outranks all.
- Every decision has one owner, named reviewers, a named approver, and named *prohibited* approvers.
- Consulted means *before*, not after — especially for security.
- The scoped security veto is unoverrulable, must carry an alternative, and covers one question only.
- The only legitimate gate override is a domain-quality threshold, two named roles jointly, recorded;
  CI-class blocking gates are never overridden.
