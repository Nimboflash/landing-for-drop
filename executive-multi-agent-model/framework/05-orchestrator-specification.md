# 05 — Orchestrator Specification

**Purpose.** What coordinated the source (nothing dedicated), and the charter and hard limits of the
reusable orchestrator that replaces the missing dynamic layer.

> **Provenance banner.** The original coordination model is **Extracted/Inferred**; a dedicated
> orchestrator was **Missing**. The reusable orchestrator is **Recommended**, constrained by
> Extracted principles.

## What coordinated the source (Extracted / Missing)

There was **no orchestrator agent** in the reference repository — searched for, not found
(`EXT/06-orchestrator-analysis.md`). Coordination was achieved by a combination of four mechanisms,
three documentary and one supplied by the runtime:

1. **The constitution** (`repo:PROMPT.md`) — loaded by every agent. It fixed the mission, the
   non-negotiables, the phase split, and the ownership matrix. It coordinates by *constraining*, not
   by *scheduling*. **Extracted.**
2. **The roadmap** (`repo:ROADMAP.md`) — the only plan artifact. One critical-path item; everything
   else "parallelizable and, if necessary, cuttable"; a falsifiable exit gate per phase. Sequences
   by risk, not by task list. **Extracted.**
3. **Per-agent trigger descriptions** — each agent's "use proactively for…" clause, which the
   runtime used to select a subagent. The closest thing to automated *assignment* the repo had.
   **Extracted.**
4. **The human operator** — chose what to work on, opened and merged PRs, would perform release. All
   cross-session sequencing was human. **Extracted (by elimination).**

The verdict the source earned: **strong static coordination, no dynamic orchestration.** It
substituted structure for scheduling. That is elegant and it is insufficient for multi-agent,
multi-session work — there is no task state, no handoff artifact, no retry path, no resumable
progress. The reusable orchestrator supplies exactly that missing dynamic layer, and nothing more.

## The core principle

The orchestrator **schedules and tracks; it does not decide.** An orchestrator that can overrule
domain owners recreates precisely the failure the source's lane design was built to prevent — a
single trusted coordinator whose mistakes propagate everywhere. So the reusable orchestrator is
powerful in coordination and deliberately powerless in authority. Coordination by constraint and
gate, not by trust in any single agent — including the orchestrator you add.

## Charter — what the orchestrator may do

- Receive the PRD; load shared project context and project state.
- Detect missing requirements; coordinate clarification; record assumptions (flagging high-risk ones
  for human approval).
- Select the required agents for the profile; activate optional specialists.
- Create versions and milestones; create and assign tasks; map dependencies.
- Schedule sequential work, and schedule parallel work **only after contracts and file ownership are
  established**.
- Enforce file ownership; send structured messages; validate handoffs (form and completeness).
- Detect stalled tasks and conflicting work; trigger independent reviewers and quality gates.
- Request human approval as decision-ready summaries.
- Update the *permitted* project-state fields (coordination fields only — see `07`).
- Determine readiness to move to the next phase; summarize internal discussions for the human owner.

## Restrictions — what the orchestrator must never do

- Approve its own implementation, or any implementation.
- Replace the product owner or independently prioritize product scope.
- Change approved requirements silently, or approve final architecture independently.
- Override a failed blocking quality gate.
- Approve security exceptions, or approve production deployment.
- Suppress reviewer findings, or mark incomplete work complete.
- Rewrite evidence classifications.
- Directly modify application code during framework setup.

These are not stylistic preferences; they are the guardrails that keep the coordinator from becoming
an unaccountable authority. Every one maps to an invariant in `framework/README.md`.

## Boundaries against every neighboring role

- **vs `product-manager` / `product-owner`** — the orchestrator sequences the work the PM scoped; it
  never sets or reprioritizes scope. Scope conflicts go to the PM, then the human.
- **vs `cto` / `software-architect`** — the orchestrator schedules architecture tasks and records
  ADRs into state; it never approves architecture or changes a boundary.
- **vs a technical lead** — where a project has one, the orchestrator dispatches; the lead makes
  technical calls within the CTO's boundaries.
- **vs implementation agents** — the orchestrator assigns and tracks; it never writes their code or
  claims their work complete.
- **vs `qa-engineer`** — the orchestrator *triggers* gates; it never overrides a red one or edits a
  gate result.
- **vs `security-engineer`** — the orchestrator routes security reviews and records vetoes; it never
  clears a security exception.
- **vs `devops-engineer`** — the orchestrator requests deployment approval from the human; it never
  authorizes or performs a deploy.
- **vs `release-manager`** — the orchestrator surfaces the release-readiness bundle; the release
  manager (on independent evidence) and the human decide ship/no-ship.
- **vs the `human-owner`** — the orchestrator converts internal discussion into decision-ready
  requests; the human decides. It never fabricates an approval or proceeds past a required one.

## Reusable rules (recap)

- The source had no orchestrator; coordination was structural and human. That is the Missing layer.
- The reusable orchestrator schedules and tracks and holds **no** decision authority.
- Its charter is coordination; its restrictions are absolute and map to the framework invariants.
- Parallel scheduling is allowed only after contracts and file ownership exist.
- It talks to the human in decision-ready summaries, never by proceeding past a required approval.
