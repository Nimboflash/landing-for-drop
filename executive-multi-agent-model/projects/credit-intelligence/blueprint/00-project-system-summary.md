# 00 — Project System Summary

The framework applied to the `credit-intelligence` evidence, in brief, with the 25 review questions
answered.

## The original system

A prompt-based **virtual engineering team of ten agents with automated quality gates** —
"semi-orchestrated at most." It scored strongly on distinct identities, distinct responsibilities,
shared context, quality gates, completion validation, conflict-resolution *rules*, and human approval
points; and scored zero on explicit delegation artifacts, shared task state, scheduling, retry/failure
handling, handoffs, and persistent progress. It is a **real multi-agent organization design**; it is
**not** a multi-agent execution engine. Coordination was *structural* — a constitution that outranks
everything, ownership lanes with hard negative scope, interfaces as the coordination mechanism between
parallel agents, escalation edges, and mechanical gates — with a **human operator** supplying all
sequencing and release.

## Confidence

High on the organization design (each agent cited to a repo file); high on the absence findings
(search-negative and attested); medium on the historical narrative (the `credit-architect` seed
story is Inferred); and **Unverified** on all chronology (no git history). The execution half was
never exercised (no code, no PRD run), so its real-world effectiveness is *could-not-verify*, not
proven.

## Main strengths (Extracted)

A constitution with declared precedence; ownership lanes with explicit "never touches"; the **scoped
security veto the CTO cannot overrule**; triple-enforced architecture rules (hook + CI test +
checklist); completion defined by non-overridable gates rather than status; fired-migration-trigger
discipline for infrastructure; interface-as-coordination for safe parallelism; and teaching
constraints (every rule carries its *why*).

## Main weaknesses (Missing → Recommended)

No orchestrator or dynamic coordination; no task/handoff/project-state layer (so multi-session work
loses everything not in a doc or diff); no release/deploy/rollback tail; no per-agent technical
permissions (all ten agents had full tool access — the highest-severity gap); and celebrated domain
gates that are specified but not implemented (verification-theater risk).

## Recommended reusable model

Keep the governance chassis; add the drivetrain. Adopt an `orchestrator` that coordinates but never
decides; a machine-readable task/handoff/state layer with gates-over-status preserved; a
`release-manager` and a release/deploy/rollback tail behind human approval; per-agent tool/path
permissions and CODEOWNERS/branch-protection generated from the ownership matrix; and the four domain
gates wired into CI *before* the first model ships. Keep the source's core insight intact:
**coordination by constraint and gate, not by trust in any single agent — including the orchestrator
you add.**

## The 25 review questions

1. **Unquestionably supported:** the ten-agent roster and lanes; the scoped veto; non-overridable CI;
   the absence of orchestrator/state/handoff/release layers. (Extracted, high.)
2. **Uncertain:** the `credit-architect` seed-agent history; authoring order; automation exact
   percentage. (Inferred/Unverified.)
3. **Duplicates/aliases:** `credit-architect ≈ domain-policy-architect`, `ai-engineer ≈ ml-engineer`,
   `security-architect ≈ security-engineer` (renames, same roles).
4. **Must stay independent:** code-reviewer vs implementer; qa vs the roles it gates; security vs
   CTO (the veto); release-manager vs implementation agents.
5. **Become deterministic workflows:** formatting, layering checks, secret scanning, dependency
   audits — enforcement, not reasoning.
6. **Become quality gates:** the four domain checks (leakage, replay, stability, monotonicity) plus
   fairness/calibration.
7. **Coordinates the system:** originally the human + constitution + trigger descriptions; going
   forward, the Recommended `orchestrator` (coordination only).
8. **Owns product scope:** `product-manager`.
9. **Owns architecture:** `cto` (drafted by `software-architect` at scale).
10. **Owns task decomposition:** `orchestrator` (form only).
11. **Owns implementation review:** an independent `code-reviewer`, then `qa-engineer` at the gate.
12. **Owns final quality approval:** `qa-engineer` (gates, non-overridable).
13. **Owns security approval:** `security-engineer` (terminal veto on the data boundary).
14. **Owns release approval:** `release-manager` on independent evidence, then the `human-owner`.
15. **Original versions divided:** three roadmap phases by falsifiable exit gate, sequenced by data
    access and legal risk; zero shipped. (Chronology Unverified.)
16. **Future versions divided:** the same falsifiable-exit-gate pattern, with the middle hierarchy
    (milestone → epic → feature → story → task) the source lacked.
17. **Large features decomposed:** into contract-first lanes with per-task file grants, parallel only
    after the contract exists.
18. **Safe parallel work:** module-per-lane, ports not JOINs, generated clients, and CODEOWNERS/
    branch protection (Recommended) on top of the Extracted structural conflict-avoidance.
19. **Context persists:** in the constitution + shared-context sections + append-only decision log +
    project-state file.
20. **Interruptions/failures/retries:** resumable project state; structured rejection → rework →
    independent re-review; retry history persisted; thresholds escalate.
21. **Require humans:** scope changes, high-risk assumptions, major architecture, new deps,
    destructive migrations, authn/authz, sensitive data, security exceptions, deployment, rollback,
    release, critical gate overrides.
22. **Reusable original patterns:** constitution precedence, ownership lanes + veto, gates-over-status,
    ADR discipline, fired triggers, interface-as-coordination, verify-don't-tick review.
23. **Patterns to adapt:** the credit-specific agents (rename/generalize); the four concrete domain
    gates (keep the slot, replace the contents); the Persian/RTL and regulatory specifics (leave in
    the project layer).
24. **Missing capabilities:** orchestrator; task/handoff/state; release/deploy/rollback; per-agent
    permissions; assumption register; the four gates as real CI.
25. **Implement next:** see `claude-code-handoff-prompt.md` — scaffold the orchestrator, schemas,
    state, message/handoff validation, gate enforcement, and human checkpoints, on a framework branch,
    without touching application code.
