# 11 — PRD-to-Production Workflow

**Purpose.** The end-to-end path from a product requirement to validated production, documented first
as the source designed it (with its honest gaps) and then as the reusable, optimized lifecycle.

> **Provenance banner.** The original 23-stage design is **Extracted** where a mechanism existed and
> **Missing** where only intent existed. The optimized lifecycle's middle layer (tasks, handoffs,
> state) and delivery tail (release, deploy, rollback, post-release) are **Recommended**.

## The original workflow (Extracted intent, with a missing middle and tail)

The reference repository specified a complete *intent* — every station had an owner, a definition of
done, and gates — but the conveyor belt between stations did not exist. Reading its 23 designed
stages honestly (`EXT/09-prd-to-product-workflow.md`): the **top** was strong (PM's PRD bar; phase
plan with a falsifiable exit gate and an explicit "do not negotiate back in" exclusion list; ADRs
with fired-trigger checks). The **middle was missing** — no task objects, no handoffs, no state; work
was proposed conversationally and left no trace. The **tail was missing** — no deploy, release,
rollback, or post-release path; the "always-releasable `main`" had nowhere to release to. The design
substituted two asymmetric safety nets for a requirements-traceability middle: falsifiable phase exit
gates at the top and standing non-negotiables at the bottom. Elegant, and incomplete for multi-agent
execution.

The optimized lifecycle keeps the strong top, adds the missing middle, and builds the missing tail —
each addition labeled Recommended.

## The optimized reusable lifecycle

The path, stage by stage:

> PRD → requirements audit → clarification & assumptions → product-scope approval → release strategy
> → version planning → architecture → contract definition → milestone planning → feature & task
> decomposition → dependency mapping → agent assignment → implementation → integration → code review
> → automated testing → QA → security review → release preparation → **human approval** → deployment
> → post-release validation → closure & lessons learned.

Each stage is specified with the same envelope: **responsible agent**, required participants, inputs,
outputs, entry and exit criteria, handoff artifact, quality gate, human approval, failure path, retry
path, escalation path, project-state update, and events emitted. The table below gives the load-
bearing fields; the per-project configuration fills the rest in `projects/<slug>/blueprint/06-...`.

| Stage | Responsible | Exit criteria | Gate | Human? | Key events |
|---|---|---|---|---|---|
| Requirements audit | product-manager | PRD meets the content bar | requirement-validation | — | `prd_received`, `prd_accepted` |
| Clarification & assumptions | orchestrator + PM | ambiguities resolved; assumptions recorded | — | high-risk assumptions | `requirements_blocked` |
| Product-scope approval | product-manager | scope + non-goals approved | — | **yes** | `scope_approved` |
| Release strategy | release-manager | release approach chosen | — | — | — |
| Version planning | product-manager | one falsifiable exit gate + OUT list | — | — | `version_plan_approved` |
| Architecture | cto / software-architect | ADRs written; triggers named | architecture-review | major | `architecture_proposed`, `architecture_approved` |
| Contract definition | contract owners | contract versioned + approved | contract-tests | — | `contract_ready` |
| Milestone planning | orchestrator + PM | next increment scoped | — | — | — |
| Feature & task decomposition | orchestrator | tasks created with lanes | — | — | `task_ready` |
| Dependency mapping | orchestrator | dependency graph set | — | — | — |
| Agent assignment | orchestrator | owners + reviewers assigned | — | — | `task_started` |
| Implementation | implementation agents | work claimed complete | edit-time hooks | — | `implementation_complete` |
| Integration | backend/devops | integrated on green | build-verification | — | `build_passed`/`build_failed` |
| Code review | code-reviewer | independent review pass | review gate | — | `review_passed`/`review_failed` |
| Automated testing | qa/test-automation | tests green | unit/integration/contract | — | `qa_passed`/`qa_failed` |
| QA | qa-engineer | acceptance criteria verified vs PRD | QA gate | — | `qa_passed` |
| Security review | security-engineer | no blocking findings; veto clear | security gate (veto) | exceptions | `security_passed`/`security_failed` |
| Release preparation | release-manager | independent evidence bundle assembled | release-readiness | — | `release_ready` |
| Human approval | human-owner | ship approved | — | **yes** | `deployment_approval_requested`, `deployment_approved` |
| Deployment | devops-engineer | deployed + verified | deployment-verification | **yes** | `deployment_completed` |
| Post-release validation | release-manager + PM | exit gate met in production | post-release gate | — | `post_release_validation_passed`/`_failed` |
| Closure & lessons | orchestrator + PM | version closed; lessons recorded | — | — | `version_completed` |

Every failure path routes through `10` (rejection → rework → independent re-review); every stage
writes its result to project state (`07`); every gate obeys the non-override rule (`14`).

## Sequential vs. parallel

Some stages must be sequential; others parallelize, but only under conditions. Sequential by
necessity: security consultation *before* a data collector or new signal is built; a fired migration
trigger *before* infrastructure adoption; the contract *before* its consumers; leakage/quality
validation *before* metrics are reported. Parallel by design, **but only after contracts and file
ownership are established**: front-end and back-end build simultaneously against a versioned contract
with a generated client; module-owned schemas let engineers work without JOIN-level collisions;
DevOps builds environment plumbing alongside implementation; QA owns gates continuously rather than
as a terminal phase. The condition that unlocks parallelism is the same one the source proved: the
interface is the coordination mechanism, so parallel work is safe once the interface is fixed and
each agent's files are owned.

The blocking conditions are equally explicit: an unresolved high-risk assumption blocks scope
approval; a missing or unfired migration trigger blocks infrastructure adoption; an unacknowledged
contract change blocks dependent implementation; a red blocking gate blocks progress entirely.

## Reusable rules (recap)

- Document the original process honestly first, then the optimized one — do not force a materially
  different source into a template.
- Keep the strong top (PRD bar, exit gates, ADRs), add the middle (tasks, handoffs, state), build the
  tail (release, deploy, rollback, post-release).
- Every stage names a responsible agent, entry/exit criteria, a gate, and its failure/retry/
  escalation paths, and emits events.
- Parallelize only after contracts and file ownership exist; keep security, triggers, and contracts
  sequential where safety demands.
- A red blocking gate stops the line; failures route through the rework loop, not around it.
