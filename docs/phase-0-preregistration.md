# Phase 0 — Hypothesis Falsification Test

## Pre-Registration Document

**Project:** Smart Wallet Copy Trading & Portfolio Intelligence System
**Document status:** `DESIGNED — NOT READY FOR EXECUTION`
**Version:** 1.1 — **FROZEN** at commit `4bbae13` on 2026-08-16 (see §17)

> **v1.1, 2026-07-31.** The three open conflicts from `decision-engine-addendum.md` §14 are resolved
> and merged. §6.6 benchmarks are now matched pairs; §8.2 the null is a within-matched-set
> permutation test; §4.5 follower orders are sized to the execution cost cap. §7.1 condition 3 keeps
> its 40% threshold, with its demotion to a backstop recorded. Nothing else changed.
**Owner:** Product / Research Owner

> This document must be **frozen before any measurement is run**. Once frozen, no parameter,
> threshold, or definition in it may be changed on the basis of an observed result. The freeze
> protocol and the invalidation rules are in §10.

---

## 1. Why this document exists

The project specification describes twelve engines (data collection, transaction classification,
wallet accounting, discovery, validation, scoring, copyability simulation, entity clustering,
strategy clustering, signal generation, portfolio construction, risk management). Building them is
estimated at 4–6 months.

All twelve rest on a single empirical claim that the specification **assumes rather than tests**.

Phase 0 tests that claim first, on historical data, for a fraction of the cost. If it fails, the
project stops before Phase 1 begins.

Phase 0 is designed to be **killable**. Its purpose is not to authorise the project. Its purpose is
to end the project cheaply if the evidence is not there.

---

## 2. Hypotheses

The premise splits into two claims. The specification treated them as one. They are not.

**H1 — Leader skill persistence**

> Wallets whose past purchases were followed by better token returns continue to have purchases
> followed by better token returns, out of sample, relative to activity-matched wallets from the
> same population.

**H2 — Economic copyability**

> That advantage survives transfer to a follower deploying `design_capital`, after price impact,
> slippage, DEX fees, gas, and execution delay.

**H1 without H2 is not a business.** Published work (§13.1) finds H1 supported and H2 failing for
four of five wallet-selection methods tested. Both must hold.

### 2.1 What Phase 0 does *not* test

- Whether alpha survives once the strategy itself deploys capital and moves prices (Berk–Green;
  see §12.5). No backtest on historical data can measure this.
- Whether the result generalises to Base, Arbitrum, Solana, or memecoin markets. See §11.
- Whether the full product, with scoring, clustering, and risk engines, would be profitable.

Passing Phase 0 does **not** prove the product will make money. It proves the hypothesis has enough
initial support to justify the cost of Phases 1 and 2.

---

## 3. Scope

| Parameter | Value |
|---|---|
| Chain | **Ethereum mainnet** (exclusive; see §11.1 for why) |
| Trading type | Spot DEX only |
| Data era | Historical only. No live execution, no waiting. |
| Secondary diagnostic | Arbitrum, optional, **outside the gate** (§11.2) |

### 3.1 Capital parameters

These are **inputs to the system**, not management preferences. Copyability cannot be computed
without them.

```
Initial capital (paper trading / limited live)   $100,000 – $250,000
Target capital (on success)                      $500,000
design_capital (ceiling the system is built for) $1,500,000 – $2,000,000
```

Copyability is simulated at five levels:

```
$100,000   $250,000   $500,000   $1,500,000   $2,000,000
```

The last two cover `design_capital` directly and are the two that gate (§7.2).

### 3.2 Target portfolio structure (mature state)

```
Wallet Signal Portfolio    50%
Core BTC/ETH               25%
Stablecoin Reserve         25%
```

Live ramp, gated on evidence at each step: **10% → 25% → 50%**.

If the wallet-signal sleeve ends up below 20% of portfolio, the economic justification for building
this system must be re-examined.

---

## 4. Definitions

### 4.1 Valid buy

A buy event is valid only if all hold:

- It is a **net balance increase at the transaction level** (see §4.2), not a raw per-hop swap row.
- It is not a same-transaction round trip (buy and sell of the same token in one transaction).
- Trade size is computable.
- It has a valid quote asset (§4.6).
- It is attributable to a specific pool and asset.
- `meta.err == null` — the transaction succeeded.

### 4.2 Buy detection — transaction-level balance netting

Buys are **not** read from per-hop DEX rows. `dex.trades` emits one row per pool hop, so a route
`USDC → WETH → TOKEN_A` produces a phantom "bought WETH" event that never represented intent.
`dex_aggregator.trades` does not solve this either: it covers only 18 aggregators and excludes
direct multi-hop routes through routers such as Uniswap's Universal Router, and it omits the wallet
routers (MetaMask Swaps, Rabby, Phantom, Coinbase Wallet) most retail flow uses.

Method:

```
1. Sign amounts: bought positive, sold negative.
2. Group by (transaction, user address, token) and sum.
3. Intermediate tokens net to ~zero and drop out.
4. The remaining non-zero endpoints are the user's actual intent.
```

Required handling:

- **Normalise ETH and WETH to a single asset before netting**, or route endpoints appear as two
  different assets.
- **Filter transfers to those touching the user address first**, or MEV bundles and multicalls in
  the same transaction corrupt the result.
- **Partial fills leave non-zero residue.** A tolerance is required. Pre-register the tolerance and
  whether residual rows are dropped or emitted.
- Fee and referral transfers must not be mistaken for endpoints.

This method is route-shape agnostic and handles split routes, which any first-hop/last-hop
heuristic does not.

### 4.3 Circular arbitrage

Round trips that net to approximately zero (e.g. USDC → SOL → USDC for $0.05 profit) must be
**explicitly detected and excluded**. Netting reports them correctly as near-zero, but there is no
"token sold" to express, and leaving them in makes arbitrage bots appear as wallets with thousands
of small profitable trades.

### 4.4 Historical Copyable Buy Quality (the primary metric)

For each valid buy, measure the return over the following **30 days**.

**Case 1 — position sold within the horizon**

```
Realized Return = Sale Proceeds / Allocated Buy Cost − 1
```

Both legs are denominated in the quote asset actually used. **No price oracle for the traded token
is required.** This is the point of the design: long-tail token price data is unreliable (§13.4),
and this case avoids it entirely.

**Case 2 — position still open at day 30**

```
Marked Value = min(
    Remaining Quantity × Pool-Level Exit Price,
    Extractable Value Given Real Pool Liquidity
)
```

The liquidity bound is **mandatory**, not optional. With 88% of new Uniswap V2 tokens reported as
honeypots, a thin-but-live pool marked at spot price is fiction. A wallet holding $50,000 of a token
whose pool has $2,000 of liquidity does not hold $50,000.

Price source must be **pool-level on-chain OHLCV**, never coin-level aggregator data. Rugged pools
retain their pool-level history; coin-level aggregator listings are auto-deactivated after 30 days
of inactivity and then deny historical access — vendor-imposed survivorship bias precisely where the
losses live.

**Case 3 — dead pool**

```
Marked Value = 0
```

Not the last stale price. Not a forward-filled price. Zero. Dune forward-fills daily prices for up
to 30 days, which would show a rugged token as flat rather than −100%, and would inflate the
apparent quality of wallets that buy garbage. Define and pre-register the inactivity window that
declares a pool dead.

**Partial sells — FIFO**

First in, first out. Imperfect but simple, reproducible, and pre-registrable. It cannot be changed
mid-analysis to improve a chart.

```
Buy 1: 100 tokens @ $1
Buy 2: 100 tokens @ $2
Sell:  150 tokens @ $3
  → 100 from Buy 1, 50 from Buy 2
```

**Aggregation to wallet level**

```
buy_quality_30d = weighted average of 30-day buy returns
Trade Weight    = log(1 + trade_value_usd)
```

Log weighting accounts for trade size without letting one whale purchase dominate a wallet's score.

### 4.5 Follower-Adjusted Buy Quality

The same metric, recomputed as a follower would actually have experienced it.

**Follower order size — resolved decision, 2026-07-31.** Each simulated order is sized to the
**largest amount that stays within the execution cost cap**, bounded by `strategy_aum` at each of the
five capital levels:

```
Order size = min(
    largest size whose total execution cost ≤ the cap for that asset tier,
    strategy_aum at this level
)

Cost caps (addendum §9.5):   major assets 1%   ·   mid-cap assets 2%
                             long-tail: excluded from Ethereum Phase 0
```

Total execution cost means everything in step 4 below — DEX fee, gas, price impact, slippage, and
liquidity limitation — not price impact alone.

> This supersedes the earlier "2% of total portfolio capital". Portfolio construction is out of scope
> (addendum §13), so a portfolio weight had nothing left to refer to. Sizing to the cost cap follows
> from the addendum's own constraints and answers the more decision-relevant question: **can this
> capital actually use this signal?**
>
> It also changes what the metric means, and the change is deliberate. The measure is no longer "what
> a fixed 2% position would have returned" but "what the largest economically executable position
> would have returned". A wallet whose edge survives only at sizes far below `design_capital` now
> shows up as such, rather than being flattered by a position size chosen for convenience.

Simulation per buy:

1. Identify the leader's trade.
2. Simulate follower entry at the **first full block after** the leader's transaction.
3. Price the order through the executable route or pool.
4. Deduct: DEX fee, historical gas, price impact, slippage, liquidity limitation.
5. Exit or mark at 30 days using the same rules as §4.4.

> **Note on the copier penalty.** For a constant-product pool, a copier trading the same size as the
> leader pays **3.1× the leader's slippage** (verified: leader 5.000%, copier 15.500%). The leader's
> size enters at double weight, because the follower eats the leader's *marginal* impact, not their
> average. General form:
> `copier slippage ≈ (2 · S_leader + C) / S₁`, where `S₁` is the trade size costing 1% and `C` is
> the aggregate copier capital.

> **Note on capacity.** Aggregator quotes **overstate** executable capacity, because part of the
> route fills against RFQ / market-maker inventory not reliably available to a latency-sensitive
> follower. Measured example: PEPE 1% size was $471 single-pool versus $114,000 routed — a 240×
> spread. Do not underwrite capacity on aggregator quotes.

> **Note on concentrated liquidity.** For Uniswap v3/v4 pools, total TVL *understates* near-spot
> depth by 5–23×, not overstates it. Use virtual reserves (`x_v = L/√P`) within the active band, and
> integrate across ticks beyond ~1%. Active-tick liquidity alone is an unreliable depth proxy for
> volatile tokens.

**Copy Retention**

```
Copy Retention = Follower-Adjusted Buy Quality / Raw Buy Quality
```

Reported only when `Raw Buy Quality` is positive and above a minimum threshold. Otherwise `N/A`, to
avoid meaningless ratios.

### 4.6 Quote assets and USD conversion

USD prices are used **only** for liquid quote assets:

```
USDC   USDT   WETH   ETH   WBTC
```

```
Buy Cost USD       = Quote Amount × Quote Asset USD Price at buy time
Sale Proceeds USD  = Received Quote Amount × Quote Asset USD Price at sell time
```

No oracle is required for long-tail tokens. This is the single most important robustness decision in
the metric.

### 4.7 Token age and buckets

Token age is **not** measured from contract creation.

```
Token Trading Start =
  the first block at which the token had usable liquidity
  AND at least one real swap in a covered pool
```

If a token has multiple pools, the first qualifying pool is used. **Migration to a new pool does not
reset token age.**

Non-overlapping buckets:

```
Bucket A:  first 10 blocks
Bucket B:  after 10 blocks through end of hour 1
Bucket C:  after hour 1 through end of hour 24
Bucket D:  token older than 24 hours

First-Hour Purchases = Bucket A + Bucket B
```

Bucket A is reported separately, but the gate condition applies to the whole first hour.

### 4.8 Window-edge handling

A buy made near the end of a forward window does not have a full 30 days remaining inside it.
Because all data is historical, the resolution is simple: **30-day return measurement is permitted to
extend up to 30 days past the end of the evaluation window.** No sample is dropped and no partial
return is used. This must be applied identically to all benchmark baskets.

---

## 5. Data sources

| Purpose | Source | Cost |
|---|---|---|
| Historical DEX trades | Dune (`dex.trades` + aggregator tables, as netting input) | $349/mo (Plus tier) |
| Pool-level OHLCV, dead-token marks | CoinGecko Onchain (Analyst), `include_inactive_source=true`, coverage back to Sept 2021 | $129/mo |
| Quote-asset USD reference | Binance public minute klines (`data.binance.vision`) | Free |
| **Independent ground truth for validation** | **Ethereum archival RPC: receipts, event logs, execution traces, raw balance deltas** | — |

Estimated data cost for the whole of Phase 0: **under $1,000**.

> **Ground truth is raw chain data, not a second vendor.** Two normalisation vendors can share
> assumptions and errors. Dune silently falls back `taker → tx_from` for unmodelled projects, which
> attributes solver-settled trades to the solver. Allium takes the opposite convention to Dune on
> aggregator swaps. Vendor output is the thing being tested, not the reference.

### 5.1 Known coverage gaps to report, not ignore

Measured gap between Dune's decoder coverage and DefiLlama's tracked DEX volume:

```
Ethereum   8.2% of tracked volume has no matching spellbook model
```

These are venues with **no decoder at all** — their trades are invisible, not merely mislabelled.
Tolerable for a falsification test; must be reported as an explicit caveat on every result.

Also note: Dune restricted community contributions in October 2025. The median age of an open
contribution request is ~156 days, and enterprise customers receive priority. You cannot close
coverage gaps yourself on a useful timescale.

---

## 6. Procedure

### 6.1 Step 0 — measure the candidate universe (mandatory, first)

Must complete **before** wallet ranking, before the null distribution, and before any forward
measurement.

For each training window, record:

```
Total active accounts
Accounts with at least one valid buy
Accounts with 20–1,000 valid buys
Eligible EOAs
Eligible Safes
Eligible ERC-4337 accounts
Excluded infrastructure contracts
Final eligible universe size
```

And the distributions of: valid buy count, trading volume, active days, wallet age, EOA vs smart
account share.

**If the eligible universe in a window is below 10,000 accounts:**

```
Window Status: INSUFFICIENT CANDIDATE UNIVERSE
```

That window is not valid, and the four-window design must be revised **before** the main test. A
replacement window may not be selected afterwards from the same data unless the replacement rule was
pre-registered.

### 6.2 Candidate universe definition

```
20 ≤ Valid Buys ≤ 1,000    (within the six-month training window)
```

The lower bound controls selection noise: if wallets with 5 buys are admitted, the top of the
ranking will be entirely 5-buy lucky wallets.

The upper bound is applied to **valid buys**, not total transactions, because approvals, transfers,
and administrative operations inflate transaction counts. 1,000 buys in six months is ~5.5/day —
conservative, retains active traders, excludes likely-automated behaviour.

**Account types included:**

- EOAs
- Safes → `Portfolio Identity = Safe address`; signers are not counted as separate traders
- ERC-4337 smart accounts → `Portfolio Identity = smart account sender`; bundler, paymaster, and
  relayer are never recorded as the trader
- Contract accounts that clearly control a single user portfolio

**Excluded:** DEX routers, aggregator contracts, relayers, bundlers, bridges, protocol treasuries,
public vaults, liquidity pools, market-making contracts, CEX hot wallets, deployers trading their own
token, and any contract whose economic controller cannot be identified.

The test for inclusion: the account must represent **one decision-maker or one portfolio**, not
infrastructure passing through other people's transactions.

Published bot heuristics available for reuse (free, in Dune's spellbook): the `likely_bots` macro
(flag on ≥100 tx and ≥25 tx/hour; or ≥2,500 tx with ≤30 distinct senders; or failed/total > 0.9), and
the inverse "human" filter (**day-of-week skewness ≠ 0** — a retail trader takes weekends off, a bot
has zero skew — plus mean inter-trade gap > 60 minutes). The latter excludes all contracts and must
be modified to retain Safes and smart accounts.

Labelled sets: `labels.mev_ethereum`, `labels.sandwich_attackers`, `labels.arbitrage_traders`,
`dex.sandwiches`, `dex.atomic_arbitrages`.

### 6.3 Walk-forward windows

All four windows are entirely in the past. "Six months forward" means six months after each
historical `T0`, not six months of waiting.

```
Window 1:   Train  Jan 2023 – Jun 2023      Test  Jul 2023 – Dec 2023
Window 2:   Train  Jul 2023 – Dec 2023      Test  Jan 2024 – Jun 2024
Window 3:   Train  Jan 2024 – Jun 2024      Test  Jul 2024 – Dec 2024
Window 4:   Train  Jul 2024 – Dec 2024      Test  Jan 2025 – Jun 2025
```

No information generated after `T0` may be used in selecting wallets at `T0`.

### 6.4 Universe freeze at T0 (survivorship control)

The candidate universe is **frozen at `T0`**. Wallets may not be filtered on the condition that they
are still active at `T0 + 6 months`. A wallet that blew up and went dormant stays in the sample with
its actual result.

After `T0`, a wallet is **never removed** for: exceeding 1,000 buys, sharply increasing activity,
reducing activity, or going fully inactive. Post-`T0` activity is **reported as an output, never used
as a selection filter.** Doing otherwise is look-ahead bias.

Benchmark baskets are drawn from the same frozen `T0` universe, and activity matching uses pre-`T0`
data only.

### 6.5 Wallet selection

```
Selected Wallet Count per Window =
    clamp( 1% of Eligible Universe, minimum = 250, maximum = 1,000 )
```

```
Universe  20,000  →  250 wallets
Universe  50,000  →  500 wallets
Universe  80,000  →  800 wallets
Universe 200,000  →  1,000 wallets
```

A percentage rather than a fixed count keeps **selection pressure approximately constant across
windows**. A fixed 500 could mean the top 2.5% in one window and the top 0.25% in another; those are
not the same experiment.

Ranking is by `buy_quality_30d` computed on the six months before `T0`.

### 6.6 Benchmarks

**Resolved decision, 2026-07-31: matched pairs are the primary benchmark, and the null is built by
permutation within matched sets.** This supersedes the earlier random-basket design.

Each selected wallet is matched to controls drawn from the frozen `T0` universe using **standardised
distance-based matching** across ten dimensions:

```
account type          median trade size
capital deployed      trade frequency
valid buy count       liquidity-band exposure
buy volume            first-hour purchase share
active days
wallet age
```

```
5 primary matched controls        → the benchmark the gate is measured against
5 additional robustness controls  → reported, cannot change the gate
```

Matching may use replacement. The report must show: number of unique controls · control reuse
frequency · effective benchmark sample size · unmatched selected wallets · covariate balance.

```
Target balance:   absolute standardised mean difference < 0.10
```

Also reported, and unable to change the gate: **Random Active Wallets** and **buy-and-hold ETH**. The
naive random basket is retained only as a sanity floor — a result that fails to beat *it* would
indicate something is wrong with the pipeline.

> **All thresholds are measured against the matched controls**, never the naive random basket.
> Beating a set of low-activity, low-capital addresses proves nothing.
>
> Two of the ten dimensions carry more weight than they appear to. **`liquidity-band exposure`**
> matters because a wallet trading only deep pools and one trading only thin pools face different
> return distributions regardless of skill. **`first-hour purchase share`** matters because without
> it, a sniper-heavy selected group would be compared against a non-sniper control and the sniping
> itself would read as skill.

> **All thresholds are measured against the Activity-Matched benchmark**, never the naive random one.
> Beating a set of low-activity, low-capital addresses proves nothing. A June 2026 study of 166,098
> token launches found apparently coordinated "skilled" wallet cohorts returning +132.3% — while
> **activity-matched placebo cohorts returned +216.3%**. The authors' conclusion: the signal was
> selection bias, not skill. Activity matching is the control that distinguishes a real result from
> that artefact.

---

## 7. Gate conditions

A window is `PASSED` only if **both gates** pass. The project enters Phase 1 only if **at least 3 of
4 windows** pass.

### 7.1 Gate 1 — Leader skill persistence

All three conditions, per window:

```
1.  Mean Buy Quality Advantage      ≥ Calibrated Mean Threshold
2.  Median Buy Quality Advantage    > 0
3.  First-Hour Edge Share           ≤ 40%
```

**Condition 2 exists because** long-tail token return distributions are severely skewed. One token
returning 1000% can make a basket look successful when 90% of its buys lost money. Requiring the
median to be positive kills that case.

**Condition 3 — Edge Origin.** The threshold stays at **40%** (resolved decision, 2026-07-31).

> **Its role has changed and this is recorded deliberately.** The 40% figure was calibrated against a
> universe that included long-tail tokens, where most first-hour sniping happens. The addendum (§9.5)
> now excludes long-tail from Ethereum Phase 0 outright, which removes the bulk of what this
> condition was defending against. It still binds for a mid-cap token in its first hour, but that is
> a far smaller population.
>
> The condition is therefore a **cheap backstop, not the primary defence** against uncopyable
> behaviour. That role now belongs to Gate 2 (§7.2), which tests economic copyability directly at
> `design_capital`.
>
> It is kept at 40% rather than tightened because a new number would be chosen by intuition rather
> than measurement — trading one uncalibrated threshold for another — and kept rather than dropped
> because it costs nothing and the mid-cap first-hour case is real.

Computed at **bucket granularity**, not per trade:

```
Bucket Edge Contribution = max(0,
    Bucket Weight × ( Selected Wallet Buy Quality − Matched Benchmark Buy Quality )
)
```

where `Bucket Weight` is that bucket's share of total selected-portfolio buy weight, using the same
`log(1 + trade_value_usd)` formula.

```
First-Hour Edge Share =
    ( Edge Contribution A + Edge Contribution B )
    / ( Edge Contribution A + B + C + D )
```

If `First-Hour Edge Share > 40%`:

```
Edge Origin Status: UNCOPYABLE-DOMINATED
Window Result:      FAILED
```

This is a **hard failure**, not a warning. Wallets that buy in the first block of a token's life and
hold are exactly the population the copyability engine exists to remove; a gate pass driven by them
would evaporate the moment that engine is switched on in Phase 2.

**Small-denominator guard.** If:

```
Total Positive Edge Contribution < 5 percentage points
```

then:

```
Edge Origin Status: INDETERMINATE
Window Result:      FAILED
```

`INDETERMINATE` is not a pass. A window whose edge origin cannot be measured does not count toward
the three required successes.

### 7.2 Gate 2 — Economic copyability

```
Follower-Adjusted Excess Buy Quality > 0  at $1,500,000
Follower-Adjusted Excess Buy Quality > 0  at $2,000,000
```

Both levels. Both positive.

### 7.3 Statistical significance

Each gate must clear its own null distribution:

```
Leader result            > 95th percentile of the Leader Null Distribution
Follower-adjusted result > 95th percentile of the Follower Null Distribution
Empirical p-value ≤ 0.05 in both cases
```

### 7.4 Summary

```
Leader Edge Positive
  AND Follower Edge Positive at design_capital
  AND both statistically significant
  AND at least 3 of 4 windows pass
→ Phase 1 authorised
```

Anything else → Phase 1 not authorised.

### 7.5 The three-state outcome

A raw positive leader edge may not conceal an execution-capacity failure:

```
Gate Result:         PASSED
Capital Feasibility: FAILED
Project Status:      CONDITIONAL REVIEW
```

In `CONDITIONAL REVIEW`, one of the following must be explicitly decided before Phase 1:

- reduce `design_capital`
- restrict the token universe to more liquid assets
- restrict wallets by copy capacity
- reduce base position size
- stop the project in its current form

---

## 8. Null distributions and threshold calibration

### 8.1 Why

`+15pp in 3 of 4 windows` is an arbitrary number until its false-positive rate is measured. Treating
each window as a coin flip gives P(≥3 of 4) ≈ 31%. The real rate under the actual threshold is
unknown — and a pre-registered threshold that random selection clears is worse than no threshold,
because it manufactures confidence.

### 8.2 Construction

**Resolved decision, 2026-07-31: the null is a within-matched-set permutation test.** This supersedes
the earlier random-basket resampling, and follows from the matched-pairs benchmark in §6.6.

Run the **entire Phase 0 pipeline 1,000 times per window per column**, each time **permuting the
selected/control labels within each matched set** and recomputing every gate condition from scratch.

```
For each matched set — 1 selected wallet + its 5 primary controls:
    randomly reassign which member carries the "selected" label
Recompute the full gate on the relabelled population
```

- Same metric, same matching, same rules, all four windows unchanged.
- The permutation preserves each matched set's covariate profile exactly, so the null asks the sharp
  question: **given groups already balanced on all ten dimensions, is the label assignment
  informative at all?** A random basket can only ask the blunter question of whether *some* selection
  of this size could do as well.
- Two null distributions are built: **Leader** and **Follower-Adjusted**.
- Child seeds for every permutation come from §"seeds" — `purpose = "null.<column>.window<N>"`,
  `index = 0..999` — so the whole distribution is reproducible from the master seed and the commit.
- No new data is pulled from Dune. This is relabelling of already-extracted data, so the cost is
  compute time only.

> **Why permutation rather than resampling.** The June 2026 placebo study
> ([arXiv:2607.02795](https://arxiv.org/abs/2607.02795)) found apparently-skilled wallet cohorts
> returning +132.3% while **activity-matched placebos returned +216.3%** — the entire signal was
> selection bias. A random-basket null would not have caught that, because the baskets were not
> matched. Permuting within matched sets is the design that would have.

Per run, per window, record:

```
Mean Buy Quality Advantage
Median Buy Quality Advantage
First-Hour Edge Share
Window Passed: Yes / No
```

**The null gate must be the full three-condition gate**, identical to §7.1. If the null used a
two-condition gate and the real test a three-condition gate, the 95th percentile would refer to a
different experiment and the calibration would be void.

### 8.3 Calibration

```
Null Pass Rate = null runs passing the full gate / total null runs

Final Mean Threshold = the smallest threshold at which Null Pass Rate ≤ 5%
```

Worked example:

```
15pp threshold  →  18% null pass rate
20pp threshold  →   9% null pass rate
24pp threshold  →   4% null pass rate
→ lock the final threshold at 24pp
```

15pp is the **starting value, not a sacred number.** If calibration shows it is loose, it is raised —
even though that makes the project harder to pass.

### 8.4 Ordering (binding)

```
1.  Metric definition finalised and locked
2.  All test parameters pre-registered
3.  Null distribution built on the FINAL robustified metric
4.  Threshold calibrated against the null
5.  Final threshold locked
6.  ONLY THEN: main test on the selected wallets, run once
7.  After observing the main result: nothing changes
```

The null must be built on the final metric **including liquidity-bound pricing**. Calibrating on an
inflated-pricing version and then adding the liquidity bound would mean the calibration belongs to a
different experiment.

---

## 9. Validation gate

The pipeline must prove itself correct **before** it is allowed to compute anything that matters.

> **The null distribution cannot detect implementation bugs.** It is computed by the same code. A
> wrong FIFO rule, a mis-applied liquidity bound, or a missed transaction class affects the selected
> basket and all 1,000 random baskets *identically*. It does not appear as an anomaly. The 95th
> percentile is computed, the number looks healthy, and the gate answers the wrong question — and
> because the design forbids post-hoc changes, the bug becomes permanent.

### 9.1 Order (binding)

```
Golden Dataset
      ↓
Known-Answer Tests
      ↓
Cross-Source Reconciliation
      ↓
Independent Validation
      ↓
Code and Data Freeze
      ↓
Null Distribution
      ↓
Main Test
```

### 9.2 Golden dataset

Minimum 30, preferably **50 accounts**, deliberately covering: full buy-and-sell, multiple partial
sells, multi-hop routes, multi-pool trades, fee-on-transfer tokens, dead pools, first-hour purchases,
thin liquidity, failed transactions, circular arbitrage, Safe, ERC-4337, transfers alongside swaps,
and tokens with multiple pools and liquidity migration.

For each account, a human records the expected output from transactions, event logs, traces, and
actual balance changes. **The golden set is built and frozen before the final pipeline output is
seen.**

**Acceptance — buy/sell events:**

```
Precision = 100%
Recall    = 100%
```

No valid buy missed. No spurious buy created. No sell recorded as a buy. No circular arbitrage
recorded as a position. No failed transaction included. **A single unresolved false positive or false
negative fails the gate.**

**Acceptance — deterministic fields (exact match required):**

```
Transaction Hash · Block Number · Wallet Address · Token Address · Pool Address
Direction · Raw Token Quantity · Raw Quote Quantity · FIFO Lot Assignment
Realized / Open Status
```

Raw token amounts must match at the raw-unit level, with no percentage tolerance, except for
differences arising from formally specified rounding rules.

**Acceptance — USD values:**

```
Maximum relative error per event                      0.5%
Maximum relative error in wallet realized value       0.5%
Maximum absolute difference in Buy Quality            0.5 percentage points
```

Pool-level marking tolerance is likewise 0.5%, provided both computations use the same block, the
same pool, and the same liquidity-bound rule.

Differences above tolerance must be **found and fixed**. Averaging errors away, or ignoring many
small discrepancies, is not permitted.

### 9.3 Known-answer tests

Synthetic cases whose answers are fixed before the code runs:

```
Simple Buy + Full Sell          Multiple Buys + Partial Sell
Multi-hop Buy                   FIFO Allocation
Open Position at Day 30         Dead Pool
Thin but Live Pool              Liquidity-Bound Marking
Fee-on-Transfer Token           Failed Transaction
Circular Arbitrage              Internal Transfer
Multiple Pools for One Token    Pool Migration
First-Hour Classification       End-of-Window 30-Day Extension
```

```
100% of known-answer tests must pass
```

No failing test may be waived as an "edge case." For deterministic logic (FIFO, net balance change,
failed-transaction exclusion) the output must equal the pre-determined answer exactly. Only machine
rounding error is tolerated in numeric results.

### 9.4 Cross-source reconciliation

Reconcile the normalised source (Dune / Spellbook) against **raw chain data** — receipts, event logs,
execution traces, raw balance deltas.

On the golden set:

```
Supported transaction coverage      100%
Unexplained missing trades          0
Unexplained extra trades            0
Raw balance delta mismatches        0
```

On an additional random sample of ≥200 accounts:

```
Event agreement            ≥ 99.5%
Notional value agreement   ≥ 99.5%
```

Every remaining difference must fall into a documented category (venue without decoder, unusual token
behaviour, incomplete trace, fee-on-transfer, rebase, contract not covered). **Unexplained
differences may not be silently dropped.** The notional share of uncovered trades must be reported
per window.

> No public benchmark of DEX decoder accuracy exists. This reconciliation is a study nobody outside
> has run for you, and vendor figures are unverified.

### 9.5 Independent validator

The validator must not have written the pipeline's transaction classification, FIFO, or valuation
logic.

```
Implementer:          pipeline and automated tests
Independent Validator: golden dataset, raw-data verification,
                       cross-source reconciliation, sign-off on the gate report
```

**If the team is one person**, three substitute controls are mandatory:

1. The golden dataset is built and frozen **before** the pipeline is written, without seeing its
   output.
2. Golden-set review is a **blind review** — system output is not seen until the manual computation
   is complete.
3. At least 10–15 complex accounts are reviewed by an **independent external specialist**.

If even limited external review is impossible:

```
Validation Status:     NOT INDEPENDENT
Main Test Execution:   BLOCKED
```

### 9.6 Freeze manifest

Before the null distribution runs, freeze:

```
Source code commit          Dataset snapshot
Golden dataset version      Protocol coverage list
Token and pool rules        Price and marking rules
Validation report           Random seed policy
```

The main test and the null runs must use the **same commit** and the **same shared functions**.

### 9.7 Bug discovered after freeze

```
Current Run Status: INVALIDATED
```

The previous result may not be patched or partially corrected. Required:

1. Fix the bug.
2. Register a new code version.
3. Re-run the **entire** validation gate.
4. Rebuild the null distribution from scratch.
5. Re-run the main test with the new version.

This is not "changing parameters after seeing the result," provided the bug is real, documented, and
the whole experiment is repeated. **Selectively using the old or the new result is prohibited.**

### 9.8 Gate summary

```
Golden Set Buy/Sell Precision            100%
Golden Set Buy/Sell Recall               100%
Known-Answer Tests Passed                100%
Raw Quantity Mismatches                  0
FIFO Assignment Mismatches               0
Per-Event USD Error                      ≤ 0.5%
Wallet Buy Quality Difference            ≤ 0.5 pp
Random Reconciliation Event Agreement    ≥ 99.5%
Unexplained Golden-Set Differences       0
Independent Review                       Completed
```

Failure of any condition:

```
Validation Gate:     FAILED
Null Distribution:   NOT AUTHORIZED
Main Test:           NOT AUTHORIZED
```

---

## 10. Required outputs

Beyond the gate decision, these must be reported. Several are decision-relevant independently of
whether the gate passes.

**Per wallet and aggregated over the selected basket:**

```
Realized Share          share of value from actual sells
Marked Share            share dependent on pool-level marking
Dead / Zeroed Share     share marked to zero
```

If only 20% of volume is realized and 80% rests on marking, the gate result lacks credibility even if
it looks strongly positive.

**Wallet churn:**

```
Churn Rate = selected wallets with no valid buy in the forward period
             / total selected wallets
```

Reported in three states: `Active`, `Reduced Activity`, `Inactive`. A wallet that fell from 100
trades to 1 is effectively dead to the system even though it is technically alive. If 60% of top
wallets go quiet within six months, the system has a churn problem no engine fixes.

**Per capital level (all five):**

```
Raw Buy Quality              Follower-Adjusted Buy Quality
Mean Copy Retention          Median Copy Retention
Positive Trade Rate          Realized / Marked / Dead Share
Unexecutable Trade Share
```

**Diagnostics — reported, never able to change the gate:**

```
Absolute profit ranking          Simple wallet return
7-day buy return horizon         90-day buy return horizon
Buy win rate                     Median return
Tail loss                        Bucket A (first 10 blocks) in isolation
Sensitivity by activity band:  20–99 / 100–499 / 500–1,000 valid buys
```

Ranking by absolute USD profit and by percentage return are computed as diagnostics. Cost is near
zero — the same data with a different `ORDER BY` — and if `buy_quality` fails while they pass, that
is informative. **Only `buy_quality` decides the gate.**

Reporting a diagnostic and then using it to overturn a gate result is the failure mode this entire
document exists to prevent.

---

## 11. Interpretation constraints

### 11.1 Why Ethereum, and what that limits

Chain selection, with reasons recorded:

- **Base — excluded.** Base launched publicly in August 2023. Window 1 has no training data and
  Window 2 has only partial data. Base can supply at most 2 clean windows of 4, and the gate requires
  3. Excluded because it is incompatible with the test design, not because it is a poor chain.
- **Solana — excluded.** Trader attribution is unreliable. Jupiter sponsors gas for wallets holding
  under 0.01 SOL on trades above ~$10, and JupiterZ market makers pay fees from per-quote-varying
  addresses, while Dune sets `trader_id = tx_signer`. Gasless swaps are therefore attributed to
  Jupiter's gas wallet or to a market maker, creating phantom mega-wallets and erasing real users —
  concentrated precisely among small and new wallets. Separately, Dune's Solana macro resolves swap
  legs by fixed positional offsets and **silently drops** trades whose transfer pattern does not
  match. Rankings built on this are not defensible in either direction.
- **Arbitrum — secondary diagnostic only** (§11.2).
- **Ethereum mainnet — selected.**

Reasons for Ethereum:

1. **Full historical coverage** for all four windows, with the most mature decoder coverage (46
   spellbook models, 35 protocol families) and Curve present (Curve is absent on Arbitrum and Base).
2. **Measurably the least bot-concentrated.** Senders with ≥20 transactions account for:

   ```
   Solana     2–3% of senders  →  52–70% of transactions
   Arbitrum   1.1%             →  37.4%
   Base       2.3%             →  29.9%
   Ethereum   0.3%             →   6.1%
   ```

   Roughly an order of magnitude cleaner, measured over the longest sample window.
3. **Trade-size composition matches the target capital profile.** Average DEX trade: Ethereum $2,980,
   Arbitrum $620, Base $532, Solana $99. Median Ethereum trade $887, with 24.1% above $10,000.
4. **Capacity fits.** Measured total AUM capacity on Ethereum is roughly **$7.9M** (majors $4.56M,
   mid-cap $3.30M), about 4× headroom over `design_capital`.

> **Correction to an earlier assumption.** Gas is *not* the mechanism. Median Ethereum swap cost is
> **$0.053**; a round trip is $0.054. The old "$10–50 gas per trade" figure no longer holds — the gas
> limit is 60M and blocks run 34–47% full. Slippage is the binding constraint on all four chains, by
> two to three orders of magnitude. Ethereum's larger trade sizes are a user/capital composition
> effect, not a fee effect.

**The hard limit this creates:**

```
Measured Ethereum long-tail capacity = $0
```

That is not rounding. The leader's own footprint consumes the entire slippage budget before a single
copier trades — median long-tail `S₁` on Ethereum is $698. This holds across every assumed edge level
(5%, 10%, 15%, 30%). **On Ethereum, the wallet signal can only ever concern liquid and mid-cap
assets** — which is consistent with the target portfolio, but is also where on-chain wallet signal is
weakest and where the competition is real quantitative funds. This is accepted, not worked around.

### 11.2 Arbitrum as secondary diagnostic

Arbitrum may be run as an optional secondary analysis if the cost is low. It:

- does **not** participate in the main gate;
- may **not** be used to rescue a weak Ethereum result;
- does not permit thresholds to be changed after results are seen;
- is reported only as a check on generalisability.

This must be pre-registered as a secondary diagnostic, not introduced after Ethereum fails.

### 11.3 Wording of a negative result

If the gate fails, the correct conclusion is:

```
No sufficient persistent and copyable wallet-selection edge was found
for the Ethereum Mainnet target population and capital profile.
```

**Not:**

```
Wallet-based copy trading does not work on any blockchain.
```

Phase 0 says nothing about whether copyable alpha exists on Base, Solana, or in memecoin markets.

### 11.4 Wording of a negative leader result specifically

If Gate 1 fails while published work suggests it should pass, that triggers **investigation of the
data and the implementation** — it is not automatic proof of a bug. The published study ran on Solana
memecoin markets with a different definition of profitability; this test runs on Ethereum with
`Historical Copyable Buy Quality`. In that study, LASSO had limited discriminative power.

---

## 12. Risks

### 12.1 Regulatory and legal

The original specification's risk section contains no legal or regulatory risk. It must.

- Through Phase 5, the system is **internal only**. No signal or allocation recommendation is shown
  to any third party. Under that constraint, investment-advice regulation is not engaged.
- The moment output reaches customers, §14 of the specification ("recommended portfolio allocation is
  5%") **is investment advice**, a licensed activity in most jurisdictions.
- ESMA Q&A 2463 (April 2025): auto-executing third-party signals with discretion constitutes
  **portfolio management under MiCA**. See also ESMA Supervisory Briefing ESMA35-42-1428 (March 2023)
  and IOSCO Final Report FR/06/2025 on imitative trading.
- No enforcement action against a crypto copy-trading platform was found for 2025–26. Guidance only.
  Claims that regulators have "cracked down" are unsupported.

A customer-facing product is a separate phase and a separate product, conditional on five proofs:
out-of-sample persistence, profitability after costs, risk-engine behaviour under real conditions, a
credible track record, and a completed legal and licensing review.

### 12.2 Staffing risk

The rigour of this design creates a hiring bar that is itself a project risk. The primary builder
profile (senior quant *and* on-chain data engineer) is scarce. The independent validator is harder:
competent enough to hand-verify on-chain accounting, not the builder, and available part-time
externally.

**The most likely cause of death for this project is now "two people were not found," not "the
hypothesis was wrong."** That is a better failure than starting badly, but it must be recorded rather
than discovered.

### 12.3 Data risk

Blockchain data may be incomplete, delayed, or incorrectly decoded — with measured, specific
instances documented in §5.1, §11.1, and §13.

### 12.4 Model risk

The scoring approach may overfit. The null distribution addresses statistical overfitting; it does
**not** address implementation error (§9).

### 12.5 Berk–Green: the product degrades its own signal

Wallet alpha has persisted partly because wallets take no outside capital. Copy flow **is** the
capital-chasing-performance mechanism. On a thin pool, capacity is exhausted at the first follower.

**Building the product degrades the signal the product depends on. No backtest on historical data can
measure this.** It must be recorded as a known, unmeasurable risk.

### 12.6 Adversarial targeting

Wallets engineered to attract copy traders and then dump on them are documented, not folklore.
Bundle bots appear in roughly a quarter of studied projects, and vendors' own documentation
acknowledges the pattern. Past-PnL rank is an adversarially targeted ranking, not merely a noisy one.
The `Edge Origin` condition (§7.1) is a partial defence; it is not a complete one.

### 12.7 Identity risk

Address ≠ agent. An operator splitting buys across many wallets makes per-wallet cost basis wrong by
construction and inflates the multiple-comparisons denominator at near-zero cost. Entity clustering
is deliberately out of scope for Phase 0; this is a known limitation of the result.

---

## 13. Research findings that shaped these decisions

Recorded so the reasoning survives the people who made it.

### 13.1 The premise splits in two — and this has been measured

Luo, Feng, Xu & Liu, *Resisting Manipulative Bots in Meme Coin Copy Trading*, ACM Web Conference 2026
— [arXiv:2601.08641](https://arxiv.org/abs/2601.08641). 6,000 pump.fun projects, chronological 70/15/15
split, label = sign of realized profit, features = past profitability across the wallet's prior 15
coins. Test-set returns **with market frictions** (Figure 8):

| Selection method | Smart-money return | Copier return |
|---|---|---|
| Lasso | **+9.2%** | **−5.8%** |
| Neural net | +6.1% | −7.8% |
| XGBoost | +4.2% | −8.3% |
| Multi-agent LLM (zero-shot) | +6.2% | −0.2% |
| Multi-agent LLM (tuned) | +14.4% | **+2.9%** |

Left column: wallet skill is real, persistent, and detectable by a simple regression on past
profitability. Right column: the sign flips for four of five methods.

The mechanism is the **imitation penalty** — on a strictly convex curve, the copier necessarily
trades at a worse point. It is a theorem, not a statistic; it holds under perfect wallet selection.

Caveats: the venue is pump.fun bonding curves, the most convex and thinnest possible — the imitation
penalty is maximal there and the absolute numbers do not transfer to Ethereum majors. The copier
model assumes a single instantaneous copier with no crowding, so even +2.9% is optimistic.

**This finding is why both columns are gates (§7).**

### 13.2 Copy trading measured at scale

Joseph, Riedl, Pentland & Moro — [arXiv:2507.01817](https://arxiv.org/abs/2507.01817). eToro: 87.5M
trades, 825k mirroring relationships, 164,634 traders.

```
Traders who never mirror              −1.15 bps mean per-order ROI
Traders who mirror                   −10.98 bps
Mirrored trades specifically         −61.24 bps
Same people's own self-initiated     −6.88 bps
```

Copied trades lost ~9× more per order than the same traders' own trades. Correlation between a
leader's 30-day performance and their popularity: **r = 0.11**. People copy who is visible, not who
is good.

Supporting: 97.04% of CEX lead traders had positive own PnL; only 43.61% produced positive follower
PnL. Copy trading increases risk-taking (Apesteguia, Oechssler & Weidenholzer, *Management Science*
66(12)). Leaders who gain followers become more susceptible to the disposition effect (Pelster &
Hofmann, *JBF* 94).

### 13.3 Activity-matched placebos overturn apparent skill

[arXiv:2607.02795](https://arxiv.org/abs/2607.02795), June 2026. 1,578,333 buyer observations across
166,098 token launches; 1,012 persistent wallet cohorts from 2,965 addresses.

```
Real "coordinated" cohorts                +132.3%
Activity-matched placebo cohorts          +216.3%
```

The placebos did better. The authors conclude the apparent coordination signal was selection bias,
not causal skill. **This is why the 40pp/15pp thresholds are measured against the activity-matched
benchmark and not a naive random one (§6.6).**

### 13.4 Price data for long-tail and dead tokens is unreliable

Measured coverage across 171 long-tail tokens:

```
DefiLlama       21.6% current price,  16.4% historical
GeckoTerminal   100%
```

DefiLlama misses live tokens with $3.9M of liquidity; HAWK (~$490M peak market cap) returns empty for
current price, historical price, and first price.

CoinGecko's coin-level API auto-deactivates a coin after 30 days without trading and then denies
historical access — vendor-imposed survivorship bias exactly where losses concentrate. **Pool-level
history survives**: a HAWK/SOL pool with $8.29 of remaining liquidity returned 181 daily candles.
CoinGecko Onchain exposes `include_inactive_source=true` for precisely this.

Dune's `prices_dex.minute` is interpolated from hourly VWAP anchors and forward-filled up to 48h; the
derivation is closed-source and Dune no longer exposes per-block prices at all.

**This is why marks are pool-level, dead pools are zeroed, and the metric avoids long-tail oracles
entirely (§4.4, §4.6).**

### 13.5 Trader attribution is broken in specific, documented ways

- **Dune's core macro** contains `coalesce(base_trades.taker, base_trades.tx_from) AS taker`. Any
  project without an explicit taker silently attributes to the transaction sender — the solver, for
  solver-settled trades.
- **0x Settler emits no trade events at all.** The trader lives in calldata at fixed byte offsets;
  amounts are partly estimated.
- **CoW Protocol's model overwrites `tx_from` with the trader**, contradicting the column's own
  documentation.
- **UniswapX appears in neither Dune sector table.**
- **1inch LOP v4** emits `OrderFilled(bytes32, uint256)` — no maker, no amounts.
- **Allium keeps `from_address` and `swapper_address` as separate columns** — the correct shape, and
  the model the pipeline should follow.

**This is why buys are detected by transaction-level balance netting (§4.2) rather than read from
vendor taker fields.**

### 13.6 Capacity is the binding constraint, measured

Copy-trade-adjusted share of Ethereum's **top 120 pools by volume** that still keep price impact
under 1%:

```
Portfolio   Weight   Position    Effective (3×)   TVL needed    % of top-120 pools
  $100k       2%      $2,000        $6,000          $1.2M            40.0%
  $250k       5%     $12,500       $37,500          $7.5M            18.3%
  $500k       5%     $25,000       $75,000         $15.0M             9.2%
    $1M       5%     $50,000      $150,000         $30.0M             5.0%
    $2M       2%     $40,000      $120,000         $24.0M             5.8%
    $2M       5%    $100,000      $300,000         $60.0M             1.7%
```

The denominator is flattering — these are the most liquid pools on the chain. Across all Ethereum
pools the true fraction is dramatically lower. **The cliff sits between $250k and $1M.**

Total AUM capacity by chain: Ethereum ~$7.9M, Base ~$10.6M, Solana ~$2.0M, Arbitrum ~$1.3M. Ethereum
long-tail is $0 at every assumed edge level.

### 13.7 Base rates for calibrating expectations

- Of 13.4M pump.fun wallets, **0.4%** ever cleared $10,000 realized profit; **0.002%** cleared $1M.
- Nansen's entire "Smart Money" universe is roughly **5,000–10,000 wallets globally** (unofficial).
- On eToro, only ~**1%** of retail accounts ever attracted a single follower.
- Barber, Lee, Liu & Odean (2014), Taiwanese day traders: top-500 earn **61.3 bps/day** vs −11.5 bps
  for the bottom, but "**less than 1% of the day trader population is able to predictably and
  reliably earn positive abnormal returns net of fees**."
- Barras, Scaillet & Wermers (2010): with false-discovery correction, **75% of mutual funds have zero
  alpha** — in a domain with far less noise and far longer track records than crypto.
- pump.fun's monthly profitable-trader share swung **30.1% (Jun 2025) → 73.3% (Apr 2026)** on market
  regime alone. Any "top trader" leaderboard sampled in a rising market is largely selecting for
  having been long. **This is why four windows across different regimes are required.**

The 200-wallet target may exceed the population that actually exists. Phase 0 should measure this,
not assume it.

### 13.8 The market itself has voted against naive copying

Solana trading-terminal and bot fees fell from **$293.9M/month (Jan 2025) to ~$27–33M (Jun–Jul
2026)** — an ~89% collapse. Solana DEX volume fell 84% from peak.

The revenue leader, Axiom (~43% of category fees), **offers no copy trading at all** — only wallet
tracking, alerts, and manual execution. The products with the most sophisticated auto-copy
implementations (Maestro, Trojan, Bloom, Photon) are all down 95%+ from peak. BullX suspended trading
in June 2026.

Trojan's own documentation is the clearest statement of the failure mechanism: against snipers "you
are becoming their exit liquidity… you will land several blocks behind, buying the top of their
candle while they dump on you," and wallets using custom programs are undetectable and uncopyable.
Their advice is to raise slippage "especially if it's a heavily copied wallet" — i.e. being copied
destroys the edge.

**Read as support for this project's design, not against it:** the market says value lies in
discovery and signal quality, not in blind automated execution. That is the distinction §13 and §14
of the original specification already draw.

### 13.9 Source reliability during this research

Two fabricated sources were caught and discarded during the research that produced this document. In
one case, a PDF summarisation returned confident verbatim quotes attributed to an arXiv paper that
contained none of them. In another, a precise-looking data table was invented for a real paper whose
actual figures were entirely different.

Separately, this document's own author twice reported "no crypto study of trader skill persistence
exists." That was **wrong** — the study is §5 of [arXiv:2601.08641](https://arxiv.org/abs/2601.08641),
a paper already cited elsewhere in the same research. Two independent adversarial reviews found it.

**Implication for the project:** the information environment around "smart money" is full of
unsupported claims in both directions. This is the strongest practical argument for testing the
premise on your own data rather than relying on secondary sources — which is what Phase 0 is.

---

## 14. What could not be verified

- Current Ethereum private-orderflow share. The measurement infrastructure was dismantled
  (Blocknative shut down June 2026; Flashbots' transparency dashboard returns HTTP 410). Best
  available figure: ~80% of DeFi transactions private, early 2025.
- Any vendor-independent measurement of follower-versus-leader fill price, on any platform.
- Any published alpha-decay-versus-latency curve for on-chain wallets.
- Any research on copy-trading bots themselves being front-run.
- `dex.trades.amount_usd` NULL rate — unpublished. Should be measured before relying on it.
- Distinct monthly DEX trader counts per chain (the §6.1 Step 0 measurement resolves this for
  Ethereum).
- Assumed gross edge per round trip, used in the capacity model of §13.6. It is the largest driver of
  those numbers and is entirely assumed. It deserves measurement against real leader-wallet PnL.

---

## 15. Execution

### 15.1 Roles

```
Product / Research Owner    owns hypotheses, gates, and the final decision
Primary Builder             Senior Quant / On-chain Data Engineer, full-time
Research / Data Support     part-time: data review, documentation, golden set
Independent Validator       external, part-time, separately budgeted
```

Required skills for the Primary Builder: advanced SQL on Dune and Spellbook models; Python for
processing, simulation, and statistical testing; EVM internals — event logs, traces, balance deltas;
DEX pools and concentrated liquidity; FIFO and position accounting; backtest design without
look-ahead bias; bootstrap and null-distribution testing; reproducible, versioned pipelines.

The Independent Validator should join in **week 1** and build or approve the golden set before the
pipeline is complete. Bringing a validator in at the end to sign a report is not independent
validation.

### 15.2 Schedule (target 10 weeks, planned maximum 12)

```
Week 1       Finalise pre-registration · assign Builder and Validator
             Run Step 0 · measure candidate universe · freeze eligibility definition
Weeks 1–3    Build golden dataset · manual review of 30–50 accounts
             Cover Safe, ERC-4337, fee-on-transfer, pool migration, other edge cases
             (Builder may prepare extraction infrastructure but must not tune logic
              selectively against golden-set output)
Weeks 3–7    Transaction netting · buy/sell classification · FIFO
             Pool-level marking · liquidity-bound pricing · token-age buckets
             Leader Buy Quality · Follower-Adjusted Buy Quality at five capital levels
             Wallet ranking · activity matching
Weeks 6–7    Known-answer tests · resolve all discrepancies · complete automated tests
Weeks 7–8    Cross-source reconciliation · 200-account sample · coverage-gap report
Week 9       Independent review · resolve findings · re-run validation gate
             Freeze commit and dataset
Week 10      Build both null distributions · ≥1,000 runs · calibrate thresholds
             Run main test ONCE · produce Go / Conditional Review / Stop report
Weeks 11–12  Reserve for decoder gaps, incomplete data, golden-set discrepancies,
             trace problems, or a required validation re-run
```

### 15.3 Phase 0 Lite — rejected

A reduced-rigour run to "see the size of the number" is **not** performed.

- No external deadline is on record.
- Early observation of the result contaminates a pre-registered design.
- A raw result can steer later decisions without anyone intending it.
- A lite version is most likely to produce a false positive **specifically on uncopyable trades and
  pricing errors** — the exact failures the gates exist to catch.

```
Phase 0 Lite: REJECTED
Reason: No confirmed external deadline
```

If the full 10–12 week run is not resourceable, the correct action is to **pause the project**, not to
run a weak test whose result would later be cited as evidence.

### 15.4 Preconditions for start

Phase 0 begins only when all four are true:

```
Primary Builder assigned
Independent Validator assigned
Data budget approved
10–12 week capacity reserved
```

Until then:

```
Phase 0 Status: DESIGNED, NOT READY FOR EXECUTION
```

---

## 16. Deliberately deferred

The following are **not** designed and must not be designed before Phase 0 returns a result.
Designing them first is precisely the error this document exists to prevent.

- Phases 1–6 in detail
- Entity clustering and strategy clustering (specification §5.8, §5.9)
- The risk engine (§5.12)
- Signal generation and portfolio construction (§5.10, §5.11)
- **The 200-wallet set is a function of capital.** A wallet copyable at $250k may not be copyable at
  $2M. Selecting at $2M restricts you to liquid-asset traders — where edge is smallest. Selecting at
  $250k gives a larger universe but requires re-selection when scaling. This is an open decision for
  Phase 2.
- The customer-facing product, its regulatory review, and its licensing

---

## 17. Sign-off

Freezing this document means: no threshold, definition, parameter, window, or rule below may change
on the basis of an observed result.

```
Pre-registration frozen on:      2026-08-16
Frozen at commit:                4bbae13
Product / Research Owner:        ____________________
Primary Builder:                 ____________________   ticket 01 — unassigned
Independent Validator:           ____________________   ticket 02 — unassigned
Validation Gate passed on:       ____________________
Main test executed on:           ____________________
```

**What was frozen.** The text of this document as it stood at commit `4bbae13`, together with
`decision-engine-addendum.md` at the same commit. The 53 parameters it fixes are loaded into
`src/phase0/parameters.py`, each one carrying the § it came from, and every downstream stage reads
its thresholds from that table rather than restating them.

**These two lines were written after the freeze, and they change no rule above.** They record a
freeze that had already happened, so the document at HEAD necessarily differs from the document at
`4bbae13` — by exactly this block and nothing else. A reader checking which text was frozen should
read `4bbae13`, not HEAD, which is the entire reason the commit hash is recorded rather than a
branch name.

**The authoritative record is not this block.** It is the hash-chained audit log written when the
freeze was performed:

```
#0  governance.transition  ->  PARAMETERS_FROZEN   Nimbo
#1  parameters.freeze          4bbae13, 2026-08-16  Nimbo
#2  parameters.change_refused  gate.starting_mean_threshold 0.15 -> 0.10, REJECTED
```

Entry #2 is the demonstration, not a hypothetical: an attempt to lower the starting mean threshold
on the grounds that 15pp "looks hard to clear" was refused, and the refusal is in the chain. This
block is a human-readable transcription of that record; where the two disagree, the chain is the one
that cannot be edited without saying so. Verify it with `phase0 audit`.

**Three lines are blank because nobody is assigned**, and no code path in this repository can
produce a name for them. The Primary Builder and Independent Validator lines are tickets 01 and 02,
and §9.5's independence requirements mean the Validator cannot be named retrospectively at sign-off
time — that is the one thing ticket 02 exists to make structurally impossible.
