# 13 — Gaps, Risks, and Improvements

Every gap in the `credit-intelligence` system, ranked. Severity is `critical | high | medium | low`.
Each carries a classification, evidence, impact, a recommended solution, the responsible role, and an
implementation priority. This register mirrors `../state/risk-register.yaml`.

## G1 — No per-agent technical permissions

- **Description:** All ten agents inherited full tool access; lanes and the veto were *normative*, not
  *technical*. No `tools:` frontmatter, no CODEOWNERS, no branch protection.
- **Classification:** Missing (the enforcement) / Extracted (the gap). **Confidence:** high.
- **Evidence:** `EXT/04-agent-definitions.md`, `EXT/15-strengths-risks-and-gaps.md` (R1);
  `repo:.claude/agents/*` (no `tools:` key).
- **Impact:** A misled or misbehaving agent can edit any file, "merge," or touch the data boundary
  regardless of its lane. The lanes are honor-system.
- **Severity:** **critical**.
- **Recommended solution:** per-agent tool/path allowlists in agent definitions; CODEOWNERS and
  branch protection generated from the file-ownership matrix.
- **Responsible role:** `devops-engineer` + `cto`. **Priority:** P0 (before any autonomous use).

## G2 — No task / handoff / project-state layer

- **Description:** No task objects, no handoff artifacts, no state file. Work was proposed
  conversationally and left no trace.
- **Classification:** Missing. **Confidence:** high.
- **Evidence:** `EXT/07-collaboration-and-handoffs.md`, `EXT/08-task-and-state-management.md`.
- **Impact:** Multi-session, multi-agent work loses everything not in a doc or diff; duplicate or
  divergent work is undetectable; nothing resumes.
- **Severity:** **high**.
- **Recommended solution:** the framework's `task`, `handoff`, and `project-state` schemas, with
  gates-over-status preserved.
- **Responsible role:** `orchestrator` (Recommended). **Priority:** P0.

## G3 — No release / deploy / rollback / post-release tail

- **Description:** No deploy job, Dockerfile, compose, environments, or IaC; "always-releasable
  `main`" had nowhere to release to.
- **Classification:** Missing. **Confidence:** high.
- **Evidence:** `EXT/13-git-devops-and-release.md`, `EXT/14-automation-assessment.md` (stages 18–21 = 0).
- **Impact:** The entire delivery half is unbuilt; no path from merged code to running product.
- **Severity:** **high**.
- **Recommended solution:** a `release-manager` role plus release/deploy/rollback/post-release
  workflows behind human approval.
- **Responsible role:** `release-manager` + `devops-engineer` (Recommended). **Priority:** P1.

## G4 — Domain gates specified but not implemented

- **Description:** The celebrated leakage/replay/stability/monotonicity/fairness/calibration gates are
  documented with named enforcing agents but not wired into CI.
- **Classification:** Extracted (the split) / Missing (as CI). **Confidence:** high.
- **Evidence:** `EXT/12-quality-testing-and-security.md` (implemented-vs-specified table).
- **Impact:** Verification theater — a reader can mistake specified for enforced; the decision-path
  correctness the product depends on is unguarded.
- **Severity:** **high**.
- **Recommended solution:** implement the four+ gates as CI jobs *before* the first model ships.
- **Responsible role:** `qa-engineer` + `ml-engineer` + `security-engineer`. **Priority:** P1.

## G5 — No orchestrator / dynamic coordination

- **Description:** Coordination was structural and human; no scheduler, no assignment mechanism, no
  retry path.
- **Classification:** Missing. **Confidence:** high.
- **Evidence:** `EXT/06-orchestrator-analysis.md`.
- **Impact:** All sequencing routes through one unnamed human; nothing tracks stalls or retries.
- **Severity:** **medium** (the structural design partly compensates).
- **Recommended solution:** the Recommended `orchestrator` (coordination only, no authority).
- **Responsible role:** `orchestrator`. **Priority:** P1.

## G6 — Stale seed-agent prompt vs constitution

- **Description:** `credit-architect.md` carries an ungated Target stack and a multi-role persona that
  contradict the constitution's phase discipline.
- **Classification:** Extracted (tension) / Inferred (cause). **Confidence:** high / medium.
- **Evidence:** `EXT/11-prompts-skills-and-instructions.md`, `EXT/24-agent-evolution-by-version.md`.
- **Impact:** An agent loading it can be steered into building ahead of the roadmap.
- **Severity:** **medium**.
- **Recommended solution:** rewrite to the nine-agent format and clamp to the policy lane (done in the
  reusable `domain-policy-architect`).
- **Responsible role:** `cto` + `domain-policy-architect`. **Priority:** P2.

## G7 — Divergent dependency denylists

- **Description:** The domain-purity hook and the CI layering test disagree on the forbidden-import
  list.
- **Classification:** Extracted. **Confidence:** medium.
- **Evidence:** `repo:.claude/hooks/domain-purity.sh` vs `repo:tests/test_layering.py`.
- **Impact:** Drift between two enforcement points; the hook can pass what CI later blocks.
- **Severity:** **low**.
- **Recommended solution:** a single shared denylist constant both consume (see FU-3).
- **Responsible role:** `devops-engineer`. **Priority:** P3.

## G8 — No assumption register / missing-requirement detection

- **Description:** Assumptions were captured only as ADRs; no register, no systematic missing-
  requirement detection.
- **Classification:** Missing. **Confidence:** high.
- **Evidence:** `EXT/09-prd-to-product-workflow.md` (steps 4, 23).
- **Impact:** High-risk assumptions can go to build without human sign-off.
- **Severity:** **medium**.
- **Recommended solution:** an assumption register in shared context; high-risk assumptions gated on
  human approval.
- **Responsible role:** `product-manager` + `orchestrator`. **Priority:** P2.

## Priority summary

- **P0 (before autonomous use):** G1 (permissions), G2 (task/state/handoff).
- **P1:** G3 (release tail), G4 (domain gates in CI), G5 (orchestrator).
- **P2:** G6 (seed prompt), G8 (assumption register).
- **P3:** G7 (denylist).
