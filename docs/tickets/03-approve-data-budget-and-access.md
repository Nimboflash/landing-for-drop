# 03 — Approve the data budget and provision vendor access

**What to build:** The third start precondition. This ticket ends with an approved budget and working
credentials for every data source Phase 0 depends on, proven by a live call against each one, and with
the total projected cost recorded against the under-$1,000 ceiling. It also ends with the archival RPC
path proven, because that is the ground truth for validation and it is the one source with no invoice
attached and therefore the one most likely to be assumed rather than provisioned.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Budget approval is recorded with the projected total for the whole of Phase 0 and the ceiling it
      is measured against.
- [ ] A live call succeeds against the historical DEX trade warehouse and returns rows for a named
      Ethereum block range inside window 1.
- [ ] A live call succeeds against the pool-level on-chain OHLCV source with the inactive-source flag
      enabled, and returns candles for a pool that is known to be dead — this is the capability the
      whole dead-pool marking rule depends on, so it is proven now, not assumed.
- [ ] A live call succeeds against the free public exchange minute-kline source for one quote asset on
      one historical day.
- [ ] An Ethereum archival RPC is reachable and returns a receipt, event logs, an execution trace, and
      a raw balance delta for a single named historical transaction.
- [ ] Coin-level aggregator price endpoints are recorded as a **prohibited** source anywhere in the
      pipeline, so that provisioning them later requires an explicit override rather than a
      convenience call.
- [ ] Vendor terms relevant to the freeze are recorded: query rate limits, historical depth, and any
      contribution or coverage constraint that means a gap discovered later cannot be closed on a
      useful timescale.
- [ ] The register entry is machine-readable and exposes `data_budget: APPROVED | PENDING` together
      with per-source reachability.
