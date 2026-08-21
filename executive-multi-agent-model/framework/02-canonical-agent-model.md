# 02 — Canonical Agent Model

**Purpose.** The roster. Who the agents are, how each is classified and how long it lives, which
project types activate it, and the rulings that keep the organization from bloating into duplicate
or self-approving roles.

> **Provenance banner.** Reusable / project-independent. The 10-role core is **Extracted** (three
> roles renamed for reuse); two roles are **Inferred**; seven are **Recommended** additions, never
> described as pre-existing.

## The agent definition

Every role is described by one machine-readable record (`schemas/agent.schema.yaml`) and one prose
definition (`templates/agent-definition-template.md`). The record fixes: `canonical_id`,
`canonical_name`, `original_names`, `aliases`, `classification`, `lifecycle_status`,
`project_types`, `versions`, `mission`, `responsibilities`, `decision_authority`,
`prohibited_actions`, `inputs`, `outputs`, `tools`, `permissions`, `restrictions`,
`parent_or_supervisor`, `receives_work_from`, `sends_work_to`, `supported_message_types`,
`handoff_requirements`, `review_responsibilities`, `escalation_path`, `definition_of_done`,
`activation_conditions`, `deactivation_conditions`, `evidence_refs`, `confidence`, and — where it
applies — `veto_authority{scope, who_cannot_overrule}`. The `canonical_id` is kebab-case and stable;
it is the name every message, task, handoff, and matrix uses.

A note the source itself made necessary: in the reference repository **no agent declared `tools` or
`permissions`** — all ten inherited full tool access, so their lanes were *normative*, not
*technical* (a real gap, classified High-severity in the source risk register). This framework keeps
`tools`/`permissions` as first-class fields precisely so a reusable deployment can scope them.

## The 19-role canonical roster

`Cls` = framework classification; `Life` = default lifecycle. The ten **Extracted** rows are the
real source roster (three renamed to drop domain nouns: `credit-architect → domain-policy-architect`,
`ai-engineer → ml-engineer`, `security-architect → security-engineer`).

| canonical_id | Cls | Life | Mission (one line) | Activation |
|---|---|---|---|---|
| `orchestrator` | Recommended | active | Owns the temporal layer: intake, decomposition, dispatch, state, handoff validation, retries. **No decision authority.** | always-on |
| `product-manager` | Extracted | active | Owns product scope and priority — "the agent that says not now". | always-on |
| `product-owner` | Recommended | conditional | Execution half of product: backlog refinement, story acceptance, per-iteration priority. | scale |
| `cto` | Extracted | active | Architecture authority and final arbiter; only role that changes a boundary. | always-on |
| `software-architect` | Inferred | conditional | Working architect: ADRs, service boundaries, phase split, migration triggers. CTO approves. | scale |
| `domain-policy-architect` | Extracted | active | Converts model/domain outputs into business decisions; owns thresholds/policy. | domain logic exists |
| `backend-engineer` | Extracted | active | Services, APIs, domain code, persistence, audit/decision log. Implements policy, never authors it. | most projects |
| `frontend-engineer` | Extracted | active | User-facing surface; barred from redefining API contracts or output semantics. | has a UI |
| `ml-engineer` | Extracted | conditional | Models and feature definitions; produces predictions, never business thresholds. | data/AI |
| `data-engineer` | Extracted | conditional | Data substrate, ingestion, contracts, lineage. Owns substrate, not feature definitions. | data/AI, infra-heavy |
| `database-engineer` | Recommended | conditional | Dedicated schema/migration lane; reversible migrations, module-owned schemas, ports not JOINs. | heavy DB work |
| `ux-design-system` | Recommended | conditional | Steward of design tokens, component library, interaction states, accessibility. | frontend-heavy |
| `qa-engineer` | Extracted | active | Owns merge and promotion **gates** (not code). Verifies acceptance criteria; gates non-overridable. | always-on |
| `test-automation-engineer` | Recommended | conditional | Hands-on suite build/maintenance; flaky-test policy; wires domain gates. | suite outgrows QA |
| `code-reviewer` | Inferred | active | Standing independent reviewer; verify-don't-tick; names the owning agent per finding. | always-on |
| `security-engineer` | Extracted | active | Security/privacy/compliance authority. **Holds the one scoped veto.** | always-on |
| `devops-engineer` | Extracted | active | Platform, CI/CD, IaC, observability plumbing, secrets delivery. Discipline: restraint. | most projects |
| `release-manager` | Recommended | active | Owns versioning and release gates and ship/no-ship on independent QA+security evidence. | standard+ |
| `documentation-engineer` | Recommended | conditional | Enforces doc governance: constitution precedence, phase split, ADR completeness. | high-risk/regulated |

Plus the `human-owner` — not an agent but the human operator, product owner, and release/
security-exception authority. It is **Extracted** by elimination: in the source, every act of
sequencing, merging, and would-be releasing routed through one unnamed human.

## Lifecycle and classification vocabularies

`lifecycle_status` is one of: `active`, `conditional`, `deprecated`, `replaced`, `experimental`,
`unverified`, `recommended`. `classification` (the *kind* of role) is one of:
`explicit_primary_agent`, `explicit_subagent`, `implicit_agent_like_role`, `supervisory_agent`,
`specialist_agent`, `workflow_automation`, `review_gate`, `approval_gate`, `human_operated_role`,
`deprecated_role`, `experimental_role`, `recommended_addition`, `unverified_role`. The source had no
deprecated or experimental agents; the only lifecycle signal it carried was the inferred
seed-agent story of `credit-architect` (a `replaced`-in-place origin, still active with a narrowed
lane) — preserved here as `domain-policy-architect` with a note, not as a live deprecated role.

## Per-role dispositions

For each discovered or proposed role the framework decides a disposition: keep separately, merge,
rename, narrow, convert into a deterministic workflow, convert into a quality gate, make
conditional, preserve only as a project-specific specialist, or remove. The notable ones:

- **Kept and renamed** to drop domain nouns: `domain-policy-architect`, `ml-engineer`,
  `security-engineer` (the same Extracted roles, generalized).
- **Kept, narrowed:** `domain-policy-architect` — its source form (`credit-architect`) carried an
  ungated "design for scale" persona that contradicted the constitution; the reusable form is
  clamped to the policy lane.
- **Made conditional:** `software-architect`, `product-owner`, `ml-engineer`, `data-engineer`,
  `database-engineer`, `ux-design-system`, `test-automation-engineer`, `documentation-engineer`.
- **Converted to deterministic workflow / quality gate rather than an agent:** formatting, layering
  checks, secret scanning, dependency audits — these are gates (`workflow_automation`), not roles,
  because they require enforcement, not reasoning.
- **Recommended additions kept as roles:** `orchestrator`, `release-manager`, `product-owner`,
  `database-engineer`, `test-automation-engineer`, `documentation-engineer`, `ux-design-system`.

## Overlap rulings

The point of these rulings is to *minimize duplicate responsibilities* without collapsing roles that
must stay independent for separation of duties. **Do not merge roles when independent review is
necessary.**

- **`orchestrator` vs `product-manager`** — keep separate. The orchestrator schedules; the PM
  decides scope. Scheduling is not deciding.
- **`orchestrator` vs a context manager** — merge context loading *into* the orchestrator plus
  auto-loaded rules; no separate context agent.
- **`cto` vs `software-architect`** — conditional split. At small scale the CTO is the architect; at
  scale the architect drafts ADRs and the CTO approves them. Keep the approval separate from the
  drafting.
- **`product-manager` vs `product-owner`** — conditional split at scale (strategy vs execution).
- **`qa-engineer` vs `test-automation-engineer`** — keep separate. QA owns *what blocks*; the test
  engineer *builds the suite*. Governance and implementation are different jobs.
- **`code-reviewer` vs `cto`/technical-lead** — keep separate. Review must be independent of
  boundary authority, or it becomes self-review.
- **`devops-engineer` vs `release-manager`** — keep separate. DevOps owns the pipeline plumbing; the
  release manager owns ship/no-ship. Building the road is not deciding to drive on it.
- **`security-engineer` vs the security gate** — the engineer owns *policy and the veto*; the gate is
  the automated check that enforces a slice of it.
- **`documentation-engineer` vs implementation agents** — conditional. In the source, doc quality was
  every agent's job and therefore no one's; a dedicated role is Recommended for high-risk/regulated
  work.

## Project-profile activation

A profile decides which agents are active so a small project does not inherit a large or high-risk
organization. Always-on core across every profile: `orchestrator`, `product-manager`, `cto`, an
implementation lane, `qa-engineer`, `security-engineer`, `code-reviewer`, and the `human-owner`.

| profile | adds beyond core |
|---|---|
| `minimal` | (core only; devops optional) |
| `standard` | frontend, devops, release-manager, software-architect (optional) |
| `high_risk` | + documentation-engineer; all human approvals on |
| `regulated` | + elevated security, documentation-engineer; audit evidence |
| `infrastructure_heavy` | + elevated devops, database-engineer, release-manager |
| `frontend_only` | frontend, ux-design-system; drop backend/data; accessibility blocking |
| `backend_only` | backend, database-engineer; drop frontend/ux |
| `mobile` | frontend (mobile), ux-design-system, release-manager; store-release checks |
| `data_or_ai` | ml-engineer, data-engineer, database-engineer; leakage/replay/stability/fairness gates |
| `experimental` | core minus release-manager; relaxed, non-blocking gates |

Activation is set per project in `project-profile.yaml` and can be overridden role by role.

## Reusable rules (recap)

- The 10 Extracted roles are real (3 renamed); 2 are Inferred; 7 are Recommended and never
  described as pre-existing.
- Keep `tools`/`permissions` technical, not just normative — the source's biggest gap.
- Minimize duplicate roles, but never merge where independent review is required.
- Prefer a deterministic workflow or a quality gate over a new agent when no reasoning is needed.
- Profiles gate activation; a small project must not inherit a large one.
