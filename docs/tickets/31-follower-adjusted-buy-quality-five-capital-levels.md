# 31 — Follower-Adjusted Buy Quality at five capital levels

**What to build:** The second gate's measurement. Recompute buy quality as a follower would actually
have experienced it, at $100k, $250k, $500k, $1.5M and $2M, so the capacity cliff is located rather
than inferred. This is the column the published evidence says fails: measured across 6,000 projects
with market frictions, smart-money returns were positive for every selection method tested while
copier returns were negative for four of the five. The engine must be able to report that honestly.

**Blocked by:** 30, 10

**Status:** ready-for-agent

> Depends on OPEN conflict 3. `follower_adjusted_buy_quality` was locked with a follower order size of
> "2% of total portfolio capital", but portfolio construction is out of scope, so that phrase has no
> definition to refer to. Option (a) keeps 2% of `strategy_aum` as a labelled capacity probe; option
> (b) sizes each order to the largest amount within the execution cost cap, bounded by `strategy_aum`.
> These measure different things and this ticket cannot be built until ticket 10 selects one.

- [ ] Follower-Adjusted Buy Quality is computed at all five capital levels, with $1.5M and $2M
      identified as the two that gate.
- [ ] Order sizing follows exactly the rule selected in ticket 10, encoded as a formula with no
      residual interpretation, including its behaviour when the cost cap admits no viable size.
- [ ] Execution cost caps are applied inside the simulation: 1% on majors, 2% on mid-caps, with
      long-tail Ethereum assets excluded outright rather than measured and discovered unusable.
- [ ] Exit or mark at 30 days uses the same valuation rules as the raw metric, including the liquidity
      bound and dead-pool zeroing.
- [ ] `Copy Retention = Follower-Adjusted Buy Quality / Raw Buy Quality` is displayed only when Raw Buy
      Quality is at or above 2 percentage points, and shows `N/A` otherwise.
- [ ] Unexecutable trade share is reported per capital level, so "the edge survived" is distinguishable
      from "most of the edge could not be traded at all".
- [ ] Per capital level, the report carries raw buy quality, follower-adjusted buy quality, mean and
      median Copy Retention, positive trade rate, realized/marked/dead shares, and unexecutable trade
      share.
- [ ] Every reported number carries its scope — chain, window, capital level, liquidity band,
      population — so an Ethereum mid-cap result is never quotable as a general claim about copy
      trading.
- [ ] Verified on constructed cases and golden accounts only; no forward number for the selected
      basket is produced before the null is complete and the threshold locked.
