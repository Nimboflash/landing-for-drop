# 44 — Arbitrum secondary diagnostic (optional, outside the gate)

**What to build:** An optional generalisability check on Arbitrum, run only after the Ethereum
decision is emitted, and structurally unable to affect it. It was pre-registered as secondary at
freeze time precisely so it cannot be introduced after Ethereum fails. It does not participate in the
main gate, may not rescue a weak Ethereum result, and cannot trigger a threshold change.

**Blocked by:** 43 (pre-registered as secondary in 11)

**Status:** ready-for-agent

- [ ] The run proceeds only if it was pre-registered as a secondary diagnostic at parameter freeze;
      otherwise the governance module refuses it.
- [ ] The same frozen commit and the same shared functions are used, with Arbitrum as the only changed
      input.
- [ ] Results are labelled `SECONDARY DIAGNOSTIC — OUTSIDE THE GATE` on every output.
- [ ] The result cannot be written into the Ethereum decision record, and cannot change any threshold,
      proven by rejection tests.
- [ ] Every number carries its scope, and the report states that Arbitrum's measured capacity and
      trade-size composition differ materially from Ethereum's.
- [ ] The run is abandoned rather than degraded if the Arbitrum data cannot meet the same validation
      standard; a weaker validation bar is not available.
- [ ] The report states that a favourable Arbitrum result is not evidence about Ethereum, and an
      unfavourable one is not evidence against it.
