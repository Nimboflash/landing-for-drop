# 14 — Source Traceability Matrix

Every important final decision, traced to its extraction document, the original repository evidence
where available, its classification, confidence, and where it ended up in the deliverable. This is
what makes the reconstruction auditable: no claim floats free of its source.

## Legend

- **Extraction doc** — `EXT/<n>` = analysis doc `n` in the source extraction; `EXT/es/*` = a file in
  `extracted-system/`.
- **Repo evidence** — the original repository path the extraction quoted (`repo:<path>`), or `—` when
  none (Recommended items).
- **Destination** — the framework/blueprint/schema file that carries the decision.

| # | Decision / finding | Extraction doc | Repo evidence | Class | Conf | Destination |
|---|---|---|---|---|---|---|
| 1 | 10-agent roster with owns/never-touches lanes | EXT/03, EXT/04 | `repo:.claude/agents/*.md` | Extracted | high | `framework/02`, `blueprint/01` |
| 2 | No orchestrator; coordination is structural | EXT/06 | `repo:PROMPT.md`, `ROADMAP.md` | Extracted/Missing | high | `framework/05`, `blueprint/03` |
| 3 | Scoped security veto, CTO cannot overrule | EXT/05 | `repo:PROMPT.md#5`, `SECURITY.md` | Extracted | high | `framework/04`, `framework/14`, profile `scoped_veto` |
| 4 | Non-overridable CI; gates over status | EXT/12 | `repo:ci.yml`, `CONTRIBUTING.md` | Extracted | high | `framework/14`, `schemas/quality-gate` |
| 5 | ADR-or-it-doesn't-exist + fired triggers | EXT/06, EXT/25 | `repo:ADR/*`, `.claude/skills/adr` | Extracted | high | `framework/06`, `schemas/decision`(→state decision-log) |
| 6 | Contract-first FE/BE, generated client | EXT/07 | `repo:API_GUIDELINES.md` | Extracted | high | `framework/13`, `schemas/contract` |
| 7 | Interface-as-coordination for parallelism | EXT/06, EXT/07 | `repo:ADR/0002` | Extracted | high | `framework/13`, `framework/15` |
| 8 | Module-owned schemas; ports not JOINs | EXT/02 | `repo:ARCHITECTURE.md`, `ADR/0001-2` | Extracted | high | `framework/15`, `blueprint/10` |
| 9 | Three roadmap phases w/ falsifiable exit gates | EXT/20 | `repo:ROADMAP.md` | Extracted | high | `framework/12`, `blueprint/07` |
| 10 | Target-section deferral pattern | EXT/23, EXT/25 | `repo:*` Target sections | Extracted | high | `framework/12`, `schemas/version` |
| 11 | Three-axis reproducibility (code+model+policy) | EXT/13 | `repo:MODEL_REGISTRY.md`, `DECISION_ENGINE.md` | Extracted | high | `framework/12`, `blueprint/07` |
| 12 | Automation ~37%; 1/21 stages automated | EXT/14 | `repo:ci.yml` | Extracted (method-dep) | medium | `blueprint/06`, `blueprint/00` |
| 13 | No task/handoff/state layer | EXT/07, EXT/08 | search-negative | Missing | high | `framework/07-09`, `blueprint/08`, gap G2 |
| 14 | No release/deploy/rollback tail | EXT/13 | search-negative | Missing | high | `framework/14`, `blueprint/11`, gap G3 |
| 15 | No per-agent tool permissions | EXT/04, EXT/15 | `repo:.claude/agents/*` (no `tools:`) | Missing | high | `framework/15`, gap G1 |
| 16 | Domain gates specified-not-implemented | EXT/12 | `repo:CONTRIBUTING.md` vs `ci.yml` | Extracted/Missing | high | `blueprint/11`, gap G4 |
| 17 | `credit-architect` = Gen-0 seed agent | EXT/24, EXT/20 | `repo:credit-architect.md` | Inferred | medium | `blueprint/01`, `audit/02`, FU-1 |
| 18 | One documented override (stability, joint) | EXT/05 | `repo:SHAP_STABILITY.md` | Extracted | high | `framework/04`, `framework/14` |
| 19 | `credit-architect→domain-policy-architect` rename | EXT/es/README | `repo:credit-architect.md` | Extracted (alias) | high | `framework/02`, `blueprint/01` |
| 20 | `ai-engineer→ml-engineer`, `security-architect→security-engineer` | EXT/es/agents | `repo:*` | Extracted (alias) | high | `framework/02`, `blueprint/01` |
| 21 | Orchestrator/release-manager/etc. additions | EXT/17, EXT/es/agents | — | Recommended | high | `framework/02`, `blueprint/01` |
| 22 | All version/release chronology | EXT/20, EXT/26 | no `.git` | Unverified | n/a | `blueprint/07`, `audit/02`, FU-4 |
| 23 | Human is the real orchestrator/release manager | EXT/03, EXT/06 | implied | Extracted (elimination) | high | `framework/16`, `blueprint/12` |
| 24 | skills-lock pins 40 third-party skills | EXT/es | `mattpocock/skills` | Extracted (external) | high | `audit/00` (noted, out of scope) |

## How to read a row

Take row 3: the scoped veto is asserted in the extraction's authority analysis (`EXT/05`), quoted from
the repo constitution (`repo:PROMPT.md#5`) and security policy (`repo:SECURITY.md`), classified
**Extracted** at **high** confidence, and it lands in three destinations — the framework's authority
and quality docs and the project's `scoped_veto` configuration. Any reader can walk the chain from the
deliverable back to the original repository text. Rows classified **Recommended** (21) or **Unverified**
(22) deliberately have no repo evidence — and are never presented as if they did.
