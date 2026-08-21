# 02 — Organization and Authority (credit-intelligence)

**Purpose.** Who owned which decision in the credit-intelligence source, and how the reusable
framework's organization model (`EXT/04-organization-and-authority.md`) applies to it.

> This document applies the framework to the **credit-intelligence evidence** — the reference
> example — not to a live project. Everything under "The credit-intelligence authority model" is the
> real repository's design; everything under "The recommended overlay" is a framework proposal that
> did not exist in the source. The two are never blended into one claim.

## The credit-intelligence authority model

**Extracted, confidence high, `EXT/12-organization-matrices.md`, `EXT/19-evidence-index.md`.**
The real roster was 10 agents (`cto`, `credit-architect`, `product-manager`, `ai-engineer`,
`data-engineer`, `backend-engineer`, `frontend-engineer`, `devops-engineer`, `security-architect`,
`qa-engineer`) plus the `human-owner`. No agent reported to another — `repo:organization-chart.md`
states authority is "over question types," not hierarchy, and the constitution (`repo:PROMPT.md`)
outranked every agent and document.

Four authority holders anchored the model:

- **`cto`** — architecture authority and final arbiter between agents; the only role permitted to
  change a bounded-context boundary (`repo:DOMAINS.md`: "only cto may change a boundary").
- **`security-architect`** — held the one scoped veto in the system, on the sensitive-data /
  cross-tenant-boundary question. The `cto` could not overrule it (Extracted, high confidence,
  `EXT/12-organization-matrices.md` §escalation-matrix). It had to ship with an alternative and was
  recorded as an ADR.
- **`product-manager`** — owned scope and priority; the PRD content bar; "the agent that says not
  now." No PRD instance was ever run against this bar (Missing, `EXT/09-prd-to-product-workflow.md`),
  but the bar itself is Extracted as a defined rule.
- **`qa-engineer`** — owned merge and promotion **gates**, not code; gates were non-overridable by
  design (Extracted, `EXT/12-organization-matrices.md` §approval-matrix row 1: "red CI never merges,
  no override").

The **`human-owner`** is Extracted by elimination (`EXT/14-automation-assessment.md`): every piece of
work was human-initiated (no scheduler existed), every merge was human, and release approval — never
exercised, since zero versions shipped — would default to human. Source: no PRs, no merges, and no
release ever occurred; this is a design inference from the repo's own stated conventions
(`repo:CONTRIBUTING.md`, `repo:CLAUDE.md`), not an observed act. **Confidence: high** for the
authority claim, **Unverified** for whether it was ever exercised (no git history to check).

The seven remaining agents (`credit-architect`, `ai-engineer`, `data-engineer`, `backend-engineer`,
`frontend-engineer`, `devops-engineer`) held peer domain-owner lanes, each with an `Owner:` line on
every file they controlled, escalating up to `cto` on boundary disputes and never sideways
(`EXT/12-organization-matrices.md` §responsibility-matrix).

## The one documented override

**Extracted, `EXT/12-organization-matrices.md` §approval-matrix row 6.** The source defined exactly
one legitimate gate override: the domain-quality (explanation-stability) threshold, overridable only
by two named roles acting **jointly** — `ai-engineer` (canonical: `ml-engineer`) and `product-manager`
— recorded in the artifact. No other gate in the system, including any CI-class gate, could be
overridden by anyone, including `cto`. This is the only asymmetry the source allowed into its
otherwise absolute "red gate stops the line" rule, and the framework generalizes it as the *only*
legitimate override shape (`EXT/04-organization-and-authority.md` §"The one documented override").

## The recommended overlay: orchestrator and release-manager

**Recommended, not in source.** Applying the reusable framework to this project adds two roles the
credit-intelligence repository never had:

- **`orchestrator`** — would own the temporal layer (intake, decomposition, dispatch, state, handoff
  validation, retries) that the source achieved structurally instead (see `03-orchestrator-
  configuration.md`). It holds no decision authority and cannot touch the scoped veto, scope, or
  architecture.
- **`release-manager`** — would own versioning, release-readiness evidence assembly, and ship/no-ship
  packaging on independent QA + security + devops evidence, never shipping without the human's go. The
  source had no release role at all (`EXT/13-git-devops-release.md`: "release approval authority: not
  found").

Both are additions to the authority map, not replacements for anything real. Neither acquires the
`cto`'s architecture authority, the `security-architect`'s veto, or the `product-manager`'s scope
ownership.

## Responsibility matrix (RACI-style)

| Artifact type | Responsible | Accountable | Consulted | Gate / Veto |
|---|---|---|---|---|
| PRD / product scope | product-manager | product-manager | cto, security-architect | — |
| Architecture / ADR | cto (drafts itself; no software-architect split existed) | cto | affected agents | human ratifies |
| Domain/business policy | credit-architect | credit-architect | ai-engineer (calibration), product-manager (appetite) | qa-engineer |
| API / data contract | backend-engineer (impl) + credit-architect (semantics) | cto (boundaries) | frontend-engineer, ai-engineer | contract tests |
| Model / feature semantics | ai-engineer | ai-engineer | — | qa-engineer (leakage/replay/stability), security-architect (fairness, designed not built) |
| Merge / promotion | qa-engineer | qa-engineer | — | non-overridable |
| Security / data legality | security-architect | security-architect | cto | terminal veto |
| Deployment plumbing | devops-engineer | devops-engineer | — | Specified, not implemented (`EXT/13`) |
| Release *(recommended row)* | release-manager | release-manager | qa-engineer, security-architect, devops-engineer | human approval |

*Consulted means before, not after — the source's hardest rule: security is consulted before a
collector is built, never after (Extracted).*

## Decision-authority matrix

| Decision type | Owner | Required reviewers | Required approver | Prohibited approvers | Human? |
|---|---|---|---|---|---|
| Product scope | product-manager | cto, security-architect | human-owner | — (orchestrator N/A: none existed) | yes, for changes |
| Architecture & boundaries | cto | affected agents | cto + human ratifies | implementation agents | yes, major |
| Domain/business policy | credit-architect | ai-engineer, product-manager | credit-architect | — | no |
| API/data contracts | backend-engineer + credit-architect + cto | frontend-engineer, ai-engineer | cto (boundaries) | — | no |
| Model/feature semantics | ai-engineer | — | ai-engineer | — | no |
| Merge & promotion gates | qa-engineer | — | qa-engineer | anyone overriding | no |
| Security / data legality | security-architect | cto | security-architect (veto) | cto | yes, for exceptions |
| Release approval *(recommended)* | release-manager | qa-engineer, security-architect, devops-engineer | human-owner | implementation agents | yes |
| Production deployment *(designed, never built)* | devops-engineer (exec) | release-manager | human-owner | implementation agents | yes |

## Approval matrix

| Change type | Requires |
|---|---|
| Any PR | Independent review + green CI (red CI never merges, no override) — Extracted |
| Boundary-crossing change | + cto approval, tagged | Extracted |
| Sensitive-data / new signal | + security-architect consulted **before building**, veto authority | Extracted |
| Infrastructure adoption | + a named migration trigger written before the proposal and demonstrably fired, recorded in an ADR; no fired trigger = auto-reject | Extracted |
| Model promotion | Every gate passing, each gate names its enforcing agent | Extracted (design); gates themselves unimplemented |
| Domain-quality gate override | Two named roles jointly (ai-engineer + product-manager) — the only documented override | Extracted |
| Release to users *(recommended)* | Human approval against a checklist | Recommended |
| High-risk assumption *(recommended)* | Human approval + a falsification condition | Recommended |

## Escalation matrix (fully Extracted — the one fully-extracted matrix)

| Question pattern | Owner | Escalates to |
|---|---|---|
| Infrastructure / boundary change | cto | human-owner |
| Threshold / limit / business term | credit-architect | cto |
| Feature meaning / model semantics | ai-engineer | cto |
| May we collect this data? | security-architect (before building) | cto → human-owner (cannot be overruled) |
| Worth building? Sequencing? | product-manager | human-owner |
| Release metric disagreement | ai-engineer + product-manager jointly | human-owner |
| Contract is wrong | backend-engineer | cto |
| Doc disagrees with constitution | — | fix the doc (no escalation; it's a bug) |

*A question pattern with no owner is an organizational bug — the source had none (Extracted rule,
`EXT/12-organization-matrices.md`).*

## Separation-of-duties matrix

| Task | Owner (implements) | Reviewer (independent) | Approver |
|---|---|---|---|
| Feature implementation | backend/frontend/ai/data-engineer | human via `/pr-check` (no standing code-reviewer agent existed) | qa-engineer (gate) |
| Architecture decision | cto (drafts) | affected agents | cto + human-owner ratifies |
| Domain policy change | credit-architect | ai-engineer, product-manager | credit-architect |
| Security review | security-architect | cto (consulted, cannot approve past the veto) | security-architect |
| Merge | any implementing agent | human (1 review + green CI required) | qa-engineer gate, non-overridable |

No agent in the source ever moved its own work into an approval or completed state — this is a
structural design property (module-owned schemas, `Owner:` lines, gates-not-code) rather than an
enforced technical permission, since **no per-agent tool restrictions existed** (`no tools: key in any
agent frontmatter`, Extracted, `EXT/19-evidence-index.md` #25). The framework's `orchestrator` and
`release-manager` additions do not change this matrix's real rows — they only add rows for the
capabilities the source never built (see `03-orchestrator-configuration.md`).

## Reusable rules applied here

- credit-intelligence proves the "authority over question types, not hierarchy" model in its purest
  form: 10 peer agents, one constitution, one arbiter, one veto, one gate-owner.
- The scoped veto is the project's single most distinctive governance fact and must never be
  described as overridable, generalizable to more than one question, or held by anyone but
  `security-architect`.
- The one documented override (ai-engineer + product-manager jointly, on the stability gate) is the
  *only* override this project's evidence supports — it must not be used to justify overriding any
  CI-class gate.
- `orchestrator` and `release-manager` are additive: they fill rows the real matrix left empty, they
  do not re-open any row the real matrix already closed.
