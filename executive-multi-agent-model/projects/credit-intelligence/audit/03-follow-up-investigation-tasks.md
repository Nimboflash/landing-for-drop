# 03 — Follow-Up Investigation Tasks

Implementation-ready tasks for a tool with access to the **original repository** (not just the
extraction). Each would upgrade or refute a currently Inferred/Unverified finding, or close a Missing
gap. They are written so an agent can execute them directly.

## FU-1 — Verify the `credit-architect` seed-agent hypothesis

- **Goal:** Upgrade or refute the Inferred claim that `credit-architect` is a generation-0 seed agent.
- **Requires:** the original `.git` directory.
- **Steps:** `git log --follow --diff-filter=A -- .claude/agents/*.md` to get creation order; compare
  the authored date of `credit-architect.md` against the other nine; `git log -p -- PROMPT.md` to see
  whether §4–5 (legal collision + veto + phase gating) post-date the seed file.
- **Evidence to capture:** creation timestamps, author, and whether the constitution's disciplining
  language was added after the seed.
- **Outcome:** reclassify from Inferred(medium) to Extracted or refuted; update
  `blueprint/01-canonical-agent-inventory.md` and `audit/02`.

## FU-2 — Confirm which domain gates are actually enforced

- **Goal:** Resolve the "specified vs implemented" split for the leakage/replay/stability/monotonicity/
  fairness/calibration gates.
- **Requires:** the original repo's `.github/workflows/`, `tests/`, and any model-CI config.
- **Steps:** grep CI configs and test suites for each gate's implementation; check whether a test file
  or CI job actually runs it versus only a doc naming it.
- **Outcome:** update `blueprint/11-quality-security-and-release-gates.md` with the true
  implemented/specified split; adjust the profile's `gates` block accordingly.

## FU-3 — Reconcile the two dependency denylists

- **Goal:** Establish the single source of truth for the domain-purity denylist.
- **Requires:** `repo:.claude/hooks/domain-purity.sh` and `repo:tests/test_layering.py`.
- **Steps:** diff the two forbidden-import lists; determine which is authoritative; recommend a shared
  constant both consume.
- **Outcome:** a remediation task in the risk register (R7) with a concrete fix.

## FU-4 — Recover version and release chronology (if `.git` becomes available)

- **Goal:** Replace Unverified chronology with evidence.
- **Requires:** the original `.git`.
- **Steps:** `git log --oneline --all`, `git tag`, `git for-each-ref`; reconstruct ADR authoring order
  from commit dates; check whether any migration trigger fired.
- **Outcome:** upgrade `blueprint/07-version-and-milestone-breakdown.md`'s Unverified rows; without
  `.git`, this task remains open and the rows stay Unverified.

## FU-5 — Confirm the absence findings against the live repo

- **Goal:** Re-verify the Missing capabilities (orchestrator, task/handoff/state, release tail,
  per-agent tool permissions, assumption register) against the current repository, in case they were
  added after the extraction snapshot.
- **Requires:** the current original repository.
- **Steps:** search for `.claude/agents/orchestrator*`, any `tasks/`/`state/`/`handoffs/` directory,
  `tools:` keys in agent frontmatter, `CODEOWNERS`, branch-protection config, and a deploy job.
- **Outcome:** confirm the gaps still hold, or downgrade any that have since been filled; update
  `blueprint/13-gaps-risks-and-improvements.md`.

## FU-6 — Validate that no secrets exist before any commit of source evidence

- **Goal:** Ensure the read-only extraction can be safely stored if the human chooses to commit it.
- **Requires:** the extraction folder.
- **Steps:** run a secret scanner (e.g. gitleaks) over the extraction; confirm the source's
  "no secrets found" attestation still holds.
- **Outcome:** a go/no-go for committing `source-extraction/original/`; default remains gitignored.

## How these feed the loop

Each task names its trigger, its required evidence, and the exact blueprint/audit file it would
update. Running them is how a rerun (`framework/17-...` idempotency rules) upgrades the reconstruction
without regenerating it: a finding moves from Inferred/Unverified/Missing to Extracted or resolved,
the affected conclusions are marked stale and re-evaluated, and the change is logged. Until then, the
current classifications stand exactly as recorded.
