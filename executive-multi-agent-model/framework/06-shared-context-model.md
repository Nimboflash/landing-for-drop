# 06 — Shared Context Model

**Purpose.** The persistent source of truth — the constitution and the shared context around it —
that every agent reads and only the right agents may edit.

> **Provenance banner.** Constitution precedence and per-document ownership (`Owner:` lines) are
> **Extracted**; the full section-level ownership model and the append-only decision log are a
> **Recommended** formalization of that Extracted kernel.

## The constitution outranks everything (Extracted)

The reference repository's most important structural idea was a single document that won every
conflict: "when a doc and this file disagree, this file wins, and the doc is a bug"
(`repo:PROMPT.md`). The framework keeps this precedence rule as invariant #1. The constitution fixes
the mission, the constraining facts, the non-negotiables (each with its *why*), the phase split, the
ownership roster, and the one scoped veto. Everything else — architecture docs, contracts, standards
— is subordinate to it, and a subordinate document that contradicts it is repaired, not obeyed.

Disagreeing with the constitution itself is allowed but must be explicit: an agent says so and
escalates; it does not quietly write a document that drifts from it.

## Shared-context sections and their owners

The shared context is stored as `projects/<slug>/state/shared-context.yaml`. It contains the
sections below, each with a **primary owner** and **required reviewers**. Ownership at the section
level is what prevents the "everyone's job, therefore no one's" failure the source suffered on
documentation.

| Section | Primary owner | Required reviewers |
|---|---|---|
| Product overview | product-manager | human-owner |
| PRD | product-manager | human-owner |
| Approved scope | product-manager | human-owner |
| Goals & non-goals | product-manager | human-owner |
| User journeys | product-manager | frontend-engineer, qa-engineer |
| Business rules | domain-policy-architect | product-manager, qa-engineer |
| Acceptance criteria | product-manager | qa-engineer |
| Active version | release-manager | product-manager |
| Architecture decisions | software-architect | cto |
| Design rules | ux-design-system | frontend-engineer |
| API contracts | contract owner (backend + domain-policy-architect + cto) | frontend-engineer |
| Database contracts | database-engineer | backend-engineer, software-architect |
| Coding standards | cto | engineers |
| Testing standards | qa-engineer | software-architect, engineering |
| Security requirements | security-engineer | cto |
| Git rules | devops-engineer | cto |
| Deployment rules | devops-engineer | release-manager |
| Release rules | release-manager | qa-engineer, security-engineer, devops-engineer |
| Known risks | orchestrator (collates) | risk owners |
| Approved assumptions | product-manager | human-owner (for high-risk) |
| Feature flags | product-owner or product-manager | devops-engineer |
| Analytics requirements | product-manager | ml-engineer / data-engineer |
| Current status | orchestrator | task owners |

## Per-section governance fields

For each section the shared context records not just an owner but a small governance envelope, so a
reader knows how much to trust it and how to change it:

- **Allowed editors** — who may write it (usually owner + reviewers).
- **Required reviewers** — who must sign off on a change.
- **Read permissions** — who may read (usually all agents; occasionally restricted for sensitive
  content).
- **Approval requirement** — whether a human must approve a change (yes for scope, high-risk
  assumptions, security).
- **Versioning method** — how changes are versioned (contracts are versioned explicitly; see `13`).
- **Staleness detection** — a `last_updated` timestamp; content older than one working day past a
  known change is suspect and flagged.
- **Conflict-resolution path** — where disputes go (the escalation matrix; ultimately the owner, then
  the human).
- **Update-notification requirements** — who must be notified (and must acknowledge) when the section
  changes, especially contracts and scope.

## The append-only decision log

Approved decisions are recorded, append-only, in `projects/<slug>/state/decision-log.yaml`
(ADR-shaped: context, decision, alternatives rejected and why, consequences accepted, reversal
trigger, and — for infrastructure — the fired migration trigger). This is the durable, ordered
memory of *why* the system is the way it is. It is never rewritten; a superseded decision is marked
superseded by a new entry, not edited away. The source's rule — "an architectural decision that is
not an ADR does not exist" — is the standard the log enforces.

## Why this is the memory

Together, the constitution, the shared-context sections, and the decision log are what an agent
re-reads to resume cold after a session ends. Combined with the project state (`07`), they let a new
session reconstruct not just *what* is true but *why* it was decided — which is what keeps a
long-running, multi-agent project coherent instead of drifting.

## Reusable rules (recap)

- One constitution outranks every document and agent; a contradicting doc is a bug, repaired not
  obeyed.
- Every shared-context section has a single primary owner and named required reviewers.
- Each section carries a governance envelope: editors, reviewers, read perms, approval, versioning,
  staleness, conflict path, notifications.
- Approved decisions are append-only in the decision log; supersede, never erase.
- The constitution + shared context + decision log are the durable memory for cold resumption.
