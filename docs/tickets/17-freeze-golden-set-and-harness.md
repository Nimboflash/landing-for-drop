# 17 — Freeze the golden set and stand up the comparison harness

**What to build:** The golden set becomes an immutable, versioned object, and a harness exists that
compares any pipeline output against it and reports pass or fail per acceptance rule. Because no
pipeline exists yet, the demo for this ticket is the harness running and reporting **every** golden
account red, with the specific unmet criterion named for each. That red report is the starting line
for every pipeline ticket that follows, and it is what makes "golden set built before the pipeline"
verifiable rather than asserted.

**Blocked by:** 15, 16

**Status:** ready-for-agent

- [ ] The golden set is frozen under a version identifier, and the version is a required field in the
      freeze manifest.
- [ ] Any change to a frozen golden answer requires a new golden-set version; in-place edits are
      rejected.
- [ ] The harness evaluates and reports, per account and in aggregate: buy/sell precision, buy/sell
      recall, deterministic-field exact match at raw-unit level, per-event USD relative error, wallet
      realized value relative error, and absolute buy quality difference.
- [ ] Acceptance is encoded, not described: precision 100%, recall 100%, deterministic fields exact
      with no percentage tolerance, per-event USD error ≤ 0.5%, wallet realized value error ≤ 0.5%,
      buy quality absolute difference ≤ 0.5 pp.
- [ ] A single unresolved false positive or false negative fails the whole gate, and the harness
      demonstrates that with a constructed example.
- [ ] The harness has no mode that averages discrepancies away, aggregates small differences into a
      tolerance, or waives an account.
- [ ] Run against an empty pipeline, the harness reports every account red with a named unmet
      criterion, and exits with a failure status.
- [ ] The blind-review protocol is recorded: system output is not shown to the tracer until manual
      computation is complete, and the harness enforces that ordering for the run in which a golden
      answer is first compared.
