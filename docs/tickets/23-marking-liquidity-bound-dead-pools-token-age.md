# 23 — Marking, the liquidity bound, dead pools, migration, and token age

**What to build:** Widen the run to positions that are still open at day 30, which is where the metric
is most easily flattered. Marks come from pool-level on-chain history and never from coin-level
aggregator data; every mark is bounded by what could actually be extracted from the real pool; dead
pools are zeroed rather than carried at a stale price; migration is followed only when it is genuinely
the same token; and token age is measured from first usable liquidity rather than contract creation.
Every valuation leaves this stage tagged with the basis it was produced by, so any later aggregate can
be decomposed into realized, marked, and dead shares.

**Blocked by:** 22

**Status:** audited 2026-08-16 — **4 met, 5 partial.** `src/marking/` is 884 lines and runs on real
Ethereum data. Boxes left unticked; the audit is below.

**Met, and the dead-pool conjunction is the one to be glad about.** All three §9.1 conditions are
required by an `all(...)`, each pair is proved insufficient on its own, the 30-day window reads from
the frozen set and is pinned to the literal 2,592,000, the `$1.00` exit floor is strict `<` at the
boundary, and three mutations cover it. A quiet-but-exitable pool and a migrated token are both left
unzeroed, pinned by property tests. `token_trading_start_block` is first usable liquidity plus at
least one real swap on a covered factory.

**The sharpest partial, and it is disclosed rather than hidden.** Criterion 8 asks that the
window-edge rule be applied identically wherever it is used, and it is not: the realized/open split
uses each buy's own day 30 (`run.py:840`) while the mark uses the run horizon (`run.py:876`). That is
a declared modelling choice — the seam supplies one `PoolState` per pool, so a per-buy snapshot is not
available — and the deviation is published per buy as `horizon_lag_seconds`.

What the disclosure did not say, and now does: **§9.1's conjunction is evaluated on that later pool
too.** A venue exitable at a buy's day 30 that drained afterwards zeroes the position outright, so the
error is not a drift in a price but the difference between a holding and a total loss — and it runs
one way only, because a pool can go quiet between day 30 and the run horizon and cannot un-quiet.
Closing it needs a `PoolState` per buy horizon, which is a change to the seam.

**Criterion 2's guard is in the wrong place.** "A coin-level aggregator fails loudly at any point in
the pipeline" is enforced in `tools/provisioning/`, not in `src/transport/` — there is no
`assert_not_prohibited` on the runtime path and no test pins it. The seam admitting only `PoolState`
plus a quote price is what actually holds today, which is a narrower claim than the criterion makes.

**Criterion 5's "liquidity history" is one snapshot.** `PoolState` carries no history, so migration
detection rests on identity, a self-check, `last_swap_block > 0` and recency. That is a defensible
test of *a* real swap; it is not a history.

**One untested asymmetry worth carrying forward.** Condition 2 of the conjunction is
position-relative (`mark.py:162`) while `PoolStatus.DEAD` is pool-level, so a dust holding in a quiet
but deep pool is published as an observed dead *pool*. Nothing tests that case either way.

**A vacuous assertion.** `tests/hand_computed/test_marking.py:786` asserts `"igration" in __doc__`.
The real migration evidence is elsewhere and is good; this line pins a substring of a docstring.

- [ ] Positions open at day 30 are marked as
      `min(Remaining Quantity × Pool-Level Exit Price, Extractable Value Given Real Pool Liquidity)`,
      and a golden thin-pool account proves the minimum actually binds.
- [ ] Marks are taken from pool-level on-chain history with inactive sources included; any attempt to
      read a coin-level aggregator price fails loudly at any point in the pipeline.
- [ ] A pool is declared dead only on the full conjunction — no successful swap for 30 days **and**
      executable exit value below the minimum threshold **and** no validated replacement pool — and a
      dead position is marked **zero**, never a stale or forward-filled price.
- [ ] A quiet-but-exitable pool and a token that migrated to a live pool are both proven **not** to be
      zeroed.
- [ ] Pool migration is followed only when supported by liquidity history, real trading activity, and
      unchanged token identity, and migration never resets token age.
- [ ] `token_trading_start_block` is derived from first usable liquidity plus at least one real swap in
      a covered pool, so a contract deployed months before it traded is not classified as mature at
      its first trade.
- [ ] Every valuation emits `value_basis` as `REALIZED | POOL_MARKED | LIQUIDITY_BOUND | DEAD_ZEROED`,
      and realized / marked / dead shares are reported per wallet.
- [ ] The window-edge rule works: 30-day measurement extends up to 30 days past the end of an
      evaluation window, no sample is dropped, no partial return is used, and the rule is applied
      identically wherever it is used.
- [ ] The dead pool, thin-but-live pool, liquidity-bound marking, multiple-pools, migration, and
      end-of-window known-answer cases all pass.
