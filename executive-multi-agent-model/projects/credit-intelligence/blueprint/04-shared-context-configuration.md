# 04 — Shared Context Configuration (credit-intelligence)

**Purpose.** How the reusable shared-context model (`EXT/06-shared-context-model.md`) maps onto the
real governance documents credit-intelligence already had, section by section.

> This document applies the framework to the **credit-intelligence evidence** — the reference
> example. The governance documents named below are real files in the source repository (Extracted).
> The section-by-section ownership table, the staleness envelope, and the append-only decision-log
> file path are the framework's Recommended formalization of that Extracted kernel — the source never
> stored this as one `shared-context.yaml`; it stored it as a set of separate root-level Markdown
> files, each with its own `Owner:` line.

## The constitution outranks everything (Extracted)

**`repo:PROMPT.md`** is the constitution. It carries the mission, the four constraining facts
(behavioral data predicts; labels can't be originated; regulation prices value; unlicensed
centralization is illegal), the eight non-negotiables (each with its stated *why*), the Phase 1 /
Target split, the 10-agent roster with an Owns / Never-touches column, and the one scoped veto. Its
precedence rule is stated verbatim in the repository: **"When a doc and this file disagree, this file
wins, and the doc is a bug."** `repo:CLAUDE.md` is the session-loaded operating layer that distills
`PROMPT.md` for automatic loading at the start of every agent session. Together these two files are
Layer 0 of the repository's own four-layer map (`EXT/01-repository-structure.md`). No governance
document below outranks either of them; a document that disagreed would be treated as a bug to fix,
not a source of truth to obey — the repository's own stated rule, evidenced concretely in
`EXT/11-prompts-skills-instructions.md`'s finding that `repo:credit-architect.md` contradicts the
constitution on Phase 1 gating, and is therefore classified in the source's own terms as "a bug to be
fixed against the constitution."

## Real governance documents mapped to shared-context sections

The source stored its shared context as separate root-level files rather than one YAML, but each
file's role maps cleanly onto a framework section:

| Real document | Shared-context section | Owner (per repo `Owner:` line) | Notes |
|---|---|---|---|
| `repo:DOMAINS.md` | Architecture decisions / boundaries | `cto` | "Only cto may change a boundary." 20 bounded contexts (Core 9 / Supporting 9 / Generic 3); ubiquitous-language glossary in §6 treated as binding ("a `bad` is not a delinquent"). |
| `repo:DECISION_ENGINE.md` | Business rules | `credit-architect` (canonical: `domain-policy-architect`) | Full decision-object schema; converts model probability into business decision (threshold, limit, term). |
| `repo:SECURITY.md` | Security requirements | `security-architect` (canonical: `security-engineer`) | Carries the scoped veto's substance — the sensitive-data / cross-tenant-boundary question. |
| `repo:ROADMAP.md` | Approved scope / active version | `product-manager` | Three phases, each one falsifiable exit gate; explicit "do not negotiate back in" OUT lists per phase. |
| `repo:MODEL_REGISTRY.md` | Quality gates (model promotion) | `qa-engineer` (gate ownership) / `ai-engineer` (content) | 8 promotion gates, **each with a named enforcing agent** — the gate *design* is Extracted; the four decision-path gates were never wired into CI (Missing as mechanism). |
| `repo:ARCHITECTURE.md` | Architecture decisions (narrative) | `cto` | 8-step runtime decision flow; two structural non-negotiables (inference/policy never merged; audit write synchronous inside the decision transaction, per `ADR/0003`). |
| `repo:API_GUIDELINES.md` + `docs/api/decision-api.md` | API contracts | `backend-engineer` (impl) + `credit-architect` (semantics) + `cto` (boundaries) | `docs/api/decision-api.md` is the single most complete artifact in the repository. |
| `repo:CODING_STANDARDS.md` | Coding standards | `cto` | Applies to all engineering lanes. |
| `repo:EXPLAINABILITY.md`, `repo:SHAP_STABILITY.md` | Testing standards (domain-correctness) | `qa-engineer` | Defines the stability/explanation gates — the one documented joint-override lives here (see `02-organization-and-authority.md`). |
| `repo:DATA_PIPELINE.md`, `repo:FEATURE_STORE.md` | Data / database contracts | `data-engineer` | Substrate ownership; feature *definitions* stay with `ai-engineer` — a deliberately sharp seam. |
| `repo:CONTRIBUTING.md`, `repo:CLAUDE.md` | Git rules | `devops-engineer` (convention) / `cto` (review) | Branch/PR/commit conventions; review priority order (boundaries → hidden business rules → replayability → PII → test level → style). |
| *(none — Missing)* | Deployment rules | — | `repo:devops-engineer.md` specifies "deploy is a single reproducible command" but no deployment-rules document or mechanism exists. |
| *(none — Missing)* | Release rules | — | No release-rules document, no release role. Recommended: owned by `release-manager` once added. |
| *(none — Missing)* | Approved assumptions | — | No assumption register existed anywhere in the repository (`EXT/09` stage 4: "Partial" — assumptions only entered via ADRs, never tracked as a standing register). |
| *(none — Missing)* | Current status | — | No status artifact of any kind; "docs are the memory," a conversational, untracked process. |

## Governance envelope per section (as configured for this project)

Applying the framework's per-section fields (allowed editors, required reviewers, read permissions,
approval requirement, versioning method, staleness detection, conflict path, notification list) to
the mapped sections above:

| Section | Allowed editors | Required reviewers | Human approval? | Staleness rule |
|---|---|---|---|---|
| Architecture (`DOMAINS.md`, `ARCHITECTURE.md`) | cto | affected agents | yes, major changes | > 1 working day since a known trigger fired = suspect |
| Business rules (`DECISION_ENGINE.md`) | credit-architect | ai-engineer, product-manager, qa-engineer | no | same |
| Security (`SECURITY.md`) | security-architect | cto | yes, for exceptions | same |
| Scope (`ROADMAP.md`) | product-manager | cto, security-architect | yes, for scope changes | same |
| Model gates (`MODEL_REGISTRY.md`) | qa-engineer (gate definitions), ai-engineer (content) | — | no | same |
| API contracts (`docs/api/decision-api.md`) | backend-engineer + credit-architect + cto | frontend-engineer, ai-engineer | no | versioned explicitly — breaking change = new `/v1/` → `/v2/` |

All sections are readable by every agent — the source recorded no restricted-read content anywhere
(`EXT/19-evidence-index.md`: no secrets found in the repository). The staleness rule is a framework
addition; the source had no `last_updated` mechanism on any of these documents (Missing), so applying
it here is Recommended, layered onto real, Extracted documents.

## The decision log: the real `ADR/` directory pattern (Extracted)

The source's decision log is not a Recommended invention — it is a real, working pattern:
**`repo:ADR/`**, containing `0001-monorepo.md`, `0002-ddd.md`, `0003-event-driven.md`, authored via the
`/adr` skill (`repo:.claude/skills/adr/SKILL.md`). Each ADR follows a 5-part format and the repository
enforces "a decision that is not an ADR does not exist" as a stated rule. Numbering evidence
(`0002` cites `0001`; `0003` cites both) shows they were authored in strict sequence — a **strong
inference**, since the source has no git history to confirm write order directly
(`EXT/26-version-specific-evidence.md` V8, confidence Med-High). `ADR/0002` itself calls the 20
bounded contexts in `credit-architect.md` "a hypothesis, not a fact" — evidence the ADR set was
written with an awareness of, and partially in correction of, the earlier seed agent
(`EXT/20-...` / `EXT/24-...`, the Gen-0 seed story).

The framework's `decision-log.yaml` (append-only, ADR-shaped: context, decision, alternatives
rejected, consequences accepted, reversal trigger, fired migration trigger) is a direct, Recommended
formalization of this real `ADR/` directory — same content shape, different storage format. Applying
it to this project means: keep authoring ADRs exactly as the source did (numbered, cited in sequence,
via a skill), and additionally mirror each into the structured log so an orchestrator or automated
tool can query it. The "fired migration trigger" field is the one genuinely new piece — the source's
8 pre-committed architecture transitions (module→service, in-process→Kafka, Postgres→+ClickHouse,
etc., all in `EXT/25-build-architecture-evolution.md`) are real and Extracted, but none has fired, so
every trigger field in this project's decision log would currently read empty by design, not by
omission.

## Reusable rules applied here

- credit-intelligence already had a working, if informally stored, shared-context model: separate
  owned documents, each with an `Owner:` line, a real precedence rule, and a real ADR-based decision
  log — this is stronger raw material than most projects starting from zero.
- The constitution (`PROMPT.md`) is non-negotiable evidence, not a framework suggestion; its
  precedence rule should be copied verbatim into any reusable constitution template.
- Deployment rules, release rules, and the assumption register are genuinely Missing — they are gaps
  to fill, not sections to relabel from something that already existed.
- The decision log for this project is Extracted, not Recommended — `ADR/` already works; the
  `decision-log.yaml` schema formalizes its shape, it does not invent its existence.
- Staleness detection, section-level read permissions, and the single unified `shared-context.yaml`
  file are Recommended additions layered onto real Extracted content — treat them as configuration,
  not as evidence of what the source did.
