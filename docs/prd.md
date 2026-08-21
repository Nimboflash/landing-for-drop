# Smart Wallet Copy Trading & Portfolio Intelligence System — PRD

**Status:** `DESIGNED — NOT READY FOR EXECUTION`
**Scope of this document:** Phase 0 (the hypothesis falsification test) plus the decision engine and
deployment models that Phase 0 gates.
**Companion documents:** [`phase-0-preregistration.md`](./phase-0-preregistration.md) ·
[`spec-amendments.md`](./spec-amendments.md) · [`decision-engine-addendum.md`](./decision-engine-addendum.md)

> Reading order for someone new: this file, then the pre-registration (the frozen protocol), then the
> amendments (what changed from the original specification), then the addendum (deployment, governance,
> capital model). Where this PRD and the pre-registration disagree, **the pre-registration wins** —
> it is the document that gets frozen.

---

## Problem Statement

I want to allocate $100,000–$250,000 today, and up to $1.5–2M eventually, on the basis of what
demonstrably skilled on-chain traders are doing. Every existing route to that goal is untrustworthy in
a way I cannot check from the outside.

**The leaderboards are selecting for luck and for being long.** pump.fun's monthly profitable-trader
share swung from 30.1% to 73.3% on market regime alone; a "top trader" list sampled in a rising market
is largely a list of people who were long. Of 13.4M pump.fun wallets, 0.4% ever cleared $10,000 of
realized profit. The population I am being sold access to may not exist at the size claimed.

**Even when skill is real, copying it loses money.** This is the part nobody tells me. Measured across
6,000 projects with market frictions, smart-money returns were positive for every wallet-selection
method tested — and copier returns were *negative* for four of the five. On eToro, across 87.5M trades
and 825k mirroring relationships, mirrored trades lost 61.24 bps per order against −6.88 bps for the
same traders' own trades: roughly nine times worse. Only 43.61% of CEX lead traders with positive own
PnL produced positive follower PnL. The mechanism is not incompetence, it is arithmetic — on a strictly
convex price curve the copier necessarily trades at a worse point than the leader, and for a
constant-product pool a copier trading the leader's size pays **3.1× the leader's slippage**.

**The apparent skill may be pure selection bias.** A study of 166,098 token launches found
"coordinated skilled" wallet cohorts returning +132.3% — while activity-matched placebo cohorts
returned **+216.3%**. The placebos did better. Without an activity-matched control I cannot tell a
result from an artefact, and no product on the market shows me one.

**The data itself is wrong in ways that flatter the answer.** Vendor DEX tables emit one row per pool
hop, so a `USDC → WETH → TOKEN_A` route manufactures a phantom "bought WETH" event; a single swap has
been counted six times. Trader attribution silently falls back to the transaction sender, so
solver-settled trades are attributed to the solver. Coin-level price APIs deactivate a token after 30
days of inactivity and then deny historical access — survivorship bias precisely where the losses are.
Daily prices are forward-filled for up to 30 days, so a rugged token shows as flat rather than −100%.
Roughly 8.2% of Ethereum's tracked DEX volume has no decoder at all: those trades are invisible, not
merely mislabelled.

**And I cannot buy my way out of the analysis.** The specification I started from describes twelve
engines and 4–6 months of work, and obtains its first real evidence about its own founding premise in
Phase 3 or 4 — after nearly everything is built. If the premise is false, I find out having spent the
entire budget.

What I actually need to know, before I build anything: **does a wallet's past buy quality predict its
future buy quality out of sample, and if it does, does any of that advantage survive being copied at
my capital?** Those are two separate questions. The published evidence says the first is probably yes
and the second is probably no. I need to test both on my own data, on a chain I can trust, with a
threshold I set *before* I see the answer — and I need the test to be cheap enough to fail.

---

## Solution

A **machine-driven wallet intelligence and decision engine**, whose first deliverable is not a product
but a falsification test that can kill the project for under $1,000 of data cost in 10–12 weeks.

The engine does five things, in order:

1. **Discovers** potentially skilled Ethereum wallets from raw DEX activity.
2. **Verifies** whether their historical skill persists out of sample, against activity-matched
   controls drawn from the same frozen universe.
3. **Tests** whether their trades remain economically copyable after price impact, slippage, DEX fees,
   gas, and execution delay, at five capital levels up to `design_capital`.
4. **Rejects** wallets, assets, and trades that are not copyable at the required capital level.
5. **Emits a deterministic decision** — `GO`, `CONDITIONAL REVIEW`, or `STOP` — that no person and no
   AI agent may reinterpret.

**Phase 0 runs first.** Four walk-forward windows across four market regimes (Jan 2023 – Jun 2025),
all entirely in the past — "six months forward" means six months after a historical `T0`, not six
months of waiting. Both gates must pass in at least 3 of 4 windows: leader skill persistence *and*
economic copyability at $1.5M and $2M. Passing does not prove the product makes money; it proves the
hypothesis has enough support to justify Phase 1.

**The metric avoids the data problems rather than working around them.** *Historical Copyable Buy
Quality* measures the 30-day return of each valid buy in the **quote asset actually used** — USDC,
USDT, WETH, ETH, WBTC — so no price oracle is ever required for the long-tail token. Positions still
open at day 30 are marked at pool-level on-chain OHLCV, **bounded by extractable value given real pool
liquidity**. Dead pools are marked to **zero**, not to the last stale price. Partial sells are FIFO.
Wallet-level aggregation weights by `log(1 + trade_value_usd)` so one whale purchase cannot carry a
wallet's score.

**Buys are reconstructed, not read.** The pipeline nets signed amounts at the
`(transaction, portfolio_owner, token)` level, so intermediate route tokens cancel out and only the
user's actual intent survives. It keeps `tx_sender` and `portfolio_owner` as separate fields that are
never allowed to overwrite each other. Circular arbitrage is detected and excluded. Failed transactions
are filtered before anything else.

**The threshold is calibrated, not asserted.** "+15pp in 3 of 4 windows" is an arbitrary number until
its false-positive rate is measured. The entire pipeline is re-run 1,000 times per window per column
with random wallets in place of selected ones, and the final threshold is set to the smallest value at
which the null pass rate is ≤ 5%. If 15pp turns out to be loose, it is raised — even though that makes
the project harder to pass.

**Nothing measures anything until the pipeline proves itself correct.** A four-layer validation gate —
golden dataset of 30–50 hand-traced accounts at 100% precision and recall, known-answer tests at 100%
pass, cross-source reconciliation against **raw chain data** (not a second vendor), and independent
validation by someone who did not write the classification, FIFO, or valuation logic — runs *before*
the null distribution, which runs before the main test. The null distribution cannot catch
implementation bugs: it is computed by the same code, so a wrong FIFO rule corrupts the selected basket
and all 1,000 random baskets identically and shows up as nothing at all.

**The discipline is mechanised, not agreed.** An Experiment Governance Module freezes definitions and
parameters, stores code/data/config/seed versions, refuses threshold changes after results are
observed, invalidates the entire run when a real bug is found post-freeze, and generates the final
machine-readable decision. Operations administrators may stop a process for security, data corruption,
or infrastructure failure. They may not modify the research result.

**If Phase 0 passes**, the same validated core supports two deployment models — a managed basket/fund
where copyability is computed against pooled `strategy_aum`, and a recommendation-only service that
answers per-user with `BUY / SELL / HOLD / WAIT / NOT ECONOMICALLY EXECUTABLE`. Both sit after Phase 5
and remain conditional on five proofs, including a completed legal review. Until then the system is
internal only and shows no signal to any third party.

---

## User Stories

### Research protocol and governance

1. As a **Research Owner**, I want the founding premise stated as two separable hypotheses — H1 leader
   skill persistence and H2 economic copyability — so that a failure tells me *which* claim broke
   rather than just that the project did not work.
2. As a **Research Owner**, I want both hypotheses to be independent gates that must both pass, so that
   a real but uncopyable edge is recorded as a failure instead of being shipped.
3. As a **Research Owner**, I want a pre-registration document frozen at a named commit before any
   measurement runs, so that no threshold, definition, window, or rule can change on the basis of an
   observed result.
4. As a **Research Owner**, I want Phase 0 inserted ahead of Phase 1, so that I test the premise for
   under $1,000 and 10–12 weeks instead of obtaining my first real evidence in Phase 3 or 4 after four
   to six months of building.
5. As a **Research Owner**, I want the pipeline to refuse to start until all four preconditions are
   satisfied — Primary Builder assigned, Independent Validator assigned, data budget approved, 10–12
   week capacity reserved — so that a half-resourced run cannot begin by drift.
6. As a **Research Owner**, I want a reduced-rigour "Phase 0 Lite" to be structurally impossible rather
   than merely discouraged, so that nobody can look at a raw number early and contaminate a
   pre-registered design.
7. As a **Research Owner**, I want a single machine-readable outcome of `GO` / `CONDITIONAL REVIEW` /
   `STOP`, so that continuing the project is not a matter of interpretation or seniority.
8. As a **Research Owner**, I want the three-state outcome to distinguish a passed gate with failed
   capital feasibility, so that a raw positive leader edge cannot conceal an execution-capacity
   failure.
9. As a **Research Owner**, I want the wording of a negative result fixed in advance — "no sufficient
   persistent and copyable edge was found for the Ethereum mainnet target population and capital
   profile" — so that a null result is neither over-claimed nor explained away as unusual market
   conditions.
10. As a **Research Owner**, I want every number the system reports to carry its scope — chain, window,
    capital level, liquidity band, population — so that an Ethereum mid-cap result is never quoted as a
    general claim about copy trading.
11. As a **Research Owner**, I want capital parameters treated as first-class system inputs rather than
    management preferences, so that copyability is computable at all: slippage and price impact are
    functions of trade size, and capital sets the liquidity floor that determines which wallets are
    even worth analysing.
12. As a **Research Owner**, I want `strategy_aum` and `user_capital` maintained as separate inputs, so
    that wallet eligibility and copyability are computed against pooled capital while individual
    suitability is computed against the individual's balance.

### Candidate universe and wallet discovery

13. As a **Primary Builder**, I want a mandatory Step 0 that measures the eligible universe per window
    before any ranking, null distribution, or forward measurement, so that the funnel numbers in the
    original specification are measured rather than assumed.
14. As a **Research Owner**, I want any window whose eligible universe falls below 10,000 accounts
    marked `INSUFFICIENT CANDIDATE UNIVERSE` and the four-window design revised *before* the main test,
    so that a replacement window cannot be chosen after seeing data.
15. As a **Primary Builder**, I want a two-stage buffer — 10–1,200 *potential* buys at the warehouse
    filter, 20–1,000 *valid* buys after netting — so that wallets that fall below the final threshold
    only because netting removed rows are still evaluated rather than silently dropped.
16. As a **Research Owner**, I want the lower eligibility bound at 20 valid buys, so that the top of the
    ranking is not entirely five-buy lucky wallets.
17. As a **Research Owner**, I want the upper bound applied to valid buys rather than total
    transactions, so that approvals, transfers, and administrative operations do not inflate a wallet
    out of eligibility.
18. As a **Primary Builder**, I want Safes and ERC-4337 accounts included with the Safe address and the
    smart-account sender as the portfolio identity, so that a real decision-maker is not excluded for
    using a smart wallet, and bundlers, paymasters, relayers, and Safe signers are never recorded as
    traders.
19. As a **Primary Builder**, I want infrastructure accounts excluded by an explicit test — the account
    must represent one decision-maker or one portfolio, not infrastructure passing through other
    people's transactions — so that routers, aggregators, bridges, treasuries, public vaults, CEX hot
    wallets, and market-making contracts never enter the ranking.
20. As a **Primary Builder**, I want published bot heuristics reused where they exist and modified where
    they are wrong for this design, so that the day-of-week-skewness "human" filter does not silently
    exclude every Safe and smart account.
21. As a **Research Owner**, I want the candidate universe frozen at `T0` with wallets never removed
    afterwards for going quiet, going inactive, or exceeding 1,000 buys, so that survivorship bias
    cannot enter through the back door as a "still active" filter.
22. As a **Research Owner**, I want post-`T0` activity reported as an output and never used as a
    selection filter, so that the design cannot look ahead.
23. As a **Research Owner**, I want the selected wallet count derived as `clamp(1% of eligible universe,
    250, 1000)`, so that selection pressure stays approximately constant across windows instead of
    meaning the top 2.5% in one and the top 0.25% in another.
24. As a **Research Owner**, I want wallet churn reported in three states — Active, Reduced Activity,
    Inactive — so that a wallet that fell from 100 trades to 1 is recognised as effectively dead even
    though it is technically alive.

### Transaction classification

25. As a **Primary Builder**, I want `tx_sender` and `portfolio_owner` stored as two distinct fields
    that never overwrite each other, so that solver-settled trades are not attributed to the solver and
    protocol-specific models cannot silently rewrite the sender into the trader.
26. As a **Research Owner**, I want an **attribution fallback rate** reported as a standing metric, so
    that the specific failure that produces phantom whales and erases real users is monitored rather
    than checked once.
27. As a **Primary Builder**, I want buys reconstructed by transaction-level balance netting rather than
    read from per-hop vendor rows or an aggregator table, so that a `USDC → WETH → TOKEN_A` route does
    not manufacture a phantom "bought WETH" event and split routes are handled correctly.
28. As a **Primary Builder**, I want ETH and WETH normalised to a single asset *before* netting, so that
    route endpoints do not appear as two different assets.
29. As a **Primary Builder**, I want transfers filtered to those touching the owner address before
    netting, so that MEV bundles and multicalls sharing a transaction do not corrupt the result.
30. As a **Primary Builder**, I want fee and referral transfers excluded from endpoint detection, so
    that they are not mistaken for the user's intent.
31. As a **Primary Builder**, I want a pre-registered netting residual tolerance with residuals above it
    excluded from the primary metric and routed to a reconciliation queue, so that partial-fill residue
    is neither silently included nor silently dropped.
32. As a **Research Owner**, I want circular arbitrage explicitly detected and excluded, so that
    arbitrage bots do not appear as wallets with thousands of small profitable trades that netting
    reports correctly as near-zero but cannot express as a position.
33. As a **Primary Builder**, I want transaction success filtered before anything else, so that failed
    transactions — which carry well-formed instructions with plausible amounts, at measured failure
    rates of 17.5% to 65% depending on venue — never enter the sample.
34. As a **Research Owner**, I want a standing **decoder coverage gap** metric reported alongside every
    result, so that the ~8.2% of Ethereum DEX volume with no decoder at all is stated as a caveat
    rather than quietly assumed away.

### Accounting and valuation

35. As a **Research Owner**, I want the primary metric to measure the quality of a wallet's *buys*,
    realized in the quote asset actually used, so that the project does not need a full cost-basis and
    PnL engine resolving transfers, airdrops, staking, and LP activity — and so that it measures the
    thing I would actually copy.
36. As a **Primary Builder**, I want USD conversion restricted to a whitelist of liquid quote assets —
    USDC, USDT, WETH, ETH, WBTC — so that no oracle is ever required for a long-tail token.
37. As a **Primary Builder**, I want partial sells allocated FIFO, so that lot assignment is simple,
    reproducible, pre-registrable, and cannot be changed mid-analysis to improve a chart.
38. As a **Research Owner**, I want open positions at day 30 marked at pool-level on-chain OHLCV and
    **bounded by extractable value given real pool liquidity**, so that a wallet holding $50,000 of a
    token whose pool has $2,000 of liquidity is not recorded as holding $50,000.
39. As a **Research Owner**, I want marks taken from pool-level history and never from coin-level
    aggregator data, so that rugged tokens — whose coin-level listings are auto-deactivated after 30
    days of inactivity and then deny historical access — do not disappear from the sample exactly where
    the losses live.
40. As a **Research Owner**, I want dead pools marked to **zero** rather than the last stale or
    forward-filled price, so that a rugged token reads as −100% rather than flat and wallets that buy
    garbage are not flattered.
41. As a **Primary Builder**, I want the dead-pool test to be a three-part conjunction — no successful
    swap for 30 days, executable exit value below threshold, and no validated replacement pool — so
    that a quiet but exitable position, or a token that migrated to a live pool, is not zeroed
    incorrectly.
42. As a **Primary Builder**, I want pool migration followed only when supported by liquidity history,
    real trading activity, and unchanged token identity, and I want migration to never reset token age,
    so that a sniper cannot launder a first-block purchase into a mature-token purchase.
43. As a **Primary Builder**, I want token age measured from first usable liquidity plus one real swap
    in a covered pool rather than from contract creation, so that a contract deployed months before it
    traded is not classified as mature at its first trade.
44. As a **Research Owner**, I want every valuation tagged with its basis — realized, pool-marked,
    liquidity-bound, or dead-zeroed — and the realized/marked/dead shares reported per wallet and per
    basket, so that a strongly positive result resting 80% on marking is visibly not credible.
45. As a **Primary Builder**, I want 30-day return measurement permitted to extend up to 30 days past
    the end of an evaluation window, applied identically to every benchmark basket, so that no sample
    is dropped and no partial return is used at the window edge.

### Scoring and ranking

46. As a **Primary Builder**, I want wallet-level buy quality aggregated as a weighted average with
    `log(1 + trade_value_usd)` weights, so that trade size is accounted for without one whale purchase
    dominating a wallet's score.
47. As a **Research Owner**, I want ranking computed strictly on the six months before `T0` with no
    information generated after `T0` used in selection, so that the walk-forward design is actually
    out of sample.
48. As a **Research Owner**, I want diagnostics — absolute profit ranking, simple wallet return, 7-day
    and 90-day horizons, win rate, median return, tail loss, first-10-blocks in isolation, sensitivity
    by activity band — computed and reported, so that a divergence between them and the primary metric
    is informative.
49. As a **Research Owner**, I want the system to make it impossible for a diagnostic to overturn a gate
    result, so that the failure mode the whole protocol exists to prevent cannot occur by good
    intentions.

### Benchmarking and matching

50. As a **Research Owner**, I want all thresholds measured against an activity-matched benchmark and
    never against naive random wallets, so that I do not repeat the study where apparently-skilled
    cohorts returned +132.3% while activity-matched placebos returned +216.3%.
51. As a **Primary Builder**, I want matched controls balanced across ten dimensions including
    **liquidity-band exposure** and **first-hour purchase share**, so that a sniper-heavy selected group
    is not compared against a non-sniper control where the sniping itself would read as skill.
52. As an **Independent Validator**, I want covariate balance reported with an absolute standardised
    mean difference target below 0.10, plus unique control count, control reuse frequency, effective
    benchmark sample size, and unmatched selected wallets, so that matching quality is auditable rather
    than asserted.
53. As a **Research Owner**, I want naive random active wallets and buy-and-hold ETH reported alongside
    the matched benchmark as context, so that the matched comparison has a scale to be read against
    even though only it gates.
54. As a **Research Owner**, I want benchmark baskets drawn from the same frozen `T0` universe with
    activity matching using pre-`T0` data only, so that the control is subject to exactly the same
    survivorship and look-ahead constraints as the selected set.

### Copyability simulation

55. As a **Research Owner**, I want follower-adjusted buy quality computed at all five capital levels —
    $100k, $250k, $500k, $1.5M, $2M — so that a single trade size does not make the engine's output
    meaningless, and so I can see where the capacity cliff sits.
56. As a **Primary Builder**, I want follower entry simulated at the first full block after the leader's
    transaction with no future information, so that the simulation reflects the latency a real copier
    faces.
57. As a **Primary Builder**, I want the simulation restricted to the best deterministic *public*
    execution source with no private RFQ or market-maker inventory, so that capacity is not underwritten
    on aggregator quotes that overstate executable size — measured at a 240× spread for PEPE, $471
    single-pool against $114,000 routed.
58. As a **Primary Builder**, I want a minimum 90% order fill required for a simulated trade to count,
    so that a quote that can only be partially filled is not recorded as a fill.
59. As a **Primary Builder**, I want depth modelled from virtual reserves inside the active band with
    integration across ticks beyond ~1%, so that concentrated-liquidity pools are not mis-sized — total
    TVL *understates* near-spot depth by 5–23×, and the size ratio between the 10% and 1% thresholds was
    7.6× for USDC/WETH but 507× for PEPE.
60. As a **Primary Builder**, I want DEX fee, historical gas, price impact, slippage, and liquidity
    limitation each deducted explicitly and reported separately, so that I can see which cost component
    destroys the edge rather than only that it was destroyed.
61. As a **Research Owner**, I want the imitation penalty treated as a theorem rather than an estimate,
    with the leader's size entering at double weight because the follower eats the leader's marginal
    impact and not their average, so that the simulation is not quietly optimistic.
62. As a **Research Owner**, I want Copy Retention reported only when raw buy quality is at or above 2
    percentage points, so that I am not shown a ratio whose denominator is small enough to be pure
    noise.
63. As a **Research Owner**, I want the unexecutable trade share reported per capital level, so that
    "the edge survived" is distinguishable from "most of the edge could not be traded at all".
64. As a **Research Owner**, I want long-tail assets excluded from Ethereum Phase 0 outright rather than
    measured and discovered to be unusable, given the measured Ethereum long-tail capacity of $0 at
    every assumed edge level — the leader's own footprint consumes the entire slippage budget before a
    single copier trades.
65. As a **Research Owner**, I want a maximum total execution cost cap of 1% on majors and 2% on
    mid-caps applied inside the simulation, so that the engine rejects trades that are only profitable
    on paper. *(How that cap interacts with follower order sizing is **OPEN** — see Further Notes.)*

### Edge origin

66. As a **Research Owner**, I want the origin of the edge decomposed across token-age buckets — first
    10 blocks, rest of hour 1, rest of hour 24, older — so that I can see whether the advantage comes
    from skill or from being early in a way I could never replicate.
67. As a **Research Owner**, I want a First-Hour Edge Share above 40% to be a **hard window failure**
    rather than a warning, so that a gate pass driven by wallets that snipe the opening blocks and hold
    does not evaporate the moment the copyability engine is switched on.
68. As a **Research Owner**, I want edge contribution computed at bucket granularity using the same
    log-weighting as the primary metric, so that the Edge Origin condition is measured on the same basis
    as the thing it constrains.
69. As a **Research Owner**, I want a small-denominator guard that marks a window `INDETERMINATE` and
    fails it when total positive edge contribution is under 5 percentage points, so that a window whose
    edge origin cannot be measured does not count toward the three required successes.

### Null distribution and calibration

70. As a **Research Owner**, I want the entire pipeline re-run 1,000 times per window per column with
    random wallets in place of selected ones, so that the false-positive rate of my threshold is
    measured rather than assumed — a pre-registered threshold that random selection clears is worse than
    no threshold, because it manufactures confidence.
71. As a **Primary Builder**, I want the null sample size for each window set to that window's actual
    selected wallet count, so that the null describes the same experiment as the main test.
72. As a **Research Owner**, I want the null gate to be the identical full three-condition gate, so that
    the 95th percentile refers to the same experiment and the calibration is not void.
73. As a **Research Owner**, I want the final mean threshold set to the smallest value at which the null
    pass rate is at or below 5%, so that 15pp is treated as a starting value and is raised if
    calibration shows it is loose — even though that makes the project harder to pass.
74. As a **Primary Builder**, I want separate Leader and Follower-Adjusted null distributions, so that
    each gate clears its own null rather than borrowing the other's.
75. As a **Research Owner**, I want the null built on the **final** metric including liquidity-bound
    pricing, so that calibration does not belong to a different experiment than the one that runs.
76. As a **Primary Builder**, I want the null runs and the main test to execute from the same frozen
    commit through the same shared functions, so that no divergence between them is possible.
77. As a **Primary Builder**, I want one master random seed with deterministic child seeds recorded in
    the freeze manifest, so that every null run is reproducible exactly.
78. As a **Primary Builder**, I want the null built by resampling already-extracted data with no new
    vendor queries, so that 1,000 runs per window per column costs compute time and nothing else.

### Validation gate

79. As an **Independent Validator**, I want a golden dataset of 30–50 hand-traced accounts built and
    frozen **before** the pipeline's output is seen, so that expected answers cannot be shaped by what
    the code produced.
80. As an **Independent Validator**, I want the golden set to deliberately cover full buy-and-sell,
    multiple partial sells, multi-hop routes, multi-pool trades, fee-on-transfer tokens, dead pools,
    first-hour purchases, thin liquidity, failed transactions, circular arbitrage, Safe, ERC-4337,
    transfers alongside swaps, and tokens with multiple pools and liquidity migration, so that the hard
    cases are tested rather than the easy ones.
81. As an **Independent Validator**, I want 100% precision and 100% recall on buy/sell events with a
    single unresolved false positive or false negative failing the gate, so that "mostly correct
    classification" is not treated as correct.
82. As an **Independent Validator**, I want deterministic fields — transaction hash, block number,
    wallet, token, pool, direction, raw quantities, FIFO lot assignment, realized/open status — to match
    exactly at raw-unit level with no percentage tolerance, so that rounding cannot hide a logic error.
83. As an **Independent Validator**, I want USD tolerances fixed at 0.5% per event, 0.5% on wallet
    realized value, and 0.5 percentage points on buy quality, with differences above tolerance found and
    fixed rather than averaged away, so that many small discrepancies cannot be dismissed collectively.
84. As an **Independent Validator**, I want a fixed battery of known-answer synthetic tests whose answers
    are set before the code runs, at 100% pass with no waivers, so that no failing case can be excused
    as an edge case.
85. As an **Independent Validator**, I want cross-source reconciliation performed against **raw chain
    data** — receipts, event logs, execution traces, raw balance deltas — rather than a second vendor, so
    that shared vendor assumptions cannot be mistaken for agreement.
86. As an **Independent Validator**, I want 100% supported transaction coverage and zero unexplained
    missing trades, extra trades, or balance-delta mismatches on the golden set, plus ≥99.5% event and
    notional agreement on a random sample of at least 200 accounts, so that the reconciliation is a real
    study and not a spot check.
87. As an **Independent Validator**, I want every remaining difference assigned to a documented category
    and the notional share of uncovered trades reported per window, so that unexplained differences can
    never be silently dropped.
88. As an **Independent Validator**, I want to derive my expected outputs from raw chain data and the
    specification only — never from the builder's code or intermediate artefacts — and to record my
    reasoning before comparison, so that my validation is genuinely independent rather than a review of
    someone else's answer.
89. As an **Independent Validator**, I want validation status stated explicitly as `MACHINE-INDEPENDENT`,
    `EXTERNALLY REVIEWED`, or `NOT INDEPENDENT`, so that the strength of the check is recorded rather
    than assumed — two agents from the same base model share priors and make correlated errors, which is
    exactly the class independent validation exists to catch.
90. As a **Research Owner**, I want 10–15 complex accounts reviewed by an external human specialist so
    that the status can reach `EXTERNALLY REVIEWED`, and I want the main test **blocked** at
    `NOT INDEPENDENT`, so that the bounded cost of external review is paid rather than skipped.
91. As a **Primary Builder**, I want the validation gate's ordering enforced — golden set, then
    known-answer tests, then reconciliation, then independent validation, then freeze, then null, then
    main test — so that the pipeline cannot compute anything that matters before proving itself correct.
92. As a **Research Owner**, I want a freeze manifest capturing source commit, dataset snapshot, golden
    dataset version, protocol coverage list, token and pool rules, price and marking rules, validation
    report, and seed policy, so that the frozen experiment is a specific reproducible object rather than
    a claim.
93. As a **Research Owner**, I want a bug discovered after freeze to mark the run `INVALIDATED` and force
    a complete repeat — fix, new version, full validation gate, null rebuilt from scratch, main test
    re-run — so that selectively using the old or new result is impossible.
94. As a **Primary Builder**, I want unsupported population events quarantined and reported while
    unexplained dropped events are prohibited outright, so that a known unknown is counted and a silent
    disappearance is a hard error.

### The governance module as an actor

95. As the **Governance Module**, I want to hold the authoritative frozen parameter set and reject any
    write to it after freeze, so that thresholds cannot change once results exist.
96. As the **Governance Module**, I want to refuse to authorise the null distribution until the
    validation gate reports pass on every condition, so that the ordering is enforced rather than
    trusted.
97. As the **Governance Module**, I want to refuse to authorise the main test until the null distribution
    is complete and the threshold is locked, so that the main test is genuinely run once against a
    pre-set bar.
98. As the **Governance Module**, I want to record who or what requested every state transition and
    reject transitions that arrive out of order, so that the protocol's ordering is a property of the
    system rather than of people's memory.
99. As the **Governance Module**, I want to emit the final gate decision as a signed machine-readable
    record tied to the freeze manifest, so that the result cannot be quoted detached from the experiment
    that produced it.
100. As the **Governance Module**, I want to deny any request from a person or an AI agent to reinterpret
     a failed gate as a successful result, so that the failure mode being guarded against — a
     well-intentioned engineer deciding a bug was small enough — has no available path.

### Operations

101. As an **Operations Administrator**, I want the authority to stop a running process for security,
     data corruption, or infrastructure failure, so that I can protect the system without needing the
     Research Owner in the loop.
102. As an **Operations Administrator**, I want my authority to stop processes to be structurally
     separate from any ability to modify a research result, so that an operational action can never
     become a research decision.
103. As an **Operations Administrator**, I want a monthly coverage audit that re-measures the decoder
     coverage gap, so that a decoder breaking without warning is caught rather than silently zeroing a
     venue.
104. As an **Operations Administrator**, I want the reconciliation queue surfaced as an operational
     work item with volume and age, so that residuals and quarantined events are worked rather than
     accumulated.
105. As an **Operations Administrator**, I want the data collection layer resourced as a standing team
     with an owner rather than a component built once, so that the ongoing cost of decoder maintenance
     is budgeted — migrating a single indexer cost QuickSwap 6–8 engineer weeks, and the Uniswap
     Foundation paid a vendor $480,000 over 21 months rather than build it in-house.

### Live wallet health (post-Phase 0)

106. As an **Operations Administrator**, I want watched wallets to move through a
     Candidate → Shadow → Active → Warning → Paused → Expired lifecycle, so that wallet state is explicit
     and every transition is auditable.
107. As an **Operations Administrator**, I want a 30-day shadow period before a newly discovered wallet
     influences anything real, so that out-of-sample testing is applied continuously rather than once —
     and so that churn is measured where it actually happens.
108. As an **Operations Administrator**, I want inactivity thresholds expressed relative to each wallet's
     own historical trade gap with an absolute floor and a 60-day hard ceiling, so that a wallet that
     normally trades weekly and one that trades hourly are not treated as equally dead after seven days
     of silence.
109. As an **Operations Administrator**, I want immediate pause triggers on attribution uncertainty,
     security concerns, manipulation, infrastructure reclassification, strategy change, liquidity
     failure, and copyability failure, so that a wallet stops influencing decisions the moment its basis
     is in doubt.
110. As an **Operations Administrator**, I want a second live data path for block-cadence wallet
     monitoring, separate from the batch path Phase 0 uses, so that a 12-second monitoring loop is not
     attempted on a warehouse with a 30-minute refresh.
111. As a **Research Owner**, I want scheduled score refresh, candidate discovery, replacement review,
     full reselection, and model revalidation on a fixed cadence, so that the wallet set does not
     silently age into irrelevance.

### Deployment Model A — managed basket or fund

112. As a **Fund Investor**, I want wallet selection and trade copyability computed against the combined
     `strategy_aum` rather than my individual investment, so that my small balance participates without
     generating economically inefficient individual trades.
113. As a **Fund Investor**, I want to receive proportional performance from a pooled execution layer, so
     that pooling is the mechanism that makes small capital viable rather than a marketing claim.
114. As a **Fund Investor**, I want the strategy's measured capacity disclosed against its current AUM,
     so that I can see when the strategy is approaching the level at which its own size destroys its
     edge.
115. As a **Research Owner**, I want the fund's execution, custody, structure, accounting, legal review,
     and customer interface treated as separate downstream workstreams, so that the research project is
     not quietly expanded into a fund build.

### Deployment Model B — recommendation-only service

116. As a **Recommendation Subscriber**, I want a structured recommendation carrying decision, asset,
     confidence, my capital, a recommended maximum amount, an estimated total cost percentage, a
     validity timestamp, and reason codes, so that I can act on it and audit it later.
117. As a **Recommendation Subscriber**, I want `NOT ECONOMICALLY EXECUTABLE` as a first-class answer, so
     that I am told honestly when a real signal is not tradeable at my size instead of being sold a
     trade that cannot work.
118. As a **Recommendation Subscriber**, I want `WAIT` as a distinct state from `HOLD`, so that "the
     signal is real but this is not the moment" is expressible.
119. As a **Recommendation Subscriber**, I want every recommendation to carry a `valid_until` timestamp,
     so that signal decay is machine-enforced rather than a caveat in a footnote.
120. As a **Recommendation Subscriber**, I want reason codes on every recommendation, so that six months
     later it is answerable which reason codes were present on the recommendations that lost money.
121. As a **Recommendation Subscriber**, I want the engine to reject a recommendation outright when cost,
     liquidity, or capital constraints make it unsuitable, so that the system never manufactures activity
     to appear useful.
122. As a **Recommendation Subscriber with roughly $1,000**, I want sizing computed against slippage and
     minimum viable position rather than against gas, so that the answer reflects the actual binding
     constraint — a median Ethereum swap round trip costs $0.053, so a $150 position pays about 0.04% in
     gas.
123. As a **Research Owner**, I want Model B recognised as the model that most clearly constitutes
     investment advice rather than the lighter compliance option, so that a per-user capital-sized
     recommendation is not shipped on the assumption that not executing makes it exempt.
124. As a **Research Owner**, I want the system to remain internal-only through Phase 5 with no signal or
     allocation shown to any third party, so that investment-advice regulation is not engaged before a
     legal and licensing review is complete.
125. As a **Research Owner**, I want any customer-facing product gated on five explicit proofs —
     out-of-sample persistence, profitability after costs, verified risk-engine behaviour under real
     conditions, a credible track record, and a completed legal and licensing review — so that building
     the engine is never confused with being allowed to deploy it.

### Reporting

126. As a **Research Owner**, I want realized share, marked share, and dead/zeroed share reported per
     wallet and per basket, so that a gate result whose value rests 80% on marking is visibly weaker than
     its headline number.
127. As a **Research Owner**, I want per-capital-level reporting of raw buy quality, follower-adjusted buy
     quality, mean and median Copy Retention, positive trade rate, valuation-basis shares, and
     unexecutable trade share, so that the capacity cliff is located rather than inferred.
128. As a **Research Owner**, I want an optional Arbitrum secondary diagnostic that is pre-registered as
     secondary, sits outside the gate, may not rescue a weak Ethereum result, and cannot trigger a
     threshold change, so that generalisability can be checked without contaminating the test.
129. As a **Research Owner**, I want the final report to state explicitly what Phase 0 did *not* test —
     Berk–Green capital-degradation effects, generalisation to other chains or memecoin markets, and
     whether the full twelve-engine product would be profitable — so that a pass is not read as more than
     it is.

---

## Implementation Decisions

### Module map

The engine is twelve modules. Phase 0 requires the first ten; M11 and M12 are built only after Phase 0
returns `GO`.

| # | Module | Responsibility |
|---|---|---|
| M1 | Data Acquisition & Warehouse Filter | Pull and pre-filter Ethereum DEX activity; own the coverage-gap metric |
| M2 | Attribution & Netting Engine | Recover `portfolio_owner`; reconstruct valid buys by transaction-level netting |
| M3 | Position Accounting Engine | FIFO lot assignment; realized/open state |
| M4 | Valuation & Marking Engine | Quote-asset realization; pool-level marks; liquidity bound; dead-pool zeroing |
| M5 | Universe & Eligibility Engine | Step 0 measurement; account typing; infrastructure exclusion; `T0` freeze |
| M6 | Scoring Engine | `buy_quality_30d`; ranking; token-age bucket decomposition |
| M7 | Matching & Benchmark Engine | Activity-matched controls; balance diagnostics; naive and ETH benchmarks |
| M8 | Copyability Simulation Engine | Follower entry, depth model, cost stack, five capital levels |
| M9 | Null & Calibration Engine | 1,000 runs per window per column; threshold calibration |
| M10 | Gate Evaluation Engine | The two gates, the Edge Origin condition, the three-state outcome |
| M11 | Experiment Governance Module | Freeze, ordering enforcement, invalidation, final decision record |
| M12 | Validation Harness | Golden set, known-answer suite, reconciliation, validator report |
| M13 | Wallet Health Monitor | Post-Phase 0 lifecycle, live data path |
| M14 | Recommendation Emitter | Post-Phase 0, Model B output contract |

M11 is listed after M10 in the table but is **upstream of all of them at runtime**: no module may
execute a stage the governance module has not authorised.

### Pipeline shape: filter early, enrich late

Broad Ethereum data stays in the warehouse. Full transaction histories are extracted only for candidate
wallets, selected wallets, benchmark wallets, golden validation accounts, and reconciliation samples.
The two-stage buffer is load-bearing: **10–1,200 potential buys** at the warehouse filter,
**20–1,000 valid buys** after netting. Filtering at the final threshold in the first pass silently drops
wallets that netting would have moved across the boundary.

### M2 — attribution and the netting rule

Every trade record carries two fields that are never merged:

```
tx_sender         msg.sender / transaction signer
portfolio_owner   recovered beneficial owner — NEVER overwritten by tx_sender
```

Follow the two-column vendor shape (`from_address` / `swapper_address`), not the single-column
coalescing shape. Smart accounts resolve as: Safe → the Safe address, signers are not separate traders;
ERC-4337 → the smart account sender, with bundler, paymaster, and relayer never recorded as the trader.

The netting rule, which is the decision this module exists to encode:

```
1. Filter to successful transactions          (meta.err == null)
2. Filter transfers to those touching portfolio_owner
3. Normalise ETH and WETH to one asset
4. Sign amounts: bought positive, sold negative
5. Group by (transaction, portfolio_owner, token) and sum
6. Intermediate route tokens net to ~0 and drop out
7. Remaining non-zero endpoints are the user's intent
8. Exclude fee and referral transfers from endpoint detection
9. Detect and exclude same-transaction round trips (circular arbitrage)
```

Residual handling — negligible when:

```
USD residual ≤ max($0.01, 0.01% of transaction notional)
```

Residuals above threshold are excluded from the primary metric and routed to a reconciliation queue.
Not silently included, not silently dropped.

Steps 2 and 3 are ordering-critical and are the two most likely places for a subtle bug: skipping the
owner filter lets MEV bundles and multicalls sharing a transaction corrupt the sum; skipping ETH/WETH
normalisation makes route endpoints appear as two different assets.

### M3/M4 — accounting and valuation contract

FIFO lot assignment, no alternatives, no configuration switch. Each closed or marked position emits a
`value_basis` of `REALIZED | POOL_MARKED | LIQUIDITY_BOUND | DEAD_ZEROED`, and every aggregate must be
decomposable by it.

Valuation branches:

```
Case 1  sold within 30d   Realized Return = Sale Proceeds / Allocated Buy Cost − 1
                          both legs in the quote asset actually used; no long-tail oracle
Case 2  open at day 30    Marked Value = min( Remaining Qty × Pool-Level Exit Price,
                                              Extractable Value Given Real Pool Liquidity )
Case 3  dead pool         Marked Value = 0
```

Dead-pool test is a conjunction, not a timer:

```
no successful swap for 30 days
AND executable exit value below the minimum threshold
AND no validated replacement pool exists
```

USD conversion is permitted only for `USDC, USDT, WETH, ETH, WBTC`. Prices for those come from public
exchange minute klines; pool-level OHLCV with inactive sources included supplies marks. Coin-level
aggregator price endpoints are prohibited as a data source for marking, at any point in the pipeline.

Window-edge rule: 30-day measurement may extend up to 30 days past the end of an evaluation window, and
must be applied identically to every benchmark basket.

### M6 — scoring contract

```
buy_quality_30d = Σ(w_i · r_i) / Σ(w_i)   where   w_i = log(1 + trade_value_usd_i)
```

Token age buckets, non-overlapping, with age measured from first usable liquidity plus one real swap and
**not reset by pool migration**:

```
A  first 10 blocks
B  after 10 blocks → end of hour 1
C  after hour 1 → end of hour 24
D  older than 24 hours

First-Hour Purchases = A + B
```

### M7 — matching contract

Ten matching dimensions: account type, capital deployed, valid buy count, buy volume, active days,
wallet age, median trade size, trade frequency, liquidity-band exposure, first-hour purchase share.
Standardised distance-based matching, 5 primary + 5 robustness controls per selected wallet, matching
with replacement permitted. Balance target `|SMD| < 0.10`. The module must emit unique control count,
control reuse frequency, effective benchmark sample size, unmatched selected wallets, and per-covariate
balance — a matched benchmark whose balance is not reported is not a control.

> **OPEN.** How M7's matched-set design and M9's null construction reconcile is unresolved. See
> Further Notes.

### M8 — copyability contract

Five capital levels: `$100k, $250k, $500k, $1.5M, $2M`. The last two gate.

Per simulated buy: identify the leader's trade → enter at the **first full block after** it → price
through the executable public route or pool → deduct DEX fee, historical gas, price impact, slippage,
liquidity limitation → exit or mark at 30 days under the M4 rules.

Constraints, all mandatory:

- best deterministic **public** execution source only — no private RFQ, no market-maker inventory
- no future information
- ≥ 90% order fill required for the trade to count
- depth from virtual reserves `x_v = L/√P` inside the active band, integrated across ticks beyond ~1%;
  active-tick liquidity alone is not an acceptable depth proxy
- both AMM pool/tick depth **and** order-book depth at each price level considered

Copier penalty, encoded rather than estimated:

```
copier slippage ≈ (2 · S_leader + C) / S₁
```

where `S₁` is the trade size costing 1% and `C` is aggregate copier capital. The leader's size enters at
double weight — the follower eats the leader's *marginal* impact, not their average. Reference point:
leader 5.000% → copier 15.500% at equal size on a constant-product pool.

Execution cost caps:

```
Major assets    1%
Mid-cap assets  2%
Long-tail       excluded from Ethereum Phase 0
```

Derived outputs:

```
Copy Retention = Follower-Adjusted Buy Quality / Raw Buy Quality
                 displayed only when Raw Buy Quality ≥ 2 pp, else N/A
```

> **OPEN.** Follower order size is undefined. See Further Notes.

### M9 — null and calibration contract

1,000 runs per window per column (leader and follower-adjusted) = 8,000 runs. Null sample size per
window equals that window's actual selected wallet count. The null gate must be the **identical full
three-condition gate**, not a simplified one. One master seed, deterministic child seeds. No new vendor
queries — this is resampling of already-extracted data, so the marginal data cost is zero.

```
Null Pass Rate       = null runs passing the full gate / total null runs
Final Mean Threshold = smallest threshold at which Null Pass Rate ≤ 5%
```

Binding order: metric locked → parameters pre-registered → null built on the **final** metric including
liquidity-bound pricing → threshold calibrated → threshold locked → main test run once → nothing
changes.

### M10 — gate conditions

```
Gate 1 — Leader skill persistence (all three, per window)
  Mean Buy Quality Advantage    ≥ Calibrated Mean Threshold
  Median Buy Quality Advantage  > 0
  First-Hour Edge Share         ≤ 40%

Gate 2 — Economic copyability
  Follower-Adjusted Excess Buy Quality > 0  at $1,500,000
  Follower-Adjusted Excess Buy Quality > 0  at $2,000,000

Significance (both gates)
  result > 95th percentile of its own null distribution
  empirical p ≤ 0.05

Project
  Gate 1 AND Gate 2 AND significance, in ≥ 3 of 4 windows → Phase 1 authorised
```

Edge Origin, computed at bucket granularity with the same log-weighting:

```
Bucket Edge Contribution = max(0, Bucket Weight × (Selected BQ − Matched Benchmark BQ))
First-Hour Edge Share    = (EC_A + EC_B) / (EC_A + EC_B + EC_C + EC_D)

> 40%                             → UNCOPYABLE-DOMINATED, window FAILED
Total positive EC < 5 pp          → INDETERMINATE, window FAILED
```

`INDETERMINATE` is a failure, not an abstention. All thresholds are measured against the
**activity-matched** benchmark; the naive random benchmark and buy-and-hold ETH are reported as context
and never gate.

Three-state outcome — a raw positive leader edge may not conceal an execution-capacity failure:

```
Gate Result: PASSED · Capital Feasibility: FAILED → Project Status: CONDITIONAL REVIEW
```

`CONDITIONAL REVIEW` requires an explicit recorded decision before Phase 1: reduce `design_capital`,
restrict the token universe, restrict wallets by copy capacity, reduce base position size, or stop.

### M11 — governance module

State machine, transitions authorised only in this order:

```
PARAMETERS_OPEN → PARAMETERS_FROZEN → VALIDATION_PASSED → CODE_AND_DATA_FROZEN
→ NULL_COMPLETE → THRESHOLD_LOCKED → MAIN_TEST_EXECUTED → DECISION_EMITTED
```

Writes to the parameter set are rejected after `PARAMETERS_FROZEN`. `NULL_COMPLETE` is unreachable
without `VALIDATION_PASSED`. `MAIN_TEST_EXECUTED` is unreachable without `THRESHOLD_LOCKED`. Every
transition records its requester. Operations administrators hold a `HALT` capability that stops
execution and holds state; they hold no capability that mutates a result.

Freeze manifest contents: source-code commit · dataset snapshot · golden dataset version · protocol
coverage version · decoder coverage version · model version · configuration · master and child seeds ·
known-answer fixtures · token and pool rules · price and marking rules · validation report.

Invalidation: a real, documented bug found after freeze sets `Current Run Status: INVALIDATED`. The
previous result may not be patched or partially corrected. Required: fix, register a new code version,
re-run the entire validation gate, rebuild the null from scratch, re-run the main test. Selectively
using the old or the new result is prohibited.

Final record:

```
GO | CONDITIONAL REVIEW | STOP
```

emitted as a machine-readable object bound to the freeze manifest hash.

### Data model additions

Trade-level records carry, beyond the standard fields:

```
tx_sender                  msg.sender / transaction signer
portfolio_owner            recovered beneficial owner (never overwritten)
account_type               EOA | SAFE | ERC4337 | OTHER_CONTRACT
token_trading_start_block  first usable liquidity + first real swap; migration does not reset
token_age_bucket           A | B | C | D
pool_depth_at_trade        pool TVL / virtual reserve at trade time
s1_at_trade                trade size costing 1% slippage, at trade time
is_circular_arb            boolean
netting_residual           residue left after transaction-level netting
value_basis                REALIZED | POOL_MARKED | LIQUIDITY_BOUND | DEAD_ZEROED
```

Versioning fields `data_timestamp`, `model_version`, `scoring_version`, `classification_version` are
joined by `decoder_coverage_version` — the protocol coverage list in force when the row was produced.

### Standing data-integrity metrics

Reported alongside every result, not measured once:

```
Decoder coverage gap             % of tracked DEX volume with no decoder    (Ethereum baseline ~8.2%)
Unexplained reconciliation diff  % of events unmatchable to raw chain data
Realized vs marked share         of all valuation, per period
Attribution fallback rate        % of trades where portfolio_owner fell back to tx_sender
```

### M14 — recommendation contract (post-Phase 0)

Decision domain: `BUY | SELL | HOLD | WAIT | NOT ECONOMICALLY EXECUTABLE`.

```json
{
  "decision": "BUY",
  "asset": "ETH",
  "confidence": 0.78,
  "user_capital_usd": 1000,
  "recommended_max_amount_usd": 150,
  "estimated_total_cost_pct": 0.6,
  "valid_until": "2026-08-01T12:00:00Z",
  "reason_codes": ["persistent_wallet_consensus", "copyable_at_user_capital", "sufficient_liquidity"]
}
```

`valid_until` makes signal decay machine-enforced rather than a footnote. `reason_codes` make every
recommendation auditable after the fact — which codes were present on the recommendations that lost
money is an answerable question only if they are stored. The engine may return a rejection; it must
never manufacture a trade to produce activity.

Model A computes eligibility and copyability against pooled `strategy_aum`; Model B computes suitability
against `user_capital`. The same M8 depth and cost model serves both — only the size input differs.

---

## Testing Decisions

The testing strategy is not an afterthought bolted onto the pipeline; it is a **gate that runs before
the pipeline is allowed to compute anything that matters**, and it is the reason to believe any number
this system produces.

### Why conventional confidence does not apply here

The null distribution cannot detect implementation bugs. It is computed by the same code. A wrong FIFO
rule, a mis-applied liquidity bound, or a missed transaction class affects the selected basket and all
1,000 random baskets *identically*. It does not appear as an anomaly. The 95th percentile is computed,
the number looks healthy, and the gate answers the wrong question — and because the design forbids
post-hoc changes, the bug becomes permanent. Statistical rigour and implementation correctness are
orthogonal, and only one of them is addressed by resampling.

There is also no external benchmark to lean on. **No public benchmark of DEX decoder accuracy exists.**
Vendor accuracy figures are unverified. This reconciliation is a study nobody outside has run.

### What makes a good test here

A good test asserts on **externally observable outputs against an answer derived independently of the
code** — from raw chain data, or from a case constructed by hand before the code ran. A test that
asserts the pipeline agrees with itself, or with a second vendor that shares its assumptions, proves
nothing. Tests are specified in terms of events, quantities, lot assignments, and returns — never in
terms of internal function calls.

### Layer 1 — golden dataset

30 accounts minimum, **50 preferred**, hand-traced by a human (or an independent validator agent working
from raw chain data only) from transactions, event logs, traces, and actual balance changes. Built and
frozen **before the final pipeline output is seen**. Where the team is one person, three substitute
controls are mandatory: the golden set is built before the pipeline is written; golden-set review is
blind, with system output unseen until manual computation is complete; and 10–15 complex accounts are
reviewed by an independent external specialist.

Coverage is deliberate, not sampled: full buy-and-sell · multiple partial sells · multi-hop routes ·
multi-pool trades · fee-on-transfer tokens · dead pools · first-hour purchases · thin liquidity · failed
transactions · circular arbitrage · Safe · ERC-4337 · transfers alongside swaps · tokens with multiple
pools and liquidity migration.

Acceptance:

```
Buy/sell precision                100%
Buy/sell recall                   100%
Deterministic fields              exact match at raw-unit level, no percentage tolerance
                                  (tx hash · block · wallet · token · pool · direction ·
                                   raw quantities · FIFO lot assignment · realized/open status)
Per-event USD error               ≤ 0.5%
Wallet realized value error       ≤ 0.5%
Buy Quality absolute difference   ≤ 0.5 pp
```

A single unresolved false positive or false negative fails the gate. Differences above tolerance must be
**found and fixed** — averaging errors away, or dismissing many small discrepancies collectively, is not
permitted.

### Layer 2 — known-answer tests

Synthetic cases whose answers are fixed before the code runs. Fixed battery:

```
Simple Buy + Full Sell      Multiple Buys + Partial Sell    Multi-hop Buy
FIFO Allocation             Open Position at Day 30         Dead Pool
Thin but Live Pool          Liquidity-Bound Marking         Fee-on-Transfer Token
Failed Transaction          Circular Arbitrage              Internal Transfer
Multiple Pools, One Token   Pool Migration                  First-Hour Classification
End-of-Window 30-Day Extension
```

100% must pass. **No failing test may be waived as an edge case.** For deterministic logic — FIFO, net
balance change, failed-transaction exclusion — output must equal the pre-determined answer exactly; only
machine rounding error is tolerated in numeric results.

This battery is also the regression suite. Every one of these cases exists because a specific documented
failure mode produced a wrong answer in a real system.

### Layer 3 — cross-source reconciliation

Reconcile the normalised vendor source against **raw chain data** — receipts, event logs, execution
traces, raw balance deltas. Ground truth is raw chain data, **not a second vendor**: two normalisation
vendors can share assumptions and errors, and in this specific domain they demonstrably take opposite
conventions on the same events. Vendor output is the thing being tested, not the reference.

```
Golden set:   supported transaction coverage   100%
              unexplained missing trades       0
              unexplained extra trades         0
              raw balance delta mismatches     0

Random sample (≥ 200 accounts):
              event agreement                  ≥ 99.5%
              notional value agreement         ≥ 99.5%
```

Every remaining difference must fall into a documented category — venue without decoder, unusual token
behaviour, incomplete trace, fee-on-transfer, rebase, contract not covered. Unexplained differences may
not be silently dropped. The notional share of uncovered trades is reported per window.

### Layer 4 — independent validation

The validator must not have written the pipeline's transaction classification, FIFO, or valuation logic,
must use a separate implementation path, must not reuse the builder's functions, and must produce
expected outputs **before** seeing the builder's results. The validator joins in week 1 and builds or
approves the golden set before the pipeline is complete — bringing a validator in at the end to sign a
report is not independent validation.

Status is stated, never assumed:

```
MACHINE-INDEPENDENT   catches transcription errors, arithmetic slips, single-path logic bugs
                      weaker than external review: two agents from the same base model share
                      priors and make correlated errors — exactly the class this layer exists
                      to catch
EXTERNALLY REVIEWED   includes 10–15 complex accounts reviewed by an external human specialist
NOT INDEPENDENT       main test BLOCKED
```

### Which modules get tested, and how

| Module | Primary test surface |
|---|---|
| M2 Attribution & Netting | Golden set (precision/recall, exact raw quantities) + full known-answer battery + reconciliation |
| M3 Position Accounting | Known-answer FIFO cases (exact lot assignment) + golden set lot-level match |
| M4 Valuation & Marking | Known-answer dead-pool / thin-pool / liquidity-bound / migration cases + 0.5% golden tolerance |
| M5 Universe & Eligibility | Account-type classification on golden set; Step 0 counts reproducible from the frozen snapshot |
| M6 Scoring | Deterministic reproduction of `buy_quality_30d` from a fixed event set; bucket assignment cases |
| M7 Matching | Balance diagnostics as the test: `\|SMD\| < 0.10` per covariate, plus reuse and effective-N reporting |
| M8 Copyability | Constructed pool states with known depth; the copier-penalty reference case (5.000% → 15.500%) |
| M9 Null & Calibration | Reproducibility from the master seed: identical results from identical seed and commit |
| M10 Gate | Table-driven cases over the full condition matrix, including `INDETERMINATE` and `CONDITIONAL REVIEW` |
| M11 Governance | Rejection tests — every out-of-order transition and every post-freeze parameter write must fail |

### Failure policy

```
Golden-set discrepancy       → hard failure
Known-answer test failure    → hard failure
Unsupported population event → quarantine and report
Unexplained dropped event    → prohibited
```

The line between *quarantine and report* and *prohibited* is the important one. An event the pipeline
does not support is a known unknown and must be counted. An event that vanishes without explanation is
the failure that makes every downstream number untrustworthy.

### Gate summary — all must hold

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

Failure of any condition: `Validation Gate: FAILED` → `Null Distribution: NOT AUTHORIZED` →
`Main Test: NOT AUTHORIZED`.

---

## Out of Scope

Scope discipline is this project's main asset. Everything below is excluded deliberately, with the
reason recorded.

**Excluded from Phase 0 entirely**

- **Phases 1–6 in detail.** Designing them before Phase 0 returns a result is precisely the error the
  pre-registration exists to prevent.
- **Entity clustering.** Address ≠ agent. An operator splitting buys across many wallets makes
  per-wallet cost basis wrong by construction and inflates the multiple-comparisons denominator at near
  zero cost. This is a known, accepted limitation of the Phase 0 result, not an oversight.
- **Strategy clustering.**
- **The risk engine.**
- **Signal generation.**
- **Portfolio construction.** Excluded — which is what leaves follower order sizing undefined; see
  Further Notes.
- **The full wallet PnL / cost-basis engine.** Resolving cost basis, transfers, airdrops, staking, and
  LP activity turns a 10-week test into a multi-month build. Buy quality needs only trade timestamps,
  sizes, and quote-asset prices — and it is the more relevant question, because you copy a wallet's
  buys, not its airdrops. The `UNKNOWN_COST_BASIS` warning from the original specification stands for
  later phases.

**Excluded chains and assets**

- **Base.** Launched publicly August 2023; supplies at most 2 clean windows of the 4 the design
  requires. Excluded as incompatible with the test, not as a poor chain.
- **Solana.** Trader attribution is unreliable — gasless swaps are attributed to a sponsor's gas wallet
  or a market maker, producing phantom mega-wallets and erasing exactly the small/new wallet cohort;
  and the vendor's Solana macro resolves swap legs by fixed positional offsets and silently drops
  non-matching trades. Rankings built on this are not defensible in either direction.
- **Arbitrum.** Secondary diagnostic only, pre-registered, outside the gate, may not rescue a weak
  Ethereum result, may not trigger a threshold change.
- **Long-tail Ethereum assets.** Measured capacity $0 at every assumed edge level. Excluded outright
  rather than measured and discovered unusable.
- **Perpetuals, options, lending, LP positions, NFTs.** Spot DEX only.
- **Cross-chain and bridged activity.**

**Excluded execution and product surfaces**

- **Live execution of any kind.** Phase 0 is historical only; no live trading, no paper trading, no
  waiting.
- **Automated execution, custody, basket/fund accounting, fund structure.**
- **The customer interface**, for either deployment model.
- **Legal and licensing implementation.** The regulatory *risk* is in scope and recorded; obtaining
  licences is a separate workstream.
- **Any third-party disclosure of signals or allocations through Phase 5.** The system is internal only.
  The moment output reaches customers it is investment advice.
- **Multi-chain expansion.**

**Excluded methodological options**

- **Phase 0 Lite.** Rejected explicitly. No external deadline is on record; early observation
  contaminates a pre-registered design; a raw result steers later decisions without anyone intending it;
  and a lite version is most likely to produce a false positive specifically on uncopyable trades and
  pricing errors — the exact failures the gates exist to catch. If the full 10–12 week run is not
  resourceable, the correct action is to **pause the project**, not to run a weak test whose result
  would later be cited as evidence.
- **Coin-level aggregator price data** as a source for marking, anywhere in the pipeline.
- **Aggregator quotes** as the basis for capacity underwriting.
- **Second-vendor cross-checks** as a substitute for raw-chain reconciliation.
- **Post-hoc threshold adjustment**, diagnostic-driven gate overrides, and partial correction of an
  invalidated run.

**Not measurable, therefore not claimed**

- Whether alpha survives once the strategy itself deploys capital and moves prices (Berk–Green).
- Whether the result generalises to Base, Arbitrum, Solana, or memecoin markets.
- Whether the full twelve-engine product would be profitable.

---

## Further Notes

### The three unresolved conflicts

Three items in the addendum change decisions that were already locked. They are **genuinely open** and
each requires an explicit resolution before the pre-registration is frozen. Nothing in this PRD resolves
them.

**1. Matching design versus null distribution — OPEN.**
The pre-registration builds the null by drawing **random baskets** of N wallets from the
activity-matched-eligible universe, repeatedly, comparing basket against basket. The addendum specifies
**5 primary + 5 robustness matched controls per selected wallet**, with standardised distance matching
and an `|SMD| < 0.10` balance target. These are different statistical designs, and **both cannot be the
gate**. Matched-pairs is generally the stronger design — it controls covariates per wallet rather than
in aggregate — and the two are reconcilable by making matched controls the primary benchmark and
building the null by **permuting selected/control labels within matched sets**, which is a standard
permutation test and stronger than random-basket resampling. But that must be specified and
pre-registered, not assumed. Until it is decided, M7 and M9 have an undefined interface.

**2. Excluding long-tail weakens the Edge Origin condition — OPEN.**
`First-Hour Edge Share ≤ 40%` is a hard gate condition built to exclude sniping and insider-like
behaviour. But most first-hour sniping happens in long-tail tokens, and the addendum now excludes
long-tail assets from Ethereum Phase 0 entirely. The condition still binds for a mid-cap token in its
first hour, but that is a much smaller population. This is not a contradiction and the condition should
stay — it costs nothing. But **the 40% threshold was calibrated against an intuition about a universe
that no longer contains its main source of first-hour activity.** Either the threshold is revisited
before freezing, or it is explicitly accepted that the condition has become a cheap backstop rather than
a primary defence. Choosing silently is the one option not available.

**3. Follower order sizing is undefined — OPEN.**
`follower_adjusted_buy_quality` was locked with an assumed follower order size of **2% of total portfolio
capital** at five capital levels. Portfolio construction is now out of scope, so "2% of portfolio" has
no definition to refer to. The addendum supplies replacement inputs — `strategy_aum` and the execution
cost caps — but does not connect them into a sizing rule. Two candidate resolutions:

- **(a)** Keep 2% of `strategy_aum` as a fixed simulation assumption, explicitly labelled a **capacity
  probe** rather than a portfolio weight. Minimal change; preserves what was locked.
- **(b)** Size each simulated order to the **largest amount within the execution cost cap** (1% majors,
  2% mid-cap), bounded by `strategy_aum`. Follows directly from the addendum's own constraints.

(b) is the better fit with the rest of the addendum, but it changes what the metric *means*: from "what
a 2% position would have returned" to "what the largest economically executable position would have
returned." Both are defensible; they are not the same measurement, and M8 cannot be built until one is
chosen.

### The original specification is not in the repository

The three source documents in `docs/` reference the original specification's sections — §5.1, §5.2,
§5.3, §5.4, §5.5, §5.7, §5.8, §5.9, §5.10, §5.11, §5.12, §9, §10, §11, §12, §13, §14 — but **the
specification itself exists only as text pasted into a chat session and is not under version control.**

Every reference of the form "currently the spec says X, change it to Y" is therefore **unverifiable
against its source**. The amendments document paraphrases what it is amending, and those paraphrases
are the only surviving record. Specific gaps a builder will hit:

- §14's example output ("recommended portfolio allocation is 5%", with a confidence and a cost estimate)
  is quoted only in fragments; its full shape is unknown.
- §5.11's original example allocation is stated only as the thing being replaced.
- §9's original data model is unknown; A14 adds fields to a table nobody can see.
- §12's original risk list is enumerated by category name only.
- The twelve engines are named but not specified.

**Do not invent the missing contents.** Where this PRD needed something the specification would have
supplied, it either derives it from the three documents in the repository or marks it open. The correct
remediation is to commit the original specification to version control before the pre-registration is
frozen, since the freeze manifest is supposed to pin every input to the experiment — and one of them is
currently a chat log.

### Staffing is the most likely cause of death

The rigour of this design creates a hiring bar that is itself the project's largest risk. The Primary
Builder profile is a senior quant *and* an on-chain data engineer: advanced SQL over warehouse spellbook
models, Python for simulation and statistical testing, EVM internals down to traces and balance deltas,
DEX pools and concentrated liquidity, FIFO position accounting, backtest design without look-ahead bias,
bootstrap and null-distribution testing, and reproducible versioned pipelines. That is a rare
combination. The Independent Validator is harder: competent enough to hand-verify on-chain accounting,
*not* the builder, and available part-time externally.

**The most likely cause of death for this project is now "two people were not found," not "the
hypothesis was wrong."** That is a better failure than starting badly, but it must be recorded rather
than discovered. Two of the four start preconditions are these two roles. Until both are filled the
status remains `DESIGNED, NOT READY FOR EXECUTION`, and the correct response to a shortfall is to pause,
not to compress the design.

The addendum's proposal to build with an AI agent and validate with a separate AI agent changes the
shape of this risk without removing it. `MACHINE-INDEPENDENT` is genuinely better than
`NOT INDEPENDENT` — it catches transcription errors, arithmetic slips, and single-path logic bugs. It is
genuinely weaker than `EXTERNALLY REVIEWED`, because two agents from the same base model share priors
and make *correlated* errors: the same misreading of an ambiguous rule, the same wrong assumption about
a token standard. That is exactly the failure class independent validation exists to catch and the class
two agents are worst at catching. The bounded mitigation — 10–15 complex accounts reviewed by an
external human specialist — should be treated as a cost to pay, not an option to consider.

### The Berk–Green limit no backtest can measure

Wallet alpha has persisted partly **because** the wallets take no outside capital. Copy flow *is* the
capital-chasing-performance mechanism. On a thin pool, capacity is exhausted at the first follower.

**Building the product degrades the signal the product depends on, and no backtest on historical data
can measure this.** Phase 0 simulates a single instantaneous copier with no crowding — which is why even
the most optimistic published copier result under that assumption (+2.9%) should be read as an upper
bound. A `GO` from this system means "the edge existed historically and would have survived transfer to
one follower at design_capital." It does not and cannot mean "the edge will survive this product
existing."

Two related limits belong in the same paragraph, because they share the property of being real and
unmeasurable by this design:

- **Adversarial targeting.** Wallets engineered to attract copy traders and then dump on them are
  documented, not folklore; bundle bots appear in roughly a quarter of studied projects. Past-PnL rank
  is an *adversarially targeted* ranking, not merely a noisy one, and the attacker's cost of
  manufacturing a plausible track record across many addresses is near zero. The Edge Origin condition
  is a partial defence, not a complete one — and per open conflict 2 above, it is now a weaker one than
  when it was designed.
- **Identity.** Address ≠ agent, and entity clustering is out of scope.

### Two smaller notes worth carrying forward

**The market has already voted, and the vote supports this design rather than contradicting it.** Solana
trading-terminal and bot fees fell ~89% from their January 2025 peak; the category's revenue leader
offers **no copy trading at all** — only wallet tracking, alerts, and manual execution — while the
products with the most sophisticated auto-copy implementations are down 95%+ from peak. Read correctly:
the value is in discovery and signal quality, not in blind automated execution.

**Two fabricated sources were caught and discarded during the research that produced these documents** —
in one case confident verbatim quotes attributed to a paper containing none of them, in another an
invented data table for a real paper whose actual figures were entirely different. Separately, the
author of the pre-registration twice asserted that no crypto study of trader skill persistence existed;
that was wrong, and the study was in a paper already cited elsewhere in the same research. Two
independent adversarial reviews caught it. The information environment around "smart money" is full of
unsupported claims in **both** directions. That is the strongest practical argument for testing the
premise on your own data rather than relying on secondary sources — which is what Phase 0 is.
