# 01 — Canonical Agent Inventory

Every discovered agent and agent-like role in the `credit-intelligence` evidence, plus the roles the
framework recommends adding. Nothing here is limited to a predefined roster; the ten real agents were
discovered from the evidence, and the additions are labeled.

## Canonical-role table

| Canonical role | Original name(s) | Classification | Authority | Versions | Lifecycle | Disposition | Reason |
|---|---|---|---|---|---|---|---|
| `cto` | cto | explicit_subagent · Extracted | architecture + final arbiter | all phases | active | Keep | Real, central authority |
| `domain-policy-architect` | credit-architect | explicit_subagent · Extracted | domain/business policy | all phases | active | Keep + rename + narrow | Drop domain noun; clamp seed persona to policy lane |
| `product-manager` | product-manager | explicit_subagent · Extracted | product scope | all phases | active | Keep | Real scope authority |
| `ml-engineer` | ai-engineer | explicit_subagent · Extracted | models + feature definitions | all phases | conditional | Keep + rename | Generalize; activate for data/AI |
| `data-engineer` | data-engineer | explicit_subagent · Extracted | data substrate + contracts | all phases | conditional | Keep | Real substrate owner |
| `backend-engineer` | backend-engineer | explicit_subagent · Extracted | services, APIs, decision log | all phases | active | Keep | Real implementation lane |
| `frontend-engineer` | frontend-engineer | explicit_subagent · Extracted | console, explanation UI | all phases | active | Keep | Real UI lane |
| `devops-engineer` | devops-engineer | explicit_subagent · Extracted | platform, CI/CD | all phases | active | Keep | Real platform lane |
| `security-engineer` | security-architect | explicit_subagent · Extracted | **scoped veto** | all phases | active | Keep + rename | Generalize; the veto is the crown jewel |
| `qa-engineer` | qa-engineer | explicit_subagent · Extracted | merge + promotion gates | all phases | active | Keep | Real gate owner |
| `code-reviewer` | `/pr-check` skill + PR review order | implicit_agent_like_role · Inferred | independent review | all phases | active | Formalize as role | Review system real; standing role is a formalization |
| `orchestrator` | — | recommended_addition · Recommended | coordination only | n/a | recommended→active | Add | The Missing dynamic layer |
| `release-manager` | — | recommended_addition · Recommended | ship/no-ship | n/a | recommended→active | Add | Source had no release role |
| `software-architect` | (folded into cto) | recommended_addition · Inferred | ADR drafting | n/a | conditional | Add at scale | Split working architect from CTO |
| `database-engineer` | (split of data/backend) | recommended_addition · Recommended | schema/migrations | n/a | conditional | Add if warranted | Dedicated DB lane |
| `test-automation-engineer` | (split of qa/CI) | recommended_addition · Recommended | suite maintenance | n/a | conditional | Add when suite grows | Separate hands-on from governance |
| `documentation-engineer` | `.claude/rules/docs.md` | recommended_addition · Recommended | doc governance | n/a | conditional | Add for regulated | Rules existed; role didn't |
| `product-owner` | (split of PM) | recommended_addition · Recommended | backlog/acceptance | n/a | conditional | Add at scale | Execution half of product |
| `ux-design-system` | (folded into frontend) | recommended_addition · Recommended | design system | n/a | conditional | Add for FE-heavy | Steward tokens/components |

## Implicit agent-like roles and automated workflows (Extracted)

Not agents, but agent-like or automated actors the evidence shows:

- **domain-purity hook** — PostToolUse hook blocking framework imports in domain layers;
  workflow_automation (blocking), no override.
- **layering CI gate** — AST check that domain imports no framework and no sibling module;
  workflow_automation (blocking), override explicitly forbidden.
- **CI quality gate** — format/lint/mypy/pytest + gitleaks; workflow_automation (blocking),
  non-overridable.
- **`/pr-check` reviewer** — the ~40-item checklist run manually; implicit_agent_like_role → the
  Inferred `code-reviewer`.
- **`/adr` scribe** — scaffolds the next ADR, refuses to relitigate settled decisions, enforces the
  fired-trigger rule; implicit_agent_like_role.
- **context loader** — `CLAUDE.md` + path-scoped `.claude/rules/*`; automated context injection →
  folded into the `orchestrator` + auto-loaded rules.
- **human operator** — the actual orchestrator and release manager of the source; human_operated_role,
  Extracted by elimination → the framework's `human-owner`.

## Representative agent records

Full records live in `../state/` and would be generated per `schemas/agent.schema.yaml`; two of the
most consequential are shown here.

```yaml
agent:
  canonical_id: security-engineer
  canonical_name: Security Engineer
  original_names: [security-architect]
  classification: explicit_subagent            # Extracted
  lifecycle_status: active
  mission: "Terminal authority on the data boundary and regulatory posture."
  decision_authority: "security policy; data legality; signal collection; the scoped veto"
  veto_authority:
    scope: "any design that centralizes/moves raw partner data across a tenant boundary"
    who_cannot_overrule: [cto, orchestrator]
  prohibited_actions: ["approve production deploy", "own product priority"]
  receives_work_from: [any engineer BEFORE building a collector/signal, orchestrator]
  sends_work_to: [cto, human-owner]
  escalation_path: [{question_pattern: "may we collect/store X?", target_agent: security-engineer}]
  definition_of_done: "no raw data crosses the boundary; every field has lawful basis + retention"
  evidence_refs: ["EXT/04-agent-definitions.md", "repo:security-architect.md", "repo:PROMPT.md#5"]
  confidence: high
```

```yaml
agent:
  canonical_id: orchestrator
  canonical_name: Orchestrator
  original_names: []                             # Recommended — did NOT exist in the source
  classification: recommended_addition
  lifecycle_status: recommended
  mission: "Coordinate the temporal layer: intake, decomposition, dispatch, state, handoff validation."
  decision_authority: "none — schedules and tracks only"
  prohibited_actions: ["approve own work", "set/reprioritize scope", "approve architecture",
                       "override a failed blocking gate", "approve security exceptions",
                       "approve deployment", "suppress reviewer findings", "mark incomplete complete",
                       "rewrite classifications"]
  activation_conditions: "all profiles"
  evidence_refs: ["EXT/06-orchestrator-analysis.md (Missing)", "framework/05-orchestrator-specification.md"]
  confidence: high        # high confidence it was ABSENT and is NEEDED
```

## Overlap resolutions (as applied here)

`orchestrator` vs `product-manager` — separate (schedule vs scope). `cto` vs `software-architect` —
conditional split (approve vs draft). `qa-engineer` vs `test-automation-engineer` — separate
(gates vs suite). `code-reviewer` vs `cto` — separate (independent review vs boundary authority).
`devops-engineer` vs `release-manager` — separate (pipeline vs ship decision). `security-engineer` vs
the security gate — engineer owns policy + veto, the gate enforces a slice. No roles merged where
independent review is required.
