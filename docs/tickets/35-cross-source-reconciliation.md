# 35 — Cross-source reconciliation against raw chain data

**What to build:** Validation layer 3. Reconcile the normalised vendor source against raw chain data —
receipts, event logs, execution traces, raw balance deltas — on the whole golden set and on a random
sample of at least 200 accounts. Ground truth is raw chain data and never a second vendor, because two
normalisation vendors share assumptions and in this domain demonstrably take opposite conventions on
the same events. No public benchmark of DEX decoder accuracy exists; this reconciliation is a study
nobody outside has run.

**Blocked by:** 24, 13

**Status:** ready-for-agent

- [ ] On the golden set: supported transaction coverage 100%, unexplained missing trades 0,
      unexplained extra trades 0, raw balance delta mismatches 0.
- [ ] On a random sample of at least 200 accounts: event agreement ≥ 99.5% and notional value
      agreement ≥ 99.5%.
- [ ] The random sample is drawn from the frozen universe by a recorded seed, not hand-picked.
- [ ] Every remaining difference is assigned to a documented category — venue without decoder, unusual
      token behaviour, incomplete trace, fee-on-transfer, rebase, contract not covered — and the
      category counts are reported.
- [ ] Unexplained differences are prohibited from being dropped; the run fails while any remain
      unexplained.
- [ ] The notional share of uncovered trades is reported **per window**, not once in aggregate.
- [ ] The reconciliation uses no second vendor anywhere, and the code path is structurally unable to
      import vendor-normalised data as a reference.
- [ ] The decoder coverage gap measured in the first data pull is re-measured here and any drift is
      reported, since decoders break without warning.
