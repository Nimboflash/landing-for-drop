# 14 — Quality, Security, and Release

**Purpose.** The gate stack that decides what may merge, promote, and ship; the scoped security veto;
and the release-readiness discipline. Completion is defined by gates, not by anyone flipping a status
field.

> **Provenance banner.** Gates-over-status, non-overridable CI, the enforcement triad, and the scoped
> veto are **Extracted**. The release/deploy/rollback/post-release tail is **Recommended** (Missing in
> the source). The specific domain gates named below are the source's *exemplars*; each project
> defines its own.

## The gate as the definition of done

The source's strongest property was that **failed work could not be declared complete** — by three
independent mechanisms: edit-time hooks that blocked at write time with no bypass; CI declared
non-overridable in several places at once; and per-agent definitions of done that made "done" a
checkable state. The framework generalizes this into one rule: **a task enters `completed` only with
attached gate evidence.** The status field records that the evidence exists; it never substitutes for
it.

## The gate record

Every gate is defined by `schemas/quality-gate.schema.yaml`: `id, name, owner, independent_from,
trigger, required_inputs, checks, pass_criteria, failure_behavior, blocking, override_authority,
human_approval_required, evidence_recorded, status`. Two fields carry the governance: `independent_from`
(the gate's owner must be independent of the implementer) and `override_authority` (which for
CI-stage blocking gates **must be `none`**).

## The canonical gate set

Configured per project (a `minimal` project runs a few; a `regulated` one runs most), spanning the
lifecycle:

| Gate | Owner | Blocking | Notes |
|---|---|---|---|
| Requirement validation | product-manager / qa | yes | acceptance criteria are QA-executable |
| Architecture review | cto / software-architect | yes | ADR exists; human ratifies major |
| Formatting | (automated) | no | auto-fix |
| Linting | (automated CI) | yes | includes security lint rules |
| Type checking | (automated CI) | yes | strict |
| Unit tests | (automated CI) | yes | red = no merge |
| Integration tests | (automated CI) | yes | real dependencies |
| Contract tests | (automated CI) | yes | consumer/provider parity |
| End-to-end tests | qa / test-automation | profile | on for UI-bearing profiles |
| Visual QA | ux-design-system / qa | profile | frontend/mobile |
| Accessibility | ux-design-system / qa | frontend_only, mobile | blocking there |
| Performance | qa / devops | profile | latency/load budgets |
| Security review | security-engineer | yes | veto; `override_authority: none` |
| Dependency check | devops / qa | yes | audit new/changed deps |
| Secret scanning | (automated CI) | yes | non-overridable |
| Migration validation | database-engineer | when a DB exists | reversibility proven |
| Build verification | devops-engineer | yes | reproducible from clean checkout |
| Documentation completeness | documentation-engineer | profile | high-risk/regulated |
| Release readiness | release-manager | yes | human approval required |
| Deployment verification | devops-engineer | yes | human authorizes |
| Post-release validation | release-manager + PM | yes | vs the version exit gate |
| Domain-correctness | qa-engineer | yes | project-defined (see below) |

## Domain-correctness gates (the project's own)

Beyond the generic gates, each project defines the small set of checks that catch its
"looks-better-when-broken" failure modes — the failures that make a build *pass* while the product is
subtly wrong. The source's exemplars (for a credit engine) were leakage, decision replay, explanation
stability, and monotonicity, each wired as a promotion gate with a named enforcing agent. The
framework keeps the *slot*, not the contents: a `frontend_only` project's domain gates might be
accessibility and visual regression; a `data_or_ai` project's might be leakage and fairness. Wire
them into CI **before** the first domain artifact ships, or they become verification theater —
specified but not enforced, the exact trap the source fell into with its four paper gates.

## No self-approval, no orchestrator override

Two hard rules bound the gate system: **no implementation agent may finally approve its own work**,
and **no orchestrator may override a failed blocking gate.** Any override at all must be explicit,
evidence-backed, time-bound where applicable, recorded in project state, and approved by the
authorized human or governance role. The only legitimate *routine* override the framework permits is
the source's one documented pattern: a domain-quality threshold, overridden by two named authorities
jointly (for example `ml-engineer` + `product-manager`), recorded in the artifact. CI-class blocking
gates are never overridden.

## The scoped security veto

Security is both a review gate and an authority. The `security-engineer` reviews architecture,
authn/authz, dependency, data-handling, and infrastructure changes, and returns findings with
severity, blocking status, and required remediation. On the one existential-compliance question
defined for the project, the engineer holds a **veto the CTO cannot overrule**; the veto must ship
with an alternative and is recorded as a decision. Security is consulted **before** the thing is built
— a signal or collector approved only after the fact, if it should never have been collected, means
deleting the feature *and everything derived from it*. Timing is the doctrine.

## Release readiness (Recommended)

The `release-manager` assembles an evidence bundle — **independent** QA results, **independent**
security results, and DevOps/build/rollback readiness — and must not rely on an implementation agent's
summary. Release readiness is a blocking gate that additionally requires human approval. Deployment is
authorized by the human and executed by DevOps; post-release validation checks the deployed system
against the version's exit gate, and a failed validation triggers the rollback path (`devops`
recommends, `release-manager` + human decide).

## Reusable rules (recap)

- Completion is gate evidence attached, never a flipped status field.
- Every gate names an owner independent of the implementer; CI-stage blocking gates have
  `override_authority: none`.
- Define project-specific domain gates and wire them into CI *before* the first domain artifact.
- No self-approval; no orchestrator override; the only routine override is a domain threshold, two
  named roles jointly, recorded.
- The security veto is scoped, unoverrulable, carries an alternative, and is exercised *before* build;
  release readiness rests on independent QA + security evidence and human approval.
