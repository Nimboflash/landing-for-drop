# 17 — Framework Validation Checklist

**Purpose.** The reusable self-check an independent reviewer runs before trusting a configured
project, the review questions every reconstruction must answer, and the rules for rerunning safely
when source material changes.

> **Provenance banner.** Reusable / project-independent. This is a checklist, not a claim about the
> source.

## The 30-item validation checklist

Before relying on a configured project, verify every item. A single failure means the configuration
is not ready.

1. All source files were inventoried.
2. Relevant source files were actually read.
3. Unread and inaccessible files were listed.
4. Missing referenced evidence was listed.
5. All discovered agents were represented.
6. The agent list was not limited to a predefined roster.
7. Duplicate agents and aliases were identified.
8. Every active agent has incoming communication rules.
9. Every active agent has outgoing communication rules.
10. Every task has an owner.
11. Every implementation task has an independent reviewer.
12. Every handoff has validation.
13. Every blocker has an escalation path.
14. Every failed review returns work to the correct owner.
15. Retry history is persistent.
16. Front-end and back-end use versioned contracts.
17. Contract changes require acknowledgement.
18. Shared context has section-level ownership.
19. Project state is persistent and machine-readable.
20. Parallel work has file-ownership protection.
21. Failed blocking gates stop progress.
22. High-risk actions require human approval.
23. Agents cannot approve their own final work.
24. The orchestrator cannot override independent reviewers.
25. The reusable framework remains separate from project-specific evidence.
26. Recommendations are clearly separated from extracted behavior.
27. Source traceability is complete.
28. Sensitive files and secrets are protected.
29. The Claude Code handoff is implementation-ready.
30. No application code was modified.

For high-stakes projects, run this checklist with an independent reviewer (a second agent or a
human), not the same agent that built the configuration — the separation-of-duties rule applies to
the validation itself.

## The 25 review questions

Every reconstruction answers these in its project summary
(`projects/<slug>/blueprint/00-project-system-summary.md`):

1. Which findings are unquestionably supported?
2. Which findings remain uncertain?
3. Which roles are duplicates or aliases?
4. Which roles should remain independent?
5. Which functions should become deterministic workflows?
6. Which functions should become quality gates?
7. What should coordinate the system?
8. Who owns product scope?
9. Who owns architecture?
10. Who owns task decomposition?
11. Who owns implementation review?
12. Who owns final quality approval?
13. Who owns security approval?
14. Who owns release approval?
15. How were the original versions divided?
16. How should future versions be divided?
17. How should large features be decomposed?
18. How can engineering agents work safely in parallel?
19. How should project context persist?
20. How should interruptions, failures, and retries work?
21. Which actions require humans?
22. Which original patterns are reusable?
23. Which patterns must be adapted?
24. Which capabilities were missing?
25. What must the implementing tool build next?

## Idempotent and incremental reruns

When source material or a PRD changes, the configuration is *updated*, not regenerated from scratch.
The procedure:

1. Detect changed, new, and removed source documents.
2. Preserve prior approved outputs and human decisions.
3. Do not replace human-approved decisions silently.
4. Update the source audit.
5. Mark affected conclusions **stale** rather than overwriting them.
6. Re-evaluate dependent findings.
7. Update the traceability matrix.
8. Add a `CHANGELOG.md` entry.
9. Generate a change summary.
10. Request human review for material blueprint changes.

The governing rule: **do not regenerate the entire system without showing what changed.** A rerun
that silently rewrites a human-approved decision has failed, no matter how good the new output looks.

## What "done" means for the framework itself

The framework is correctly applied to a project when: the 30-item checklist passes; the 25 questions
are answered with classified, evidence-referenced answers; the framework layer and the project layer
are cleanly separated; recommendations are never presented as extracted behavior; no secrets are
exposed; and no application code was modified. Those conditions are the definition of done for a
reconstruction, and they are exactly what the project's `15-implementation-readiness-checklist.md`
re-checks before handing off to an implementing tool.

## Reusable rules (recap)

- Run all 30 checks before trusting a configuration; use an independent reviewer for high-stakes work.
- Answer all 25 review questions with classified, evidence-referenced answers.
- Reruns are incremental: preserve human decisions, mark stale, show the diff, never silently
  regenerate.
- Framework/project separation, provenance discipline, secret protection, and no-app-code-changes are
  the definition of done.
