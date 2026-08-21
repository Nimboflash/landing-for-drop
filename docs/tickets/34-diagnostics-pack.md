# 34 — Diagnostics pack that cannot move a gate

**What to build:** Everything worth knowing that is deliberately not allowed to decide anything. These
cost almost nothing — the same data with a different ordering — and a divergence between them and the
primary metric is informative. The load-bearing property of this ticket is the second half of its
title: reporting a diagnostic and then using it to overturn a gate result is the exact failure mode
the whole protocol exists to prevent, so the separation must be structural.

**Blocked by:** 33

**Status:** audited 2026-08-16 — **3 met, 3 partial, 1 not met.** `src/reporting/` is 2,781 lines.
Boxes left unticked; the audit is below, and its shape is unusual: **the separation machinery is
excellent and there is almost nothing yet to separate.**

**Not met: criterion 1.** The pack names the nine diagnostics and computes none of them. There is no
`simple_wallet_return`, `buy_return_7d`, `buy_return_90d`, `buy_win_rate`, `median_return`,
`tail_loss`, `bucket_a_isolated` or `activity_band_sensitivity` anywhere in `src/` — and
`diagnostic_pack(())` is a valid report. So the pack currently guarantees that an empty set of
numbers cannot move a gate.

**Met, and this is the part that is genuinely done.** Every diagnostic is labelled in its own record,
and the labelling is re-derived at publish rather than trusted. The gate physically cannot read the
pack: enforced by the lane graph and by tests that AST-walk every module. The report states that only
`buy_quality` decides, and a rewritten gate-relevance statement is refused.

**Two rules checked adversarially, both clean.** SS10's activity bands tile the eligible range exactly —
inclusive `(20,99)`, `(100,499)`, `(500,1000)`, integer-only, refusing anything outside the
eligibility floor and ceiling, so there is no gap for a wallet to fall through. Copy Retention returns
`None` and not zero below an inclusive 2pp floor, and `CapitalLevelReport` forces the N/A to agree
with the count of retentions reported — so "not shown" and "shown as low" cannot be confused.

**Closed 2026-08-16: the four standing metrics now have a home.** `reporting.DataIntegrity` is a
required block on `RunReport`, carrying the decoder coverage gap, the attribution fallback rate, the
unexplained reconciliation difference and the reconciliation-queue volume. It survives into the
hashed artifact — `null` for unmeasured, the exact decimal string for measured.

The design point is that **`None` means not measured and never zero**. A run reporting `0` claims
somebody looked and found nothing missing; a run reporting `None` says nobody looked, and
`NOT_MEASURED` names the reason for each. Those are one keystroke apart and they are opposite claims.
`unmeasured` reports *which* figures are absent rather than how many, because which is what decides
whether the headline number can be read at all. Today every run in this tree reports four `None`s,
which is the true statement about it.

**Previously:** Churn and the realized/marked/dead shares are
reported; the decoder coverage gap, the attribution fallback rate, the unexplained reconciliation
difference and the reconciliation-queue volume have no field in any report type. This is the same
finding as tickets 20, 21, 24 and 29 — five packages computing integrity figures that the published
report cannot carry.

**Partial, honestly bounded.** The no-promotion claim is real but not absolute: `.amount` and `str()`
extraction remain available, and the module says so rather than overclaiming. And two of the five
scope fields — `capital_level` and `liquidity_band` — default to `None`, so "every diagnostic carries
its scope" is true of three.

- [ ] The pack computes and reports: absolute USD profit ranking; simple wallet return; 7-day and
      90-day buy return horizons; buy win rate; median return; tail loss; Bucket A in isolation; and
      sensitivity by activity band across 20–99, 100–499 and 500–1,000 valid buys.
- [ ] Each diagnostic is labelled as a diagnostic in its output record, so a number cannot travel
      without its status.
- [ ] The gate engine cannot read the diagnostics pack, proven by a test that attempts it and fails.
- [ ] There is no configuration, flag, or override that promotes a diagnostic into a gate input.
- [ ] The report states plainly that only `buy_quality` decides the gate, and that a diagnostic passing
      while `buy_quality` fails is informative but changes nothing.
- [ ] Wallet churn in three states, realized/marked/dead shares, decoder coverage gap, attribution
      fallback rate, unexplained reconciliation difference, and reconciliation-queue volume all appear
      alongside the diagnostics as standing metrics.
- [ ] Every diagnostic carries its scope: chain, window, capital level, liquidity band, population.
