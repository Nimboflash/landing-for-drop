# 19 — TRACER BULLET: one wallet, one window, one buy, hand-checked

**What to build:** The first end-to-end run of the pipeline, and the narrowest complete path through
it. One golden-set account, one window, one simple buy-then-full-sell position, taken from raw source
data all the way to a wallet-level `buy_quality_30d` — and that number equals the hand-computed answer
already frozen in the golden set. No marking, no matching, no copyability, no ranking. Every later
pipeline ticket widens this path rather than adding a layer beside it. The demo is one green account
in an otherwise entirely red golden report.

**Blocked by:** 17, 18

**Status:** ready-for-agent

- [ ] A single command runs the whole path for one named golden account in one window and prints a
      wallet-level `buy_quality_30d`.
- [ ] The run refuses to start unless the governance module authorises it, and it opens a run record
      carrying commit, configuration hash, dataset snapshot identifier, and seed before executing.
- [ ] Transaction success is filtered **first**, before any other step, and the run reports how many
      transactions it dropped for failure.
- [ ] The buy is produced by transaction-level netting grouped by `(transaction, portfolio_owner,
      token)` and summed — not read from a per-hop row and not read from an aggregator table.
- [ ] `tx_sender` and `portfolio_owner` are both present on the emitted record as separate fields, and
      neither overwrites the other.
- [ ] The realized return is computed in the quote asset actually used, with no price lookup for the
      traded token: `Realized Return = Sale Proceeds / Allocated Buy Cost − 1`.
- [ ] Wallet aggregation applies `w_i = log(1 + trade_value_usd_i)` even with a single trade, so the
      formula is exercised rather than short-circuited.
- [ ] The golden harness reports this account green — deterministic fields exact at raw-unit level,
      per-event USD within 0.5%, buy quality within 0.5 pp — and every other golden account still red.
- [ ] The run is recorded as validation, not as forward measurement of the experiment; no
      selected-wallet forward number is produced and no ranking is computed.
- [ ] Re-running with the same commit, snapshot, and seed produces a byte-identical result.
