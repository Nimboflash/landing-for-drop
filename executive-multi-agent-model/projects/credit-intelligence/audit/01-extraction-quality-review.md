# 01 — Extraction Quality Review

An assessment of the *prior extraction's* reliability — not the repository's. The question here is:
how much can we trust the 27 analysis documents and the proposed `extracted-system/`?

## Overall verdict

**High quality, unusually honest.** The extraction states its own limits up front (no git history →
no chronology), separates fact from inference from recommendation with a six-label scheme, backs
load-bearing claims with repo paths in an evidence index, and repeatedly refuses to overstate (it
calls the system "semi-orchestrated at most," scores automation conservatively with a disclosed
method, and labels its own reusable additions as recommendations). It is a secondary source that
behaves like a good one.

## Strongly supported findings (safe to reuse)

- The ten-agent roster with ownership lanes and negative scope — each agent cited to a repo file.
- The absence of an orchestrator, task/state layer, handoffs, and release pipeline — attested as
  search-negative with the locations searched.
- The scoped security veto, non-overridable CI, ADR-or-it-doesn't-exist, and fired-migration-trigger
  discipline — each quoted.
- The quality-gate split between *implemented* (CI: format/lint/type/tests/secret-scan/layering) and
  *specified-not-implemented* (leakage/replay/stability/monotonicity/fairness/calibration).

## Weakly supported findings (reuse only with the label)

- **`credit-architect` as a generation-0 seed agent** — an Inferred narrative resting on structural
  signals (format outlier, "nine professions" persona, ungated Target stack, an ADR calling its
  20 contexts "a hypothesis, not a fact"). Plausible and well-argued; not proven. A counter-hypothesis
  (all ten co-authored, with this one deliberately styled "visionary") is acknowledged in the source.
- **Automation ~37%** — a single method-dependent number; the source discloses the method, which is
  what makes it usable. Reuse as "~35–40%, method-disclosed," not as a hard figure.

## Overstatement check

The extraction does **not** overstate automation or invent workflows as implemented. The one place a
careless reader could be misled is the celebrated domain gates (leakage, replay, stability,
monotonicity): they are *documented*, not *implemented*, and the extraction says so — but a summary
reader might mistake specified for enforced. The framework carries that distinction forward
explicitly (see `blueprint/11-...`).

## Aliases and overlapping roles the extraction flagged

- The proposed `extracted-system/` **renamed** three real roles (`credit-architect →
  domain-policy-architect`, `ai-engineer → ml-engineer`, `security-architect → security-engineer`) —
  correctly, to drop domain nouns. This framework keeps those renames and treats the pairs as
  aliases, not new roles.
- It **added** seven roles (orchestrator, product-owner, release-manager, database-engineer,
  test-automation-engineer, documentation-engineer, ux-design-system) as recommendations, and two
  (software-architect, code-reviewer) as inferred splits/formalizations — all clearly labeled.
- The only genuine intra-source overlap it found was `credit-architect` vs `cto` (the seed file's
  "enterprise architect / security / PM" persona), cleanly resolved by the constitution's narrower
  lane but with stale prompt text still loaded.

## Count discrepancies caught

The prior extraction's own brief mis-stated two directory counts (it said "agents (20)" and
"templates (19)"; the on-disk reality is **19 agents** and **20 templates**). The digest corrected
these; this framework uses the corrected counts. A minor issue, but exactly the kind of thing an
extraction-quality review exists to catch.

## References to unavailable evidence

Every claim requiring git history is marked "could not verify" in the source and **Unverified** here.
The source also names repo artifacts absent from the working copy (Docker Compose, Alembic
migrations, OpenAPI) — correctly labeled "not found." No claim in the extraction relies on evidence
it does not have without saying so.

## Bottom line for reuse

The extraction is **safe to build on**, provided its labels are preserved. The framework does exactly
that: Extracted findings become Extracted framework claims; the source's inferences stay Inferred; its
recommendations stay Recommended; its could-not-verify items stay Unverified; and its not-found items
become the Missing gaps that justify the framework's Recommended additions.
