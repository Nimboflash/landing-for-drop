# 00 — Source-Audit Method

**Purpose.** The reusable discipline for auditing a prior repository extraction *before* building an
organization on top of it. Nothing downstream is trustworthy if this step is skipped or faked.

> **Provenance banner.** Reusable / project-independent. Claims about the source carry
> Extracted / Inferred / Recommended / Unverified / Missing labels. This method was applied to the
> `credit-intelligence` extraction (105 files); the applied result is in
> `projects/credit-intelligence/audit/`.

## Why audit first

An extraction is a *secondary source*: someone (here, a prior Claude Code run) already read a
repository and wrote it up. Generated Markdown is convenient and confidently worded, which is
exactly why it is dangerous. A summary can overstate automation, invent a workflow that was only
aspirational, give one agent three names, or assert a version history that no git log could support.
The audit exists to rebuild a defensible evidence base and to *refuse to optimize before that base
exists*. The rule is blunt: **do not design the improved system until the source audit is complete.**

## Recursive inventory

Walk the whole extraction tree — not just the files with promising names — and record, for each
file, a fixed set of fields:

- relative path
- file type
- file size (when available)
- apparent purpose
- relevance (to the reconstruction)
- read status (fully read / partially read / not read / inaccessible)
- reason when unread
- related topics
- referenced repository evidence (the original repo paths the file cites)
- possible duplication (does another file assert the same thing?)
- possible staleness (does it contradict a newer or higher-precedence file?)

Open and read the contents of every *relevant* file. Do not infer a file's content from its name or
from another document's summary of it. Filenames lie; summaries drift.

## Required coverage

Prioritize files touching the topics that decide how an engineering organization actually runs:
agents and subagents; agent prompts; skills and commands; hooks; orchestration; product
requirements; architecture; versions, releases, and milestones; epics, features, and task
breakdowns; handoffs; shared context; project state; testing; quality gates; security; DevOps;
deployment; release; git history; evidence indexes; deprecation history; human approval; and
failure/retry handling. If a topic has no file, that absence is itself a finding — classify it
**Missing** and record where you looked.

## Handling unreadable and low-value files honestly

Do not claim you read everything when you did not. Record explicitly: binary files that could not be
meaningfully inspected; unsupported formats; corrupted files; empty files; duplicate files;
generated files that add no new evidence; files deliberately excluded as irrelevant; and files that
another document references but that are **missing**. In practice, OS sidecar noise (for example
`__MACOSX/` AppleDouble entries and `.DS_Store`) is excluded as irrelevant and said so, not silently
dropped.

## Coverage map

Summarize the inventory into a coverage map that a reviewer can audit at a glance:

- documents fully read, partially read, not read, inaccessible
- topics covered and topics not covered
- evidence gaps that require additional investigation of the *original* repository (not the
  extraction) — these become follow-up tasks for a tool like Claude Code

The coverage map is where honesty becomes visible. A reconstruction that read 30% of a large
extraction and says so is more useful than one that implies full coverage and is wrong.

## Evidence priority order

When two sources disagree, prefer them in this order, and never treat all generated Markdown as
equally reliable:

1. Original repository file references and evidence indexes (the strongest — a path and a locator).
2. Extracted source excerpts (quoted repo text).
3. Git-history evidence (commits, tags, blame) — **absent here, so anything needing it is
   Unverified**.
4. Configuration and workflow evidence (CI files, hooks, settings).
5. Architecture and implementation findings.
6. Generated summaries (useful, but secondary).
7. Unsupported speculation (lowest; usually discard or mark Unverified).

## What the audit produces

Four artifacts, all under `projects/<slug>/audit/`:

- `00-source-folder-audit.md` — the inventory, read status, coverage map, unread/inaccessible
  files, missing references, topic coverage, and per-finding evidence quality.
- `01-extraction-quality-review.md` — an assessment of the *extraction's* reliability, not just the
  repo's.
- `02-contradictions-and-unverified-findings.md` — the contradiction and evidence-quality tables.
- `03-follow-up-investigation-tasks.md` — implementation-ready tasks for verifying claims against
  the original repository when the extraction alone is insufficient.

## Reusable rules (recap)

- Audit before you optimize; a faked or skipped audit poisons everything downstream.
- Inventory every file with the fixed field set; read the relevant ones for real.
- Absence is a finding — classify unfound capabilities **Missing** and say where you looked.
- Never claim full coverage you do not have; publish the coverage map.
- Rank evidence; git-dependent claims are **Unverified** when there is no git history.
