# 15 — Implementation-Readiness Checklist

For an **independent reviewer** (a second agent or a human, not the author) to run before handing this
project to an implementing tool. A single unchecked item means "not ready." This applies
`framework/17-framework-validation-checklist.md` to `credit-intelligence`.

## Evidence and provenance

- [ ] All 105 source files were inventoried; read status recorded (`audit/00`).
- [ ] Unread/excluded files (OS sidecars) and missing referenced artifacts (Compose, migrations,
      OpenAPI) are listed, not hidden.
- [ ] Every load-bearing claim carries a classification and evidence refs (`blueprint/14`).
- [ ] No Recommended item is presented as pre-existing; all chronology is Unverified.
- [ ] The extraction is preserved read-only; no source evidence was overwritten or deleted.

## Organization and authority

- [ ] All ten real agents are represented; the roster was discovered, not assumed.
- [ ] Aliases identified (`credit-architect/ai-engineer/security-architect` renames).
- [ ] Every active agent has incoming and outgoing communication rules (`framework/08`,
      `blueprint/02`).
- [ ] Every decision has a single owner and named prohibited approvers (`blueprint/02`).
- [ ] The scoped security veto is configured, unoverrulable, and requires an alternative
      (`project-profile.yaml`).

## Work, handoffs, gates

- [ ] Every task has an owner and an independent reviewer; no self-approval path exists
      (`framework/08`, `schemas/task`).
- [ ] Every handoff is validated (15 checks, 5 statuses); incomplete handoffs are rejected, not
      repaired (`framework/09`).
- [ ] Every blocker has an owner and an escalation path; failed reviews return to the owner;
      retry history is persistent (`framework/10`, `state/project-state.yaml`).
- [ ] Front-end and back-end coordinate through a versioned contract; contract changes require
      acknowledgement (`blueprint/09`, `state/contract-registry.yaml`).
- [ ] Failed blocking gates stop progress; CI-stage gates have `override_authority: none`
      (`project-profile.yaml`, `blueprint/11`).
- [ ] The four domain gates are scheduled for CI implementation before the first model ships (G4).

## State, ownership, human control

- [ ] Project state is persistent, machine-readable, and field-owned (orchestrator ≠ approval/gate
      owners) (`state/project-state.yaml`).
- [ ] Shared context has section-level ownership (`state/shared-context.yaml`).
- [ ] Parallel work has file-ownership protection; per-agent permissions are scheduled (G1, P0).
- [ ] High-risk actions require human approval; requests are decision-ready summaries
      (`blueprint/12`).
- [ ] The orchestrator cannot override reviewers, gates, scope, architecture, security, or release.

## Separation and safety

- [ ] The framework layer and this project layer are cleanly separated.
- [ ] No secrets, credentials, or sensitive content are exposed; `.gitignore` protects state secrets
      and the local extraction copy.
- [ ] No application code was modified by this reconstruction.
- [ ] The Claude Code handoff (`claude-code-handoff-prompt.md`) is self-contained and
      implementation-ready.

## Sign-off

- [ ] Reviewer name / id: ____________________
- [ ] Date: ____________________
- [ ] Result: ready / not ready (if not ready, list the failed items and route each to its owner).

The reviewer must be independent of whoever configured the project — the separation-of-duties rule
applies to this validation itself.
