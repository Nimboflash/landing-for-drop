# Changelog

All notable changes to the Virtual Software Organization framework are recorded here. Because this
framework is evidence-based, changes note whether they affect **Extracted**, **Inferred**, or
**Recommended** material, and whether any evidence classification changed.

The format is loosely based on Keep a Changelog. Schema-affecting changes bump the relevant
`schema_version`.

## [0.1.0] — 2026-07-13

Initial framework release, distilled from the `credit-intelligence` extraction (documentation-first
repository, no git history).

### Added — framework layer
- 18 method documents in `framework/` (`00`–`17` + `README.md`): source-audit method, evidence
  classification, canonical agent model, communication architecture, organization & authority,
  orchestrator specification, shared-context model, project-state model, message protocol, handoff
  protocol, blocker/escalation/retry, PRD-to-production workflow, version & milestone model,
  contract governance, quality/security/release, file ownership & parallel work, human-control
  model, framework validation checklist.
- 12 machine-readable schemas in `schemas/` (`schema_version: 1`): agent, message, task, handoff,
  blocker, review, approval, quality-gate, project-state, version, contract, event.
- 15 fillable templates in `templates/`.
- 10 Mermaid diagrams in `diagrams/`, each with a six-way provenance legend.
- Top-level `README.md`, `USAGE.md`, `CONTRIBUTING.md`, `.gitignore`, `project-profile.example.yaml`.

### Added — project layer (reference example)
- `projects/credit-intelligence/`: source-folder audit, extraction-quality review, contradictions &
  unverified findings, follow-up investigation tasks, a 16-part blueprint, a self-contained Claude
  Code handoff prompt, and illustrative state/context/log YAML instances.

### Provenance notes
- The 10-role real roster is **Extracted** (three roles renamed for reuse: credit-architect →
  `domain-policy-architect`, ai-engineer → `ml-engineer`, security-architect → `security-engineer`).
- The `orchestrator`, `release-manager`, `product-owner`, `database-engineer`,
  `test-automation-engineer`, `documentation-engineer`, and `ux-design-system` roles are
  **Recommended** additions — they did not exist in the source.
- `software-architect` (split from cto) and `code-reviewer` (formalized from the review system) are
  **Inferred**.
- All version/release history is **Unverified** (source had no git history).
- The task/handoff/project-state layer, the release/deploy/rollback tail, and per-agent tool
  permissions are **Recommended** (they were **Missing** from the source).

### Known limitations carried forward
- The source's execution half was never exercised (no code, no PRD run), so effectiveness in real
  multi-agent operation is `Unverified`, not proven.
- Automation metrics from the source (~37% weighted; 1 of 21 stages fully automated) are
  method-dependent and reproduced with that caveat.
