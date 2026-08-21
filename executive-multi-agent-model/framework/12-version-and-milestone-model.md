# 12 — Version and Milestone Model

**Purpose.** How work is divided into versions and milestones, how scope is deferred without being
lost, and how a version is closed. The unit of a version is a *falsifiable exit gate*, not a feature
list.

> **Provenance banner.** Versions-as-falsifiable-exit-gates, the "do not negotiate back in" exclusion
> list, and the Target-section deferral pattern are **Extracted**. The full planning hierarchy below
> the phase level (epics → stories → tasks) is **Recommended** — the source stopped at the lane level
> (`EXT/22-product-breakdown-structure.md`, that middle Missing). All version *chronology* is
> **Unverified** (no git history).

## How the source divided versions (Extracted)

The reference repository shipped zero versions; its operative "version system" was three roadmap
phases, each defined by a single **falsifiable exit gate** and sequenced by *risk and data access*,
not by dates or feature counts. Phase 1's gate: "a design partner says: run this on our next cohort."
Each phase carried an explicit exclusion list — scope written down as *out*, "do not negotiate these
back in" — and transitions were governed by written migration triggers, none of which had fired. This
is the pattern worth generalizing: a version is a hypothesis with an externally observable success
condition, plus an honest list of what it deliberately excludes.

## The reusable planning hierarchy

Below the version, the framework provides the middle layer the source lacked:

> Product → Release strategy → Version → Milestone → Epic → Feature → User story → Technical task →
> Agent assignment → Review task → Validation task → Release task

Adapt the hierarchy when a project's evidence supports a different shape — a small project may collapse
epics and features; a large one may need them all. The schemas support this directly:
`version.schema.yaml` (with its single `exit_gate` and `excluded_scope`), plus task grouping via
`parent_version`, `parent_milestone`, `parent_epic`, and `parent_feature` on `task.schema.yaml`.

## The version record

A version (`schemas/version.schema.yaml`) documents, for each version: objective; single falsifiable
exit gate; included scope; excluded scope ("do not negotiate back in"); milestones; architecture
requirements; agent assignments; dependencies; risks; quality gates; release criteria; deferred work;
rollback requirements; post-release validation; lessons carried into the next version; and evidence
confidence.

## Deferral without loss — the Target-section pattern (Extracted)

The source's most novel planning idea was to write deferred work *into the same document* as the
current work, each deferral tagged with the migration trigger that would pull it back in. Deferral was
therefore visible and reversible, and every deferral named its forcing function. The framework keeps
this: deferred scope lives in `excluded_scope`/`deferred_work` with a named condition, and moves to a
later version's plan when that condition fires — never quietly dropped, never quietly re-added.

## Reusable planning rules

- **MVP inclusion** — include the smallest scope that tests the version's hypothesis and can meet its
  exit gate; everything else is a candidate for deferral.
- **Scope deferral** — deferred work is written down with its forcing condition; "we'll need it
  eventually" is a deferral, not an inclusion.
- **Separate-version decisions** — work that cannot meet the current exit gate, or that depends on an
  unfired trigger, belongs to a separate version.
- **Architecture milestones** — a boundary/contract that must exist before parallel work can start is
  its own milestone with its own exit criterion (the ADR set approved).
- **Integration milestones** — where independently built lanes must converge, an explicit integration
  milestone gates the convergence on green build + contract tests.
- **Release blockers** — a failed blocking gate, an unresolved critical security finding, or an
  unmet exit gate blocks the release; none is overridable by the orchestrator.
- **Incomplete-work transfer** — work not finished when a version closes moves to `deferred_tasks`
  with its context intact, carried into the next version, not marked done.
- **Technical-debt registration** — debt incurred to hit an exit gate is registered as a risk/task,
  with the condition under which it must be repaid.
- **Version closure** — a version closes only when its exit gate is honestly evaluated as met; if the
  gate fails, the version is not done regardless of how much shipped. Lessons are recorded and carried
  forward.

## The three-axis reproducibility pattern (Extracted)

The source versioned three axes independently — code, model/artifact, and policy — and pinned all of
them (plus a data-vector hash) to every business outcome, so any historical decision was attributable
to an exact set of artifacts. Where a project has independently versioned components, the framework
recommends the same: version each axis, and pin the set to each outcome. It is "release management as
reproducibility engineering, not ship ceremony."

## Reusable rules (recap)

- A version is a falsifiable exit gate plus an explicit exclusion list, sequenced by risk.
- Provide the full hierarchy below the version, but collapse it to fit the project.
- Defer visibly with a named forcing condition; never drop or silently re-add scope.
- A version closes only when its exit gate is honestly met; unfinished work transfers with context.
- Version independent axes and pin the set to each outcome for reproducibility.
