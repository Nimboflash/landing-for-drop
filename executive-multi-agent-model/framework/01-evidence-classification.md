# 01 — Evidence Classification

**Purpose.** The five-label provenance system and the classified-item block that every other
framework document, schema, and blueprint uses. This is the backbone: it is what keeps proven fact
separate from proposal.

> **Provenance banner.** Reusable / project-independent. This document *defines* the labels the
> banners use.

## The five labels

Every important finding, agent, workflow, architectural conclusion, gap, or recommendation carries
**exactly one** of these classifications.

**Extracted** — Directly supported by recorded repository evidence in the supplied documents. You
can point at a file path and a quote. Example: "the source has ten explicit subagents" is Extracted;
`EXT/03-agent-inventory.md` lists them, each with a repo path.

**Inferred** — Strongly suggested by multiple pieces of evidence, but not explicitly proven. You are
reasoning across several files, and you state the reasoning. Example: "`credit-architect` is a
generation-0 seed agent later disciplined by the constitution" is Inferred — several structural
signals point to it, none states it outright.

**Recommended** — A proposed improvement for the reusable system. It was **not** in the source. This
is the label that protects honesty: a Recommended agent, gate, or workflow is *never* described as
something that existed. Example: the `orchestrator` role is Recommended — the source had no
orchestrator at all.

**Unverified** — Mentioned or suspected, but the evidence is insufficient or contradictory. Example:
any claim about commit order, authorship, branch history, or release dates in a repository captured
without git history is Unverified — no evidence could settle it.

**Missing** — A capability the reusable system needs that was searched for and not found. Example:
the source's task/handoff/project-state layer is Missing; the release/deploy/rollback tail is
Missing. Missing is a finding about the source; the fix for it is usually a Recommended addition.

## The classified-item block

Attach this to every classified item:

```yaml
classification:  # Extracted | Inferred | Recommended | Unverified | Missing
evidence_refs:   # list of EXT/<doc> and repo:<path> pointers, or "none" for Recommended
confidence:      # high | medium | low
notes:           # one line of reasoning, especially for Inferred/Unverified
```

`confidence` is about *how sure you are of the classification and the claim*, independent of the
label. An Extracted fact with a single clear quote is `high`; an Inferred conclusion resting on two
weak signals is `low`. A Recommended item's `evidence_refs` is `none` by definition — it is a
proposal, and pretending otherwise is the failure this whole system guards against.

## What to classify — and what not to

Classify: findings, agents, workflows, responsibilities, authorities, version-history conclusions,
automation claims, quality gates, gaps, and final blueprint components. Do **not** classify ordinary
explanatory prose — a sentence that teaches a concept needs no label, and littering labels over
teaching text drains them of meaning. The test is whether the sentence *asserts something about the
source or proposes something for the reusable system*. If yes, label it; if it is exposition, leave
it.

## Two load-bearing rules

1. **A Recommended item is never presented as extracted behavior.** This is the single most
   important discipline in the framework. It is why the reader can trust the Extracted claims: they
   are not diluted with wishful ones.
2. **Anything requiring git history is Unverified when there is none.** The reference source was
   captured as a working copy with no `.git`, so its entire version and release chronology is
   Unverified by construction. Do not upgrade such claims without new evidence (for example, the
   original `.git` becoming available).

## Mapping from the source extraction's own labels

The prior extraction used a six-label scheme. This framework maps it to the five above so provenance
survives translation:

| Source label | This framework |
|---|---|
| Explicit repository fact | **Extracted** |
| Strong inference | **Inferred** (confidence high/medium) |
| Weak inference | **Inferred** (confidence low) |
| Recommended improvement / addition | **Recommended** |
| Not found | **Missing** |
| Could not verify | **Unverified** |

## How classifications flow downstream

The label chosen here propagates: into the agent roster (`02-canonical-agent-model.md`), the
authority matrices (`04-organization-and-authority.md`), the gaps register
(`projects/<slug>/blueprint/13-gaps-risks-and-improvements.md`), and the traceability matrix
(`projects/<slug>/blueprint/14-source-traceability-matrix.md`). No agent — including the
orchestrator — may rewrite a classification; changing one requires new evidence and a recorded
decision.

## Reusable rules (recap)

- Exactly one of five labels per classified item: Extracted, Inferred, Recommended, Unverified,
  Missing.
- Attach `classification / evidence_refs / confidence / notes` to each.
- Never label ordinary teaching prose; never present Recommended as pre-existing.
- No git history ⇒ chronology is Unverified.
- Classifications are immutable without new evidence and a recorded decision.
