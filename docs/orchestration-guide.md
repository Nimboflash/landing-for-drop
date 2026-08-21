# Orchestration Guide — Running Phase 0 with Agents

**Status of the project:** `DESIGNED, NOT READY FOR EXECUTION`. Tickets 01–04 are the four start
preconditions and nothing downstream of them may begin. This guide describes how to run the work once
they are met; it does not authorise starting.

**Precedence, in this order.** Where two documents disagree, the higher one wins and the lower one is a
bug to be repaired:

1. The **governance state machine** (M11, tickets 05/06) — what is *authorised right now*.
2. [`docs/phase-0-preregistration.md`](./phase-0-preregistration.md) — the frozen protocol.
3. [`docs/spec-amendments.md`](./spec-amendments.md) and
   [`docs/decision-engine-addendum.md`](./decision-engine-addendum.md).
4. [`docs/prd.md`](./prd.md) and [`docs/tickets/`](./tickets/) — derived, and paraphrase the above.
5. This guide — operating procedure only. It has no authority over any experimental parameter.

The VSO framework at `/Users/nimaalishahi/wallet/executive-multi-agent-model/` supplies the schemas,
handoff protocol, gate model and file-ownership rules referenced throughout. It is a global,
read-mostly layer; per-project configuration belongs in `projects/wallet-phase-0/`.

**Evidence discipline.** Following `framework/01-evidence-classification.md`, anything below that is a
proposal rather than a rule taken from the source documents is marked **(Recommended)**. Those are the
items an operator may change without breaking the protocol. Everything unmarked is derived from the
pre-registration, the addendum, the PRD or the ticket list, and changing it changes the experiment.

---

## 1. Which VSO roles this project needs, and which it does not

### 1.1 The four real roles, and where they land

The pre-registration (§15.1) names four roles — Product/Research Owner, Primary Builder, a part-time
Research/Data Support, and the Independent Validator. The addendum (§2) adds two more actors that
§15.1 does not: the Operations Administrator, and the Experiment Governance Module, which is not a
person at all. The mapping onto VSO is not one-to-one, and the mismatches are the interesting part.

| Project role | VSO mapping | Notes |
|---|---|---|
| **Research Owner** | `human:research-owner` **and** `product-manager` | One person wearing both hats. Do not split them into a human and an agent that negotiate — there is only one owner, so a negotiation between the two manufactures a disagreement that does not exist and gives the agent half a decision it does not hold. The `product-manager` agent lane exists only to *draft* scope, version records and decision-ready summaries for the Owner to sign. Every signature in tickets 08, 09, 10, 11, 41, 43 is the human. |
| **Primary Builder** | `backend-engineer` (default implementation lane), absorbing `data-engineer` | One lane, one agent at a time. See §5 for why this lane is never fanned out. |
| **Independent Validator** | **no VSO role fits** — see §1.3 | Not `code-reviewer` (which reads the builder's code — forbidden here). Not `qa-engineer` (which verifies the builder's artefacts against the PRD). The validator *reimplements from raw chain data*. VSO has no reimplementer. |
| **Operations Administrator** | `devops-engineer`, heavily narrowed | Holds `HALT`. Its `prohibited_actions` must explicitly include every write to a research artefact, matching PRD story 102: an operational action can never become a research decision. |
| **Research / Data Support** | folded into the validator lane | Part-time: golden-set tracing, documentation, coverage audits. In practice this is the per-account fan-out described in §5. |
| **Experiment Governance Module (M11)** | **not an agent at all** — see §1.3 | Enforcement, not reasoning. VSO's own agent-design restraint says so. |

### 1.2 The rest of the roster

**Active, with a real job:**

- `orchestrator` — but with *less* authority than VSO's default. It schedules, tracks and dispatches;
  the governance module tells it what is authorised. It is also the single most dangerous contamination
  vector in the project (§2.4).
- `cto` — thin but load-bearing. Its three jobs here: adjudicate file-ownership disputes across the
  independence wall, be the terminus for "untestable as designed", and settle the framework's own known
  inconsistency (`integration` before or after `implementation_review`). **Decide it once:** use the
  schema ordering — `implementation_complete → implementation_review → qa → …`, with `integration`
  under orchestrator scheduling. Record it in the project blueprint before wiring any validator.
- `qa-engineer` — owns the golden-set harness gate and the known-answer battery gate. It does **not**
  write the golden set; the validator does. QA owns *what blocks*.
- `code-reviewer` — standing independent reviewer of the builder's code. **It sits on the builder side
  of the independence wall by construction.** It may never be the Independent Validator and its findings
  may never travel into the validator lane.
- `security-engineer` — holds the one scoped veto. Named question for this project:

  > **`scoped_veto.question`:** *Does any Phase 0 artefact, signal, wallet allocation or ranking reach
  > any third party before the legal and licensing review is complete?*

  This is the right choice because it is the one question where being wrong is existential rather than
  expensive: the moment output reaches a customer it is investment advice (PRD stories 123–125,
  pre-registration §12.1). It must be consulted **before** the vendor data acquisition of ticket 12 and
  before any output surface is built, not after. A veto without an `offered_alternative` is an invalid
  instance.
- `documentation-engineer` — **on**, contrary to what a small internal tool would normally justify.
  There are five governing documents, 44 tickets and a twelve-item freeze manifest, and the whole design
  turns on documents not drifting from the pre-registration. Its scope here is narrow: freeze-manifest
  completeness and document-precedence enforcement.

**Off, and why:**

| Role | Why off |
|---|---|
| `frontend-engineer`, `ux-design-system` | No user interface exists in Phase 0. The customer interface is explicitly out of scope. |
| `product-owner` | One owner. Splitting strategy from execution invents a second decision-maker. |
| `release-manager` | **There is no release.** The terminal artefact is a decision record (ticket 43) bound to a manifest hash. Its authority belongs to the governance module and the Research Owner. Inserting a release-manager here would create a role that could plausibly be asked to interpret a gate result — precisely the thing PRD story 100 forbids. |
| `ml-engineer` | There is no model. The pipeline is deterministic accounting plus a resampling null. Activating an ML lane invites feature engineering into a frozen protocol. |
| `database-engineer` | Fold into the builder lane. The store is a warehouse pull plus local artefacts; there is no migration programme. |
| `software-architect` | Folds into `cto`. The architecture is dictated by the M1–M12 module map and the binding pipeline ordering; there is very little left to architect. |
| `domain-policy-architect` | **The most interesting omission.** Its VSO job is owning thresholds and business-rule policy. In this project that authority has been deliberately removed from every agent and vested in a frozen document plus a machine that refuses writes to it. There is no agent that owns a threshold. That is the design. |
| `test-automation-engineer` | The suite is the known-answer battery and the golden harness, both frozen before the pipeline exists. There is no suite to grow. |

**Profile:** `data_or_ai + high_risk`, with `release-manager: off`, all thirteen `human_approvals: true`,
`domain_correctness: { enabled: true, blocking: true }`, and `retry.max_review_retries: 2` — but see
§1.3 on why the retry policy must be set per lane.

### 1.3 Three things this project needs that VSO does not name

**(a) A reimplementer.** Every VSO reviewer reads the artefact under review. The Independent Validator
must produce its answer *without* reading it. Add a **Recommended** agent record:

```yaml
canonical_id: independent-validator
classification: recommended_addition
lifecycle_status: active
mission: >
  Derive expected outputs from raw chain data and the frozen specification only,
  through an implementation path that shares no classification, FIFO, or valuation
  function with the builder, and record the reasoning before any comparison.
prohibited_actions:
  - read any file in the builder worktree
  - import, vendor, or transcribe any builder function
  - revise a sealed expected output after the builder's result is revealed
  - assert EXTERNALLY REVIEWED without a completed ticket-37 human review
veto_authority: { scope: [] }      # NOT a veto — see below
```

Its power to block the main test is a **quality gate**, not a veto:

```yaml
id: independent-validation
owner: independent-validator
independent_from: [backend-engineer, code-reviewer, cto]
pass_criteria: "validation_status in (MACHINE-INDEPENDENT, EXTERNALLY REVIEWED)"
failure_behavior: "governance module refuses MAIN_TEST_EXECUTED"
blocking: true
override_authority: none
```

This matters. VSO permits exactly one agent to hold a non-empty `veto_authority.scope`, and that is the
security-engineer. Modelling the validator's block as a gate with falsifiable, pre-registered
pass criteria keeps the one-veto invariant intact *and* is a better fit: a gate is mechanical, a veto is
discretionary, and PRD story 100 exists to remove discretion.

**(b) A machine authority above every agent.** The Governance Module outranks the orchestrator on
dispatch, outranks the CTO on ordering, and cannot be overruled by a human approval — an Operations
Administrator may `HALT` but may not mutate. VSO has no class for this. Implement it as a **validator
plus hooks**, never as an agent, following the framework's own restraint rule: enforcement is a
deterministic workflow, not a reasoning role. Its state is the authoritative answer to "where are we";
`project-state.yaml` is coordination only, and where they disagree the module wins.

**(c) A sealed handoff and a void-the-run status.** Two gaps in the schemas:

- VSO's handoff carries content from sender to receiver. Here the validator must commit its answer
  *before* the builder's answer is revealed. That is a **commit-then-reveal** two-phase handoff (§2.3).
  It also needs a field VSO lacks: **`forbidden_inputs`** — the paths this receiver must not read.
- VSO has rework, rollback and deferral, but nothing that voids an entire version's evidence. Add
  `run_status: INVALIDATED` to project state (§3.3), append-only, never edited back.

**One more mismatch, and it is a trap.** VSO's retry loop (`max_review_retries: 2`, then escalate) is
correct for tickets 19–35 and *actively dangerous* for tickets 40–43. Ticket 42 runs the main test
**once**. A "retry" on ticket 42 is not a retry — it is an invalidation. Set the retry policy per lane:
build lane retries; execution lane has `max_review_retries: 0` and any failure routes to §3.3.

---

## 2. The independence constraint, and how to enforce it structurally

This is the section that decides whether any number the project produces is worth anything.

### 2.1 What the constraint actually requires

From pre-registration §9.5, addendum §3, PRD stories 88–90, and ticket 36:

1. The validator did not write the classification, FIFO, or valuation logic.
2. The validator uses a **separate implementation path** and reuses none of the builder's functions.
3. The validator derives expected outputs from **raw chain data and the specification only** — never
   from the builder's code, intermediate artefacts, or output.
4. The validator produces those outputs **before** seeing the builder's results, and records its
   reasoning before comparison, with audit-log timestamps that support the ordering.
5. The validator joins in **week 1** and builds or approves the golden set before the pipeline is
   complete. A validator brought in at the end to sign a report is not independent validation.
6. Status is stated as `MACHINE-INDEPENDENT` | `EXTERNALLY REVIEWED` | `NOT INDEPENDENT`, never assumed.
   `NOT INDEPENDENT` blocks the main test *through the governance module*, not through a note.

Four separations follow: **code**, **source**, **context**, and **time**. Three of them are easy to
enforce and one of them is where projects actually fail.

### 2.2 Code and source separation

**Two worktrees, two branches, disjoint file sets.**

```
/Users/nimaalishahi/wallet              branch: builder/main     lane: builder
/Users/nimaalishahi/wallet-validator    branch: validator/main   lane: validator
```

```bash
git worktree add /Users/nimaalishahi/wallet-validator -b validator/main
```

Rules, in decreasing order of how much they actually protect you:

1. **CI dependency-graph check (the real guarantee).** The validator package declares zero import edges
   into the builder package. This is a static check on committed code; it survives any agent
   misbehaviour, any harness configuration, and any future session. It is the only control on this list
   that a reviewer can verify from the repository alone.
2. **CODEOWNERS and branch protection**, generated from the file-ownership matrix. The builder cannot
   merge into validator paths and vice versa. `git log --name-only` across the two branches must show no
   file touched by both lanes.
3. **A `PreToolUse` hook** denying `Read`/`Grep`/`Glob` on builder source paths from a validator-lane
   session, and on validator expected-output paths from a builder-lane session. Deny wins over allow
   (VSO file-ownership invariant). This is defence in depth, **not** the guarantee — it only holds
   inside the agent harness.
4. **A declared shared surface, written down.** The constraint names three things — classification,
   FIFO, valuation. It does not forbid both lanes from calling an Ethereum node. Draw the line
   explicitly and record it in the validation report:

   ```
   PERMITTED SHARED SURFACE   raw transport only — RPC/receipt/log/trace bytes as returned by the node
   FORBIDDEN SHARED SURFACE   anything that interprets those bytes: swap decoding, transfer filtering,
                              ETH/WETH normalisation, endpoint detection, lot matching, marking,
                              dead-pool tests, token-age derivation
   ```

   Ticket 13's raw-chain reader sits exactly on this line. **(Recommended)** give ownership of it to the
   validator lane and let the builder maintain its own transport, so that the shared surface is zero
   rather than thin. If it is shared, its file paths are enumerated in the validation report and any
   change to it re-opens the independence question.

**The failure mode this prevents is not theft, it is convenience.** Nobody sets out to import the
builder's FIFO. What happens is that a helper labelled "utility" starts by parsing a log and ends up
normalising ETH and WETH, and by then both lanes depend on the same wrong assumption. The enumerated
forbidden surface exists so that this is a reviewable diff rather than a judgement call.

### 2.3 Time separation: commit-then-reveal

The mechanism is a two-phase handoff.

**Phase 1 — seal.** The validator writes, on `validator/main`:

```
validator/expected/<account>.json     the expected outputs
validator/reasoning/<account>.md      the derivation, written before any comparison
```

and commits. The governance module records the commit hash and the tree hash of `validator/expected/`
in the **append-only audit log** established in ticket 05 — the log the run skeleton cannot rewrite.

**Phase 2 — reveal.** Only after the seal is recorded does the comparison job read the builder's output.
The comparison harness **refuses to run** unless the sealed record for that account predates the
builder-output record for that account in the audit log.

Do not rely on git commit timestamps as the ordering evidence. They are set by the committer and are
trivially forgeable. The audit log written by the run skeleton, plus the governance module's record of
who requested each transition, is the evidence that survives review.

**After reveal, the sealed expectation is immutable.** A discrepancy is resolved by finding the cause in
whichever path is wrong and fixing *that*; the expected value changes only through a new golden-set
version. Ticket 36 is explicit: averaging errors away or dismissing many small discrepancies
collectively is not an available outcome.

### 2.4 Context separation, and the orchestrator as contamination vector

This is the separation that fails silently, and it is the one no file-permission scheme catches.

**One agent session touches exactly one lane, for its entire life.** A session that has read the
builder's FIFO implementation and then writes the validator's FIFO is not independent even if the files
live in different worktrees — the correlation already happened inside the context window. Separate
worktrees prevent copying; only separate sessions prevent priming.

Concretely:

- Never run builder and validator work in one conversation, one background agent, or one `/implement`
  invocation. Fresh context per lane, always.
- **The orchestrator may pass a validator-lane session only: pointers to raw chain data, the frozen
  specification, and the account list.** Never a builder artefact, never a summary of one, never a
  number. "The builder gets 4.2% on account 0x… — check that" destroys the layer in one sentence, and it
  is the single most natural thing for a coordinating agent to say.
- The same rule binds handoff documents (§6). A validator-lane handoff carries `forbidden_inputs` and
  contains no builder results.
- The `code-reviewer` reads builder code; therefore code-review findings are builder-lane artefacts and
  never enter a validator brief.

**The golden set is a deliberate exception, and its limits must be stated.** The builder runs the golden
harness and learns pass/fail per account per criterion. That is the point — the golden set is an
acceptance test the builder is *supposed* to turn green. The cost is that the builder can iterate
against it, which means the golden set alone cannot detect overfitting to the golden set. That is
exactly why there are four layers. Two consequences for operations:

- Layer 3's random reconciliation sample (≥200 accounts) and layer 4's reimplementation are **not**
  iterated against.
- **(Recommended)** Draw the 200-account sample once, from a seeded draw recorded in the freeze
  manifest. If a bug found by reconciliation is fixed, draw a fresh sample rather than re-running the
  same one. This is not in the source documents; it is a cheap guard against the same iteration effect
  reappearing one layer up.

### 2.5 The artefacts that prove independence held

Nine items. Each one is a file or a command output that a reviewer can check without trusting anyone's
account of what happened.

1. `git log --name-only builder/main` and `validator/main` showing **no file touched by both lanes**.
2. Committed CI output of the dependency-graph check: zero import edges validator → builder.
3. The enumerated permitted/forbidden shared surface, with file paths, in the validation report.
4. Audit-log entries showing, per golden account, `validator_expected_sealed` strictly before
   `builder_output_revealed`.
5. `validator/reasoning/<account>.md`, committed at seal time, showing derivation from raw chain data
   and the frozen spec — with the specific transaction hashes, receipts and traces it worked from.
6. The comparison harness's own refusal record for at least one deliberately out-of-order attempt
   (prove the check fires; a check never observed failing is a check never tested).
7. Session inventory: which session ran in which worktree. Weak evidence, but its absence is a finding.
8. The validator's list of **ambiguities in the frozen specification**, raised as clarification requests
   *before* implementing them (§2.6).
9. The external specialist's signed review of 10–15 complex accounts (ticket 37).

What these prove: no copy channel existed, and the ordering held. What they **do not** prove: that the
two lanes did not make the same mistake.

### 2.6 MACHINE-INDEPENDENT is weaker than EXTERNALLY REVIEWED — say so, and act on it

Two agents built from the same base model, given the same specification, share priors. They tend to make
*correlated* errors: the same misreading of an ambiguous rule, the same wrong assumption about a token
standard. That is exactly the failure class independent validation exists to catch, and the class two
agents are worst at catching (addendum §3; PRD "Staffing is the most likely cause of death").

Every control in §2.2–§2.5 removes the **copy** channel. None of them removes the **prior**. Structural
separation is necessary and not sufficient, and an operator who conflates the two will ship a
`MACHINE-INDEPENDENT` label believing it means more than it does.

Four things actually reduce correlated error, in descending order of value:

1. **Ticket 37 — 10–15 complex accounts reviewed by an external human specialist.** This is the only
   thing that changes the label to `EXTERNALLY REVIEWED`. It is a bounded, budgeted cost. The PRD's
   instruction is to treat it as a cost to pay, not an option to consider. `NOT INDEPENDENT` blocks the
   main test; `MACHINE-INDEPENDENT` does not, which is precisely why the temptation to stop at
   `MACHINE-INDEPENDENT` is real and must be named in advance.
2. **Ambiguity surfacing before implementation.** Have the validator record, before implementing, every
   place where the frozen specification is ambiguous — quoting the exact sentence, per VSO's
   clarification-request template, never paraphrasing the ambiguity away — and route each to the
   Research Owner *before* the builder implements it. An ambiguity resolved by two independent
   judgements that happen to agree is a correlated error. An ambiguity resolved by a recorded owner
   decision is not. This is the highest-leverage control available and it costs a document.
3. **(Recommended) Run the validator lane on a different base model.** Not in the source documents. It
   is a configuration change with no schedule cost and it is the only control that attacks the shared
   prior directly. If two models are available, using one per lane is close to free decorrelation.
4. **Print the limitation in the report itself.** Ticket 36 requires it: the correlated-error caveat
   travels with the status so the strength of the check cannot be quietly upgraded downstream.

### 2.7 Independence failure modes, named

- The orchestrator briefs the validator with a builder number.
- One session does both lanes "to save time".
- Shared-utility creep across the forbidden surface.
- The validator debugging against the builder's output before sealing ("why do we differ?").
- Editing a sealed expected value after reveal instead of finding the cause.
- Claiming `EXTERNALLY REVIEWED` without ticket 37 completing.
- The builder copying golden expected answers into its own test fixtures — which converts an independent
  check into a tautology and would still show green.

---

## 3. Freeze and invalidation as an orchestration problem

### 3.1 The state machine is the orchestrator's boss

```
PARAMETERS_OPEN → PARAMETERS_FROZEN → VALIDATION_PASSED → CODE_AND_DATA_FROZEN
→ NULL_COMPLETE → THRESHOLD_LOCKED → MAIN_TEST_EXECUTED → DECISION_EMITTED
```

VSO's orchestrator normally owns dispatch. Here dispatch is subordinate: **before assigning any ticket,
the orchestrator asks the governance module which stage is authorised, and a refusal is final.** Wire
this into `/assign` so it is mechanical rather than remembered. The orchestrator holds no decision
authority in VSO and it holds even less here — it cannot advance the state, cannot override a refusal,
and cannot record a transition.

Tickets that advance the state: **38** (`VALIDATION_PASSED`), **39** (`CODE_AND_DATA_FROZEN`), **40**
(`NULL_COMPLETE`), **41** (`THRESHOLD_LOCKED`), **42** (`MAIN_TEST_EXECUTED`), **43**
(`DECISION_EMITTED`), and **11** (`PARAMETERS_FROZEN`). Every one of them is single-threaded (§5).

### 3.2 What the Governance Module checks, and how agents respect a freeze

The module's checks (tickets 05, 06, 39; pre-registration §8.4, §9.7; addendum §2, §11):

| Check | Effect |
|---|---|
| Transition order | Out-of-order transitions rejected; every transition records its requester |
| Parameter writes after `PARAMETERS_FROZEN` | Rejected |
| `NULL_COMPLETE` without `VALIDATION_PASSED` | Unreachable |
| `MAIN_TEST_EXECUTED` without `THRESHOLD_LOCKED` | Unreachable |
| Validation status `NOT INDEPENDENT` | Main test refused |
| Any code change after `CODE_AND_DATA_FROZEN` | Requires a **new registered version**, not an in-place edit |
| Manifest hash | Every later result binds to it |
| Second execution of the main test | Rejected |
| `HALT` from operations | Stops execution, holds state, mutates nothing |

Mechanically, after ticket 39, an agent respects the freeze because it cannot do otherwise:

1. **Tag and protect.** The frozen commit is tagged; the branch is protected; the twelve manifest inputs
   are path-pinned (source commit, dataset snapshot, golden dataset version, protocol coverage list,
   decoder coverage version, model version, configuration, master and child seeds, known-answer
   fixtures, token and pool rules, price and marking rules, validation report — plus ticket 07's
   specification pin or its explicit `UNAVAILABLE` marker).
2. **Deny writes at the tool boundary.** A `PreToolUse` hook denies `Write`/`Edit` on every
   manifest-pinned path while the run is frozen and no new version is registered. Deny wins over allow.
3. **Freeze the data, not just the code.** The null must resample already-extracted data with **no new
   vendor queries**. Enforce it by removing the vendor API credential from the environment for tickets
   40–43. A new query then fails loudly instead of succeeding silently — which is the difference between
   a caught violation and a contaminated null.
4. **Determinism as a standing check.** Same commit + same master seed + same snapshot ⇒ byte-identical
   output. Re-verify it at the start of tickets 40 and 42, not only when convenient.

**The traps.** *"It's config, not code"* — configuration is in the manifest. *"It's a comment"* — any
write to a pinned path requires a new version, so the cheap correct move is not to write. *"Let's run
the main test again to check"* — every execution after the first is a protocol violation and the module
must reject it.

### 3.3 What happens mechanically when a bug is found after freeze

There is no patch path. The sequence:

1. **File a blocker** (VSO `blocker.schema.yaml`), `severity: critical`,
   `responsible_owner: human:research-owner` — authorising a full repeat is a scope and budget decision
   and belongs to no agent.
2. **Adjudicate the bug — but not by the builder.** Someone must decide whether it is a "real,
   documented bug". That determination is exactly the failure mode the whole design guards against: a
   well-intentioned engineer deciding a bug was small enough. Therefore: **the default is `INVALIDATED`,
   the burden of proof is on "not a bug", and the determination is made by the Independent Validator
   together with the Research Owner — never by the builder alone.**
3. **The module sets `Current Run Status: INVALIDATED`** as an automatic consequence of the blocker
   being accepted, not as a separate discretionary act.
4. **Everything downstream of the freeze is void:** null distributions, calibrated threshold, main test
   result, decision record. Void, not deleted — retained, tagged `INVALIDATED`, and never quotable.
   (VSO append-only: supersede, never erase.)
5. **The required restart, in full:** fix → register a **new code version** → re-run the **entire**
   validation gate (all four layers) → rebuild the null **from scratch** → re-run the main test. New
   freeze manifest, new hash.
6. **Prohibited and structurally unavailable:** patching, partial correction, cherry-picking old versus
   new, and — the one that will actually be attempted — computing both and comparing them to decide
   which to keep. Ticket 39 requires proving unavailability by an attempt that is rejected with an audit
   record.
7. **Re-run ≠ rebuild.** The validation gate is *re-run* against the frozen golden set at its existing
   version. The golden set is only *rebuilt* if the bug was in the golden set itself — a much larger
   event, requiring a new golden-set version and re-sealing under §2.3.

### 3.4 The drill, and the schedule arithmetic

Ticket 39's second half injects a real bug after freeze and proves the system invalidates rather than
patches, then reverts cleanly and re-hashes the manifest. **Do not skip it because the policy is
understood.** The drill's product is not understanding; it is the audit record of a rejected patch
attempt, which is the evidence that the control exists.

Weeks 11–12 are the reserve. **One invalidation is survivable inside the plan; two are not.** That is
the entire orchestration argument for the tracer-bullet ordering, the four validation layers, and the
red-harness-first discipline: every hour spent finding a bug before ticket 39 is cheaper than every hour
after it, by roughly the width of the whole validation gate. When the schedule slips, the
pre-registered response is to **pause, not compress** (§15.3). Compression converts a schedule problem
into an invalidation.

---

## 4. Which skill to use at which phase

### 4.1 Ticket range → skill

| Tickets | Phase | Skills |
|---|---|---|
| 01–04 | Preconditions | None. These are human acts — a person is assigned, a budget is approved. An agent may draft the register (ticket 05) and may **not** mark a precondition met. `grilling` on the staffing plan is worthwhile: this is the project's most likely cause of death. |
| 05, 06 | Run skeleton, governance | `implement` → `tdd` → `code-review`. Ticket 06's tests are *rejection* tests — every out-of-order transition and every post-freeze write must fail. |
| 07 | Commit the original specification | None. It is a commit, not a build. **Do not use `research` to reconstruct the missing contents** — the PRD is explicit that inventing them is worse than recording the gap. If it cannot be recovered, the manifest carries `UNAVAILABLE`. |
| 08, 09, 10 | The three open conflicts | `research` (primary sources: within-matched-set permutation tests, SMD-based matching, concentrated-liquidity depth) → `design-an-interface` or `codebase-design` for ticket 08's undefined M7↔M9 boundary → `grilling` on the recommendation → `domain-modeling` to record it as an ADR. **The Owner signs; the agent prepares.** |
| 11, 17, 18, 39 | Freeze events | `domain-modeling` before, to pin ubiquitous language into the frozen definitions. `grilling` on manifest completeness. **No `implement`.** |
| 12, 13 | Data access, raw-chain reader | `research` first (vendor table shapes, the two-column `from_address`/`swapper_address` convention, receipt/trace semantics), then `implement` → `tdd` → `code-review`. Security consultation happens **before** ticket 12, not after. |
| 14–16 | Golden set | Validator lane. `research` against raw chain data, per account. **Not `implement`** — the deliverable is hand-derived expected answers, and generating them with pipeline-shaped code defeats the layer. |
| 19–24 | Tracer bullet, widening | The standard build sequence (§4.2). `domain-modeling` once around 19–20 to fix `tx_sender` vs `portfolio_owner`, *valid buy*, `value_basis`. `diagnosing-bugs` when a harness goes red for a reason you cannot state in one sentence. |
| 25–28 | Universe and selection | Standard build sequence. If a window falls below the 10,000-account floor, stop and use `wayfinder` — that is a pre-main-test design revision, not a bug fix. |
| 29–33 | Benchmark, copyability, gates | Standard build sequence, gated on 08/09/10 being signed. |
| 34 | Diagnostics pack | `implement`, then a `code-review` pass aimed specifically at the boundary question: *can any diagnostic reach a gate?* Boundaries are first in the reviewer's fixed priority order, and this ticket is entirely a boundary. |
| 35–38 | Validation layers 3–4, gate summary | Validator lane. `research` against raw chain data; `qa` for filing defects conversationally as they surface. |
| 40–43 | Null, threshold, main test, decision | **No `implement` on the pipeline.** These are executions of frozen code. `code-review` *before* entering, nothing after. `diagnosing-bugs` here is a governance event first and a debugging task second (§3.3). |
| 44 | Arbitrum diagnostic | `implement` on a branch structurally unable to write to any gate artefact. |

### 4.2 The standard build ticket sequence (19–34)

The task's shape is `implement → tdd → code-review`. In this project the first two are inverted by
design, and it is worth being precise about why.

1. **Read, in this order:** the ticket file; the *pre-registration* section it implements (not the PRD's
   paraphrase); the current golden and known-answer harness report; the previous session's handoff.
2. **`tdd` — the red tests already exist.** Tickets 17 and 18 froze the golden set and the known-answer
   battery *before any pipeline code was written*. Identify which frozen cases this ticket must turn
   green. Write additional tests only for behaviour the frozen battery does not cover. **Those new tests
   are yours and may be revised; the frozen ones may not.** This is the strongest form of test-first
   available and it is structural rather than a preference.
3. **`implement`** — make the named cases green. No edit outside `allowed_files`.
4. **Determinism check** — same commit, seed and snapshot ⇒ byte-identical output. Not optional; it is
   an acceptance criterion on most build tickets and a precondition for the null.
5. **`code-review`** since the previous ticket's commit, both axes. The Spec axis compares against the
   **frozen pre-registration**, not the PRD. Reviewer priority order is fixed: boundaries → hidden
   business rules → replayability → PII → test level → style.
6. **Demo, then handoff.** A ticket is done when the named cases are green and the behaviour can be
   shown running. "Implemented but not demonstrable" is not done.

### 4.3 Where the remaining skills fit

- **`research`** — before any ticket whose facts come from outside the repository. It writes findings to
  a Markdown file in the repo, which makes it doubly valuable here: the finding survives the session
  boundary (§6). **Never** use it to decide a threshold; thresholds come from the frozen document.
- **`domain-modeling`** — twice. Once at 08/09/10 to record the three conflict resolutions as ADRs, once
  around 19–20 to pin the ubiquitous language before it diverges across modules. Not per ticket.
- **`triage`** — when a harness comes back red on many cases at once, which is the normal state after
  tickets 17 and 18 and again after any widening ticket. Triage first, to sort the reds into *this
  ticket's named cases* versus *not yet built* versus *a real defect in something already green*. Only
  the third class is a bug; treating all reds as bugs is the fastest way to widen the path out of order.
- **`diagnosing-bugs`** — the trigger is "a harness went red and I cannot name why in one sentence".
  Before ticket 39 it is an ordinary fix. After ticket 39, file the blocker and get the run status set
  *first*; diagnose second.
- **`grilling` / `grill-me`** — reserve it for the irreversible moments: the three conflict
  recommendations before signature, and the freeze manifest before ticket 39. Those are the two places
  where being wrong is expensive and being challenged is cheap.
- **`wayfinder`** — only for a genuine design revision: a Step 0 universe shortfall, or a
  `CONDITIONAL REVIEW` outcome at ticket 43.
- **`to-spec` / `to-tickets`** — already run. Re-run only if the four-window design is revised.
- **`handoff` / `claude-handoff`** — end of every session, with the path override in §6.
- **Do not use:** `prototype` on anything downstream of the freeze; `simplify` or any refactor skill
  after ticket 39 (every edit needs a new registered version); `implement` on 40–43.

---

## 5. When to fan out, and when not to

### 5.1 The rule

> **Fan out only where each lane's output is independently checkable against a fixed answer and no
> lane's output is an input to another lane inside the fan. Anything that writes to, reads from, or
> advances the governance state machine is single-threaded by definition.**

Two corollaries that do most of the work:

- **Compute parallelism is not agent parallelism.** Running 8,000 null runs across cores is fine and
  expected — same frozen code, same commit, deterministic child seeds from one master seed. Running two
  *agents* that write or interpret those runs is not.
- **Fan out analysis; converge signature.** Independent analyses may run in parallel; the decision that
  consumes them is one act by one authority.

### 5.2 Right to fan out

- **Tickets 01, 02, 03, 04, 07** — five of the eight items on the current frontier. No shared artefact
  between them; 01–04 are human acts an agent can only prepare the register for.
- **Tickets 08, 09, 10** — the other three frontier items, three independent conflict analyses. But
  note the convergence: conflict 1's
  resolution changes the inputs to tickets 32 and 40, so the three *recommendations* are prepared in
  parallel and reviewed **together** before the Owner signs. Signing them one at a time invites a
  combination nobody assessed.
- **Tickets 15, 16 — per-account golden-set tracing. The best fan-out case in the project.** 30–50
  accounts, each traced from raw chain data, each with a hand-computed answer, no shared state. One
  agent per account or per small batch. Fanning out here *improves* independence: it prevents a single
  agent's assumption from propagating identically across all 50 accounts. Two conditions: the case
  matrix (ticket 14) must be settled first and single-threaded, or the fan produces fifty easy cases and
  no fee-on-transfer token; and every tracer sits on the validator side of the wall.
- **Research streams** — vendor semantics, EVM decoding, concentrated-liquidity depth, permutation
  tests. Four background `research` agents, four Markdown findings, zero coupling.
- **Ticket 35's ≥200-account reconciliation** — per-account comparison, batchable.
- **Ticket 40's runs** — compute parallelism only, safe by construction because the child seeds are
  deterministic and recorded.

### 5.3 Wrong to fan out

- **Tickets 19→24, the widening tracer bullet.** The ticket README's own rule: *widen, do not stack*.
  Two agents building M3 and M4 in parallel against an unfinished M2 will each invent a different M2
  contract, and the integration will silently pick one. Sequential by necessity.
- **Anything writing the pre-registration or the parameter set** (11).
- **Every governance-advancing ticket** — 05, 06, 38, 39, 41, 42, 43. Each is one authorised transition
  with a recorded requester. Two requesters is a protocol violation, not a speedup.
- **Ticket 42.** The main test runs once. There is no version of "two agents run the main test."
- **Post-freeze debugging.** A fan of agents hunting a post-freeze bug produces a fan of patches. Single
  thread; governance first.
- **The builder and validator lanes.** They run concurrently *in time* and must never be concurrent *in
  one session*, and they exchange no work products. That is a wall, not a fan (§2.4).

### 5.4 The failure mode that matters

**Fan-out used as schedule compression.** The plan is 10 weeks with two reserve weeks, and the reserve
exists for validation re-runs. When the project is behind, the instinct is to parallelise the pipeline
build — which is exactly the region where parallelism produces divergent contracts and where a divergent
contract discovered after ticket 39 costs the whole run. The pre-registered response to a resourcing
shortfall is written down and is not "go faster": pause the project rather than run a weak test whose
result would later be cited as evidence.

---

## 6. Handoff between sessions

Ten to twelve weeks; no agent session spans it. There will be on the order of a hundred session
boundaries, and the project's integrity has to survive every one.

### 6.1 Three tiers of memory

1. **Frozen artefacts (the constitution).** Pre-registration, parameter set, golden-set version,
   known-answer fixtures, freeze manifest. Files in the repository. A session **reads** them; it never
   summarises them into a handoff. VSO's rule applies with force here: reference by path, never
   duplicate. A summary of the pre-registration inside a handoff is how the summary quietly becomes the
   spec.
2. **Durable machine state.** The governance state and the run's append-only audit log (tickets 05/06)
   are the authoritative answer to "where are we". `project-state.yaml` carries coordination fields
   only. **Where they disagree, the governance module wins** and `project-state.yaml` is the bug.
3. **The session handoff document.** Everything that was in a head and nowhere else.

### 6.2 Write handoffs into the repository

The `handoff` skill saves to the OS temporary directory. **Override that for this project** — write to
`docs/handoffs/<NN>-<ticket>-<yyyy-mm-dd>.md` and commit it. A temp-directory handoff will not survive a
week, let alone twelve, and the twelve-week horizon is exactly why it matters. Use `claude-handoff` when
the next session should start immediately; use `handoff` when it will start days later, which is the
common case here.

### 6.3 What a handoff must contain

The VSO handoff record, with the fields that actually carry weight in this project called out:

- `task_id` (ticket number), **`lane`** (`builder` | `validator` | `governance` | `owner`), worktree
  path, branch.
- **Harness state by name** — which golden accounts and which known-answer cases are green, which are
  red. This is the project's most reliable statement of progress; prose about progress is not.
- **Frozen pins** — pre-registration commit, golden-set version, manifest hash if frozen, governance
  state.
- `decisions` with their ADR path (append-only decision log).
- **`assumptions` — the highest-value field in this project.** Every place a judgement was made because
  the frozen spec was silent or ambiguous. An unrecorded judgement call is precisely how a correlated
  error becomes permanent and unfindable. If the assumption concerns a definition, it is a clarification
  request to the Research Owner, not an assumption to carry.
- `unresolved_questions`, routed to their owner by question type — **never to the orchestrator**, which
  holds no decision authority.
- `acceptance_criteria_status`, one line per checkbox in the ticket file, each `met` / `not_met` with
  evidence. "Looks fine" is `not_met`.
- The **15-item receiver checklist**, every item explicitly `true` or `false`. An omitted item is a
  validation failure, never "not applicable".
- `return_status`: exactly one of `accepted`, `accepted_with_conditions`, `rejected_incomplete`,
  `blocked_by_dependency`, `requires_human_decision`. There is no sixth "mostly done".
- **`forbidden_inputs` (project-specific, Recommended).** For a validator-lane handoff: the builder
  source paths the next session must not read. VSO has no such field; this project needs it.

### 6.4 Cold-resume order

Before taking any action:

0. **Read the governance state and the run status first.** If `INVALIDATED`, stop and go to §3.3;
   nothing else in the handoff matters.
1. `project-state.yaml`: `active_tasks` → `pending_handoffs` → `pending_reviews` → `blocked_tasks`.
2. The current golden and known-answer harness report.
3. The active ticket file.
4. The pre-registration section that ticket implements.
5. The last handoff document.

Only then act. In particular, do not re-run the golden harness against a modified pipeline before you
know the run status — after a freeze, running is not free of consequence.

### 6.5 Weekly cadence

At each week boundary the Research Owner receives a decision-ready summary in the VSO
human-approval-request shape — options, recommendation, risks, blocking status, and a
`safe_default_action` that is always the conservative one — **even in weeks where no approval is
needed**. The Owner's signature is on the critical path in weeks 1 (preconditions), 1–2 (the three
conflicts), 2 (freeze), 9–10 (validation status, threshold lock, decision), and the project's stated
most-likely cause of death is a staffing shortfall, not a wrong hypothesis. A weekly handoff that
reports ticket progress but not the precondition register is reporting the wrong thing.

### 6.6 Handoff failure modes

- Handoff written to a temp directory, then lost.
- Handoff that summarises the pre-registration, and the summary drifts into being the spec.
- Handoff that carries a builder result into the validator lane (§2.4).
- Handoff with `return_status` improvised as "partially done".
- A session that resumes from the handoff without re-reading the harness report and rebuilds something
  already green.
- A judgement call made and not recorded in `assumptions` — the one failure with no detection path.

---

## 7. A worked example: ticket 22, FIFO position accounting

Ticket: [`docs/tickets/22-fifo-position-accounting.md`](./tickets/22-fifo-position-accounting.md).
Chosen because it is an ordinary build ticket on the tracer path, and because FIFO is one of the three
things the Independent Validator is explicitly forbidden to share.

**1 — Precondition check (orchestrator, no decisions).** Governance state at or past
`PARAMETERS_FROZEN`; run status not frozen (22 is pre-freeze); ticket 21 in `completed_tasks` with the
netting hard cases green in the harness report. If 21 is not green, 22 does not start — and the
orchestrator surfaces that rather than adjudicating it.

**2 — Assignment.** Task created with `owner_agent: backend-engineer` (the Primary Builder lane),
`reviewer_agent: code-reviewer`, `approver: qa-engineer`. `reviewer_agent != owner_agent`;
`approver != owner_agent`.

```yaml
allowed_files:
  - <builder-worktree>/pipeline/position_accounting/**
  - <builder-worktree>/tests/position_accounting/**
restricted_files:
  - docs/phase-0-preregistration.md
  - <frozen golden set and its expected values>
  - <frozen known-answer fixtures>
  - <parameter set>
  - /Users/nimaalishahi/wallet-validator/**        # the entire validator worktree
```

Narrow, never widen; `restricted_files` wins over `allowed_files`. Note what is **not** grantable: the
golden expected values. The builder runs the harness; it does not edit the answers.

**3 — What the agent reads, in order.** The ticket file; pre-registration §4.4 (the primary metric and
FIFO) as the frozen source rather than the PRD's paraphrase; the current harness report, to identify
which frozen cases are red and named for FIFO or partial sells; the previous session's handoff. It does
**not** read the validator worktree, the golden expected-value file, or any PRD text that differs from
the pre-registration.

**4 — `tdd`.** The frozen red cases already exist: the FIFO and partial-sell known-answer cases (ticket
18) and every golden account whose hard case is lot assignment (ticket 17). Name them. Then write only
the tests the frozen battery does not cover — the running open-quantity reconciliation against raw
balance deltas, and the quarantine path for a sell exceeding tracked open quantity. Those are the
agent's own tests and are revisable; the frozen ones are not.

**5 — `implement`.** Produce: FIFO lot assignment with the reference case resolving as buy 100 @ 1, buy
100 @ 2, sell 150 → 100 from lot 1 and 50 from lot 2; per-sell-event lot assignment as a deterministic
field; realized/open status per position; and a **quarantined discrepancy** — not a silent clamp — when
a sell exceeds tracked open quantity, because that condition indicates a missed buy. One negative
requirement matters as much as the positive ones: there must be **no configuration option, environment
variable, or parameter selecting a lot-matching method other than FIFO**. The rule exists precisely so
it cannot be changed mid-analysis to improve a chart.

**6 — Determinism.** Same commit, same master seed, same snapshot ⇒ byte-identical output.

**7 — `code-review`** since the ticket-21 commit, both axes, Spec axis against the pre-registration.
Priority order applies literally: *boundaries* first — does lot-matching logic leak into valuation or
scoring? — then *hidden business rules*, where the reviewer greps for any reachable alternative to FIFO
(the negative requirement is a review obligation, not a self-certification), then *replayability*, then
test level, then style. Each finding carries severity, location, `owning_agent`, `required_correction`.

**8 — Handoff, builder → code-reviewer.** Fifteen-item checklist, each item explicitly true or false. If
any is false, the reviewer returns `rejected_incomplete` with all six rejection sub-fields populated;
the task goes to `rework_required`; `retry_count` increments; the acceptance criteria **do not change**;
and the builder submits a **fresh handoff, not a patch**.

**9 — QA gate.** `qa-engineer` verifies each of the ticket's seven acceptance criteria against the
frozen pre-registration, with evidence per criterion — "harness reports golden account `0x…` green on
lot assignment at raw-unit level", not "looks correct". An unverifiable criterion is `not_met`, not
skipped. The gate is blocking with `override_authority: none`: FIFO and partial-sell known-answer cases
green, every golden account whose hard case is lot assignment green, determinism reproduced.

**10 — Who is *not* in this path.** The `security-engineer` is not consulted: no collector, no new
external dependency, no third-party disclosure — the scoped veto question is not engaged. The
`documentation-engineer` is not involved: no manifest input changed. Saying so matters, because a
framework configured for `high_risk` will otherwise fire every role on every ticket and the gates stop
meaning anything.

**11 — Commit and state.** One atomic commit on `feat/22-fifo-position-accounting`, merged to
`builder/main`, message referencing the ticket and the harness delta (which cases went green).
`completion_evidence`: harness report path, reproducibility hash, review result, QA report. The
orchestrator writes `active_tasks`/`completed_tasks`; the `qa-engineer` writes `quality_gate_status`;
nobody writes `release_status` — there is no release-manager and there is no release.

**12 — Handoff out.** Written to `docs/handoffs/`, naming: cases now green, cases still red, and any
assumption made where the frozen spec was silent — for example, whether a sell of exactly the open
quantity closes the lot or leaves a zero-quantity lot. If the pre-registration does not answer it, that
is not an assumption to carry: it is a clarification request to the Research Owner, quoting the exact
sentence, with an options table. And because `PARAMETERS_FROZEN` has already passed, the only admissible
answers are "the frozen document already answers this and it was misread" or "a recorded Owner decision,
demonstrably independent of any observed result". Deciding it silently is the one option unavailable.

**13 — What did not happen.** The validator was not told ticket 22 is done. No validator artefact was
read or written. No golden expected value was edited. No threshold moved. And the governance state did
not advance — ticket 22 does not touch it. Only tickets 11, 38, 39, 40, 41, 42 and 43 do.
