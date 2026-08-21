# Phase 0 — Tracer-Bullet Tickets

44 tickets covering Phase 0, the hypothesis falsification test, in dependency order. Each one cuts a
narrow but complete path through every layer and is verifiable on its own. Numbers are dependency
order, not priority — blockers come first.

**Project status is `DESIGNED, NOT READY FOR EXECUTION`.** Tickets 01–04 are the four start
preconditions and they block everything else. That is deliberate: the status is a fact about the
project, not an obstacle to route around.

Source of truth is [`phase-0-preregistration.md`](../phase-0-preregistration.md). Where a ticket and
the pre-registration disagree, the pre-registration wins.

---

## The ordering is the experiment

Four blocking edges below are not scheduling preferences. They are the integrity of the test and they
must not be relaxed:

1. **Step 0 completes before any ranking** (26 → 28). The funnel numbers are measured, not assumed,
   and a window under 10,000 eligible accounts forces a design revision *before* the main test.
2. **The golden set is built and frozen before the pipeline is written** (17, 18 → 19). Expected
   answers cannot be shaped by what the code produced.
3. **All four validation layers pass before the null runs** (38 → 40). The null cannot detect
   implementation bugs — it is computed by the same code, so a wrong FIFO rule corrupts the selected
   basket and all 1,000 random baskets identically and shows up as nothing at all.
4. **The null is built and the threshold locked before the main test, which runs exactly once**
   (40 → 41 → 42). After observing the result, nothing changes.

Ticket 06 makes these machine-enforced rather than agreed.

---

## Ticket list

| # | Title | Blocked by | Status |
|---|---|---|---|
| 01 | Assign and record the Primary Builder | None | ready-for-agent |
| 02 | Assign and record the Independent Validator | None | ready-for-agent |
| 03 | Approve the data budget and provision vendor access | None | ready-for-agent |
| 04 | Reserve 10–12 weeks of capacity and record the Phase 0 Lite refusal | None | ready-for-agent |
| 05 | Run skeleton, precondition register, and the start gate | 01, 02, 03, 04 | ready-for-agent |
| 06 | Governance state machine: ordering enforcement and post-freeze write rejection | 05 | ready-for-agent |
| 07 | Commit the original specification to version control | None | ready-for-agent |
| 08 | Resolve OPEN conflict 1: matching design versus null construction | None | ready-for-agent |
| 09 | Resolve OPEN conflict 2: the Edge Origin threshold after long-tail exclusion | None | ready-for-agent |
| 10 | Resolve OPEN conflict 3: follower order sizing | None | ready-for-agent |
| 11 | Freeze the pre-registration and the parameter set | 06, 07, 08, 09, 10 | **ready-for-agent** |
| 12 | First data pull: one window in the warehouse, coverage gap measured | 05 (03 for access) | ready-for-agent |
| 13 | Raw-chain ground truth reader for a single transaction | 05 (03 for access) | ready-for-agent |
| 14 | Golden set: case matrix and account selection | 12, 13 (02 leads) | ready-for-agent |
| 15 | Golden set: hand-traced expected outputs, core cases | 11, 14 | ready-for-agent |
| 16 | Golden set: hand-traced expected outputs, hard cases | 11, 14, 15 | ready-for-agent |
| 17 | Freeze the golden set and stand up the comparison harness | 15, 16 | ready-for-agent |
| 18 | Freeze the known-answer battery and stand up its harness | 06, 11 | ready-for-agent |
| 19 | **TRACER BULLET** — one wallet, one window, one buy, hand-checked | 17, 18 | ready-for-agent |
| 20 | Attribution and account typing end to end | 19 | ready-for-agent |
| 21 | Netting hard cases and the reconciliation queue | 20 | ready-for-agent |
| 22 | FIFO position accounting across partial sells | 21 | ready-for-agent |
| 23 | Marking, the liquidity bound, dead pools, migration, and token age | 22 | ready-for-agent |
| 24 | buy_quality_30d, log weights, and token-age buckets | 23 | ready-for-agent |
| 25 | Candidate universe for one window: two-stage buffer and infrastructure exclusion | 24 | ready-for-agent |
| 26 | Step 0: measure the eligible universe in all four windows | 25 | ready-for-agent |
| 27 | Freeze the universe at T0 and report churn as an output | 26 | ready-for-agent |
| 28 | Rank and select: clamp(1% of universe, 250, 1000) | 26, 27 | ready-for-agent |
| 29 | Activity-matched benchmark engine | 28, 08 | **ready-for-agent** |
| 30 | Depth model and the copier penalty on constructed pool states | 24 | ready-for-agent |
| 31 | Follower-Adjusted Buy Quality at five capital levels | 30, 10 | **ready-for-agent** |
| 32 | Edge Origin decomposition and First-Hour Edge Share | 29, 09 | **ready-for-agent** |
| 33 | Gate evaluation engine over the full condition matrix | 31, 32 | ready-for-agent |
| 34 | Diagnostics pack that cannot move a gate | 33 | ready-for-agent |
| 35 | Cross-source reconciliation against raw chain data | 24, 13 | ready-for-agent |
| 36 | Independent validation with a separate implementation path | 35, 02 | ready-for-agent |
| 37 | External specialist review of 10–15 complex accounts | 36 | ready-for-agent |
| 38 | Validation gate summary and the transition to VALIDATION_PASSED | 34, 35, 36, 37 | ready-for-agent |
| 39 | Code and data freeze, freeze manifest, and the invalidation drill | 38 | ready-for-agent |
| 40 | Null distributions: 1,000 runs per window per column | 39, 08 | **ready-for-agent** |
| 41 | Calibrate and lock the final mean threshold | 40 | ready-for-agent |
| 42 | Run the main test, once | 41 | ready-for-agent |
| 43 | Emit the decision record | 42 | ready-for-agent |
| 44 | Arbitrum secondary diagnostic (optional, outside the gate) | 43 (pre-registered in 11) | ready-for-agent |

---

## How to work the frontier

The frontier is every ticket whose blockers are all done. Pick any of them; there is no queue
position to respect beyond the blocking edges.

**The frontier today** is 01, 02, 03, 04, 07, 08, 09, 10 — the four preconditions, the specification
commit, and the three open-conflict resolutions. All eight can be worked in parallel and none of them
requires writing pipeline code.

Working rules:

- **One ticket, one fresh agent context.** Tickets are sized so a single agent can complete one
  without carrying state from another.
- **Never skip a blocker to unblock yourself.** Four of the edges are the experiment's integrity (see
  above); the rest exist because the widening tracer bullet only works in order.
- **A completed ticket is demoable.** If you cannot show the behaviour working, it is not done.
- **Widen, do not stack.** Tickets 19–24 are one path getting wider. Do not build a module beside the
  path and integrate later.
- **Red harnesses are the starting line.** After 17 and 18, the golden and known-answer harnesses run
  and report everything failing. Every pipeline ticket is measured by which of those go green.
- **If a bug is found after ticket 39, stop.** The run is `INVALIDATED` and the whole sequence repeats
  from a new code version. Patching is not an option and neither is selectively keeping a result.

---

## Blocked on open decisions

Five tickets cannot start until the Research Owner resolves the three conflicts recorded in
[`decision-engine-addendum.md`](../decision-engine-addendum.md) §14. The resolution tickets themselves
(08, 09, 10) are workable now — an agent can prepare the options and the recommendation; the Owner
signs.

| Blocked ticket | Open conflict | Why it cannot start |
|---|---|---|
| 11 — Freeze the pre-registration and the parameter set | 1, 2, 3 | The frozen document must *contain* all three resolutions. It cannot be frozen around an undefined matching/null interface, an unjustified Edge Origin threshold, or an undefined follower order size. |
| 29 — Activity-matched benchmark engine | 1 | Random-basket resampling and 5+5 matched controls with `\|SMD\| < 0.10` are different statistical designs and both cannot be the gate. The interface to the null engine is undefined. |
| 40 — Null distributions | 1 | The 95th percentile means something different under basket resampling than under within-matched-set label permutation. |
| 31 — Follower-Adjusted Buy Quality at five capital levels | 3 | "2% of total portfolio capital" has no definition since portfolio construction went out of scope. Option (a) capacity probe and option (b) largest size within the cost cap are not the same measurement. |
| 32 — Edge Origin decomposition and First-Hour Edge Share | 2 | The `≤ 40%` threshold was calibrated against a universe that no longer contains long-tail assets, where most first-hour sniping happens. The ticket cannot state its acceptance threshold. |

Because 11 gates the golden-set traces and everything downstream of them, **resolving conflicts 1, 2
and 3 is the critical path.** Nothing in the PRD or the pre-registration resolves them, and choosing
silently is the one option not available.

---

## One further gap

Ticket 07 exists because the original project specification is not in this repository — it exists only
as text pasted into a chat session. Three documents cite its sections and none of those references
resolve. The freeze manifest is meant to pin every input to the experiment, and one of them is
currently a chat log. Where the specification would have supplied something, the tickets either derive
it from the repository documents or record it as a gap. **Do not invent the missing contents.**
