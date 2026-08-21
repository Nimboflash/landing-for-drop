# 12 — First data pull: one window in the warehouse, coverage gap measured

**What to build:** The first vertical slice through the data layer. Pull Ethereum spot DEX activity
for one training window into the warehouse, and produce three things that later tickets depend on: a
reproducible dataset snapshot identifier, a measured decoder coverage gap, and a working quote-asset
USD reference. The coverage gap is not a footnote — roughly 8.2% of tracked Ethereum DEX volume has no
decoder at all, meaning those trades are invisible rather than mislabelled, and that number must be
reported alongside every result the project ever produces.

**Blocked by:** 05 (and 03 for access)

**Status:** ready-for-agent

- [ ] One training window of Ethereum spot DEX activity is pulled and stored under a dataset snapshot
      identifier that a later run can pin exactly.
- [ ] The decoder coverage gap for the window is **measured**, not quoted: tracked DEX volume with no
      matching decoder, expressed as a percentage, with the comparison source named.
- [ ] The coverage gap is emitted as a standing metric attached to the snapshot, and a
      `decoder_coverage_version` is recorded so any row produced later can be traced to the protocol
      coverage list in force at the time.
- [ ] Quote-asset USD reference prices are loaded from the free public exchange minute klines for
      `USDC, USDT, WETH, ETH, WBTC` across the window, and a spot check against a known historical
      price passes.
- [ ] Pool-level on-chain OHLCV is retrieved with inactive sources included for at least one pool that
      has been dead for over 30 days, proving the dead-pool marking path has data.
- [ ] The NULL rate of the warehouse's USD notional field is measured and recorded, since it is
      unpublished and the pipeline may not rely on it unmeasured.
- [ ] Any use of a coin-level aggregator price endpoint fails loudly rather than falling back.
- [ ] Re-running the pull against the same snapshot identifier returns identical row counts and
      checksums.
