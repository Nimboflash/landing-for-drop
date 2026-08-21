# Addendum — Decision Engine and Deployment Models

**Project:** Smart Wallet Copy Trading & Portfolio Intelligence System
**Status:** Accepted into the project. Items marked ⚠ change previously locked decisions and are listed in §14.
**Companion documents:**
[`phase-0-preregistration.md`](./phase-0-preregistration.md) · [`spec-amendments.md`](./spec-amendments.md)

This addendum restates the project as a **machine-driven decision engine** rather than a portfolio
management system, separates strategy capital from user capital, and defines two deployment models
that share one validated core.

---

## 1. Core system definition

The project is a **machine-driven wallet intelligence and decision engine**. Its purpose:

1. Discover potentially skilled on-chain wallets.
2. Verify whether their historical skill persists out of sample.
3. Test whether their trades remain economically copyable after execution costs.
4. Reject wallets, assets, and trades that are not copyable at the required capital level.
5. Generate a deterministic final decision.

Two deployment models may later use the machine:

- **Model A — Managed Basket or Fund** (§5)
- **Model B — Recommendation-Only Service** (§6)

Both use the same validated wallet-selection, copyability, risk, and decision engine. The engine is
built once; the deployment models are downstream.

> **Note on continuity.** This re-framing does not weaken the internal-only constraint recorded as
> Decision 1. Both deployment models sit *after* Phase 5 and remain conditional on the five proofs:
> out-of-sample persistence, profitability after costs, verified risk-engine behaviour, a credible
> track record, and a completed legal and licensing review. Building the engine is not the same as
> deploying it.

---

## 2. Machine governance

The system does not require a discretionary investment owner to choose the final result.

An **Experiment Governance Module** will:

- freeze all definitions and parameters before measurement;
- store code, data, configuration, and random-seed versions;
- prevent thresholds from changing after results are observed;
- invalidate the complete run when a real implementation bug is discovered;
- generate the final machine-readable gate decision.

Final research outcome, machine-readable:

```
GO
CONDITIONAL REVIEW
STOP
```

**No person and no AI agent may manually reinterpret a failed gate as a successful result.**

Operational administrators may stop a process for security, data corruption, or infrastructure
failure. They may **not** modify the research result.

> This mechanises the discipline that was previously procedural. The pre-registration document
> (§8.4, §9.7) describes the same rules as a protocol humans follow. The governance module makes
> them enforced rather than agreed. This is a strict improvement: the failure mode being guarded
> against is not dishonesty, it is a well-intentioned engineer deciding a bug was "small enough."

---

## 3. Builder and independent validation

The project may be built by an **AI agent** with combined capabilities in: EVM and Ethereum data,
DEX transaction reconstruction, quantitative finance, statistics and experimental design, SQL and
Python, and liquidity and execution modelling.

A separate **Independent Validator Agent** must:

- use raw Ethereum transactions, receipts, logs, traces, and balance changes;
- use an implementation path **separate from the primary builder**;
- avoid reusing the builder's classification, FIFO, or valuation functions;
- produce expected outputs **before** seeing the builder's results;
- generate a machine-readable validation report;
- block the main test when validation conditions fail.

Validation status must state explicitly which of these applies:

```
MACHINE-INDEPENDENT
EXTERNALLY REVIEWED
NOT INDEPENDENT
```

> ⚠ **Honest note on what `MACHINE-INDEPENDENT` is worth.** Two agents built from the same base model,
> given the same specification, share priors. They will tend to make *correlated* errors — the same
> misreading of an ambiguous rule, the same wrong assumption about a token standard. That is exactly
> the failure class independent validation exists to catch, and it is the class two agents are worst
> at catching.
>
> `MACHINE-INDEPENDENT` is genuinely better than `NOT INDEPENDENT`: it catches transcription errors,
> arithmetic slips, and single-path logic bugs. It is genuinely weaker than `EXTERNALLY REVIEWED`.
> The three-state label is the right design precisely because it forces the distinction to be stated
> rather than assumed.
>
> **Recommended mitigation, if `EXTERNALLY REVIEWED` is not achievable:** require the validator agent
> to derive its expected outputs from the **raw chain data and the specification only**, never from
> the builder's code or intermediate artefacts, and to record its reasoning before the comparison.
> Additionally, keep the requirement of 10–15 complex accounts reviewed by an external human
> specialist (pre-registration §9.5) — that is a small, bounded cost that converts the status to
> `EXTERNALLY REVIEWED`.

---

## 4. Capital model

The system maintains **two separate capital inputs**. Conflating them was an unstated ambiguity in
the earlier design; separating them is the single most useful change in this addendum.

```
strategy_aum     total capital controlled by the basket / fund / strategy
user_capital     amount invested by one individual user
```

### 4.1 `strategy_aum`

Determines: wallet eligibility · position capacity · liquidity requirements · slippage · trade
copyability · maximum executable order size.

Tested at:

```
$100,000   $250,000   $500,000   $1,500,000   $2,000,000
```

### 4.2 `user_capital`

The amount invested by one user. Recommendations must remain practical for small balances, including
around **$1,000**.

**The system must not recommend economically inefficient trades merely to produce activity.**

For low-capital users the machine may return:

```
BUY
SELL
HOLD
WAIT
NOT ECONOMICALLY EXECUTABLE
```

> `WAIT` and `NOT ECONOMICALLY EXECUTABLE` are new states and both are valuable. `WAIT` says the
> signal is real but this is not the moment. `NOT ECONOMICALLY EXECUTABLE` says the signal is real
> but not for this user's size — the honest answer that most retail products refuse to give.
>
> The economics support this: median Ethereum swap round-trip cost is **$0.053**, so a $150 position
> pays ~0.04% in gas. Gas does not make small trades unviable. **Slippage and minimum viable position
> sizing do**, and those are what `NOT ECONOMICALLY EXECUTABLE` must be computed against.

---

## 5. Deployment Model A — Managed Basket or Fund

```
User investments
      ↓
Combined strategy AUM
      ↓
Machine decision engine
      ↓
Basket or fund execution layer
      ↓
Users receive proportional performance
```

**Wallet selection and trade copyability are calculated using the combined `strategy_aum`, not each
user's individual investment.** This lets small investors participate without generating inefficient
individual trades — the pooling *is* the mechanism that makes small capital viable.

The machine produces the investment signal. Execution, custody, fund structure, accounting, legal
review, and the customer interface are **separate downstream workstreams** and are not implemented by
the current research project.

---

## 6. Deployment Model B — Recommendation-Only Service

The engine does not control capital and does not execute trades. It produces structured
recommendations from: user capital · wallet consensus · asset liquidity · execution cost ·
copyability · risk · recommendation validity period.

```json
{
  "decision": "BUY",
  "asset": "ETH",
  "confidence": 0.78,
  "user_capital_usd": 1000,
  "recommended_max_amount_usd": 150,
  "estimated_total_cost_pct": 0.6,
  "valid_until": "2026-08-01T12:00:00Z",
  "reason_codes": [
    "persistent_wallet_consensus",
    "copyable_at_user_capital",
    "sufficient_liquidity"
  ]
}
```

The engine **may reject a recommendation** when cost, liquidity, or capital constraints make the
trade unsuitable.

> Two fields here are doing more work than they appear to. `valid_until` makes signal decay explicit
> and machine-enforced rather than a caveat in a footnote. `reason_codes` makes every recommendation
> auditable after the fact — you can ask, six months later, which reason codes were present on the
> recommendations that lost money. Keep both.
>
> ⚠ **Regulatory note.** Model B is the model that most clearly constitutes investment advice. See
> `spec-amendments.md` A12.1: ESMA Q&A 2463 (April 2025) treats auto-executing third-party signals
> with discretion as portfolio management under MiCA, and a per-user, capital-sized recommendation is
> advice in most jurisdictions regardless of whether execution is automated. Model B is not the
> "lighter" option from a compliance standpoint — in several respects it is the heavier one.

---

## 7. Data retrieval and wallet discovery

Phase 0 uses **Ethereum mainnet only**.

The pipeline follows **filter early, enrich late**:

```
Ethereum DEX activity
      ↓
Warehouse-level filters
      ↓
Candidate wallet summaries
      ↓
Infrastructure and bot exclusions
      ↓
Detailed extraction for surviving wallets
      ↓
Transaction-level balance netting
      ↓
Eligible wallet universe
      ↓
Ranking and copyability simulation
```

Two-stage buffer:

```
Initial candidate buffer:   10–1,200 potential buys
Final eligibility:          20–1,000 valid buys
```

> The wider outer buffer is correct and was missing from the earlier design. "Potential buys" are
> counted before balance netting, and netting *removes* rows (circular arbitrage, intermediate route
> tokens, failed transactions). A wallet with 22 potential buys can easily fall below 20 valid buys
> after netting. Filtering at the final threshold in the first pass would silently drop wallets that
> should have been evaluated.

Broad Ethereum data stays in the warehouse. Full transaction histories are extracted only for:
candidate wallets · selected wallets · benchmark wallets · golden validation accounts ·
reconciliation samples.

---

## 8. Transaction classification rules

Every transaction preserves both:

```
tx_sender
portfolio_owner
```

**The transaction sender must never overwrite the recovered economic owner.**

Valid buys are reconstructed through **transaction-level balance netting**. The pipeline must:

- include successful transactions only;
- normalise ETH and WETH;
- remove intermediate route tokens;
- exclude fee and referral transfers;
- detect and exclude circular arbitrage;
- identify actual buy and sell endpoints;
- exclude uncertain owner attribution from the primary metric.

**Netting residual tolerance** — negligible when:

```
USD residual ≤ max($0.01, 0.01% of transaction notional)
```

Residuals above the threshold are **excluded from the primary metric and sent to a reconciliation
queue**. They are not silently dropped, and they are not silently included.

> ✅ **Closes an open item.** The pre-registration (§4.2) required a partial-fill tolerance to be
> pre-registered but did not name one. This does. The floor-plus-percentage form is the right shape:
> a fixed dollar floor handles dust on small trades, the percentage handles large ones.

---

## 9. Valuation and copyability rules

### 9.1 Dead pool definition

```
No successful swap for 30 days
AND executable exit value is below the minimum threshold
AND no validated replacement pool exists
```

Dead positions are valued at **zero**.

> ✅ **Closes an open item.** The pre-registration (§4.4, Case 3) required the inactivity window to be
> defined. The three-part conjunction is stricter and better than a bare time window: a pool can be
> quiet for 30 days and still be exitable, and a token can migrate to a live pool. Requiring all
> three conditions avoids zeroing a position that could actually be sold.

### 9.2 Pool migration

Migration may be followed **only** when supported by liquidity history, real trading activity, and
unchanged token identity. **Migration does not reset token age.**

### 9.3 Copy Retention display threshold

```
Copy Retention is displayed only when Raw Buy Quality ≥ 2 percentage points
```

> ✅ **Closes an open item.** The pre-registration (§4.5) said "above a minimum threshold" without
> naming it. 2pp is a reasonable floor: below it, the ratio's denominator is small enough that the
> retention figure is dominated by noise.

### 9.4 Follower simulation constraints

- entry at the **first full block after** the leader;
- the **best deterministic public execution source**;
- **no private RFQ or unavailable market-maker inventory**;
- no future information;
- at least **90% order fill**.

> ✅ **Directly encodes a measured finding.** Aggregator quotes overstate executable capacity because
> part of the route fills against RFQ / market-maker inventory not reliably available to a
> latency-sensitive follower — measured at a 240× spread for PEPE ($471 single-pool versus $114,000
> routed). Excluding private RFQ from the simulation is the correct and conservative choice.
>
> The 90% fill requirement is the other half of the same defence: a quote that can only be partially
> filled is not a fill.

### 9.5 Maximum total execution cost

```
Major assets:    1%
Mid-cap assets:  2%
Long-tail:       excluded from Ethereum Phase 0
```

> ✅ **Encodes the measured capacity result.** Ethereum long-tail capacity measured **$0** at every
> assumed edge level (5%, 10%, 15%, 30%): the leader's own footprint consumes the entire slippage
> budget before a single copier trades, with median long-tail `S₁` at $698. Excluding long-tail from
> Ethereum Phase 0 outright is more honest than measuring it and discovering it is unusable.
>
> ⚠ **This has a consequence for the gate.** See §14.2.

### 9.6 Depth model

The engine must consider **both**:

- AMM pool liquidity and tick depth;
- order-book depth and available quantity at each price level.

> Correct, and it matters more than it looks. For Uniswap v3/v4, total TVL *understates* near-spot
> depth by 5–23× — use virtual reserves (`x_v = L/√P`) inside the active band and integrate across
> ticks beyond ~1%. Active-tick liquidity alone is unreliable for volatile tokens: the measured size
> ratio between the 10% and 1% thresholds was 7.6× for USDC/WETH but **507×** for PEPE.

---

## 10. Wallet matching and benchmarks

Selected wallets are compared with **activity-matched controls** across ten dimensions:

```
account type          median trade size
capital deployed      trade frequency
valid buy count       liquidity-band exposure
buy volume            first-hour purchase share
active days
wallet age
```

Use **standardised distance-based matching**. Each selected wallet receives:

```
5 primary matched controls
5 additional robustness controls
```

Matching may use replacement, but the report must show: number of unique controls · control reuse
frequency · effective benchmark sample size · unmatched selected wallets · covariate balance.

Target balance:

```
Absolute standardised mean difference < 0.10
```

> This is a significant strengthening, and it is well-founded. The June 2026 placebo study
> ([arXiv:2607.02795](https://arxiv.org/abs/2607.02795)) found apparently-skilled wallet cohorts
> returning +132.3% while **activity-matched placebo cohorts returned +216.3%** — the whole signal
> was selection bias. Matching quality is therefore not a methodological nicety; it is the difference
> between a result and an artefact. SMD < 0.10 is the standard threshold from the causal-inference
> literature and is the right one to borrow.
>
> Two dimensions here deserve specific note. **`liquidity-band exposure`** matters because a wallet
> trading only deep pools and a wallet trading only thin ones face different return distributions
> regardless of skill. **`first-hour purchase share`** matters because without it, a sniper-heavy
> selected group would be compared against a non-sniper control and the sniping itself would read as
> skill.
>
> ⚠ **This changes the null distribution design.** See §14.1.

---

## 11. Reproducibility and failure rules

The frozen experiment must include: source-code version · data snapshot · protocol-coverage version ·
decoder version · model version · configuration · random seeds · known-answer fixtures · validation
report.

**Seeding:** one master random seed with deterministic child seeds.

**Final null testing:**

```
1,000 leader null runs per window
1,000 follower null runs per window
```

**Failure policy:**

```
Golden-set discrepancy         → hard failure
Known-answer test failure      → hard failure
Unsupported population event   → quarantine and report
Unexplained dropped event      → prohibited
```

> ✅ **Closes an open item** (random-seed policy was listed in the freeze manifest but not defined) and
> **tightens another**: null runs move from "200 minimum, 1,000 preferred" to 1,000 fixed, per window,
> per column. That is 8,000 total runs. Since this is resampling of already-extracted data, the data
> cost remains zero; the cost is compute time only.
>
> The distinction between *quarantine and report* and *prohibited* is the important line in the
> failure policy. An event the pipeline does not support is a known unknown and must be counted. An
> event that vanishes without explanation is the failure that makes every downstream number
> untrustworthy.

---

## 12. Live wallet health policy

Applies **after Phase 0 passes**. Not part of Phase 0.

Lifecycle:

```
Candidate → Shadow → Active → Warning → Paused → Expired
```

Initial health rules:

```
Warning:  max(7 days,  2× historical trade gap)
Pause:    max(14 days, 3× historical trade gap)
Expire:   max(30 days, 5× historical trade gap)
Hard inactivity ceiling: 60 days
```

Immediate pause on: attribution uncertainty · security concerns · manipulation · infrastructure
reclassification · strategy changes · liquidity failure · copyability failure.

Operating cadence:

```
Wallet crawling:        every block
Health monitoring:      daily
Score refresh:          weekly
Candidate discovery:    monthly
Shadow period:          30 days
Replacement review:     monthly
Full reselection:       quarterly
Coverage audit:         monthly
Model revalidation:     every 6 months
```

> The relative thresholds (`2× historical trade gap`) are better than fixed windows alone, because a
> wallet that normally trades weekly and a wallet that normally trades hourly are not equally dead
> after seven days of silence. Using `max()` of both keeps a floor under the fast traders.
>
> **The Shadow state is the most valuable item here.** A 30-day shadow period before a newly
> discovered wallet influences anything real is the operational equivalent of out-of-sample testing,
> applied continuously rather than once. It is also the natural place to measure churn — the metric
> the pre-registration (§10) requires Phase 0 to report.
>
> **Note on cadence cost:** *wallet crawling every block* on Ethereum means a 12-second loop. For 200
> watched wallets this is inexpensive, but it is a real-time streaming requirement, not a batch one —
> and Dune is the wrong tool for it (30-minute refresh, not partitioned on `taker`). Phase 3 needs a
> second data path for live monitoring, separate from the batch path Phase 0 uses.

---

## 13. Current project scope

**Included:**

```
Phase 0 research pipeline       activity-matched benchmarks
wallet discovery                copyability simulation
transaction reconstruction      independent validation
wallet scoring                  deterministic recommendation output
```

**Excluded:**

```
portfolio construction          basket / fund accounting
automated execution             legal and licensing implementation
customer interface              multi-chain expansion
custody
```

These may become separate downstream projects **after the core hypothesis and decision engine pass
validation**.

---

## 14. ✅ Conflicts with previously locked decisions — RESOLVED 2026-07-31

Three items in this addendum changed decisions that were already locked. All three were resolved by
the Research Owner on 2026-07-31 and merged into `phase-0-preregistration.md` v1.1. The original
statements are kept below with the resolution recorded against each, because the reasoning is part of
the audit trail — a later reader should be able to see what the alternatives were, not just what was
chosen.

| # | Conflict | Resolution | Merged into |
|---|---|---|---|
| 14.1 | Matching design vs null construction | **Matched pairs + within-set permutation null** | §6.6, §8.2 |
| 14.2 | Edge Origin threshold after long-tail exclusion | **Keep 40%, recorded as a backstop** | §7.1 |
| 14.3 | Follower order sizing | **Largest size within the execution cost cap** | §4.5 |

### 14.1 The matching design changes the null distribution

> **RESOLVED — matched pairs + within-matched-set permutation.** Matched controls are the primary
> benchmark; the null permutes selected/control labels within each matched set and recomputes the
> full gate. The naive random basket is retained only as a sanity floor that cannot change the gate.
> Chosen because the permutation preserves each set's covariate profile exactly, so the null asks
> whether the label assignment is informative *given already-balanced groups* — the question the
> June 2026 placebo study shows actually matters. Merged into pre-registration §6.6 and §8.2.


**Locked (pre-registration §6.6, §8.2):** the null distribution is built by drawing **random baskets**
of N wallets from the activity-matched-eligible universe, repeatedly, and comparing basket against
basket.

**Addendum §10:** each selected wallet receives **5 primary + 5 robustness matched controls**, with
standardised distance matching and an SMD < 0.10 balance target.

These are different statistical designs. Matched-pairs is generally the stronger one — it controls
covariates per wallet rather than in aggregate — but it changes how the null is constructed and what
the 95th percentile refers to. **Both cannot be the gate.**

The two are reconcilable: matched controls become the *primary* benchmark, and the null distribution
is then built by permuting the selected/control labels within matched sets. That is a standard
permutation test and it is stronger than random basket resampling. But it must be specified, not
assumed.

### 14.2 Excluding long-tail weakens the Edge Origin condition

> **RESOLVED — keep 40%, record the demotion.** The threshold is unchanged and the condition still
> binds, but it is now documented as a cheap backstop rather than the primary defence against
> uncopyable behaviour; that role belongs to Gate 2, which tests economic copyability directly at
> `design_capital`. Not tightened, because a new number would be intuition rather than measurement —
> one uncalibrated threshold traded for another. Not dropped, because it costs nothing and the
> mid-cap first-hour case is real. Merged into pre-registration §7.1.


**Locked (Decision 7):** `First-Hour Edge Share ≤ 40%` is a hard gate condition per window, built to
exclude sniping and insider-like behaviour.

**Addendum §9.5:** long-tail assets are excluded from Ethereum Phase 0 entirely.

Most first-hour sniping happens in long-tail tokens. Excluding those assets removes most of what the
Edge Origin condition was defending against — the condition still binds for a mid-cap token in its
first hour, but that is a much smaller population.

This is not a contradiction, and the condition should stay (it costs nothing). But the **40% threshold
was calibrated against an intuition about a universe that now excludes its main source of first-hour
activity.** Either the threshold should be revisited before freezing, or it should be explicitly
accepted that the condition is now a cheap backstop rather than a primary defence.

### 14.3 Excluding portfolio construction leaves follower sizing undefined

> **RESOLVED — size to the execution cost cap.** Each simulated order is the largest amount whose
> total execution cost stays within the §9.5 cap (1% majors, 2% mid-cap), bounded by `strategy_aum`
> at each of the five levels. This changes the metric's meaning from "what a fixed 2% position
> returned" to "what the largest economically executable position returned" — deliberately, because
> it answers whether this capital can use the signal at all. Merged into pre-registration §4.5.


**Locked (Decision 8):** `follower_adjusted_buy_quality` is computed with an assumed follower order
size of **2% of total portfolio capital**, at five capital levels.

**Addendum §13:** portfolio construction is **excluded** from current project scope.

If there is no portfolio construction, "2% of portfolio" has no definition to refer to. The addendum
supplies the replacement inputs — `strategy_aum` (§4.1) and the execution cost caps (§9.5) — but does
not connect them into a sizing rule.

Two candidate resolutions:

- **(a)** Keep 2% of `strategy_aum` as a fixed simulation assumption, explicitly labelled as a
  capacity probe rather than a portfolio weight. Minimal change; preserves what was locked.
- **(b)** Size each simulated order to the **largest amount that stays within the §9.5 execution cost
  cap** (1% majors, 2% mid-cap), bounded by `strategy_aum`. This measures maximum executable size
  rather than a fixed weight, and follows directly from the addendum's own constraints.

**(b) is the better fit** with the rest of the addendum, but it changes what
`follower_adjusted_buy_quality` means: from "what a 2% position would have returned" to "what the
largest economically executable position would have returned." Both are defensible; they are not the
same measurement.

---

## 15. Items this addendum closes

Recorded so they are not re-litigated:

| Previously open | Now fixed at | Where |
|---|---|---|
| Netting residual tolerance | `max($0.01, 0.01% of notional)`, excess to reconciliation queue | §8 |
| Dead-pool inactivity window | 30 days **and** exit value below threshold **and** no replacement pool | §9.1 |
| Copy Retention minimum denominator | Raw Buy Quality ≥ 2 pp | §9.3 |
| Random-seed policy | one master seed, deterministic child seeds | §11 |
| Null run count | 1,000 per window per column (was 200 min / 1,000 preferred) | §11 |
| Follower execution source | best deterministic public source, no private RFQ, ≥90% fill | §9.4 |
| Long-tail treatment on Ethereum | excluded from Phase 0 | §9.5 |
| Candidate buffer vs final eligibility | 10–1,200 potential / 20–1,000 valid | §7 |
