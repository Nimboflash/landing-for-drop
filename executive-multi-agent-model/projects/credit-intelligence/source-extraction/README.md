# Source Extraction — READ-ONLY

This folder is a **pointer** to the original Claude Code extraction that this project audits and
builds on. The extraction is treated as **read-only evidence**: it is never overwritten, never
edited, and never deleted.

## What the original extraction is

A folder named `multi-agent-system-extraction/` produced by a prior Claude Code analysis of the
`credit-intelligence` repository on 2026-07-11. It contains **105 files** (~482 KB):

- 27 numbered analysis documents (`00-executive-summary.md` … `26-version-evidence-index.md`).
- A generalized `extracted-system/` package the prior analysis proposed: 19 agent definitions, 10
  schemas, 20 templates, 16 workflows, 5 organization matrices, 4 examples, and a `skills-lock.json`.
- OS sidecar noise (`__MACOSX/` AppleDouble entries, `.DS_Store`) — excluded from analysis as
  irrelevant.

## Why it is not copied in here

The extraction is large and is the *primary evidence*, not a framework artifact. Copying it into this
repository would (a) risk mixing project-specific evidence into a reusable framework and (b) bloat the
repo. Instead:

- The **audit** (`../audit/`) inventories and classifies it.
- The **blueprint** (`../blueprint/`) applies the framework to it and cites it as `EXT/<doc>` (an
  extraction document) or `repo:<path>` (a path the extraction quoted from the original repository).
- The working **evidence digest** used during reconstruction lives in the build tooling, not in the
  committed repo.

## How to attach the real extraction

To reproduce or extend this analysis, place the original `multi-agent-system-extraction/` folder here
as `source-extraction/original/` (this path is gitignored so the evidence stays local unless you
explicitly choose to commit it). Then re-run the audit method in
`../../../framework/00-source-audit-method.md`.

## Provenance and safety notes

- No secrets were found in the source (verified by the original extraction; gitleaks also ran in its
  CI). Do not introduce any.
- The source had **no git history**, so every commit/branch/tag/release/authorship claim is
  **Unverified** — see `../audit/02-contradictions-and-unverified-findings.md`.
- The extraction is evidence, not automatically-optimal architecture. The framework treats it as
  something to learn from and improve on, with every improvement labeled **Recommended**.
