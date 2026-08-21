# Project: credit-intelligence (reference example)

This is the **one worked example** of the Virtual Software Organization framework — and the
**evidence source** the whole framework was distilled from. It is not a client deliverable and not a
required part of the framework; it exists so the reusable rules in `../../framework/` have something
concrete and honest to point at.

## What the source is

`credit-intelligence` is an AI credit-underwriting engine ("not a lender… the intelligence layer that
powers lenders"), captured by a prior Claude Code analysis at its **documentation-first, pre-code
stage**: a constitution, ~15 governance documents, three ADRs, full API and ML specifications, a
complete Python toolchain — and essentially **zero application code**. The analyzed copy had **no git
history**, so all findings are file-level and any claim about chronology is *Unverified*.

## What this folder contains

| Folder | What it holds |
|---|---|
| `source-extraction/` | A pointer to the original extraction, treated as **read-only** evidence. The 105 source files are not copied in; they are referenced. |
| `audit/` | The source-folder audit, extraction-quality review, contradictions and unverified findings, and follow-up investigation tasks. This is `framework/00-source-audit-method.md` applied. |
| `blueprint/` | The framework applied to this evidence: system summary, canonical agent inventory, authority, orchestrator config, context, state, workflow, versions, tasks/handoffs, contracts, ownership, gates, human approvals, gaps, traceability, readiness — and the self-contained `claude-code-handoff-prompt.md`. |
| `state/` | Illustrative YAML instances (`project-state`, `shared-context`, `decision-log`, `risk-register`, `contract-registry`, `approval-log`) showing how the framework's state layer *would* look here. Marked illustrative; not live runtime state. |
| `project-profile.yaml` | The profile that activates agents, gates, and human approvals for this project (`data_or_ai` + `high_risk`). |

## The headline findings (all classified)

- The real organization had **10 agents** and **no orchestrator** — coordination was *structural*
  (constitution + ownership lanes + escalation edges + non-overridable gates), with a human supplying
  all sequencing. **Extracted.**
- Its distinctive, reusable inventions: a constitution with declared precedence; ownership lanes with
  explicit "never touches"; a **scoped security veto the CTO cannot overrule**; architecture-as-ADR
  with fired-migration-trigger discipline; and completion defined by non-overridable gates rather than
  status. **Extracted.**
- What it was missing, and what the framework adds as **Recommended**: an orchestrator; a
  task/handoff/project-state layer; a release/deploy/rollback tail; and per-agent technical
  permissions.
- Automation was ~37% weighted, with **1 of 21 lifecycle stages fully automated** (CI test
  execution). Zero versions shipped; three roadmap phases gated by falsifiable exit conditions.
  **Extracted / Unverified where chronology is involved.**

Start with `blueprint/00-project-system-summary.md`, then `audit/00-source-folder-audit.md`.
