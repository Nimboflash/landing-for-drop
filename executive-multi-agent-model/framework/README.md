# The Framework Layer — Index

**Purpose.** This is the reusable, project-independent core of the Virtual Software Organization
(VSO): the method, the vocabulary, and the rules that let a set of AI agents run software
development as a real organization — assigning work, validating handoffs, gating completion, and
escalating to a human — without being tied to any one product, language, or stack.

> **Provenance banner.** Reusable / project-independent. Claims about the source carry
> Extracted / Inferred / Recommended / Unverified / Missing labels.

## What the framework layer is (and is not)

The `framework/` directory holds the *thinking*. Its sibling directories hold the *machinery* the
thinking produces: `schemas/` (machine-readable artifact definitions), `templates/` (fillable
communication and governance documents), and `diagrams/` (Mermaid pictures of the same structure).
Everything here is written to be lifted whole into a new project of any technology. Nothing here
names a credit product, a Python module, or a specific regulation; when a concrete example is
unavoidable it lives in `projects/credit-intelligence/`, never in these docs.

Two ideas hold the layer together. First, **an organization is defined by its authority, not its
hierarchy** — who owns which *kind of decision*, who may approve it, and who may never approve it.
Second, **every claim about how the source really worked is labeled**, so a reader can always
separate what was proven from what is proposed. The framework is deliberately more than a pile of
role prompts: it is a governance chassis (constitution, lanes, veto, gates, review) welded to a
drivetrain (orchestration, task/handoff/state, release), each part traceable to evidence or marked
as a recommended addition.

The framework is not a runtime, not a client deliverable, and not a description of the source
repository. The source (`credit-intelligence`) is *evidence for what patterns work*, cited but
never treated as automatically optimal.

## Reading order (00 → 17)

Read the method top-to-bottom the first time; after that, treat it as reference. The numbering
encodes dependency — earlier documents fix the vocabulary that later ones consume.

| # | Document | What it fixes |
|---|---|---|
| 00 | `00-source-audit-method.md` | How to audit a prior extraction *before* building on it. The discipline that produced everything downstream. |
| 01 | `01-evidence-classification.md` | The five provenance labels and the classified-item block every other doc uses. The backbone. |
| 02 | `02-canonical-agent-model.md` | The 19-role roster, lifecycle/classification vocabularies, per-role dispositions, overlap rulings, activation matrix. The heart of the org. |
| 03 | `03-communication-architecture.md` | How the agents form one interconnected network: messages, handoffs, events, state, and who may talk to whom. |
| 04 | `04-organization-and-authority.md` | Authority over question types; the responsibility, decision-authority, approval, escalation, and separation-of-duties matrices. |
| 05 | `05-orchestrator-specification.md` | What coordinated the source (nothing dedicated), and the reusable orchestrator's charter and hard limits. |
| 06 | `06-shared-context-model.md` | The constitution that outranks everything; shared-context sections and their section-level owners. |
| 07 | `07-project-state-model.md` | Persistent, machine-readable project state; interrupted-session recovery; field-level ownership. |
| 08 | `08-message-protocol.md` | The message envelope, the 19 message types, and per-agent communication rules. |
| 09 | `09-handoff-protocol.md` | The one handoff format, its 15-item validation, and the five accept/reject outcomes. |
| 10 | `10-blocker-escalation-and-retry.md` | Blockers, escalation ladders that always end at a human, and the retry/rework loop. |
| 11 | `11-prd-to-production-workflow.md` | The original path and the optimized reusable lifecycle, stage by stage, plus events. |
| 12 | `12-version-and-milestone-model.md` | Versions as falsifiable exit gates; the planning hierarchy; deferral and closure rules. |
| 13 | `13-contract-governance.md` | Contract-first parallel work and the cross-lane coordination pairs. |
| 14 | `14-quality-security-and-release.md` | The canonical gate set, the scoped security veto, and release readiness. |
| 15 | `15-file-ownership-and-parallel-work.md` | The file-ownership matrix and the branch/merge rules that make parallelism safe. |
| 16 | `16-human-control-model.md` | The four decision classes and the mandatory human-approval checkpoints. |
| 17 | `17-framework-validation-checklist.md` | The reusable self-check an independent reviewer runs before trusting a configured project. |

If you only read three, read `01`, `02`, and `04`: labels, roles, authority.

## The five provenance labels

Every assertion about the source — every agent, workflow, responsibility, gate, or gap — carries
exactly one of these. Ordinary explanatory prose does not. `01-evidence-classification.md` is the
full treatment; this is the index-level summary.

| Label | Use it when… | Maps from source's own labels |
|---|---|---|
| **Extracted** | The claim is directly supported by recorded repository evidence. | "Explicit repository fact" |
| **Inferred** | Multiple evidences strongly suggest it, but it is not explicitly proven. | "Strong inference" / "Weak inference" |
| **Recommended** | A proposed improvement for the reusable system; it was *not* in the source. | "Recommended improvement/addition" |
| **Unverified** | Mentioned or suspected, but evidence is insufficient or contradictory. | "Could not verify" |
| **Missing** | The reusable system needs it; it was searched for and not found. | "Not found" |

The source repository had **no git history**, so any claim about a commit, branch, tag, release, or
authorship is **Unverified by construction** — no evidence could exist. And a **Recommended** agent
or workflow is *never* described as something that existed in the source. These two rules are
load-bearing everywhere.

## How the docs map to schemas, templates, and diagrams

The framework docs state the rules; the schemas make them machine-checkable; the templates make
them fillable; the diagrams make them legible at a glance.

| Framework doc | Schemas (`schemas/`) | Templates (`templates/`) | Diagrams (`diagrams/`) |
|---|---|---|---|
| 02 agent model | `agent.schema.yaml` | `agent-definition-template.md` | `organization.mmd` |
| 03 communication | `message.schema.yaml`, `event.schema.yaml` | `agent-message-template.md` | `communication-network.mmd` |
| 04 authority | `agent.schema.yaml`, `approval.schema.yaml` | `escalation-template.md`, `human-approval-request-template.md` | `organization.mmd` |
| 05 orchestrator | `project-state.schema.yaml` | `task-assignment-template.md` | `communication-network.mmd` |
| 06 shared context | (described in-doc; instances in `state/shared-context.yaml`) | — | — |
| 07 project state | `project-state.schema.yaml` | — | — |
| 08 message protocol | `message.schema.yaml` | `agent-message-template.md`, `clarification-request-template.md`, `review-request-template.md`, `review-result-template.md` | `communication-network.mmd` |
| 09 handoff | `handoff.schema.yaml` | `agent-handoff-template.md` | `handoff-validation.mmd` |
| 10 blocker/escalation/retry | `blocker.schema.yaml` | `blocker-report-template.md`, `escalation-template.md` | `blocker-escalation.mmd` |
| 11 PRD-to-production | `task.schema.yaml`, `handoff.schema.yaml`, `contract.schema.yaml`, `event.schema.yaml` | (most templates) | `prd-to-production.mmd`, `task-state-machine.mmd` |
| 12 versions/milestones | `version.schema.yaml` | — | `version-milestone-breakdown.mmd` |
| 13 contract governance | `contract.schema.yaml` | `contract-change-template.md` | `frontend-backend-coordination.mmd` |
| 14 quality/security/release | `quality-gate.schema.yaml`, `review.schema.yaml`, `approval.schema.yaml` | `qa-report-template.md`, `security-report-template.md`, `release-readiness-template.md`, `post-release-report-template.md` | `quality-approval-gates.mmd`, `release-communication.mmd` |
| 15 file ownership | `agent.schema.yaml`, `task.schema.yaml` | — | — |
| 16 human control | `approval.schema.yaml` | `human-approval-request-template.md` | — |

Two schemas — `agent.schema.yaml` and `quality-gate.schema.yaml` — are *partially extracted* (a real
source kernel plus a formalized shape). The other ten are **Recommended**: the source coordinated
through prose documents, not structured state, so `task`, `handoff`, `project-state`, `message`,
`event`, `blocker`, `review`, `approval`, `version`, and `contract` are additions this framework
contributes. Every schema states its own provenance in its top comment.

## The non-negotiable invariants

These hold across *every* file in the framework. A generated document that violates one is a bug,
not a variation. This list is the canonical short form; each document owns the full statement.

1. **Constitution supremacy.** A shared constitution outranks every document and every agent; a doc
   that disagrees with it is a bug (`06`).
2. **Single owner per decision.** Every decision has exactly one owner in the decision-authority
   matrix (`04`).
3. **Separation of duties.** Implementation and final approval are different roles; no agent moves
   its own implementation task from `in_progress` to any approval or `completed` state (`08`, `04`).
4. **Orchestrator holds no decision authority.** It schedules, tracks, validates form, and requests
   approvals; it may not approve its own work, set or reprioritize scope, approve architecture,
   override a failed blocking gate, approve a security exception or deployment, suppress reviewer
   findings, mark incomplete work complete, or rewrite classifications (`05`).
5. **The scoped security veto.** The `security-engineer` may veto the one defined
   existential-compliance question; the `cto`/arbiter cannot overrule it; it must ship *with an
   alternative*; it is recorded as a decision/ADR; it is scoped to exactly that one question (`14`).
6. **Gates over status.** A task enters `completed` only with attached gate evidence; status fields
   never outrank gates (`11`, `14`).
7. **Red blocking gate = stop.** No one — including orchestrator or CTO — overrides a failed
   CI-class blocking gate; `quality_gate.override_authority` for CI-stage gates is `none` (`14`).
8. **Human approval required** for product-scope change, high-risk assumption, major architecture
   decision, new external dependency, destructive migration, authn/authz change, sensitive-data
   change, security exception, production deployment, production rollback, release approval, and
   critical gate override (`16`).
9. **No self-approval, no silent handoff repair, no orchestrator scope/architecture edits.** An
   incomplete handoff is named and returned, never quietly fixed (`09`).
10. **Field-level ownership of state.** Only the `orchestrator` writes coordination fields; owning
    agents write their own evidence; approval, gate, security, and release fields belong to their
    authorities, not the orchestrator (`07`).
11. **Provenance discipline.** Extracted vs. Inferred vs. Recommended is preserved in every
    artifact; recommendations are never presented as source behavior (`01`).

## The one worked example

The framework has exactly one applied example, and it lives outside this directory:
`projects/credit-intelligence/`. That folder audits the real source extraction (`audit/`), applies
the framework to it (`blueprint/`, including a Claude Code handoff prompt), and holds illustrative
state instances (`state/`). It is always labeled as the *evidence source*, never as a required part
of the framework. When these docs cite `EXT/<doc>` or `repo:<path>`, they point into that evidence.

## Reusable rules (recap)

- The framework layer is technology- and project-independent; concrete examples belong in
  `projects/`, never in these docs.
- Read `00 → 17` in order the first time; `01`, `02`, `04` are the irreducible core.
- Every claim about the source carries one of five labels; ordinary prose does not.
- No git history means every commit/branch/tag/release claim is **Unverified**; a **Recommended**
  item is never described as pre-existing.
- The eleven invariants are non-negotiable across all files — a violation is a bug.
