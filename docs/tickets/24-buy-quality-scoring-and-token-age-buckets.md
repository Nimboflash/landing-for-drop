# 24 — buy_quality_30d, log weights, and token-age buckets

**What to build:** Close the loop on the primary metric. Every golden account now runs end to end and
produces a `buy_quality_30d` within 0.5 percentage points of its hand-computed answer, with each buy
assigned to a non-overlapping token-age bucket. This is the point at which the whole golden report and
the whole known-answer battery should be green — and the point at which the pipeline has earned the
right to be pointed at data nobody hand-checked.

**Blocked by:** 23

**Status:** audited 2026-08-16 — **7 met, 1 partial, 1 not met.** The strongest of the four packages
audited that day. `src/scoring/` is 876 lines and runs on real Ethereum data. Boxes left unticked; the
audit is below.

**The 5pp small-denominator guard was attacked deliberately and held.** It is the most dangerous
condition in the scoring path — an unmeasurable window carrying a share of zero would pass the ≤40%
Edge Origin test — so the auditor was pointed straight at it. The guard is evaluated *before* the
share; the `None` ↔ `INDETERMINATE` pairing is enforced in two separate modules rather than one;
`passes` requires `VALID` alone; a property test rejects `INDETERMINATE` at **every** threshold
including −1,000,000; and it serialises as `null`, never as `"0"`. That is the shape a guard should
have.

**Met.** `Σ(w·r)/Σw` with `w = log(1+v)`, pinned by a hand-computed `buy_quality == 0.2` exactly plus
38-digit bucket shares in the frozen battery. Exactly one age bucket per buy, block-first so bucket A
is measured in **blocks** and not elapsed time, with both sides of every edge pinned against literals
and the edges themselves read from the frozen set. Age measured from the token's trading start rather
than any pool, so a migration cannot reset it. Bucket A reported separately *and* inside the
first-hour aggregate, with an import-time check on the prefix relationship. Four `value_basis` shares
that must sum to 1, refusing a wallet with no basis. No forward measurement, held by the post-T0
barrier's in-degree and transitive-closure rules.

**Not met: criterion 5**, the 0.5pp/exact/0.5% agreement with traced golden accounts. Not merely
untested — **unbuildable in the current tree**, because `golden_set.trace` is a blocked stage with no
archival node and no raw-chain reader behind it. The `max_wallet_buy_quality_difference_pp` gate
condition exists and is fed only by hand-written dictionaries in tests, so the 0.5pp tolerance has
never been applied to a number derived independently of the builder lane. This criterion's own claim
is that the pipeline "has earned the right to be pointed at unchecked data"; that claim is currently
unsupported, and the sixteen synthetic battery cases are the real evidence.

**Partial: criterion 8's four standing data-integrity metrics.** All four are computed —
`attribution/coverage.py`, the basis shares, the queue volume, the census counts — and `RunReport`
(`src/reporting/run.py:117`) has **no field for any of them**. The pinned published surface omits
`result.attribution` entirely, and no decoder *coverage gap rate* exists at all, only counts. So the
figures accompanied the output only in the sense that something computed them, which is not what the
criterion asks — the same shape as ticket 21's orphaned reconciliation queue.

**A home now exists.** `reporting.DataIntegrity` is a required block on `RunReport` carrying all four
standing figures, and it survives into the hashed artifact. `None` means *not measured* and never
zero: a run reporting `0` claims somebody looked and found nothing missing, a run reporting `None`
says nobody looked, and `NOT_MEASURED` gives the reason for each. What remains for this ticket is the
wiring — computing this package's figure into the block at the composition root, rather than the
block being unable to hold it at all.

- [ ] Wallet-level scoring is `buy_quality_30d = Σ(w_i · r_i) / Σ(w_i)` where
      `w_i = log(1 + trade_value_usd_i)`, and it is reproducible deterministically from a fixed event
      set.
- [ ] Each buy is assigned exactly one token-age bucket, non-overlapping:
      A = first 10 blocks; B = after 10 blocks through end of hour 1; C = after hour 1 through end of
      hour 24; D = older than 24 hours. First-Hour Purchases = A + B.
- [ ] Bucket assignment uses `token_trading_start_block` and is unaffected by pool migration.
- [ ] Bucket A is reported separately as well as inside the first-hour aggregate.
- [ ] Every golden account matches within 0.5 pp on buy quality, exactly on deterministic fields, and
      within 0.5% on per-event and wallet realized USD values.
- [ ] The full sixteen-case known-answer battery passes at 100% with no waivers.
- [ ] Realized / marked / dead shares are reported alongside every wallet score, so a score resting
      largely on marking is visibly weaker than its headline number.
- [ ] The standing data-integrity metrics accompany the output: decoder coverage gap, attribution
      fallback rate, realized versus marked share, and reconciliation-queue volume.
- [ ] No forward measurement of any selected basket has occurred — the pipeline has still only run on
      golden and synthetic inputs.
