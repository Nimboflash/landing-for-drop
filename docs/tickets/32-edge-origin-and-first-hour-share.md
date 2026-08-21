# 32 — Edge Origin decomposition and First-Hour Edge Share

**What to build:** Decompose where the advantage actually comes from, so a gate pass driven by wallets
that snipe the opening blocks and hold cannot survive. Edge contribution is computed at bucket
granularity using the same log weighting as the primary metric, so the condition is measured on the
same basis as the thing it constrains. The small-denominator guard is part of the same mechanism: a
window whose edge origin cannot be measured is a failure, not an abstention.

**Blocked by:** 29, 09

**Status:** ready-for-agent

> Depends on OPEN conflict 2. The `≤ 40%` threshold was calibrated against an intuition about a
> universe that now excludes long-tail assets — which is where most first-hour sniping happens. The
> condition should stay, but whether the threshold is 40%, whether it moves, and whether it is claimed
> as a primary defence or recorded as a cheap backstop is undecided. This ticket cannot state its
> acceptance threshold until ticket 09 is resolved and signed.

- [ ] Bucket edge contribution is computed as
      `max(0, Bucket Weight × (Selected Buy Quality − Matched Benchmark Buy Quality))`, where bucket
      weight is that bucket's share of total selected-portfolio buy weight using `log(1 +
      trade_value_usd)`.
- [ ] `First-Hour Edge Share = (EC_A + EC_B) / (EC_A + EC_B + EC_C + EC_D)`.
- [ ] Exceeding the threshold resolved in ticket 09 sets `Edge Origin Status: UNCOPYABLE-DOMINATED`
      and `Window Result: FAILED` — a hard failure, not a warning, with no override path.
- [ ] Total positive edge contribution below 5 percentage points sets
      `Edge Origin Status: INDETERMINATE` and fails the window; `INDETERMINATE` never counts toward
      the three required successes.
- [ ] Bucket A is additionally reported in isolation as a diagnostic, while the gate condition applies
      to the whole first hour.
- [ ] All comparisons are against the activity-matched benchmark; the naive random benchmark and
      buy-and-hold ETH are reported as context and cannot enter this computation.
- [ ] The decomposition is exercised on constructed baskets with known bucket weights before it ever
      touches the selected basket.
- [ ] The recorded limitation is carried in the output: the Edge Origin condition is a partial defence
      against adversarial targeting, not a complete one.
