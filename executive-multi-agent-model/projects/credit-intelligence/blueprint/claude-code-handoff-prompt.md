# Claude Code Handoff Prompt — Implement the Virtual Software Organization (credit-intelligence)

> This file is a **self-contained prompt**. Paste it to Claude Code (or an equivalent agent runtime)
> from the root of the `virtual-software-organization` repository. It instructs the tool to implement
> the framework *runtime* for the `credit-intelligence` project — agents, hooks, commands, skills,
> schemas, state, and enforcement — **without modifying any application code**. Everything it needs is
> in this repository; it should not invent project facts.

---

## Role and mode

You are implementing a governance-and-coordination framework, not building product features. Operate
in **framework-setup mode**: you create and wire up the organization's machinery; you do **not** write
application logic, refactor the target app, or implement product requirements. If a step would require
touching application code, **stop and request human approval first** (see Approval checkpoints).

## Step 0 — Read before you write

1. Read this entire repository recursively. Start with `README.md`, `USAGE.md`, `CONTRIBUTING.md`.
2. Read the framework layer in order: `framework/00` → `framework/17`. These are the rules you
   enforce.
3. Read all twelve `schemas/*.schema.yaml` and all fifteen `templates/*.md`.
4. Read this project's configuration and blueprint: `projects/credit-intelligence/project-profile.yaml`
   and every file under `projects/credit-intelligence/blueprint/` and `.../audit/`.
5. Read the illustrative instances under `projects/credit-intelligence/state/`.
6. Treat `projects/credit-intelligence/source-extraction/` and any local original extraction as
   **read-only evidence**. Do not modify, overwrite, or delete it.
7. **Preserve every evidence classification** (Extracted / Inferred / Recommended / Unverified /
   Missing). Never present a Recommended item as if it existed in the source. Never rewrite a
   classification.

## Step 1 — Branch and safety

- Create and work on a dedicated branch: `framework/vso-setup`.
- Make **reviewable, atomic commits** — one logical change per commit, with a message explaining why.
- Never commit secrets, credentials, tokens, or the raw source extraction. Confirm `.gitignore`
  already excludes `_extraction_src/`, `*.zip`, `.env*`, and `**/state/*.local.yaml`.

## Step 2 — What to create (files)

Create the runtime under a project runtime root (recommended: `.claude/` for agent/hook/command/skill
wiring, and `projects/credit-intelligence/state/` for live state). Specifically:

- **Agent definitions** (`.claude/agents/*.md`) — only for the agents listed under "Agents to
  implement" below, each generated from `templates/agent-definition-template.md` and conforming to
  `schemas/agent.schema.yaml`, with `tools:`/`permissions:` scoped per lane (this closes gap G1).
- **Schemas** — copy/reference the twelve `schemas/*.schema.yaml` as the validation contracts; add a
  validator (below) that checks instances against them.
- **Shared-context files** — instantiate `projects/credit-intelligence/state/shared-context.yaml` as
  the live constitution + context, with section-level ownership enforced.
- **Persistent project-state files** — `project-state.yaml`, `decision-log.yaml`, `risk-register.yaml`,
  `contract-registry.yaml`, `approval-log.yaml` (seed from the illustrative instances, then keep
  live).
- **Message, handoff, blocker, review, approval instances** — written to a runtime store (e.g.
  `.claude/vso/messages/`, `.../handoffs/`, `.../reviews/`) conforming to their schemas.
- **A validation report** — `projects/credit-intelligence/blueprint/validation-report.md`, produced
  before you claim completion.

## Step 3 — Agents to implement (and not)

**Implement as actual agents/subagents** (justified by the `data_or_ai + high_risk` profile):
`orchestrator`, `product-manager`, `cto`, `domain-policy-architect`, `ml-engineer`, `data-engineer`,
`backend-engineer`, `frontend-engineer`, `devops-engineer`, `security-engineer`, `qa-engineer`,
`code-reviewer`, `release-manager`.

**Do NOT implement as agents** (leave conditional/off for this project unless a human activates them):
`product-owner`, `software-architect` (fold into `cto` until scale warrants), `database-engineer`,
`test-automation-engineer`, `ux-design-system`, `documentation-engineer`. Note them as available but
inactive in `project-profile.yaml`.

For each implemented agent: set its mission, owns/never-touches lanes, `tools`/`permissions` scoped to
its files, `receives_work_from`/`sends_work_to`, accepted message types, escalation paths, and
definition of done. `security-engineer` must carry the `veto_authority` block; `orchestrator` must
carry the full `prohibited_actions` list and **no** decision authority.

## Step 4 — Convert deterministic behavior to commands / hooks / workflows / validators

Do not make an agent do what a deterministic mechanism should. Implement:

- **Hooks** (`.claude/hooks/`): an edit-time **file-ownership guard** (block writes outside the acting
  agent's lane / task `allowed_files`; deny wins over allow); a **domain-purity / layering guard**
  (parameterized denylist — single source of truth, closing gap G7); a **formatter** hook.
- **Commands** (`.claude/commands/`): `/assign` (orchestrator creates+assigns a task),
  `/handoff` (submit a handoff for validation), `/review` (route to an independent reviewer),
  `/gate` (run a quality gate and record the result), `/approve` (raise a human-approval request),
  `/state` (read/update permitted project-state fields).
- **Workflows / validators** (scripts): a **schema validator** (validate every message/task/handoff/
  approval/gate instance against its schema); a **handoff validator** (the 15 checks → exactly one of
  five statuses); a **self-approval guard** (reject any transition where reviewer/approver == owner);
  a **gate-bypass guard** (reject any completion without attached passing gate evidence; reject any
  override of a CI-stage blocking gate); a **state-update guard** (reject any agent action that does
  not write its required project-state/evidence update).

## Step 5 — Implement the coordination behaviors

- **Structured messages** — all inter-agent traffic uses `schemas/message.schema.yaml`; consequential
  changes (scope, contracts, dependencies, ownership, sequence, quality, release) require
  acknowledgement before work continues.
- **Handoff validation** — enforce Step-4's handoff validator; an incomplete handoff is **rejected
  with named reasons**, never silently repaired.
- **Blocker & escalation** — every blocker gets an owner and an escalation ladder; route by question
  type to the named owner, ending at the human.
- **Retry tracking** — record each rework loop in `retry_history`; escalate at
  `retry.max_review_retries` (2).
- **Quality-gate enforcement** — a red blocking gate stops progress; CI-stage gates are
  non-overridable; the only routine override is a domain-quality threshold by two named roles jointly,
  recorded.
- **Human-approval checkpoints** — see below.
- **File-ownership protection** — the hook plus generated `CODEOWNERS` and branch protection mirroring
  the ownership matrix (closes gap G1).
- **No-orphan-state rule** — prevent any agent from operating without updating project state; prevent
  incomplete handoffs; prevent self-approval; prevent quality-gate bypass.

## Approval checkpoints (STOP and request human approval)

Request human approval — as a decision-ready summary via `templates/human-approval-request-template.md`
— before any of: product-scope change; high-risk assumption; major architecture decision; new external
dependency; destructive migration; authentication or authorization change; sensitive-data change;
security exception; production deployment; production rollback; release approval; critical gate
override; **and before modifying any application code at all**. The scoped security veto has **no
override path** — do not build a bypass for it.

## Validation commands (run before claiming completion)

- Schema-validate every generated instance against `schemas/`.
- Run the self-approval guard, gate-bypass guard, state-update guard, and handoff validator over the
  seeded runtime; all must pass.
- Confirm every implemented agent has incoming and outgoing communication rules and a scoped
  `tools`/`permissions` set.
- Confirm no file under the source extraction changed (diff it).
- Confirm no application code changed (diff the target app path, if present; it must be empty).

## Completion evidence (required before you say "done")

Produce `projects/credit-intelligence/blueprint/validation-report.md` containing: the list of files
created; the agents implemented vs. deliberately not implemented; the hooks/commands/skills/validators
wired; the results of every validation command above; a confirmation that classifications were
preserved; a confirmation that the source extraction and application code are unchanged; and any items
that still require human decision. Do not claim completion without this report.

## Skills to implement (only where reusable reasoning is needed)

- `/adr` — scaffold and record a decision in `decision-log.yaml` (refuse to relitigate settled ones;
  require a fired trigger for infrastructure).
- `/pr-check` — the independent verify-don't-tick review producing Fails / Needs-a-human / Passes and
  naming the owning agent.
- `/version-plan` — turn a version into a single falsifiable exit gate plus an explicit exclusion list.
  Do not create skills for anything a deterministic validator already handles.

## Existing files to preserve (do not modify)

The entire `framework/`, `schemas/`, `templates/`, `diagrams/` layers; every `audit/` and `blueprint/`
document; `project-profile.yaml`; the read-only source extraction. You *instantiate* state from the
illustrative `state/` files; you do not rewrite the blueprint.

## Rollback instructions

Everything happens on `framework/vso-setup`. To undo: `git checkout main` and delete the branch
(`git branch -D framework/vso-setup`); the `main` branch and the source extraction are untouched. No
runtime artifact is created outside the branch, and no application code is modified, so rollback is a
branch delete. If a hook or guard proves too strict, adjust it on the branch and re-run the validation
commands before merging.

## The one rule above all

Coordinate by constraint and gate, not by trust in any single agent — including the orchestrator you
are implementing. If any instruction here would let an agent approve its own work, bypass a blocking
gate, override the security veto, or change scope or architecture silently, treat that as a bug in the
setup and stop.
