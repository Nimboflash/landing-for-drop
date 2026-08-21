# Virtual Software Organization (VSO)

A reusable, technology-independent framework for running software development as an **interconnected
virtual organization of AI agents** — agents that assign and receive tasks, pass work through
validated handoffs, request reviews, return rejected work, report blockers, escalate disagreements,
request human approval, and resume from persistent state, with traceability preserved from PRD
through release.

This is not a collection of role prompts. It is a governance chassis with a drivetrain: a
constitution that outranks every agent, ownership lanes with negative scope, one scoped security
veto, non-overridable quality gates, an orchestrator that coordinates but never decides, and a
persistent task/handoff/state layer that lets multiple agents work in parallel without colliding.

## Where this came from

The framework is **evidence-based**. It was distilled from a prior Claude Code analysis of a real
repository (codenamed `credit-intelligence` — an AI credit-underwriting engine captured at its
documentation-first, pre-code stage, with no git history). That analysis is preserved, audited, and
applied as a single worked reference under `projects/credit-intelligence/`.

Everything in this repository is labeled with one of five provenance classes so you always know what
is proven versus proposed:

| Class | Meaning |
|---|---|
| **Extracted** | Directly supported by recorded repository evidence. |
| **Inferred** | Strongly suggested by multiple evidences; not explicitly proven. |
| **Recommended** | A proposed improvement for the reusable system; not present in the source. |
| **Unverified** | Mentioned or suspected; evidence is insufficient or contradictory. |
| **Missing** | A capability the reusable system needs; searched for, not found in the source. |

**A `Recommended` agent or workflow is never described as something that existed in the source.**
The source repository is treated as *evidence, not as automatically optimal architecture*.

## What is proven vs proposed (one-paragraph honesty note)

The source proved a strong **governance top-half**: a constitution with declared precedence,
ownership lanes with explicit "never touches" scope, a compliance veto the CTO cannot overrule,
architecture-as-ADR with fired-migration-trigger discipline, and completion defined by
non-overridable gates rather than status fields. It was **missing the execution bottom-half**: no
orchestrator, no task/handoff/project-state layer, no release/deploy/rollback tail, and no
per-agent tool permissions. This framework keeps the proven chassis (marked *Extracted*/*Inferred*)
and adds the missing drivetrain (marked *Recommended*), each clearly labeled.

## Repository layout

```
virtual-software-organization/
├── README.md                     # this file
├── USAGE.md                      # how to apply the framework to a project
├── CONTRIBUTING.md               # how to extend framework vs. project layers
├── CHANGELOG.md                  # provenance-tracked change history
├── .gitignore
├── project-profile.example.yaml  # copy → projects/<slug>/project-profile.yaml
│
├── framework/    # 18 reusable, project-independent method documents (00–17 + README)
├── schemas/      # 12 machine-readable schemas for every state-changing artifact
├── templates/    # 15 fillable communication & governance templates
├── diagrams/     # 10 Mermaid diagrams (each with a provenance legend)
└── projects/
    └── credit-intelligence/   # the one worked reference example (evidence source)
        ├── project-profile.yaml
        ├── source-extraction/  # pointer to the READ-ONLY original extraction
        ├── audit/              # source-folder audit + extraction-quality review
        ├── blueprint/          # framework applied to the evidence + Claude Code handoff
        └── state/              # illustrative state/context/log YAML instances
```

- `framework/` — the reusable rules. Project-independent. Start at `framework/README.md`.
- `schemas/` — reusable machine-readable definitions (agent, message, task, handoff, blocker,
  review, approval, quality-gate, project-state, version, contract, event).
- `templates/` — reusable message and governance templates.
- `projects/<slug>/` — project-specific evidence, configuration, and outputs. Never mix
  project-specific claims into the global framework.

## The 19-role organization at a glance

Always-on core: `orchestrator` (coordinates, no authority), `product-manager` (scope), `cto`
(architecture + arbiter), `backend-engineer`, `qa-engineer` (gates), `security-engineer` (scoped
veto), `code-reviewer` (independent review), and the `human-owner`. Conditional specialists —
`software-architect`, `product-owner`, `domain-policy-architect`, `frontend-engineer`,
`ml-engineer`, `data-engineer`, `database-engineer`, `ux-design-system`,
`test-automation-engineer`, `release-manager`, `documentation-engineer` — activate by **project
profile** (`minimal`, `standard`, `high_risk`, `regulated`, `infrastructure_heavy`,
`frontend_only`, `backend_only`, `mobile`, `data_or_ai`, `experimental`). See
`framework/02-canonical-agent-model.md`.

## Non-negotiable invariants

1. The constitution outranks every document and every agent.
2. Every decision has exactly one owner.
3. Implementation and final approval are separate roles — no self-approval.
4. The orchestrator coordinates but holds **no** decision authority.
5. The `security-engineer` holds one scoped veto the arbiter cannot overrule (and it must ship with
   an alternative).
6. A task reaches `completed` only with attached gate evidence — gates outrank status.
7. A failed blocking gate stops progress; no one overrides it.
8. High-risk actions require human approval.
9. Interrupted work resumes from persistent, machine-readable state.
10. An incomplete handoff is never silently repaired.

## Quick start

1. Read `USAGE.md`.
2. Copy `project-profile.example.yaml` to `projects/<your-slug>/project-profile.yaml` and pick a
   profile.
3. Fill `projects/<your-slug>/state/shared-context.yaml` from your PRD.
4. Hand `projects/<your-slug>/blueprint/claude-code-handoff-prompt.md` to Claude Code to scaffold
   the runtime (agents, hooks, commands, skills, schemas, state) on a dedicated framework branch.
5. Drive the PRD-to-production workflow in `framework/11-prd-to-production-workflow.md`.

See `projects/credit-intelligence/` for a complete worked example.
