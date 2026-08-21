# CONTRIBUTING

This repository has two layers with different rules. Read this before changing anything.

## The two layers

1. **Global framework layer** — `framework/`, `schemas/`, `templates/`, `diagrams/`, and the
   top-level docs. Project-independent and reusable. Changes here affect every project.
2. **Project layer** — `projects/<slug>/`. Project-specific evidence, configuration, and outputs.

**Never mix project-specific claims into the global framework layer without explicit review.** If a
useful pattern emerges in a project, promote it deliberately: generalize it, strip project nouns,
label its provenance, and review it as a framework change.

## Provenance discipline (the most important rule)

Every claim about the source system carries exactly one of five classes: **Extracted**,
**Inferred**, **Recommended**, **Unverified**, **Missing** (defined in
`framework/01-evidence-classification.md`). Rules:

- A `Recommended` agent, workflow, or capability is **never** written as if it existed in the
  source.
- Do not upgrade a classification without new evidence. The source had **no git history**, so any
  commit/branch/tag/release/authorship claim is `Unverified` by construction — leave it that way.
- Classified items carry `classification`, `evidence_refs`, `confidence` (high|medium|low), and
  `notes`.
- The orchestrator (or any agent) must not rewrite evidence classifications.

## Editing the framework layer

- Keep it technology-stack independent. No language-, cloud-, or vendor-specific assumptions in
  `framework/` or `schemas/`.
- Prefer simple governance over adding agents. Before adding a role, check whether the function
  should instead be a deterministic workflow (no reasoning needed) or a quality gate.
- Preserve the invariants in `framework/README.md` §"invariants". In particular: separation of
  implementation and approval, the orchestrator's lack of decision authority, the scoped security
  veto, gates-over-status, and non-overridable blocking gates.
- Schema changes bump `schema_version` and are noted in `CHANGELOG.md`.
- Diagram changes keep the six-way legend (Extracted / Inferred / Recommended / Human / Automated /
  Gate) and the shared `classDef` colors.

## Editing a project layer

- Treat the source extraction as **read-only**. Do not overwrite or delete source evidence.
- Do not commit secrets, credentials, tokens, personal data, or proprietary source. If the
  extraction contains sensitive content, keep it local or excluded via `.gitignore`.
- Project state and logs are append-only where they record consequential decisions.

## Commits and review

- Work on a dedicated branch (e.g. `framework/<change>` or `project/<slug>/<change>`).
- Produce **reviewable, atomic commits** — one logical change each. A large unreviewable commit is
  approved, not reviewed; this framework exists to prevent exactly that.
- All generated work must be reviewable through Git.
- Application code is out of scope for this repository. If a change would touch a target
  application's code, stop and request human approval first.

## Idempotent reruns

When source material or a PRD changes, do not regenerate the whole system blindly:

1. Detect changed, new, and removed source documents.
2. Preserve prior human-approved outputs and decisions.
3. Update the source audit (`projects/<slug>/audit/`).
4. Mark affected conclusions **stale** rather than silently rewriting them.
5. Re-evaluate dependent findings and update the traceability matrix.
6. Add a `CHANGELOG.md` entry and generate a change summary.
7. Request human review for material blueprint changes.

## Definition of done for a contribution

A change is done when: it carries correct provenance labels; it preserves the invariants; schemas
validate and cross-references resolve; diagrams render with a legend; the framework/project
separation is intact; no secrets are exposed; and it is delivered as atomic, reviewable commits.
