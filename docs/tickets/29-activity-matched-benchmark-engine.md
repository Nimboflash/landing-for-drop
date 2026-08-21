# 29 — Activity-matched benchmark engine

**What to build:** The control that separates a result from an artefact. Every threshold in this
experiment is measured against activity-matched wallets and never against naive random ones, because a
study of 166,098 token launches found apparently-skilled cohorts returning +132.3% while
activity-matched placebo cohorts returned **+216.3%** — the placebos did better, and the signal was
selection bias. This ticket produces matched controls for each selected wallet, drawn from the same
frozen `T0` universe using pre-`T0` data only, with balance reported rather than asserted.

**Blocked by:** 28, 08

**Status:** audited 2026-08-16 — **4 met, 3 partial, 1 not met.** `src/matching_null/` is 1,628 lines.
Boxes left unticked; the audit is below.

**The null is right, and it was the thing most worth checking.** SS8.2 permutes selected/control labels
*within* each matched set, and the null gate must be the full three-condition gate or the 95th
percentile belongs to a different experiment. Verified: the permutation refuses anything but a
`WindowScore`, cross-checks column and window, `NullRun.passed` is `score.passes()` — all three
conditions — and the observed value is the identity labelling through the same statistic function.

**Met.** Balance across all ten dimensions, with a missing row raising rather than asserting. The
liquidity-band and first-hour dimensions genuinely matched. Controls drawn from the frozen T0
universe with every record checked pre-T0, not merely the ones used. Balance reported per covariate
against |SMD| < 0.10, with the `all(())` vacuous-truth trap closed.

**Robustness controls are excluded structurally in two places and pinned by no test.** SS6.6 says they
are reported and cannot change the gate. `MatchedSet.members` omits them and `nullstat` reads
`primary_controls` only — but editing `nullstat` to extend the benchmark group with
`robustness_controls` breaks nothing in the suite. `MatchedSet.__post_init__` also does not refuse a
robustness control equal to the selected wallet or to a primary control. The rule holds today by
construction rather than by enforcement, which is the distinction this repository usually insists on.

**Not met: the context baskets.** The naive random basket and buy-and-hold ETH exist only in prose —
in `scoring/edge.py`'s comments and in the frozen set's note. Neither is computed anywhere. SS6.6's
resolution demoted the naive basket to a sanity floor rather than the benchmark, and that half is
unimplemented.

**Computed and not published, again.** The SS6.6 balance table is the ticket's own acceptance
condition — an unreported balance is not a control — and `unique_controls`, `control_reuse_rate`,
`effective_sample_size` and `unmatched_selected` are computed on `BenchmarkMatch` and carried to the
stage, then serialized by nothing. No block in `RunReport`, no hit in any artifact writer.

**A home now exists.** `reporting.DataIntegrity` is a required block on `RunReport` carrying all four standing figures, with `None` meaning *not measured* and never zero. What remains for this ticket is the wiring: computing this package's figure into the block at the composition root, rather than the block being unable to hold it.

**One frozen parameter with zero consumers.** `measurement.window_edge_extension_days` is in the
frozen set and nothing reads it; `MEASUREMENT_HORIZON_SECONDS` is hardcoded in `pipeline/inputs.py`
for the reason recorded in ticket 11's `UNMIGRATED` list. No test asserts the benchmark basket's
window-edge treatment is identical to the selected wallets'.

> Depends on OPEN conflict 1. The pre-registration builds the benchmark by random-basket resampling;
> the addendum specifies 5 primary plus 5 robustness matched controls per wallet with `|SMD| < 0.10`.
> These are different statistical designs and both cannot be the gate. The interface between this
> engine and the null engine is undefined until ticket 08 is resolved and signed.

- [ ] Matching balances across all ten dimensions: account type, capital deployed, valid buy count,
      buy volume, active days, wallet age, median trade size, trade frequency, **liquidity-band
      exposure**, and **first-hour purchase share**.
- [ ] Liquidity-band exposure and first-hour purchase share are genuinely matched, so a sniper-heavy
      selected group is never compared against a non-sniper control where the sniping itself would
      read as skill.
- [ ] Controls are drawn from the same frozen `T0` universe, using pre-`T0` data only.
- [ ] Covariate balance is reported per covariate against a target of `|SMD| < 0.10`; a matched
      benchmark whose balance is not reported is not accepted as a control.
- [ ] The report emits unique control count, control reuse frequency, effective benchmark sample size,
      and the list of unmatched selected wallets.
- [ ] Naive random active wallets and buy-and-hold ETH are computed and reported as context, and are
      structurally unable to gate anything.
- [ ] The window-edge 30-day extension rule is applied identically to every benchmark basket and to
      the selected basket.
- [ ] The emitted interface matches whatever ticket 08 selected, and the engine exposes exactly what
      the null engine consumes — no second, incompatible shape is left in the codebase.
