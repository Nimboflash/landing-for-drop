# 11 — Quality, Security, and Release Gates

**Purpose.** Catalog what's actually enforced today in credit-intelligence versus what's only written
down, the one scoped veto, the one documented override, and the release/deploy/rollback tail this
project still needs to specify.

> This document applies the quality/security/release framework (`framework/14-quality-security-and-release.md`)
> to the credit-intelligence EVIDENCE. CI gates are Extracted and implemented; the four domain gates
> are Extracted-as-specification but explicitly NOT implemented; the release/deploy/rollback tail is
> Recommended (Missing in source).

## Extracted, implemented: the CI floor

Two CI jobs run on every push to `main` and every PR — `check` and `secrets` — and both are blocking
with **no override authority for anyone**:

| Gate | Owner | Blocking | Override authority |
|---|---|---|---|
| Format (`ruff format --check`) | CI (automated) | yes | none |
| Lint (`ruff`) | CI (automated) | yes | none |
| Type check (`mypy --strict`) | CI (automated) | yes | none |
| Unit/property tests (`pytest` + hypothesis) | CI (automated) | yes | none |
| Secret scan (`gitleaks`, full history) | CI (automated) | yes | none |
| Layering test (`tests/test_layering.py`, AST dependency-rule check) | CI (automated) | yes | none |

The job header states the doctrine directly: "Red CI does not merge — no exceptions, no overrides, no
'just this once before the demo.'" This is the project's one fully-automated lifecycle stage (of 21
scored stages, only test execution scores 1.0 — fully automated). — *Classification: Extracted.
Evidence: EXT/06-automation-assessment.md (stage 12), repo:.github/workflows/ci.yml. Confidence: high.*

## Specified, NOT implemented: the four domain gates

`MODEL_REGISTRY.md` names 8 promotion gates, each with a named enforcing agent — but the four
credit-specific correctness checks exist only as documentation, with no CI mechanism behind them:

| Gate | Enforcing agent (named) | Status |
|---|---|---|
| Leakage detection | qa-engineer | specified, not implemented |
| Decision replay | qa-engineer | specified, not implemented |
| Explanation (SHAP) stability | qa-engineer / ai-engineer | specified, not implemented |
| Monotonicity | qa-engineer | specified, not implemented |

These four are exactly the "looks-better-when-broken" failure class the framework's domain-correctness
slot exists for (`14`): checks that catch a build that *passes* while the underlying credit decision is
subtly wrong (a leaked label, a decision that can't be replayed from its pinned artifacts, an
explanation that flips under noise, a risk score that goes the wrong direction as an input worsens).
Today they are what the automation assessment calls "verification theater" risk — named, owned, but
not wired. **Recommended sequencing**: wire these into CI before the first Version-1 decision-path
artifact ships, per the framework's general rule that a domain gate specified after the fact becomes
theater rather than protection. — *Classification: Extracted (the specification, the naming, the
enforcing-agent assignment) / Missing (the implementation). Evidence: EXT/01 (MODEL_REGISTRY.md, "8
promotion gates each with an enforcing agent"), EXT/06 (stage 13: "the four decision-path gates
unimplemented"), EXT/16-reusability-assessment.md ("keep the slot, replace the contents" — noted as
project-specific content to leave behind, but the slot itself as a reusable pattern). Confidence: high.*

A fifth domain concern, **fairness**, is named in the agent-evolution record as a duty `qa-engineer`
is expected to gain in Version 2 ("qa gains champion/challenger + fairness gates") but is not yet
specified as a Version-1 gate at all — included here as a Recommended addition to the domain-gate slot
for this project, given the regulatory profile of credit underwriting, not because the source
specifies it for Phase 1.

## The scoped security veto

`security-architect`/`security-engineer` holds a veto on exactly one existential-compliance question
for this project — the sensitive-data / data-collection boundary (what may lawfully be collected and
used as a signal, given unlicensed centralization is illegal per this project's own founding
constraints). This veto:

- **The `cto` cannot overrule it.** It is the one deliberate asymmetry the source's own escalation
  matrix preserves on purpose.
- **It must ship with an alternative** — a veto without an alternative is incomplete.
- **It is recorded as a decision** (an ADR-shaped record), not a verbal no.
- **It is exercised before building**, not before merging — the project's own doctrine is that if a
  signal should never have been collected, catching it after the fact means "deleting the feature *and
  everything derived from it*," which is categorically worse than catching it at design time.
- **It is scoped to exactly this one question and nothing else** — the framework's own caution applies
  doubly here: letting the veto creep beyond the data-boundary question degrades it into general
  obstruction rather than a targeted compliance control.

*Classification: Extracted. Evidence: EXT/07-reusability-assessment.md (organization-chart.md: "the
scoped VETO the arbiter cannot overrule"), EXT/09 (stage 18: security review "before building"),
EXT/12c (escalation-matrix.md: "may-we-collect-data → security-engineer *before building*").
Confidence: high.*

## The one documented override

The only routine override pattern the source records anywhere: a **domain-quality gate threshold**
overridden jointly by two named roles — `ai-engineer` + `product-manager` — recorded in the artifact.
This is not a general escape hatch; it applies to exactly this one threshold-override pattern and is
the only override this project should replicate. CI-class blocking gates (the six in the table above)
are never overridden by anyone, including this pair. — *Classification: Extracted. Evidence:
EXT/12c (approval-matrix.md row 6: "domain-quality-gate override = two agents jointly... the only
documented override"), design-spine §12. Confidence: high.*

## The Recommended release/deploy/rollback/post-release tail

The source specifies deployment intent (`devops-engineer.md`: "Deploy is a single reproducible
command, and rollback is a single command too — test the rollback before you need it") but implements
**none** of it: no Dockerfile, no Compose file (despite Compose being named the Phase-1 runtime), no
environments, no IaC, no release notes, no changelog, no rollback mechanism, no release-approval
authority named anywhere in the docs. This is one of the "zero-implementation stages" (5 of 21, ≈24%)
— the entire delivery tail plus dependency management. — *Classification: Missing. Evidence:
EXT/05-git-devops-release.md, EXT/06 (stages 18–21 all score 0). Confidence: high.*

Recommended tail for this project, gated the same way the framework specifies generically:

- **Release readiness** (owner `release-manager`, blocking, human approval required) — assembled from
  **independent** QA and Security evidence (per `09`), never from `backend-engineer`'s or
  `ai-engineer`'s own handoff summary.
- **Deployment verification** (owner `devops-engineer`, blocking, human authorizes) — the single
  reproducible command the source already names in doctrine, actually wired to Compose for Version 1.
- **Post-release validation** (owner `release-manager` + `product-manager`, blocking) — checked against
  the version's own falsifiable exit gate (`07`) — for Version 1, literally: did a design partner say
  "run this on our next cohort"?
- **Rollback** (`devops-engineer` recommends, `release-manager` + human decide) — rehearsed, not just
  documented; "test the rollback before you need it" becomes an actual pre-release check, not a line in
  a markdown file.

## Blocking vs. non-blocking table

| Gate | Blocking? | Override authority |
|---|---|---|
| Format, lint, type-check, unit tests, secret scan, layering | yes | none |
| Requirement validation | yes | qa/PM, no CI-stage override |
| Architecture review | yes | cto; human ratifies major decisions |
| Domain-correctness (leakage/replay/stability/monotonicity) | yes (once implemented) | qa-engineer; the one joint threshold-override exception above |
| Security review (the veto) | yes | none — by design |
| Formatting auto-fix | no | n/a |
| Visual QA / accessibility | profile-dependent (not blocking for this backend/data-heavy profile) | n/a |
| Release readiness | yes | release-manager, human approval required |
| Deployment verification | yes | devops-engineer, human authorizes |
| Post-release validation | yes | release-manager + PM vs. exit gate |

## Reusable rules (recap)

- The CI floor (format/lint/mypy/pytest/gitleaks/layering) is real, blocking, and non-overridable —
  keep it exactly as strict when Version 1 work starts.
- The four domain gates are named and owned but not implemented; wire them into CI before the first
  decision-path artifact ships, or they remain paper gates.
- The security veto is scoped to the data-collection boundary alone, unoverrulable by `cto`, exercised
  before building, and always ships with an alternative.
- The only override anywhere is the domain-quality threshold, jointly by `ai-engineer` + `product-manager`,
  recorded — do not generalize this into a broader override pattern.
- The release/deploy/rollback/post-release tail does not exist yet; build it gated on independent QA +
  security evidence and human approval, with rollback rehearsed before Version 1 ships.
