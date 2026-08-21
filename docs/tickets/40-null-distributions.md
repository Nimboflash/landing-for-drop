# 40 — Null distributions: 1,000 runs per window per column

**What to build:** Measure the false-positive rate of the threshold instead of assuming it. The entire
pipeline re-runs with random wallets in place of selected ones — 1,000 runs per window for the leader
column and 1,000 for the follower-adjusted column, 8,000 in total — through the same frozen commit and
the same shared functions as the main test. "+15pp in 3 of 4 windows" is an arbitrary number until this
is measured, and a pre-registered threshold that random selection clears is worse than no threshold,
because it manufactures confidence.

**Blocked by:** 39, 08

**Status:** ready-for-agent

> Depends on OPEN conflict 1. Random-basket resampling and within-matched-set label permutation are
> different null constructions and the 95th percentile means something different under each. The null
> cannot be built until ticket 08 selects one and the matching/null interface is specified.

- [ ] 1,000 leader null runs and 1,000 follower-adjusted null runs are executed per window, all four
      windows unchanged, using whichever construction ticket 08 selected.
- [ ] Null sample size per window equals **that window's actual selected wallet count**, so the null
      describes the same experiment as the main test.
- [ ] The null gate is the **identical full three-condition gate**, not a simplified one — a
      two-condition null against a three-condition test voids the calibration.
- [ ] The null is built on the **final** metric including liquidity-bound pricing; calibrating on an
      inflated-pricing version and adding the bound afterwards would belong to a different experiment.
- [ ] Separate leader and follower-adjusted distributions are produced; neither borrows the other's.
- [ ] Null runs and the main test execute from the same frozen commit through the same shared
      functions, and this is verified rather than intended.
- [ ] Per run per window, the following are recorded: mean buy quality advantage, median buy quality
      advantage, First-Hour Edge Share, and window passed yes/no.
- [ ] No new vendor query is issued; the whole exercise resamples already-extracted data and the
      marginal data cost is zero.
- [ ] Reproducibility is proven: the same master seed and commit reproduce all 8,000 runs identically.
- [ ] On completion the governance state advances to `NULL_COMPLETE`.
