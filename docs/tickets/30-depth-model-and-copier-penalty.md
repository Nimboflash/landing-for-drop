# 30 — Depth model and the copier penalty on constructed pool states

**What to build:** The physics of copying, verified on pool states whose answers are known before the
code runs — not on the experiment's own data. Given a constructed pool, the engine must size a trade
correctly against real depth, apply the copier penalty as a theorem rather than an estimate, and
itemise every cost component separately so that a later result can say *which* cost destroyed the edge
rather than only that it was destroyed. This ticket deliberately excludes follower order sizing, which
is undefined until OPEN conflict 3 is resolved; it establishes everything sizing will later plug into.

**Blocked by:** 24

**Status:** audited 2026-08-16 — **3 met, 6 partial, 1 not met.** `src/depth/` is 1,585 lines. Boxes
left unticked; the audit is below.

**Met.** The 3.1x depth reference case (5.000% -> 15.500%) reproduced exactly from hand-computed
literals. The copier penalty `(2*S_leader + C)/S1`, leader at double weight. Everything runs on
constructed pool states with no import of the basket or the universe, and the 38-digit expectations
carry their derivations.

**Fail-closed cost caps, checked because they are the easiest thing to get wrong.**
`EXECUTION_COST_CAP` has no `LONG_TAIL` key at all and `cost_cap_for` raises for long tail *and* for
any missing key, pinned twice and killed by mutation 05. Addendum SS9.5 says there is no long-tail cap
because there is no long-tail trade, and absence is how the code says it. A10.4's measured 5-23x TVL
band is used only as a reported constant and as quarantine bounds — **never as a multiplier on any
result**, which is the misuse worth checking for.

**Not met: criterion 6, and it is the ticket's headline result that depends on it.** "The follower
enters at the first full block after the leader, using no future information" is a **docstring claim
over an interface that accepts an arbitrary `PoolState`.** There is no block arithmetic anywhere in
`src/depth/`, `last_swap_block` is never read, and no test asserts entry timing or the absence of
look-ahead. A caller passing the pre-leader state, the same-block state, or a state read hours later
gets numbers the module publishes without complaint.

The copier penalty is entirely determined by which block's state is handed in, so the one input that
decides the finding is the one input nothing checks. This repository has a five-layer post-T0 barrier
for precisely this class of error, and this path is outside it.

**One gap closed here.** Criterion 8's >=90% fill: both `fills` properties read
`fill_ratio >= MIN_FILL_RATIO` and every existing case sat well inside the band — 0.7575 and 0.80
below, 1.00 above — so **flipping `>=` to `>` survived the whole suite.** Addendum SS9.4 says *at least*
90%, and the failure direction discards a copyable trade rather than admitting an uncopyable one.
Both types are now pinned at exactly 0.90 and one decimal place below it.

Still open on the same criterion: nothing enforces `fills` on the sizing path, which explicitly opts
out and yields `copyable=True` at a fill ratio of 0.7, and `allow_partial_fill=True` is exercised by
no test.

**Partials worth naming.** No tick integration exists — past roughly 1% the model raises
`OutsideValidityBand`, and a refusal is not an integration. `s1_at_trade` and `pool_depth_at_trade`
are computed and then dropped by `SizingResult.simulation`, the only record the pipeline emits — the
same computed-and-not-published theme as tickets 20, 21, 24 and 29. `liquidity_limitation_pct` is
excluded from `total_priced_cost_pct`, contradicting the frozen cap's own text, and is always exactly
zero on the wired path. And criterion 7's "constructed routed-vs-single-pool case" compares two frozen
constants, which pins nothing.

- [ ] Depth is modelled from virtual reserves `x_v = L/√P` inside the active band, integrated across
      ticks beyond roughly 1%; active-tick liquidity alone is rejected as a depth proxy.
- [ ] Both AMM pool/tick depth and order-book depth at each price level are considered.
- [ ] The engine reproduces the copier-penalty reference case exactly: leader 5.000% slippage → copier
      15.500% at equal size on a constant-product pool, i.e. 3.1×.
- [ ] The general form is implemented as `copier slippage ≈ (2 · S_leader + C) / S₁`, with the
      leader's size entering at **double weight** because the follower eats the leader's marginal
      impact and not their average.
- [ ] `s1_at_trade` — the trade size costing 1% slippage at trade time — and `pool_depth_at_trade` are
      emitted per simulated trade.
- [ ] Follower entry is simulated at the **first full block after** the leader's transaction, with no
      future information available to the simulation.
- [ ] Only the best deterministic **public** execution source is used; private RFQ and market-maker
      inventory are excluded, and a constructed case shows the routed-versus-single-pool gap that
      makes aggregator quotes unusable for capacity.
- [ ] A trade counts only at ≥ 90% order fill; partial fills below that are recorded as unexecutable,
      not as fills.
- [ ] DEX fee, historical gas, price impact, slippage, and liquidity limitation are each deducted
      explicitly and reported as separate components.
- [ ] Every case in this ticket is verified against constructed pool states with pre-determined
      answers; no number is produced from the selected basket.
