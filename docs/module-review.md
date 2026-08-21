# Module review — findings

**Date:** 2026-08-01 · **Reviewers:** five independent adversarial agents, one per module,
high effort, instructed to mark `CONFIRMED` only if the failing case was traced.

The synthesis agent stalled, so this is assembled from the raw returns. Severity and verdict
**Totals: 3 critical, 9 high, 14 medium, 10 low.**

are the reviewers' own.

> One finding is already fixed: the precision defect in `LotConsumption.realized_return`
> (commit 367fda0). It was in the shared seam, so it is recorded here under fifo where it was
> found, but it affected every module.

---

## attribution

Checks failed: 4, 5, 7, 10

> Mostly trustworthy on the axes it was designed around, with one real methodological gap. The seam discipline is clean: it imports only `contracts`, returns the frozen `Attribution`/no shadow types, has no float, no `round()`, no `/` on non-Decimals, no quantization anywhere (rates go through `contracts.divide` under CALCULATION_CONTEXT and are left unquantized on purpose), every output survives `to_canonical_json`, hand-computed expectations carry their arithmetic (1/4=0.25, 18/20=0.9) rather than back-filled literals, and UNRESOLVED is a typed status with an evidence string rather than an exception. A 12-mutant campaign against a copy of the tree caught 10, including every confidence value, the fee/zero-amount filters, the null-endpoint filter, the ordering of Safe vs 4337 evidence, and the empty-population `None` rate. The gap is the ambiguity rule: the module refuses a multi-owner transaction only when the signer is a bystander. `_resolve_direct_eoa` runs before any ambiguity check and `_resolve_single_recipient` deletes the sender from its candidate set instead of counting it, so a batch signed by one of its own traders resolves to that trader at confidence 1 while the other traders are dropped with no quarantine record (prohibited outright by the failure policy), and an untyped sender trading against an unlisted venue resolves to the *venue* at confidence 0.8 under an evidence string stating the sender "is not the beneficiary". Secondary: the null address can still enter as a portfolio owner through `SafeExecution`/`UserOperation`, and the property generator that asserts otherwise never draws it into those fields. None of these crash; all of them produce a plausible-looking wrong owner, which is the failure mode this review was asked to weight most heavily. I recommend fixing the sender-as-candidate handling and the NULL_ADDRESS guard in `_finalise` before this module's output feeds netting.

### attribution.1 [HIGH] CONFIRMED — check 10

`src/attribution/resolve.py:104`

**Problem.** A multi-owner transaction is refused as UNRESOLVED only when the signer is *not* one of the traders. `_resolve_direct_eoa` runs before any ambiguity check, so if one of the settled users signed the batch, that user is returned as the sole owner with DIRECT_EOA / confidence 1 / usable_for_primary_metric=True, and every other trader in the transaction is dropped with no quarantine record, no reason string, and no trace in the coverage report. `test_batched_settlement_with_two_users_is_unresolved` pins only the solver-signed variant, so the identical economic shape gets two different answers depending on who paid the gas.

**Failing case.** ctx = AttributionContext(infrastructure={SETTLEMENT}, eoas=frozenset(TRADERS)); transfers = 25 users' USDC->WETH legs through SETTLEMENT; resolve_attribution(TX, TRADERS[0], transfers, ctx) -> DIRECT_EOA, portfolio_owner=TRADERS[0], confidence=1, usable=True, evidence=('sender is a known EOA and an economic endpoint of the transaction (sent=1, received=1)',). The same call with SOLVER as sender returns UNRESOLVED. Traders 1..24 are erased -- exactly the failure the module's header docstring says it exists to prevent.

### attribution.2 [HIGH] CONFIRMED — check 7

`src/attribution/resolve.py:268`

**Problem.** `_resolve_single_recipient` removes the transaction sender from the candidate set (`endpoint.address != tx_sender`) instead of treating a two-sided sender as evidence that the transaction has more than one owner. When the sender's code status is UNKNOWN (the eoas set is never complete for new addresses), the sender's own two-sided legs are discarded and the *counterparty* -- an unlisted pool, a market-making EOA, an OTC counterparty -- becomes portfolio_owner at confidence 0.8, carrying the evidence line 'transaction sender X was routed through and is not the beneficiary' about an address that demonstrably both sent and received value. The record is counted as `resolved` in AttributionCoverage, so unresolved_rate under-reports it.

**Failing case.** ctx = AttributionContext(infrastructure={SETTLEMENT, SOLVER}, contract_accounts={NEWPOOL}); ALICE (untyped) swaps 1000 USDC -> 0.5 WETH against NEWPOOL and signs it; resolve_attribution(TX, ALICE, legs(ALICE, NEWPOOL), ctx) -> ROUTER_RECIPIENT, portfolio_owner=NEWPOOL, account_type=OTHER_CONTRACT, confidence=0.8, is_usable_for_primary_metric=True. A liquidity pool, which §6.2 excludes from the candidate universe entirely, enters the primary metric as a portfolio. With NEWPOOL untyped the same call still returns the pool as owner (usable=False), and coverage reports resolved=1, unresolved_rate=0.

---

## netting

Checks failed: 5, 6, 7, 10

> Mostly trustworthy, with one methodological defect that would move numbers. The mechanics are clean: layering is strict (contracts only), the frozen seam types are returned unmodified and never subclassed or shadowed, there is no float, no round, no division, and no quantization anywhere in the module or its tests, every hand-computed expectation carries its arithmetic in the docstring above it and I re-derived each one (956_049_000-956_000_000=49_000 -> $0.049 vs tolerance $0.0956049; 1e18-4e17=6e17 -> $1,800 at $3,000/ETH; 0.01% of $1,006=$0.1006), every emitted status carries a reason, and the conservation property genuinely asserts that endpoints plus residuals plus fee legs reconcile to raw balance change in exact units. The unpriceable-leg handling is the right way round: `None` is never treated as small, and an unpriced quote leg becomes UNSUPPORTED rather than a number. The defect is in the definition of 'transaction notional'. Because the notional is the max gross one-way flow over every token the owner touched, legs that net to exactly zero — the phantom intermediates netting exists to erase, plus flash loans and owner-to-owner transfers — inflate it, and with it the `max($0.01, 0.01% of notional)` negligibility threshold. I confirmed that adding a 300 WETH loan that cancels to zero converts an identical $1,000 buy carrying an unexplained $50 residual from NO_CLEAR_ENDPOINT (queued under addendum §8) into a clean VALID_BUY with the $50 written off as dust. That is a plausible-looking number produced by a rule flip that no existing test or hypothesis generator can reach, and it biases sample inclusion in the direction that most flatters the gate. Fix the notional definition (exclude legs whose net is zero; count a self-transfer once) and add a test where the cancelling leg is larger than the endpoint before trusting this module's coverage figures.

### netting.1 [HIGH] CONFIRMED — check 10

`src/netting/balance.py:192`

**Problem.** `_notional_from_flows` defines the transaction notional as `max(sent, received)` per token, taken over every token the owner touched — including tokens whose net is exactly zero. So an intermediate hop, a flash loan, or any leg that cancels sets the negligibility tolerance (`max($0.01, 0.01% of notional)`), even though netting exists precisely to declare those legs phantom. The result is that a genuine, above-threshold residual is reclassified as dust and the transaction is admitted to the primary metric as a clean trade instead of being sent to the reconciliation queue (addendum §8). The bias is directional and self-selecting: the transactions it wrongly admits are exactly the ones carrying money nobody can explain. No test reaches this — in every hand-computed and integration case the cancelling intermediate is *smaller* than the endpoint leg (test_multi_hop_route: WETH hop $900 vs USDC $956), and the `swaps()` generator in tests/properties/test_netting.py:115-117 builds its intermediate from the same `quote_raw` as the endpoint, so it structurally cannot produce one that exceeds it.

**Failing case.** Owner sells 1,000 USDC for 500e18 PEPE and is also left with +50 USDC-equivalent USDT (raw 50_000_000). (A) As written: notional $1,000.000000, tolerance $0.10, three surviving legs -> NO_CLEAR_ENDPOINT, queued. (B) Add two transfers that net to exactly zero — 300e18 WETH in from a lender at log_index 0 and 300e18 WETH out to the same lender at log_index 4: notional jumps to $900,000.000000, tolerance to $90.00, the $50 USDT leg is now 'negligible' -> VALID_BUY, quote_usd $1,000.000000, and the $50 sits in `residuals` where nothing downstream reads it. Same economic intent, opposite classification, decided by a loan that netted to zero.

---

## fifo

Checks failed: 2, 3, 4, 5, 6, 10

> The matching logic itself is the strongest part: layering is clean (contracts and stdlib only), there is no float ingress and no quantization anywhere, the FIFO order/conservation/no-look-ahead invariants are genuinely asserted under hypothesis, outputs carry full provenance (each LotConsumption holds the whole buy and sell NetTradeResult) and survive canonical JSON, the refusal paths are typed and legible, and 8 of the 10 methodological mutants I injected were killed by named tests -- the dust rules, the pro-rata denominator, LIFO, intra-block ambiguity and the zero-cost buy are all properly pinned. But it is not yet trustworthy for a go/no-go number, for two reasons that both live in the arithmetic rather than the assignment. First, the §4.4 primary metric itself (`realized_return`) performs its `- 1` outside CALCULATION_CONTEXT, so it is emitted at 28 digits and its value depends on the caller's ambient context; the integration test blesses this because its expectation is the implementation's own expression rather than a hand computation. Second, the closing-slice dust rule silently degrades and then hard-fails with an untyped ValueError once a lot's raw quantity is large relative to the residual -- at 10^36 raw units the closing basis was 67% wrong in my search, and at 10^39 it hits zero -- a regime that is entirely realistic for the long-tail, high-supply tokens this study targets and that the property suite cannot reach, because its generator caps quantities at 10^18 and its `_close` helper floors the tolerance at an absolute 1e-18. The frozen-context guard inside `_pro_rata` is likewise unpinned: remove it and all 55 tests still pass while the numbers change in the 22nd decimal. Fix the realized_return context, widen the generator to real uint256 scale, drop the 1e-18 floor from `_close`, and make the large-N basis exhaustion a typed refusal, and the module would be sound.

### fifo.1 [HIGH] CONFIRMED — check 3

`tests/integration/test_fifo.py:114`

**Problem.** The primary-metric expectation is written as the implementation's own expression rather than hand-computed, and it thereby blesses a real precision defect: `LotConsumption.realized_return` (src/contracts/trades.py:226) evaluates `divide(...) - Decimal("1")` where the subtraction runs under the *ambient* context, not CALCULATION_CONTEXT. divide() returns 38 digits, then `- 1` truncates to whatever prec the caller happens to have (28 by default). The test cannot see it because lines 116-117 and line 256 recompute the expectation with the identical context-less expression. The test's own docstring admits the back-fill: "Written this way rather than with a literal because a 1/3 return has no exact decimal form." This is exactly the flagged pattern -- arithmetic *after* a divide() call outside a localcontext block.

**Failing case.** Verified: `divide(D('800'), D('600')) - D('1')` = 0.3333333333333333333333333333 (28 digits) at ambient prec, but 0.3333333333333333333333333333333333333 (37 digits) inside `localcontext(CALCULATION_CONTEXT)`; the two are `!=`. WALLET_STORY consumption[1] is exactly this case. So §4.4's Sale Proceeds / Allocated Buy Cost - 1 is emitted at 28 digits, and its value changes depending on the caller's ambient context -- a validator re-deriving under the frozen context gets different bytes and a different canonical_hash, breaking §9's byte-identical-output requirement.

### fifo.2 [HIGH] CONFIRMED — check 6

`src/fifo/matching.py:152`

**Problem.** The dust rule `cost = lot.cost_remaining_usd` assumes the accumulated pro-rata subtractions never consume the whole basis. They do, once the lot's raw quantity is large relative to the closing residual, because `_pro_rata` (line 184) rounds to 38 significant digits while raw quantities are uint256 ints that routinely carry 33+ digits (numeric.py's own comment notes 2^256 is ~78 digits). At that point the closing slice gets 0 and `LotConsumption.__post_init__` raises a bare `ValueError`, which escapes `match_fifo` untyped -- neither a QuarantineRequired nor an AttributionUnresolvedError, contradicting the module docstring's "Refusals typed". Below that threshold the same rounding produces a materially wrong -- but positive and therefore silent -- basis for the closing slice.

**Failing case.** buy(block=10, qty_raw=10**39, usd='1000'); sell(block=20, qty_raw=10**39-1, usd='900'); sell(block=30, qty_raw=1, usd='1') -> ValueError: 'allocated_cost_usd must be > 0' out of match_fifo. Silent-wrong-number regime, randomized search over 300 lots each: at 10^33 raw units (SHIB-scale supply at 18dp) the closing slice's allocated_cost_usd departs from the exact pro-rata value by 4.5e-4 relative; at 10^34, 5.7e-3; at 10^35, 6.0e-2; at 10^36, 0.67 (e.g. N=8381645821762705802638131723677786654, cost $23632 -> computed closing basis 4.7E-33 against an exact 2.819E-33). No test in any of the three suites detects any of it.

---

## marking

Checks failed: 4, 5, 6, 7, 8, 10

> Not yet trustworthy, for one reason above all: `mark_position` follows a migration to `replacement_pool` without ever checking that the replacement's quote asset matches the primary's, while continuing to multiply by the caller's `quote_usd` for the primary's quote. A TOKEN/USDC -> TOKEN/WETH migration (the most common real shape) silently returns a mark 3.3e8x too large -- or, in the reverse pairing, 3.3e8x too small, which lands as an entirely plausible -100% rug -- and the evidence tuple does not record the venue's quote asset, so the error is not recoverable from the audit record either. That is exactly the "wrong number that looks plausible" class. Second, the §9.1 parameters that decide which positions get zeroed are unpinned by the suite: mutation testing shows the 30-day inactivity window can be widened to 90 days and the $1.00 minimum-exit threshold raised 1000x with all 60 marking tests still green, because every dead-pool test derives its timestamps from the constant itself. Third, condition 2 is position-relative while `PoolStatus.DEAD` is pool-level, so a $0.50 dust holding -- or a fully-sold position with `remaining_raw == 0` -- in a quiet but $500k-deep pool is reported as an observed dead pool, inflating the §10 dead-pool diagnostic the module's own docstrings say must never absorb modelling artefacts. The rest is genuinely well built: layering and seam conformance are clean, the hand-computed tests carry real worked arithmetic, the exit<=spot and monotone-per-unit-price invariants are asserted over wide generators, quarantine-vs-status discipline is right for the unmodelled and pre-start cases, and 12 of 16 dangerous mutations are caught. The remaining defects are the virtual-reserve floor whose direction claim is backwards (and which no property test reaches at all) and two bare Decimal divisions outside the frozen calculation context, one of which demonstrably flips a `value_basis` label.

### marking.1 [CRITICAL] CONFIRMED — check 6

`src/marking/mark.py:115`

**Problem.** When a migration is followed, the mark is computed against `replacement_pool`'s reserves but still multiplied by the caller's `quote_usd`, which is USD per raw unit of the PRIMARY pool's quote asset. Neither `mark_position` nor `validate_replacement` (src/marking/pools.py:99, which checks asset identity, address, swap history, recency and modellability) ever compares `replacement.quote` to `pool.quote`. A migration from a TOKEN/USDC v2 pool to a TOKEN/WETH v3 pool -- the single most common real migration shape -- silently prices the exit in raw WETH units at the raw-USDC price. The evidence tuple records `venue=0x...` but never the venue's quote asset, so the unit swap is invisible to a §9.2 re-derivation from the record.

**Failing case.** primary = TOKEN/USDC (quote_reserve 1e6 raw USDC, last swap 30d ago), replacement = TOKEN/WETH (asset 1e25, quote 100e18 raw WETH, live), remaining 1e24, quote_usd = Decimal('0.000001') (USD per raw USDC). Returns value_usd = 9,066,108,938,801.49 with PoolStatus.MIGRATED / LIQUIDITY_BOUND. Correct value using the replacement's own quote price (3e-15 USD per raw WETH) is 27,198.33 -- a 3.33e8x overstatement. The reverse pairing (WETH primary, USDC replacement) divides the mark by 3.3e8, turning a $270k position into $0.0009 and manufacturing a plausible-looking -100% rug.

### marking.2 [HIGH] CONFIRMED — check 5

`src/marking/pools.py:26`

**Problem.** The two pre-registered §9.1 parameters that decide which positions are zeroed are not pinned by any test. Every dead-pool test builds its timestamps as `HORIZON_TS - DEAD_INACTIVITY_SECONDS`, so the tests move with the constant instead of pinning it, and the exit-value threshold is only ever exercised against marks of ~1e-6 (dead) or >=$4,533 (not dead), leaving the whole range in between free. Widening the inactivity window is the Dune-flattering direction the module exists to prevent: rugs stay marked at their dust value instead of zeroed.

**Failing case.** Verified by mutation against the full marking suite (hand_computed + properties + integration, 60 tests): `DEAD_INACTIVITY_SECONDS = 30 * 24 * 60 * 60` -> `90 * 24 * 60 * 60` passes 60/60. `MINIMUM_EXIT_VALUE_USD = Decimal("1.00")` -> `Decimal("100.00")` passes 60/60, and -> `Decimal("1000.00")` also passes 60/60. (30d -> 7d is caught, by the 25-day window-edge integration test, so the window is pinned only from below.) Also surviving: `MARKING_TOLERANCE` 0.005 -> 0.05, `THIN_SHORTFALL_RATIO` 0.10 -> 0.40, `below_threshold = marked_usd < MINIMUM` -> `<=`, `shortfall > MARKING_TOLERANCE` -> `>=`, and deleting the `replacement.address == pool.address` self-replacement guard.

---

## depth

Checks failed: 4, 5, 6, 10

> The physics is right and the writing is honest — but the module is not yet trustworthy, for two separable reasons. First, one live defect: a concentrated pool with a zero real quote reserve slips past the `virtual_usd < real_usd` quarantine (it can never fire when real is zero) and is priced, producing $5,000,000 of depth and a $35,000 copyable order from a pool holding $0 of the quote asset — while the constant-product branch rejects the identical input eight lines earlier. Second, and more consequential for a pre-registered pipeline: the test evidence is far thinner than it looks. `tests/properties/test_depth.py` and `tests/integration/test_depth.py` do not exist at all, so there is zero hypothesis coverage and the module's own stated central invariant (`execution_price_ratio` monotone in size) is asserted nowhere. The 37 hand-computed tests are genuinely worked-by-hand and the reference case is reproduced exactly, but they run on a single fixture monoculture — one pool, one quote asset at exactly $1.00, one token-decimal count, and `sqrt_price_x96 = Q96` in every concentrated case — which leaves whole methodological rules unfalsifiable. I confirmed nine one-character mutations that survive the entire suite, including swapping the quote/asset legs of the virtual reserves, deleting the USD price multiply, flipping `best_public_execution` from cheapest to most expensive, inverting the leader adjustment on the validity-band ceiling, and flipping the sign that recombines the two slippage halves. Layering, seam conformance, the no-float rule, canonical serialization, and quantization placement are all clean, and the directional claims in the docstrings (flooring lowers VWAP, flooring understates depth) check out. On the spec side, `walk_order_book` / `best_public_execution` are implemented but called by nothing — ticket 30's requirement that both AMM and order-book depth be considered is satisfied in parts, not in composition.

### depth.1 [CRITICAL] CONFIRMED — check 10

`src/depth/amm.py:365`

**Problem.** A concentrated pool with `quote_reserve_raw == 0` is priced instead of quarantined. The quarantine guard is `if virtual_usd < real_usd`, which can never fire when `real_usd == 0`, so a drained pool carrying stale `active_liquidity`/`sqrt_price_x96` is converted into a large depth figure and a copyable order. The identical condition IS rejected on the constant-product branch at line 344 (`if real_usd <= 0: raise`), so the module refuses a $0 pool it does not model and prices a $0 pool it does. Line 389 then sets `tvl_understatement_factor = None` because the denominator is zero — but the DepthMeasurement docstring (line 239) reserves `None` for constant product, 'where the two coincide by construction'. A zero-denominator and a not-applicable are collapsed onto the same value, so nothing downstream can tell them apart.

**Failing case.** PoolState(quote_reserve_raw=0, active_liquidity=5*10**12, sqrt_price_x96=2**96) with USDC as quote -> measure_depth returns model=CONCENTRATED_VIRTUAL_RESERVES, quote_reserve_usd=0, effective_depth_usd=5000000, tvl_understatement_factor=None, band.max_size_usd=50000. size_to_cost_cap_detail(pool, MAJOR, aum=1000000, leader=0, gas=0) returns copyable=True, order_usd=35000, binding_constraint='cost_cap' — $35,000 of executable capacity against a pool holding $0 of the quote asset.

### depth.2 [CRITICAL] CONFIRMED — check 4

`tests/properties/test_depth.py:1`

**Problem.** `tests/properties/test_depth.py` and `tests/integration/test_depth.py` do not exist. Every other builder module (attribution, fifo, marking, netting) has both. `grep -rl hypothesis tests/` returns four files, none of them depth — so the module has zero property coverage. The module's own stated central invariant is in amm.py:496 ('Monotone non-decreasing in size_usd. That is the invariant the whole module rests on'), and `execution_price_ratio` has zero references in the entire test tree. The other unasserted invariants: copier_penalty >= 0 for all non-negative inputs (the whole justification for the closed form at amm.py:462), the sized order's cost never exceeding its cap, and copier_slippage == own_price_impact + copier_penalty for arbitrary inputs (asserted only at the single reference point).

**Failing case.** Mutating amm.py:499 from `+(ONE + copier_slippage(...))` to `+(ONE - copier_slippage(...))` — turning the execution price ratio into a discount that decreases with size — passes all 37 tests. Any hypothesis test over (depth, leader, size) asserting non-decreasing ratio would kill it.

### depth.3 [HIGH] CONFIRMED — check 5

`src/depth/orderbook.py:273`

**Problem.** `best_public_execution` selecting `min` versus `max` is unverified: no test ever supplies two public sources that both fill and differ in cost. `test_private_liquidity_never_wins_the_route` has two sources but only one survives the private filter; `test_a_public_source_that_cannot_fill_is_not_a_source` has one. With a single candidate, min == max. §9.4's 'best deterministic public execution source' is therefore asserted nowhere, and a one-character flip would make the engine underwrite every trade at the most expensive public route.

**Failing case.** Mutation `min(fillable, key=...)` -> `max(fillable, key=...)` at orderbook.py:273 passes all 37 tests. Failing input the suite lacks: two public sources at 0.9% and 0.1%, both fill_ratio=1 — correct answer is the 0.1% route, mutant returns the 0.9% one.

### depth.4 [HIGH] CONFIRMED — check 5

`src/depth/amm.py:280`

**Problem.** The USD conversion in `raw_to_usd` is untested for any quote asset other than a $1 stablecoin. Every fixture in the suite uses `QuoteAsset(USDC, decimals=6, usd_price=D('1'))`, so the `* quote.usd_price` factor is multiplication by one in all 37 tests. WETH and WBTC are both in `contracts.QUOTE_ASSETS` and are the usual quote leg for exactly the volatile pairs this experiment is about; every depth, S1, band edge, and capacity number for such a pool flows through a code path with no coverage. The same fixture monoculture leaves `decimals` untested at any value but 6.

**Failing case.** Mutation `divide(raw_amount, 10 ** quote.decimals) * quote.usd_price` -> `divide(raw_amount, 10 ** quote.decimals)` passes all 37 tests. On a WETH-quoted pool with 400 WETH of reserve at $2,500, correct depth is $1,000,000 and the mutant reports $400 — the pool is then declared uncopyable at every capital level.

### depth.5 [HIGH] CONFIRMED — check 5

`src/depth/amm.py:303`

**Problem.** The quote/asset orientation of `virtual_reserves` cannot be detected by any test, because every concentrated fixture uses `sqrt_price_x96 = Q96` (price = 1), where `x_v == y_v` identically. The docstring at amm.py:288 concedes this convention is 'pinned here because contracts.PoolState does not pin it' — so it is the one input assumption the module admits is unenforceable at the seam, and it has no test that can observe a violation. The `virtual_usd < real_usd` quarantine catches an inversion only when it happens to shrink depth; when it inflates depth it is silent.

**Failing case.** Mutation `quote_virtual = active_liquidity * sqrt_price_x96 // Q96` -> `active_liquidity * Q96 // sqrt_price_x96` (i.e. returning the asset-side reserve as quote depth) passes all 37 tests. At sqrt_price_x96 = 4*Q96 with L = 5e12, correct quote depth is 2e13 raw and the mutant gives 1.25e12 — a 16x error at that price, and ~1e12x at real WETH/USDC raw scales where token decimals differ by 12.
