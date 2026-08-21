# Amendments to the Project Specification

**Document:** Smart Wallet Copy Trading & Portfolio Intelligence System
**Purpose:** Changes to the original specification arising from design review and research.
**Companion document:** [`phase-0-preregistration.md`](./phase-0-preregistration.md)

Each amendment states what the specification currently says, what it should say, and why. Sources for
research-derived claims are in §13 of the pre-registration document.

---

## A1 — Insert Phase 0 before Phase 1

**Currently:** §10 begins at *Phase 1: Data and Wallet Discovery*.

**Change:** Insert **Phase 0 — Hypothesis Falsification Test** ahead of Phase 1, per the companion
pre-registration document.

**Why:** The specification builds twelve engines across Phases 1–3 and obtains its first real evidence
about the founding premise in Phase 3 or 4 — after nearly everything is built. That ordering is
inverted. Phase 0 tests the premise on historical data in 10–12 weeks for under $1,000 of data cost,
against 4–6 months for Phases 1 and 2.

**Also add to §10:** the project does not enter Phase 1 unless Phase 0's gate passes. A failing gate
stops the project in its current form, and the result is not reinterpreted afterwards as "unusual
market conditions," "incomplete data quality," or "needs a more sophisticated model."

---

## A2 — §1/§2: state the premise as two claims, not one

**Currently:** the premise is implicit and singular — good wallets vote, better wallets get more
weight, output is a portfolio decision.

**Change:** state it as two separable claims, and record that only the first has published support:

```
H1  Leader skill persistence — past buy quality predicts future buy quality
H2  Economic copyability     — that advantage survives transfer to a follower
                               at design_capital, after costs
```

**Why:** measured, with market frictions, on 6,000 projects (arXiv:2601.08641, WWW'26): smart-money
returns were positive for every selection method tested, while **copier returns were negative for four
of the five**. Lasso: leader +9.2%, copier −5.8%. The gap between the two claims is where this class
of project dies. §13 of the specification already draws the distinction conceptually; it needs to be
load-bearing, not a closing remark.

---

## A3 — §3.2: network selection is resolved

**Currently:** *"Possible starting options: Ethereum, Base, Arbitrum, Solana. The project should begin
with only one network."*

**Change:** **Ethereum mainnet**, with the exclusions recorded:

- **Base — excluded.** Launched publicly August 2023. Supplies at most 2 clean windows of the 4 the
  walk-forward design requires. Incompatible with the test, not a poor chain.
- **Solana — excluded.** Trader attribution is unreliable: Jupiter sponsors gas for wallets under
  0.01 SOL on trades above ~$10 and JupiterZ market makers pay fees from per-quote-varying addresses,
  while Dune sets `trader_id = tx_signer`. Gasless swaps are attributed to Jupiter's gas wallet,
  producing phantom mega-wallets and erasing exactly the small/new wallet cohort. Separately, Dune's
  Solana macro resolves swap legs by fixed positional offsets and silently drops non-matching trades.
- **Arbitrum — secondary diagnostic only**, pre-registered, outside the gate.

**Reasons for Ethereum:** full coverage of all four historical windows; the most mature decoder
coverage (46 spellbook models, 35 protocol families, Curve present — Curve is absent on both Arbitrum
and Base); measurably the least bot-concentrated (senders with ≥20 tx are 0.3% of senders and 6.1% of
transactions, versus Solana's 2–3% / 52–70%); and a trade-size composition matching the target capital
profile (average DEX trade $2,980 vs Solana's $99).

**Correction to a common assumption:** gas is *not* the mechanism behind Ethereum's larger trades.
Median Ethereum swap cost is **$0.053**. Slippage is the binding constraint on all four chains, by two
to three orders of magnitude. The size difference is user/capital composition.

---

## A4 — New section: capital parameters are system inputs

**Currently:** the specification never states how much capital the system manages.

**Change:** add capital as a first-class input, before §5.7:

```
Initial capital (paper / limited live)   $100,000 – $250,000
Target capital (on success)              $500,000
design_capital (ceiling designed for)    $1,500,000 – $2,000,000
```

**Why:** §5.7's `Copy Retention Ratio` is not computable without it. Slippage and price impact are
functions of trade size. Capital also sets the liquidity floor, which determines which tokens are
tradeable, which determines which wallets are worth analysing at all — it closes §5.4's funnel from
the top.

**Consequence to record (open decision for Phase 2):** the set of ~200 wallets is a *function of
capital*, not a fixed set. A wallet copyable at $250k may not be copyable at $2M. Selecting at $2M
restricts the universe to liquid-asset traders — where edge is smallest. Selecting at $250k gives a
larger universe but forces re-selection when scaling.

---

## A5 — §5.1: the data collector is a permanent team, not a component

**Currently:** §5.1 reads as a component to be built once.

**Change:** re-scope it as ongoing operational cost with a standing owner.

**Evidence:**

- Migrating a **single** indexer cost QuickSwap **6–8 engineer-weeks**, and by their own account most
  of it was not writing handlers but parity-hunting and recovering undocumented accounting invariants.
- The Uniswap Foundation paid **Allium $480,000 over 21 months** for DEX data normalisation rather
  than build it in-house.
- DefiLlama's shared, crowd-sourced baseline: **625 live DEX adapters, ~45 new and ~250 repaired per
  month, 296 contributors** — and it still misses venues and still disagrees with Dune.
- Decoders break without warning. Jupiter upgraded in place at slot 433,056,714 with a new
  `route_v2` instruction family and a `SwapsEvent` that **drops the `amm` field**; parsers counting
  `SwapEvent` occurrences silently go to zero on v2 routes. Jupiter's own official parser had not been
  updated in twenty months.
- Dune restricted community contributions in October 2025; median age of an open contribution request
  is ~156 days, with enterprise priority. You cannot close your own coverage gaps on a useful
  timescale.

**Also add:** a standing **coverage-gap metric**. Measured gap between Dune's decoder coverage and
DefiLlama's tracked volume is **8.2% on Ethereum** — venues with no decoder at all, whose trades are
invisible rather than mislabelled. This must be reported alongside every result, not silently ignored.

---

## A6 — §5.2: attribution and buy detection

Three changes to the Transaction Classification Engine.

### A6.1 Keep msg.sender and the recovered economic owner as separate fields

**Change to §9 (data model) and §5.2:** every trade record carries **two** distinct fields:

```
tx_sender          the address that sent the transaction (msg.sender)
portfolio_owner    the recovered beneficial owner of the trade
```

Never overwrite one with the other. Follow Allium's shape (`from_address` / `swapper_address`), not
Dune's.

**Why:** Dune's core macro contains `coalesce(base_trades.taker, base_trades.tx_from) AS taker`. Any
project without an explicit taker silently attributes to the transaction sender — the solver, for
solver-settled trades. Conversely, CoW Protocol's model *overwrites* `tx_from` with the trader,
contradicting that column's own documentation. Both directions of error exist in the same table.

Also record: **0x Settler emits no trade events at all** (the trader is in calldata at fixed byte
offsets, amounts partly estimated); **UniswapX appears in neither Dune sector table**; **1inch LOP v4
emits `OrderFilled(bytes32, uint256)`** with no maker and no amounts.

For smart accounts:

```
Safe        → portfolio_owner = Safe address; signers are not separate traders
ERC-4337    → portfolio_owner = smart account sender
              bundler, paymaster, relayer are NEVER recorded as the trader
```

### A6.2 Detect buys by transaction-level balance netting

**Change:** buys are reconstructed by signing amounts and netting per `(transaction, owner, token)`,
not read from per-hop rows and not read from a vendor's aggregator table.

**Why:** `dex.trades` emits one row per pool hop, so `USDC → WETH → TOKEN_A` produces a phantom
"bought WETH" event. Spellbook issue #610 documents a single swap counted **6×**.
`dex_aggregator.trades` does not fix it: it covers only 18 aggregators, excludes direct multi-hop
routes through routers such as Uniswap's Universal Router, and omits the wallet routers (MetaMask
Swaps, Rabby, Phantom, Coinbase Wallet) that carry most retail flow.

Balance netting is route-shape agnostic and handles split routes, which first-hop/last-hop heuristics
do not — Dune's own `dex_multihop_trades` macro has that bug and fails to detect two-hop routes at all
(`having count(*) >= 3`).

Required handling: normalise ETH/WETH before netting; filter to transfers touching the owner address
first (MEV bundles and multicalls in the same transaction otherwise corrupt the result); define a
tolerance for partial-fill residue; and exclude fee and referral transfers from endpoint detection.

### A6.3 Add circular arbitrage as an explicit exclusion

**Change:** add to the §5.2 transaction type list and to §5.5's exclusion criteria.

**Why:** a real transaction routed $956 USDC → SOL → USDC for **$0.049** of profit. Per-leg summing
reports ~$1,912 of "user swap volume"; netting correctly reports ~zero, but there is no "token sold"
to express. Left in, arbitrage bots appear as wallets with thousands of small profitable trades.

Also add: **filter on transaction success before anything else.** Failed transactions carry
well-formed instructions with plausible amounts. Measured failure rates ranged from 17.5% to 65%
depending on venue and sample.

---

## A7 — §5.3: cost-basis handling, and what Phase 0 avoids

**Currently:** §5.3 correctly warns that transfers must not be treated as profit and introduces
`UNKNOWN_COST_BASIS`. That warning is right and stays.

**Add:** a note that Phase 0 **does not require this engine**. Its metric measures the quality of a
wallet's *buys* — realized in the quote asset actually used — rather than the wallet's total PnL.

**Why it matters:** computing true wallet PnL requires resolving cost basis, transfers, airdrops,
staking, and LP activity. That turns a 10-week test into a multi-month build. Measuring buy quality
requires only trade timestamps, sizes, and quote-asset prices — and quote assets (USDC, USDT, WETH,
ETH, WBTC) have reliable price data, while long-tail tokens do not. It is also the *more relevant*
question: you copy a wallet's buys, not its airdrops.

---

## A8 — §5.4: the funnel numbers must be measured, not assumed

**Currently:** §5.4 shows a funnel from 1,000,000 active addresses down to 200 selected wallets.

**Change:** mark these as illustrative and require measurement. Add a **Step 0** that measures the
eligible universe before any ranking, and derive selection size from it:

```
Selected Wallet Count = clamp( 1% of Eligible Universe, min 250, max 1,000 )
```

**Why:** Ethereum has ~33,375 daily DEX traders (versus Solana's ~599,000), and an estimated
340,000–500,000 distinct monthly. After filtering to `20 ≤ valid buys ≤ 1,000`, the eligible universe
is unknown. A fixed count of 500 could mean the top 2.5% in one window and the top 0.25% in another —
those are not the same experiment. A percentage keeps selection pressure constant.

**Add a floor:** if a window's eligible universe is below 10,000 accounts, that window is
`INSUFFICIENT CANDIDATE UNIVERSE` and the design must be revised before the test, not after.

---

## A9 — §5.5: add first-hour concentration to the exclusion criteria

**Currently:** §5.5 lists one-hit wonders, airdrop recipients, deployers, wash traders, MEV bots,
sandwich bots, and arbitrage bots.

**Add:** *snipers and insider-like wallets that buy in the opening blocks of a token's life and hold.*
Sandwich and cross-DEX arbitrage bots are already removed by balance netting (their round trip nets to
zero in one transaction). Snipers are not — they genuinely hold, and they will rank at the very top of
any buy-quality ranking.

**Add the measurement**, with token age defined from first usable liquidity plus one real swap — not
contract creation, and **migration to a new pool does not reset it**:

```
Bucket A:  first 10 blocks
Bucket B:  after 10 blocks through end of hour 1
Bucket C:  after hour 1 through hour 24
Bucket D:  older than 24 hours
```

**Why:** these are exactly the wallets §5.7 exists to remove. Trojan's own product documentation
states the mechanism plainly: against snipers "you are becoming their exit liquidity… you will land
several blocks behind, buying the top of their candle while they dump on you."

---

## A10 — §5.7: the copyability engine

Four changes.

**A10.1 — The imitation penalty is a theorem, not an estimate.** On a strictly convex curve the copier
strictly overpays on every replicated buy. Record the verified magnitude for constant-product pools:

```
A copier trading the same size as the leader pays 3.1× the leader's slippage.
(verified: leader 5.000%, copier 15.500%)

copier slippage ≈ (2 · S_leader + C) / S₁
```

where `S₁` is the trade size costing 1% and `C` is aggregate copier capital. The leader's size enters
at **double weight** — the follower eats the leader's marginal impact, not their average.

**A10.2 — Simulate at multiple capital levels, not one.** `$100k / $250k / $500k / $1.5M / $2M`. A
single trade size makes the engine's output meaningless.

**A10.3 — Do not underwrite capacity on aggregator quotes.** They overstate executable size because
part of the route fills against RFQ / market-maker inventory not reliably available to a
latency-sensitive follower. Measured: PEPE's 1% size was **$471 single-pool versus $114,000 routed** —
a 240× spread.

**A10.4 — Correct the concentrated-liquidity assumption.** For Uniswap v3/v4, total TVL *understates*
near-spot depth by 5–23×, not overstates it. Use virtual reserves (`x_v = L/√P`) inside the active
band and integrate across ticks beyond ~1%. Active-tick liquidity alone is unreliable for volatile
tokens — measured, the size ratio between the 10% and 1% thresholds was 7.6× for USDC/WETH but 507×
for PEPE.

**Add the capacity result:**

```
Measured total AUM capacity — Ethereum ~$7.9M (majors $4.56M, mid-cap $3.30M)
Measured Ethereum long-tail capacity — $0, at every assumed edge level
```

The `$0` is not rounding: the leader's own footprint consumes the entire slippage budget before a
single copier trades (median long-tail `S₁` on Ethereum is $698). **On Ethereum, the wallet signal can
only ever concern liquid and mid-cap assets.**

---

## A11 — §5.11: replace the example allocation

**Currently:** *BTC 20%, ETH 15%, SOL 5%, TOKEN_A 2%, Stablecoins 58%.*

**Problem:** 58% cash plus 35% in assets requiring no wallet-intelligence system leaves the twelve
engines deciding **2% of the portfolio**. Under that allocation, total return is explained almost
entirely by holding BTC and ETH, and the system's contribution is lost in noise.

**Change to:**

```
Wallet Signal Portfolio   40–60%   (base case 50%)
Core BTC/ETH              20–30%   (base case 25%)
Stablecoin Reserve        20–30%   (base case 25%)
```

with a live ramp gated on evidence at each step:

```
Initial live test   10%
After validation    25%
Target state        50%
```

**Add a standing test:** if the wallet-signal sleeve ends up below **20%** of the portfolio, the
economic justification for building a system of this complexity must be re-examined.

---

## A12 — §12: add four missing risks

### A12.1 Regulatory and legal risk — currently absent entirely

The risk section lists data, identity, copyability, manipulation, liquidity, model, market-regime, and
execution risk. It contains no legal risk. This is the largest unlisted risk in the document.

**Add:**

- Through Phase 5 the system is **internal only**. No signal or allocation is shown to any third
  party.
- The moment output reaches customers, §14's *"recommended portfolio allocation is 5%"* **is
  investment advice** — a licensed activity in most jurisdictions.
- ESMA Q&A 2463 (April 2025): auto-executing third-party signals with discretion constitutes
  **portfolio management under MiCA**. See also ESMA Supervisory Briefing ESMA35-42-1428 (March 2023)
  and IOSCO Final Report FR/06/2025 on imitative trading.
- No enforcement action against a crypto copy-trading platform was found for 2025–26 — guidance only.
  Claims of a regulatory crackdown are unsupported.

### A12.2 Berk–Green — the product degrades its own signal

Wallet alpha has persisted partly *because* wallets take no outside capital. Copy flow **is** the
capital-chasing-performance mechanism. On a thin pool, capacity is exhausted at the first follower.

**Building the product degrades the signal the product depends on, and no backtest on historical data
can measure this.** It belongs in §12 as a known, unmeasurable risk.

### A12.3 Adversarial targeting of the ranking

Wallets engineered to attract copy traders and then dump on them are documented, not folklore. Bundle
bots appear in roughly a quarter of studied projects, and vendors' own documentation acknowledges the
pattern. Past-PnL rank is an **adversarially targeted** signal, not merely a noisy one — and the
attacker's cost of manufacturing a plausible track record across many addresses is near zero.

### A12.4 Staffing risk

The rigour this design requires creates a hiring bar that is itself a project risk: a senior quant who
is also an on-chain data engineer, plus an independent validator competent enough to hand-verify
on-chain accounting who did not write the pipeline.

**The most likely cause of death for this project is now "two people were not found," not "the
hypothesis was wrong."**

---

## A13 — §14: qualify the final product definition

**Currently:** §14's example output states a confidence, a cost estimate, a 5% allocation, and a risk
approval.

**Add two qualifications:**

1. **That output is investment advice** if shown to anyone outside the team. See A12.1.
2. **Every such statement must carry its scope.** A result obtained on Ethereum, for a specific
   capital profile and token liquidity band, does not generalise to Base, Solana, or memecoin markets.
   Report the population and capital profile alongside the number, always.

---

## A14 — §9: data model additions

Add to the trade-level tables:

```
tx_sender                  msg.sender / transaction signer
portfolio_owner            recovered beneficial owner (NEVER overwritten by tx_sender)
account_type               EOA | SAFE | ERC4337 | OTHER_CONTRACT
token_trading_start_block  first usable liquidity + first real swap; migration does not reset
token_age_bucket           A | B | C | D
pool_depth_at_trade        pool TVL / virtual reserve at trade time
s1_at_trade                trade size costing 1% slippage, at trade time
is_circular_arb            boolean
netting_residual           partial-fill residue left after transaction-level netting
value_basis                REALIZED | POOL_MARKED | LIQUIDITY_BOUND | DEAD_ZEROED
```

`value_basis` matters: any aggregate result must be reportable as realized share versus marked share
versus dead-zeroed share. A strongly positive number resting 80% on marking is not a credible result.

The existing versioning fields (`data_timestamp`, `model_version`, `scoring_version`,
`classification_version`) stay, and should be joined by `decoder_coverage_version` — the protocol
coverage list in force when the row was produced.

---

## A15 — §11: add data-integrity metrics to success criteria

**Add to the Data Metrics list:**

```
Decoder coverage gap            % of tracked DEX volume with no decoder
Unexplained reconciliation diff % of events that cannot be matched to raw chain data
Realized vs marked share        of all valuation, per period
Attribution fallback rate       % of trades where portfolio_owner fell back to tx_sender
```

**Why:** the last one is the specific failure that produces phantom whales and erases real users. It
should be a monitored metric, not a one-time check.

---

## Summary of amendments

| # | Section | Change |
|---|---|---|
| A1 | §10 | Insert Phase 0 before Phase 1 |
| A2 | §1, §2 | State the premise as two separable claims |
| A3 | §3.2 | Ethereum mainnet selected; Base, Solana excluded with reasons |
| A4 | new | Capital parameters as first-class system inputs |
| A5 | §5.1 | Data collector re-scoped as a permanent team; add coverage-gap metric |
| A6 | §5.2, §9 | Separate `tx_sender` / `portfolio_owner`; balance netting; circular arb |
| A7 | §5.3 | Note that Phase 0 does not require the accounting engine |
| A8 | §5.4 | Funnel numbers measured, not assumed; add Step 0 and a universe floor |
| A9 | §5.5 | Add snipers/insiders and token-age buckets to exclusions |
| A10 | §5.7 | Imitation penalty; multi-tier simulation; capacity corrections |
| A11 | §5.11 | Replace the example allocation; add the 20% justification test |
| A12 | §12 | Add regulatory, Berk–Green, adversarial-targeting, staffing risks |
| A13 | §14 | Qualify the final output as advice; require scope on every claim |
| A14 | §9 | Data model additions |
| A15 | §11 | Data-integrity success metrics |
