# 00 — Source-Folder Audit

`framework/00-source-audit-method.md` applied to the `credit-intelligence` extraction. This is the
evidence base; nothing in the blueprint is trusted beyond what this audit supports.

## Inventory summary

The extraction (`multi-agent-system-extraction/`) contains **105 files (~482 KB)**, plus OS sidecar
noise excluded as irrelevant. Structure:

| Group | Count | What it is |
|---|---|---|
| Numbered analysis docs (`00`–`26`) | 27 | The prior analysis of the repo (executive summary, agent inventory, orchestration, quality, versions, evidence indexes). |
| `extracted-system/agents/` | 19 | The prior analysis's *proposed generalized* roster (10 real + 2 inferred + 7 recommended). |
| `extracted-system/schemas/` | 10 | Proposed machine-readable schemas (2 partially extracted, 8 recommended). |
| `extracted-system/templates/` | 20 | Proposed templates (7 extracted patterns, 13 recommended). |
| `extracted-system/workflows/` | 16 | Proposed workflows (12 partially extracted, 4 recommended). |
| `extracted-system/organization/` | 5 | Responsibility, approval, escalation, file-ownership, org-chart matrices. |
| `extracted-system/examples/` | 4 | Illustrative "Acme Boards" YAML instances (fictional, not from source). |
| `extracted-system/README.md` + root `README.md` | 2 | Provenance discipline + reading order. |
| `skills-lock.json` | 1 | A lockfile pinning 40 third-party skills from `mattpocock/skills` (external; not part of the repo). |
| Excluded | — | `__MACOSX/` AppleDouble sidecars, `.DS_Store` — OS noise, irrelevant. |

## Read status

| Status | Count | Which |
|---|---|---|
| Fully read (directly) | ~15 | `README`, `00`, `03`, `04`, `05`, `06`, `07`, `08`, `12`, `15`, `17` analysis docs; `task.schema.yaml`; several written schemas/templates cross-checked. |
| Fully read (via structured digest) | ~40 | `01`, `02`, `09`–`11`, `13`, `14`, `16`, `18`–`26`; all `extracted-system/agents`, `schemas`, `organization`, `workflows`, `templates`, `examples`; `skills-lock.json`. A dedicated pass digested each with citations. |
| Partially read | ~10 | Some `extracted-system/workflows/*` and `templates/*` were surveyed for name + one-line purpose rather than full text (their content is derivative of the extracted patterns). |
| Not read (excluded as irrelevant) | ~40 | `__MACOSX/*` AppleDouble sidecars and `.DS_Store` files — binary/OS metadata with no analytic value. |
| Inaccessible / corrupted | 0 | None. |

Honesty note: this audit does **not** claim every byte of every workflow/template was read verbatim.
The load-bearing analysis docs and the full agent/schema/organization inventories were read; the
derivative workflow/template prose was surveyed. This is stated rather than hidden.

## Coverage map

- **Topics fully covered:** agent roster and definitions; organization and authority; orchestration
  (its absence); collaboration and handoffs (their absence); task/state management (its absence);
  quality/testing/security; PRD-to-production intent; automation assessment; strengths/risks/gaps;
  reusability; the proposed reusable system; version/phase model; evidence indexing.
- **Topics covered with known limits:** version and release *history* — covered as design, but all
  chronology is **Unverified** because the working copy had no `.git`.
- **Topics not present in the source (findings, not omissions):** an orchestrator artifact; a
  task/handoff/state layer; a release/deploy/rollback pipeline; per-agent tool permissions; an
  assumption register. Each is classified **Missing** with the search recorded.
- **Evidence gaps needing original-repo access:** commit/branch/tag history; authorship and decision
  dates; true file-write order; CI run history. These become follow-up tasks (`03-...`).

## Evidence quality per major finding

| Finding | Classification | Evidence quality | Safe to reuse |
|---|---|---|---|
| 10 explicit agents with owns/never-touches lanes | Extracted | High (each has a repo path) | Yes |
| No orchestrator; coordination is structural | Extracted / Missing | High | Yes |
| Scoped security veto the CTO cannot overrule | Extracted | High (`PROMPT.md §5`, `SECURITY.md`) | Yes |
| Non-overridable CI gates; gates-over-status | Extracted | High (stated in 4 places) | Yes |
| No task/handoff/state layer | Missing | High (search-negative, attested) | Yes (as a gap) |
| No release/deploy/rollback tail | Missing | High | Yes (as a gap) |
| `credit-architect` is a Gen-0 seed agent | Inferred | Medium (structural signals) | With the label |
| Automation ~37%; 1/21 stages automated | Extracted (method-dependent) | Medium | With the caveat |
| Any version/release chronology | Unverified | None (no git history) | No — do not assert |

## Missing referenced evidence

The source analysis referenced repo artifacts that do not exist as files in the working copy: a
Docker Compose file (named as the Phase-1 runtime), Alembic migrations, and an OpenAPI document — all
"docs ahead of the toolchain," classified **Missing** in the source and preserved as Missing here.

## Reusable takeaway

The extraction is a strong, self-consistent, honestly-labeled secondary source. Its own provenance
discipline (Explicit fact / inference / recommendation / not found / could-not-verify) mapped cleanly
onto the framework's five labels, which is why this audit could reuse it with confidence rather than
re-deriving everything from the original repository — while still flagging exactly where original-repo
access would be required to upgrade an Inferred or Unverified claim.
