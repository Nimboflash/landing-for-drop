# 10 — File Ownership and Parallel Work

**Purpose.** The ownership model that lets credit-intelligence's agents work in parallel on
`ingest → features → decision → explain` without merge conflicts, filled in for this project's real
modules, plus the technical-enforcement gap the source left open.

> This document applies the file-ownership framework (`framework/15-file-ownership-and-parallel-work.md`)
> to the credit-intelligence EVIDENCE. The `Owner:` line, the triple enforcement, and the
> module-per-lane/ports/auto-discovery design are Extracted. Technical permission enforcement
> (CODEOWNERS + branch protection) is Recommended — the source has none.

## The Extracted ownership model

Every file in the source that matters declares an `Owner:` line **in the file itself** — not in a side
registry that can drift out of sync with the tree. This single fact carries most of the ownership
discipline: `ROADMAP.md` (owner product-manager), `ARCHITECTURE.md` / `DOMAINS.md` (owner cto),
`DECISION_ENGINE.md` (owner credit-architect), and so on through the governance layer. — *Classification:
Extracted. Evidence: EXT/01-repository-structure.md (Layer 2 doc list with owners), EXT/12c
(file-ownership-matrix.md summary). Confidence: high.*

**Triple enforcement**, three independent layers checking the same invariant so that no single failure
mode (a careless edit, a stale rule, a missed review) breaks it alone:

1. **Review-time** — the `Owner:` line itself, checked by a human/reviewer at PR time.
2. **Edit-time** — the `domain-purity.sh` PostToolUse hook, which **blocks** framework imports inside
   `src/*/domain/` the instant a `Write`/`Edit` tool call would introduce one. No bypass exists at this
   layer.
3. **CI-time** — `tests/test_layering.py`, an AST-based dependency-rule check that re-walks the *whole*
   tree on every push, catching what the hook can't: "a human, an IDE refactor, a merge." Plus the PR
   template's ~40-box checklist as a fourth, softer layer at PR time.

Failure protocol is fixed and non-negotiable: **never whitelist a violation.** If a module needs to
reach across a boundary, the fix is to declare a port and an adapter, not to add the module to an
allowlist. — *Classification: Extracted. Evidence: EXT/01, EXT/12c, repo:.claude/hooks/domain-purity.sh,
repo:tests/test_layering.py, repo:.github/PULL_REQUEST_TEMPLATE.md. Confidence: high.*

**Module-per-lane + ports, not JOINs**: the four Phase-1 modules (`ingest`, `features`, `decision`,
`explain`) are each hexagonal (`domain/application/adapters`), each **owns its own database schema**,
and cross-module reads happen through **in-process ports**, never through a cross-schema SQL JOIN. This
is a structural, not procedural, answer to merge conflicts — module boundaries are enforced by the
architecture itself, not by agents remembering to stay in their lane. — *Classification: Extracted.
Evidence: EXT/01 (Boundaries), repo:ARCHITECTURE.md. Confidence: high.*

**Package auto-discovery**: `pyproject.toml` is configured so that adding a new module never requires a
one-line edit to a shared package list — "the tree is the source of truth." This closes off the most
common parallel-agent merge conflict pattern (every new module = a hand-edit to one shared file that
every other agent is also touching that week). — *Classification: Extracted. Evidence:
EXT/01, EXT/12c, repo:pyproject.toml. Confidence: high.*

## The file-ownership matrix — Phase 1 modules + shared files

| Path or file type | Primary owner | Allowed contributors | Required reviewer | Approval | Conflict risk |
|---|---|---|---|---|---|
| `src/ingest/**` | data-engineer | — | code-reviewer | review + CI (layering test) | medium |
| `src/features/**` | ai-engineer | data-engineer (substrate calls via port) | code-reviewer | review + CI (layering test) | medium |
| `src/decision/**` | backend-engineer | domain-policy-architect (policy logic within domain layer) | code-reviewer | review + CI (layering test) | high |
| `src/explain/**` | ai-engineer | backend-engineer (adapter wiring) | code-reviewer | review + CI (layering test) | medium |
| Shared libraries (`src/shared/**` if introduced) | cto | owning engineers, by port declaration only | cto | review + CI | high |
| API contract (`docs/api/decision-api.md` + generated schema) | backend-engineer + domain-policy-architect (joint) | frontend-engineer (consumer only, via generated client) | cto | review + ack (per `09`'s 8 steps) | high |
| Migrations (`alembic/**`, once it exists) | database-engineer (Recommended split; source has no dedicated DB lane — data/backend share it today) | backend-engineer | software-architect | migration gate + human (if destructive) | high |
| CI/CD (`.github/workflows/ci.yml`) | devops-engineer | — | cto | review + CI | high |
| Security configuration (`SECURITY.md`, secret-scan config) | security-engineer | — | cto | security gate | high |
| `pyproject.toml` / package config | cto | devops-engineer | cto | review | high (mitigated by auto-discovery) |
| `.claude/rules/*`, `.claude/hooks/*` | cto | devops-engineer | cto | review | high |
| Test fixtures / `tests/**` | qa-engineer | engineers | qa-engineer | CI | medium |
| Documentation (`docs/**`, root governance docs) | documentation-engineer (Recommended; today each doc's own named owner per its `Owner:` line) | all, per doc's own owner | documentation-engineer | review | low |

Rows for `ingest/features/decision/explain` map owners from the real 10-agent roster (`data-engineer`,
`ai-engineer`, `backend-engineer`); rows for shared/contract/migration/CI/security-config apply the
framework's generic matrix (`framework/15`) to this project's actual file paths. — *Classification:
Extracted for the module-owner mapping and the boundary rules; Recommended for `database-engineer` as
a distinct row-owner (source splits this work across data-engineer and backend-engineer without a
dedicated lane) and for `documentation-engineer` as a distinct owner (source: "doc quality was every
agent's job and no one's"). Evidence: EXT/01, EXT/12c, EXT/12a (agent list #16, #18). Confidence:
high (mapping), medium (recommended-role assignment).*

## Branch and merge rules

- **Branch naming**: short-lived branches off `main`, prefixed `feat/`, `fix/`, `docs/`, `chore/` —
  Extracted, `repo:CONTRIBUTING.md`.
- **`main` always releasable**: every PR requires 1 review plus green CI; "red CI does not merge — no
  exceptions, no overrides, no 'just this once before the demo'" — Extracted, `repo:.github/workflows/ci.yml`
  header comment.
- **Review priority order**: boundaries → hidden business rules → replayability → PII → test level →
  style — Extracted, `repo:CONTRIBUTING.md`.
- **Small PRs as a control, not a style preference**: "a 2,000-line PR is not reviewed; it is
  approved... in a system where a bug lends someone the wrong amount of money, that distinction
  matters" — Extracted, load-bearing for this specific domain.
- **Merge order**: contract and migration changes merge before the consumers that depend on them —
  Recommended (framework generic rule, not stated verbatim in source, but consistent with the
  contract-first discipline in `09`).
- **Conflict resolution**: a real content conflict escalates to the file's declared owner; an
  ownership dispute escalates to `cto`. The source does not name who resolves a live merge conflict in
  practice — inferred to default to the human operator, with `cto` arbitrating ownership disputes. —
  *Classification: Unverified (who resolves a live conflict) / Extracted (cto arbitrates ownership
  disputes). Evidence: EXT/13-git-devops-release.md ("Not found" on conflict resolution; inference
  noted explicitly). Confidence: medium.*

## The Recommended addition: technical permission enforcement

**Critical gap R1**: the source has **no technical enforcement** of any of the above. No CODEOWNERS
file, no branch protection, no per-agent git permissions of any kind — "no agent technically restricted
from committing/merging/force-pushing; rules are normative only." Every rule in this document today
depends on an agent choosing to follow it. — *Classification: Missing (source). Evidence:
EXT/13-git-devops-release.md, EXT/19-evidence-index.md #25 ("no per-agent tool restrictions — no
`tools:` key in any frontmatter"). Confidence: high.*

The framework's Recommended remedy for this project: generate a `CODEOWNERS` file mechanically from
the matrix above (one line per path pattern, mapping to the owning agent's identity), and turn on
branch protection requiring the CODEOWNERS-designated review plus green CI before merge to `main`. This
converts every "Allowed contributors" and "Required reviewer" column above from a norm an agent could
ignore into a check GitHub (or the equivalent CI provider) enforces mechanically — closing the same
class of gap the `domain-purity` hook already closed for framework-import violations, but for
*who may touch which file* rather than *what a file may import*.

## Reusable rules (recap)

- One accountable owner per file, declared in the file — never a side registry.
- Enforce the same invariant at three independent layers (edit-time hook, CI-time re-check, review-time
  checklist); never whitelist a violation, declare a port instead.
- Module-per-lane with owned schemas and ports-not-JOINs turns merge-conflict avoidance into an
  architectural property, not a discipline problem.
- Auto-discover packages so a new module never forces an edit to a file every other lane is also
  touching.
- Add technical enforcement (CODEOWNERS + branch protection) on top of the normative matrix — this
  project's Critical Gap R1 is exactly the absence of that layer.
