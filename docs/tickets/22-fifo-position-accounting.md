# 22 — FIFO position accounting across partial sells

**What to build:** Widen the run so a wallet with many buys and several partial sells produces the
correct lot assignment and the correct realized/open split. FIFO, no alternatives, no configuration
switch — the rule exists precisely so it cannot be changed mid-analysis to improve a chart. Lot
assignment is a deterministic field, so it must match the golden set exactly, with no tolerance.

**Blocked by:** 21

**Status:** audited 2026-08-16 — **3 met, 3 partial, 1 not met.** Boxes below left unticked; the
audit is recorded here instead, because three of the seven turn on a golden set that does not exist
and ticking them would be the drift `docs/build-status.md` exists to catch.

`src/fifo/` is 475 lines and runs on real Ethereum data through `tools/case_runs.py`.

**Met, and properly.** The 100/50 reference case is pinned with all four money figures as literals,
plus out-of-order and multi-sell variants. The no-other-method criterion is enforced rather than
described: the signature is pinned literally as `["buys", "sells"]` with no defaults, and a static
scan of the package refuses `environ`, `getenv`, `argv`, `random`, `time.`, `datetime` and `open(` —
so there is no lever to reach for, and a repo-wide search finds no LIFO, HIFO or average-cost knob.
Oversell is quarantined and never clamped, pinned universally by a property test and end to end
through the pipeline's queue.

**Not met: realized/open status.** Criterion 3 asks that every position carry it. There is no such
field on `Lot`, `LotConsumption` or `FifoResult`, and `ValueBasis.REALIZED` is defined at
`src/contracts/core.py:124` and constructed nowhere in `src/`. Realized-versus-open is implicit in
which tuple a row lands in. So the criterion has nothing to compare even once a golden set arrives —
which makes it the one gap here that is *not* waiting on tickets 12–17.

**A frozen answer that cannot fail.** `FifoResult.unmatched_sell_raw` is declared at
`src/contracts/trades.py:233` and **written by no code path**. It is asserted `== {}` in two tests and
carried as an expected answer in two known-answer cases, where `battery.py` describes it as "the
check that the buy and the sell agree about how many tokens ever existed". It cannot ever fail. The
oversell quarantine took over the job and the field was left behind.

This is the same class of defect as the `token_imbalance()` method removed from `groundtruth` earlier
the same day: a vacuous green that is *reported* as a conservation law, which is worse than a missing
check. **It was not fixed here, deliberately.** Two of the four readers are frozen battery cases, so
removing the key moves `known_answer_fixture_hash` — pinned as `FROZEN_KNOWN_ANSWER_FIXTURE_HASH` and
in the §9.6 freeze manifest. Re-freezing the battery is cheap now, because nothing has been measured,
and it is not a thing to do silently. It needs the same deliberate act ticket 18's freeze had.

- [ ] Partial sells are allocated first in, first out, and the reference case resolves as: buy 100 @ 1,
      buy 100 @ 2, sell 150 → 100 from the first lot and 50 from the second.
- [ ] Lot assignment is emitted per sell event and matches the golden set exactly, at raw-unit level,
      with no percentage tolerance.
- [ ] Every position carries a realized or open status that matches the golden expectation.
- [ ] There is no configuration option, environment variable, or parameter that selects a lot-matching
      method other than FIFO.
- [ ] A wallet with interleaved buys and multiple partial sells across the window produces a correct
      running open quantity at every point, and the final open quantity reconciles to raw balance
      deltas.
- [ ] Sells exceeding the tracked open quantity are surfaced as a quarantined discrepancy rather than
      silently clamped, since that condition indicates a missed buy.
- [ ] The FIFO and partial-sell known-answer cases pass, and every golden account whose hard case is
      lot assignment reports green.
