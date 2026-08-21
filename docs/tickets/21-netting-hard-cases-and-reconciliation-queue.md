# 21 — Netting hard cases and the reconciliation queue

**What to build:** Widen the same run until netting is correct for every route shape in the golden set.
Multi-hop routes must not manufacture a phantom "bought WETH" event; split routes must resolve to a
single intent; MEV bundles and multicalls sharing a transaction must not corrupt the sum; circular
arbitrage must be excluded rather than recorded as a tiny profitable position; and partial-fill residue
must go to a reconciliation queue instead of being silently included or silently dropped. Two steps
here are ordering-critical and are the two most likely places for a subtle bug.

**Blocked by:** 20

**Status:** audited 2026-08-16 — **1 met, 8 partial**, and the sharpest partial (criterion 7's orphaned reconciliation queue) closed the same day; see below. `src/netting/` is 604 lines, 86 tests green,
and it runs on real Ethereum data through `tools/case_runs.py`. Boxes left unticked; the audit is
below.

Most of the partials are one fact: the hard cases are exercised on **synthetic fixtures** because no
golden account exists (`golden_set.trace` is a blocked stage). Multi-hop collapsing to one buy, split
routes reading as a single intent, an MEV multicall byte-identical to the clean transaction — all
pinned, none against an independently traced account.

**Met.** Criterion 8: the classifier is a total function where every branch returns, a reason is
mandatory on every non-trade, quarantined events are counted, and a dropped event raises from the
census invariant rather than reducing a total.

**Closed 2026-08-16: the reconciliation queue had a producer and no consumer, and now has both.**
`netting.reconciliation_queue` had **zero callers anywhere in `src/` outside `src/netting/`** —
verified by grep, not inferred — so addendum §8's residual above tolerance was excluded from the
primary metric and then surfaced in no queue record, no total and no report. Criterion 7's "routed to
a reconciliation queue with volume and age visible" was true of a function a caller could simply
forget to call, which is exactly the silent exclusion the criterion exists to prevent and the failure
mode this project treats as worse than a wrong number.

`pipeline.run` now routes every `ABOVE_TOLERANCE_RESIDUAL` result to the queue, carrying the volume
netting priced and the block it happened at. Only that status is routed: `UNSUPPORTED` and
`NO_CLEAR_ENDPOINT` are already accounted for (an UNSUPPORTED §8 attribution exclusion has an
`ExclusionRecord` and is counted in `unsupported_from_attribution`), so re-routing them would record
the same transaction twice.

Three things made it correct rather than a leak:

1. **A time field.** `QuarantineRecord` gained `block_number` — the age criterion 7 requires, so a
   residual that has waited a month is not indistinguishable from one that arrived this morning.
   `QuarantineQueue.oldest_first` orders by it, undated records last.
2. **A distinct stage.** The record is `Stage.RECONCILIATION`, not `NETTING`. Three invariants read
   a NETTING record as "netting refused this and produced no result" — the opposite of a residual,
   which *has* a result. Misfiling it as NETTING would double-count it against the census's
   netting-quarantine count and the population-conservation check. RECONCILIATION brackets
   `STAGE_ORDER` in `ACCOUNTING_STAGES` the way `INGESTION` does, without joining §4's sequence.
3. **An invariant so the wiring cannot rot back out.** `_require_every_residual_reached_the_queue`
   refuses a run where the count of `ABOVE_TOLERANCE_RESIDUAL` results and the count of
   RECONCILIATION records disagree. Mutations 118 (misfile the record as NETTING) and 119 (report
   its volume as `None`) both die.

The residual's volume now appears in `notional_usd_quarantined` and the queue's `total_volume_usd`
— the published-surface hash moved to record it, with the reason in the tripwire's own note. It is
also in `notional_usd_non_trades`, and those are two lenses on the same dollar rather than a
partition, so the overlap is two true statements, not a double-count of a total.

**Two counterfactual demos are weaker than they read.** Criterion 4's "skipping the owner filter
corrupts the result" sums a local dict inside the test rather than exercising a mutated code path, and
criterion 5's ETH/WETH counterfactual uses a fake `0xeee…` token rather than the real path with the
collapse disabled. Both are illustrations; the real evidence is mutation 02, which deletes the filter
from the source and is killed.

**Criterion 1's nine-step order rests on a docstring.** The steps are all present and two of them are
mutation-covered, but nothing static enforces the sequence — and the repo has that pattern already
(`tests/test_quantization_boundary.py`, `tests/test_shared_purity.py`). Also worth stating: ETH/WETH
normalisation is not one of the nine steps in the code at all; it happens in `contracts.core` and
netting only asserts it.

- [ ] The netting sequence executes in exactly this order and the order is enforced, not incidental:

      1. Filter to successful transactions
      2. Filter transfers to those touching portfolio_owner
      3. Normalise ETH and WETH to one asset
      4. Sign amounts: bought positive, sold negative
      5. Group by (transaction, portfolio_owner, token) and sum
      6. Intermediate route tokens net to ~0 and drop out
      7. Remaining non-zero endpoints are the user's intent
      8. Exclude fee and referral transfers from endpoint detection
      9. Detect and exclude same-transaction round trips (circular arbitrage)

- [ ] A multi-hop golden account produces exactly one buy event for the route endpoint and zero events
      for intermediate tokens.
- [ ] A split-route golden account resolves to a single netted intent, proving the method is route-
      shape agnostic rather than a first-hop/last-hop heuristic.
- [ ] A golden transaction containing an MEV bundle or multicall alongside the owner's trade produces
      the owner's intent only; skipping the owner filter is shown to corrupt it.
- [ ] ETH and WETH normalisation happens before netting; skipping it is shown to split one endpoint
      into two assets.
- [ ] `is_circular_arb` is emitted and circular arbitrage cases produce **no** position at all.
- [x] `netting_residual` is emitted per transaction; residuals within
      `max($0.01, 0.01% of transaction notional)` are treated as negligible, and residuals above it
      are excluded from the primary metric and routed to a reconciliation queue with volume and age
      visible.
      — closed 2026-08-16. `pipeline.run` routes every `ABOVE_TOLERANCE_RESIDUAL` to the queue with
      its priced volume and its block (age); `QuarantineQueue.oldest_first` orders by age;
      `_require_every_residual_reached_the_queue` refuses a run where the counts disagree. See
      above. The tolerance itself reads from the frozen set.
- [ ] No event may leave the pipeline unexplained: unsupported events are quarantined and counted;
      silently dropped events are a hard error.
- [ ] Every netting-related known-answer case passes, and the golden harness reports green on all
      route-shape and arbitrage accounts.
