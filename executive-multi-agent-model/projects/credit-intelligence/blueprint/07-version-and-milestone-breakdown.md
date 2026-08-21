# 07 — Version and Milestone Breakdown

**Purpose.** Reconstruct `credit-intelligence`'s three roadmap phases as versions under the
framework's version model, then show the full planning hierarchy applied to the one phase with real
detail (Phase 1).

> This document applies the version-and-milestone framework (`framework/12-version-and-milestone-model.md`)
> to the credit-intelligence EVIDENCE. It reconstructs, it does not invent: every phase, gate, and
> exclusion below is what the source repository actually wrote down.

## Zero shipped, all chronology unverified

Before the breakdown: `credit-intelligence` shipped **zero versions**. Package version stayed at
`0.1.0`; `src/` is an empty hexagonal skeleton; there is **no `.git`** (`git rev-parse` fails), so no
commit, branch, tag, or date claim below can be verified against history — every date, "first,"
"then," or ordering claim in this document is **Unverified**, evidenced only by file content and ADR
cross-citation (0002 cites 0001; 0003 cites both — Inferred authorship order). The three phases are
not observed increments; they are the plan the repository declares for increments that have not yet
happened. — *Classification: Unverified (chronology). Evidence: EXT/20-version-release-history.md,
EXT/26-version-specific-evidence.md V1–V3. Confidence: high (absence itself is well-evidenced).*

## The 3 roadmap phases reconstructed as versions

The source's "version system" was three roadmap phases, sequenced by **data access and legal risk**,
not by feature count or date. — *Classification: Extracted. Evidence: EXT/20, repo:ROADMAP.md.
Confidence: high.*

### Version 1 — Foundation

- **Objective**: one partner, one loan tape, one explainable decision.
- **Exit gate (single, falsifiable)**: "A design partner says: run this on our next cohort." This is
  externally observable — a partner's statement, not an internal completion checklist.
- **Included scope**: the Decision API end to end for one tenant — ingest one loan tape, compute
  features, produce a calibrated decision, explain it, log it durably.
- **Excluded scope — "do not negotiate back in"**: federated learning, consortium data-sharing,
  multi-tenancy, billing, admin console, mobile SDKs, Kafka, Kubernetes, ClickHouse, microservices.
  Each of these has a named future trigger (§ below) and none has fired.
- **Agent assignments**: all 10 real agents are active in Phase 1 — `cto` (architecture, boundary
  authority), `product-manager` (scope, roadmap), `credit-architect`/`domain-policy-architect`
  (decision/policy logic), `ai-engineer`/`ml-engineer` (model + features), `data-engineer` (ingestion
  substrate), `backend-engineer` (Decision API, audit log), `frontend-engineer` (partner-facing
  surface), `devops-engineer` (CI, eventual Compose deploy), `security-architect`/`security-engineer`
  (data-boundary veto, pre-build review), `qa-engineer` (gates).
- **Quality gates**: CI (`format`, `lint`, `mypy`, `pytest`) plus `secrets` (gitleaks), plus the
  layering test — all Extracted and implemented. The four domain gates (leakage, replay, stability,
  monotonicity) are named in `MODEL_REGISTRY.md` but are **specified, not implemented** (see `11`).
- **Deferred work and forcing trigger**: module→service extraction triggers on 2nd tenant /
  independent-scaling need / team > 6 (`ADR/0001`); in-process events → Kafka triggers on a 2nd
  consumer (`ADR/0003`); Postgres → +ClickHouse triggers on OLTP p99 degradation or log table > ~50M
  rows; Compose → K8s triggers on > 3 deployable units; single-tenant → federated + differential
  privacy triggers on a Type 2 licence being granted (a legal trigger, not a technical one). — *Classification:
  Extracted. Evidence: EXT/25-build-architecture-evolution.md, repo:ADR/0001, repo:ADR/0003. Confidence: high.*

### Version 2 — AI

- **Objective**: production platform plus an outcome flywheel (the platform's own originated outcomes
  start improving the model).
- **Exit gate**: "Our own originated outcomes measurably improve the model, and a 2nd partner has
  signed."
- **Included scope**: whatever moves the model from static to outcome-fed, plus onboarding a 2nd
  partner (which itself fires the multi-tenancy and 2nd-consumer triggers deferred from Version 1).
- **Excluded scope**: consortium data-sharing is still explicitly out.
- **Agent assignments**: same 10-agent roster; per `EXT/24-agent-evolution.md`, responsibilities
  tighten rather than the roster growing — `qa-engineer` gains fairness/champion-challenger duties,
  `devops-engineer` gains K8s/Terraform (now trigger-fired), `ai-engineer` gains federated-training
  groundwork, `security-architect` gains differential-privacy sign-off. No orchestration upgrade is
  planned in the source docs at any phase — that gap is exactly what this framework's `orchestrator`
  role (Recommended) fills.
- **Quality gates**: same CI floor, plus whichever domain gates get promoted from paper to CI (a
  Recommended sequencing choice — see `11`); model-promotion gates gain real enforcement.
- **Deferred / forcing trigger**: consortium learning remains gated on Version 3's legal trigger.

### Version 3 — Partners

- **Objective**: a shared learning layer across partners.
- **Exit gate**: "Type 2 licence granted, and 2+ partners training against a shared model without raw
  records leaving their boundaries."
- **Included scope**: federated/consortium training infrastructure — now justified because its
  trigger (the licence) has fired.
- **Excluded scope**: none stated at this horizon in the source.
- **Agent assignments**: same 10, further specialized per the Version 2 pattern.
- **Quality gates**: full domain-gate suite expected to be enforced by this point; this is the
  version where "specified, not implemented" would no longer be tolerable.
- **Deferred / forcing trigger**: none named beyond Version 3 — the source's roadmap stops here.

All three exit gates, exclusion lists, and triggers above are — *Classification: Extracted. Evidence:
EXT/20-version-release-history.md (phase table), EXT/24-agent-evolution.md, repo:ROADMAP.md,
repo:cto.md (migration-trigger table). Confidence: high.*

## The reusable planning hierarchy, applied

Product → Release strategy → Version → Milestone → Epic → Feature → Story → Task, per
`framework/12-version-and-milestone-model.md`. The source only reached the **lane** level — below
that, `EXT/22-product-breakdown-structure.md` records "milestones-as-artifacts, epics, stories, tasks
— Not found." Applying the full hierarchy to Version 1:

- **Product**: credit-intelligence (AI credit-underwriting engine).
- **Release strategy**: phase-gated, sequenced by data-access and legal risk (Extracted principle).
- **Version**: Version 1 — Foundation (above).
- **Milestones** (Recommended decomposition of Version 1's single critical path — the source names
  ONE critical-path item and marks the rest "parallelizable and, if necessary, cuttable" —
  *Classification: Extracted for the critical-path/parallelizable split; Recommended for naming these
  as discrete milestones*): M1 ingest one loan tape (critical path — everything depends on data
  existing); M2 feature computation; M3 decision + explanation; M4 partner-facing surface; M5 CI +
  observability baseline.
- **Epics**: one per Phase-1 module (ingest, features, decision, explain) — the nearest the source
  gets to an epic-shaped artifact is the module's own governance doc (e.g. `docs/api/decision-api.md`
  functions as the Decision epic).
- **Features / Stories / Tasks**: Recommended — the source has no instances of any of these; the
  schemas (`epic.schema.yaml`, `task.schema.yaml`) supply the shape.

## The Target-section deferral pattern (Extracted)

The source's genuinely novel planning invention: deferred work is written **into the same governance
doc** as the current-phase work, under a "Target" section, each entry tagged with the trigger that
would pull it back in. This makes deferral visible (you see what's NOT being built and why) and
reversible (the trigger condition is written down, not re-litigated from memory). Example: `02` (tech
stack doc) marks Kafka, K8s, ClickHouse, Feast, OTel all as "Target [planned]" next to their Phase 1
counterpart, each with its firing condition. This framework generalizes the pattern into
`version.schema.yaml`'s `excluded_scope`/`deferred_work` fields. — *Classification: Extracted.
Evidence: EXT/23-requirement-decomposition.md Q12, repo:02 (tech stack table). Confidence: high.*

## The 3-axis reproducibility pattern, pinned per decision

Every decision this roadmap eventually produces should pin three independently versioned axes — code
(git SHA, once git exists), model (MLflow registry, sha256-addressed, never overwritten), and policy
(`policy_version` on the decision object) — plus a feature-vector hash, so any historical decision is
reproducible to an exact quadruple. The source calls this "release management as reproducibility
engineering, not ship ceremony," and it is the standard this project's release gate (`11`) should hold
every Version 1+ decision to. — *Classification: Extracted. Evidence: EXT/13-git-devops-release.md
(versioning table), repo:DECISION_ENGINE.md. Confidence: high.*

## Reusable rules (recap)

- A version here is a falsifiable, externally observable exit gate plus an explicit "do not negotiate
  back in" list — not a date or feature count.
- Phases are sequenced by risk (data access, legal exposure), matching this project's own stated
  principle: "do the thing that could kill the company first."
- The full Product→Task hierarchy is supplied by the framework below the phase/lane level the source
  actually reached; treat epics/stories/tasks here as Recommended scaffolding, not reconstructed fact.
- Deferred scope is never silently dropped: it lives in a Target section (or `deferred_work`) with its
  firing trigger, and moves into a version's included scope only when that trigger fires.
- Pin code + model + policy (+ feature-vector hash) to every decision this system produces, from
  Version 1 onward.
