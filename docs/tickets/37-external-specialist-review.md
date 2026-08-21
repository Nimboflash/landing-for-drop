# 37 — External specialist review of 10–15 complex accounts

**What to build:** The bounded cost that converts validation status from `MACHINE-INDEPENDENT` to
`EXTERNALLY REVIEWED`. An external human specialist independently reviews the 10–15 most complex
golden accounts — the ones flagged during golden-set selection — working from raw chain data, and
their findings are resolved rather than noted. This is small and it is the only defence against two
same-model agents making the same wrong assumption about an ambiguous rule or a token standard.

**Blocked by:** 36 (accounts flagged in 14)

**Status:** ready-for-agent

- [ ] An external human specialist, not the builder and not the validator agent, is engaged and
      recorded.
- [ ] Between 10 and 15 complex accounts are reviewed, drawn from the accounts flagged as most complex
      during golden-set selection and covering at minimum: fee-on-transfer, dead pool, pool migration,
      Safe, ERC-4337, and a solver-settled or aggregator-routed trade.
- [ ] The specialist works from raw chain data and the frozen specification, and does not review the
      builder's or the validator's code.
- [ ] Every finding is resolved — the golden answer is corrected, or the pipeline is corrected, or the
      finding is recorded as a documented non-issue with reasoning. Nothing is left open.
- [ ] If a golden answer changes, the golden set gets a new version and every dependent comparison is
      re-run against it.
- [ ] On completion with no unresolved findings, validation status advances to `EXTERNALLY REVIEWED`
      and the change is recorded.
- [ ] If external review proves impossible, the status is recorded as `MACHINE-INDEPENDENT` with the
      correlated-error limitation stated, or `NOT INDEPENDENT` if the substitute controls also fail —
      and in the latter case the main test is blocked.
