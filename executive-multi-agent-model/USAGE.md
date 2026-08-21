# USAGE — Applying the Virtual Software Organization to a Project

This guide explains how to take the reusable framework and stand up a governed, multi-agent
development organization for one project — and how to run one project without forking the global
framework for every new one.

## Mental model

- `framework/`, `schemas/`, `templates/`, `diagrams/` are **global and read-mostly**. You reuse
  them across every project. You do not edit them per project.
- `projects/<slug>/` is **per-project**. It holds the project profile, the shared context
  (constitution) filled from your PRD, the live project state, and the blueprint that records how
  the framework is configured for this project.
- A **project profile** decides which agents, gates, and human approvals are active. This is how a
  small project avoids inheriting a large or high-risk organization.

## Step 1 — Create the project

```
mkdir -p projects/<slug>/{audit,blueprint,state,source-extraction}
cp project-profile.example.yaml projects/<slug>/project-profile.yaml
```

Edit `projects/<slug>/project-profile.yaml`:
- Set `project.slug`, `project.name`, `target_application_repository` (or `UNKNOWN`).
- Choose one `profile` (see Step 2).
- Confirm the activated agents/gates/approvals, or override per-project.

## Step 2 — Choose a project profile

Profiles are defined in `framework/02-canonical-agent-model.md` and
`project-profile.example.yaml`. Pick the closest, then adjust:

| Profile | Use when | Adds beyond core |
|---|---|---|
| `minimal` | small tool, one surface, low risk | (core only) |
| `standard` | typical product with UI + API | frontend, devops, release-manager, software-architect (opt) |
| `high_risk` | money, safety, irreversible actions | documentation-engineer; all human approvals on |
| `regulated` | legal/compliance obligations | elevated security + documentation; audit evidence |
| `infrastructure_heavy` | lots of infra, migrations, IaC | devops (elevated), database-engineer, release-manager |
| `frontend_only` | UI library / static site | frontend, ux-design-system; accessibility blocking |
| `backend_only` | service/API, no UI | backend, database-engineer |
| `mobile` | iOS/Android app | frontend (mobile), ux-design-system; store-release checks |
| `data_or_ai` | data pipelines / ML | ml-engineer, data-engineer, database-engineer; leakage/replay/stability/fairness gates |
| `experimental` | spike / throwaway | core minus release-manager; relaxed, non-blocking gates |

Always-on core (every profile): `orchestrator`, `product-manager`, `cto`, an implementation lane,
`qa-engineer`, `security-engineer`, `code-reviewer`, `human-owner`.

## Step 3 — Fill the shared context (constitution) from your PRD

Copy the section list from `framework/06-shared-context-model.md` into
`projects/<slug>/state/shared-context.yaml`. Fill: product overview, PRD, approved scope, goals &
non-goals, user journeys, business rules, acceptance criteria, architecture decisions, API/database
contracts, coding/testing/security standards, git/deployment/release rules, known risks, approved
assumptions. Each section has a **primary owner and required reviewers** — keep those.

The constitution outranks everything. If a later document disagrees with it, that document is a bug.

## Step 4 — Initialize project state

Create `projects/<slug>/state/project-state.yaml` from `schemas/project-state.schema.yaml`, plus
`decision-log.yaml`, `risk-register.yaml`, `contract-registry.yaml`, and `approval-log.yaml`. These
are the persistent, machine-readable memory that lets work resume after an interruption and prevents
duplicate work. Only the `orchestrator` writes coordination fields; approval, gate, security, and
release fields are written by their authorities.

## Step 5 — Scaffold the runtime with Claude Code

Open `projects/<slug>/blueprint/claude-code-handoff-prompt.md`. It is a **self-contained** prompt
that instructs Claude Code to implement the runtime for this project: agents (only where justified),
deterministic behavior as commands/hooks/workflows/validators, skills where reusable reasoning is
needed, the schemas, the shared-context files, the project-state files, message and handoff
validation, blocker/escalation/retry handling, quality-gate enforcement, human-approval
checkpoints, and file-ownership protection — on a dedicated framework branch, with atomic commits,
and **without modifying application code**.

## Step 6 — Run the PRD-to-production workflow

Drive the lifecycle in `framework/11-prd-to-production-workflow.md`:

> PRD → requirements audit → clarification & assumptions → scope approval → release strategy →
> version planning → architecture → contract definition → milestone planning → feature/task
> decomposition → dependency mapping → agent assignment → implementation → integration → code
> review → automated testing → QA → security review → release preparation → **human approval** →
> deployment → post-release validation → closure & lessons learned.

Each stage names its responsible agent, entry/exit criteria, handoff artifact, quality gate, human
approval, and failure/retry/escalation paths. Parallel work is permitted only after contracts and
file ownership are established (`framework/13-contract-governance.md`,
`framework/15-file-ownership-and-parallel-work.md`).

## Step 7 — Operate: handoffs, blockers, retries, approvals

- **Handoffs** are validated, not trusted. The receiver returns exactly one status; an incomplete
  handoff is rejected, never silently repaired (`framework/09-handoff-protocol.md`).
- **Blockers** always have an owner and an escalation path
  (`framework/10-blocker-escalation-and-retry.md`).
- **Failed reviews** return the task to the responsible agent; retry history is recorded in project
  state.
- **Human approvals** are requested as decision-ready summaries, never raw agent chatter
  (`framework/16-human-control-model.md`).

## Running multiple projects

Each project lives under its own `projects/<slug>/`. The global framework, schemas, templates, and
diagrams are shared unchanged. Per-project differences live entirely in the profile, the shared
context, the contract registry, the state, and the risk/approval configuration. Do not copy or fork
`framework/` per project.

## Reruns when the extraction or PRD changes (idempotent operation)

When source material changes, do not regenerate everything blindly. Detect changed/new/removed
inputs, preserve prior human-approved decisions, update the audit, mark affected conclusions stale,
re-evaluate dependents, update traceability, add a `CHANGELOG.md` entry, and request human review
for material blueprint changes. See `CONTRIBUTING.md` → "Idempotent reruns".

## Validate before you trust it

Run the checklist in `framework/17-framework-validation-checklist.md` before relying on any
configured project: every active agent has incoming/outgoing communication rules, every task has an
owner and an independent reviewer, every handoff is validated, every blocker has an escalation path,
failed gates stop progress, high-risk actions require human approval, and agents cannot approve
their own final work.
