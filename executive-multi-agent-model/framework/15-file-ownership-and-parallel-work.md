# 15 — File Ownership and Parallel Work

**Purpose.** How agents work in parallel without corrupting each other's files. Ownership is declared,
shared files change through a controlled procedure, and branches and merges follow rules that keep
`main` always releasable.

> **Provenance banner.** Declared-owner-per-file, structural conflict avoidance, and the enforcement
> triad are **Extracted**. Per-task file grants and technical permission enforcement (CODEOWNERS,
> branch protection) are **Recommended** — the source's lanes were normative only, with no technical
> enforcement (a High-severity gap).

## Ownership is declared, not assumed

Every file has exactly **one accountable owner**, and — the source's genuinely good idea — that
owner is declared *in the file itself* (an `Owner:` line), not in a side registry that drifts. The
framework keeps that, and adds the technical enforcement the source lacked: a `CODEOWNERS`-style map
generated from the ownership matrix, plus branch protection, so a lane is enforced by the tooling and
not only by an agent's good behavior.

## The file-ownership matrix

Configured per project (the shape is fixed here; the paths are filled in
`projects/<slug>/blueprint/10-...`):

| Path or file type | Primary owner | Allowed contributors | Required reviewer | Approval | Conflict risk |
|---|---|---|---|---|---|
| Frontend source | frontend-engineer | ux-design-system | code-reviewer | review + CI | medium |
| Backend source | backend-engineer | — | code-reviewer | review + CI | medium |
| Shared libraries | cto / software-architect | owning engineers | cto | review + CI | high |
| API contracts | contract owners | affected agents | cto | +ack (13) | high |
| Database schemas | database-engineer | backend-engineer | software-architect | migration gate | high |
| Migrations | database-engineer | — | backend-engineer | migration gate + human (destructive) | high |
| Infrastructure / IaC | devops-engineer | — | cto | fired trigger + human | high |
| CI/CD | devops-engineer | — | cto | review + CI | high |
| Global configuration | cto | devops-engineer | cto | review | high |
| Security configuration | security-engineer | — | cto | security gate | high |
| Test fixtures | qa / test-automation | engineers | qa-engineer | CI | medium |
| Project state | orchestrator (coordination fields) | field owners | — | field ownership (07) | medium |
| Shared context | section owners (06) | section reviewers | per section | per section | high |
| Documentation | documentation-engineer | all | documentation-engineer | review | low |
| Release configuration | release-manager | devops-engineer | release-manager | release gate + human | high |

## Per-task file grants

On top of the standing lanes, each task carries `allowed_files` and `restricted_files`
(`task.schema.yaml`). A task-level grant may **narrow** an owner's standing lane but never **widen**
it, and `restricted_files` wins over `allowed_files` when both could apply. This is defense in depth:
the standing lane says what an agent *may* own; the per-task grant says what *this* task may touch.

## Changing a shared or contract file

Shared and contract files are the high-conflict surface, so changes to them run a controlled
procedure (the same shape as the contract-change steps in `13`):

1. Send a change request.
2. Identify affected agents.
3. Receive required acknowledgements.
4. Assign a change owner.
5. Update the contract or document version.
6. Update project state.
7. Apply the change.
8. Trigger required reviews.

## Branch, worktree, and merge rules

- **Branch naming** — short-lived branches off `main`, prefixed by intent (`feat/`, `fix/`, `docs/`,
  `chore/`).
- **Worktrees** — one worktree per parallel task where the runtime supports it, so agents do not
  contend for a single working tree.
- **Task-specific branches** — one branch per task, scoped to the task's `allowed_files`.
- **Shared files** — changed only through the eight-step procedure above; never edited directly on a
  feature branch without acknowledgement.
- **Merge order** — contract and migration changes merge *before* the consumers that depend on them;
  the orchestrator sequences merges to respect dependencies.
- **Contract changes** — bump the version and regenerate consumers before dependent work resumes.
- **Migration changes** — reversible, gated, and (if destructive) human-approved before merge.
- **Global configuration** — treated as a shared file; auto-discovery is preferred over explicit
  lists so a new module does not force a one-line edit to a shared file (the source's merge-conflict
  antidote: "the tree is the source of truth").
- **Conflict resolution** — a real content conflict escalates to the file's owner; an ownership
  dispute escalates to the `cto`; the orchestrator surfaces conflicts but does not adjudicate them.
- **Abandoned branches** — a branch with no progress past a threshold is flagged, its task returned to
  the backlog or cancelled, and its lane released.
- **Deferred work** — moved to `deferred_tasks` with its forcing condition; its branch is closed, not
  left dangling.

## Reusable rules (recap)

- One accountable owner per file, declared in the file; enforce it technically (CODEOWNERS + branch
  protection), not just normatively.
- Per-task grants narrow standing lanes, never widen them; deny wins over allow.
- Change shared/contract files only through the controlled procedure, with acknowledgement.
- Merge contracts and migrations before their consumers; keep `main` always releasable.
- Escalate content conflicts to the file owner and ownership disputes to the CTO; the orchestrator
  surfaces, never adjudicates.
