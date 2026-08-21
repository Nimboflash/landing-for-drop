# 15 — Golden set: hand-traced expected outputs, core cases

**What to build:** The first tranche of hand-computed answers. For every selected account covering the
core cases, a human or the Independent Validator working from raw chain data only records the expected
output: every buy and sell event, exact raw quantities, FIFO lot assignment, realized or open status,
and the resulting buy quality. These answers are computed **before the pipeline is written**, from
transactions, event logs, traces, and actual balance changes — never from the builder's code or
intermediate artefacts. Answers depend on the frozen definitions, which is why this ticket sits after
the parameter freeze.

**Blocked by:** 11, 14

**Status:** ready-for-agent

- [ ] Core-case accounts are traced end to end: full buy and sell, multiple partial sells, multi-hop
      routes, multi-pool trades, first-hour purchases, failed transactions, and transfers alongside
      swaps.
- [ ] Each expected event records transaction hash, block number, wallet, token, pool, direction, raw
      token quantity, raw quote quantity, FIFO lot assignment, and realized or open status.
- [ ] Realized returns are computed in the quote asset actually used, with no price lookup for the
      traded token, following `Realized Return = Sale Proceeds / Allocated Buy Cost − 1`.
- [ ] Failed transactions appear in the trace as explicitly expected exclusions, so the pipeline is
      tested on recall of exclusions and not only of inclusions.
- [ ] Every expected answer records the reasoning that produced it, written down before any comparison
      to a pipeline output exists.
- [ ] The tracer confirms in writing that no pipeline output was consulted, and the audit log supports
      the claim by timestamp.
- [ ] Wallet-level expected `buy_quality_30d` is computed by hand for each traced account using
      `w_i = log(1 + trade_value_usd_i)` weights.
