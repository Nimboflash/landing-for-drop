# 25 — Candidate universe for one window: two-stage buffer and infrastructure exclusion

**What to build:** Widen from one wallet to one window's worth of accounts. The warehouse filter
admits accounts on **potential** buys, the netted pipeline then decides eligibility on **valid** buys,
and infrastructure is excluded by an explicit test rather than by a name list. The two-stage buffer is
load-bearing: filtering at the final threshold in the first pass silently drops wallets that netting
would have moved across the boundary. The demo is a single window's eligible account list with every
exclusion attributable to a stated rule.

**Blocked by:** 24

**Status:** ready-for-agent

- [ ] The warehouse filter admits accounts with 10–1,200 **potential** buys, and final eligibility is
      20–1,000 **valid** buys after netting, with the count of accounts that moved across the boundary
      reported.
- [ ] The upper bound is applied to valid buys, not total transactions, so approvals, transfers, and
      administrative operations cannot inflate an account out of eligibility.
- [ ] Infrastructure is excluded by the stated test — the account must represent one decision-maker or
      one portfolio, not infrastructure passing through other people's transactions — covering DEX
      routers, aggregator contracts, relayers, bundlers, bridges, protocol treasuries, public vaults,
      liquidity pools, market-making contracts, CEX hot wallets, deployers trading their own token,
      and any contract whose economic controller cannot be identified.
- [ ] Safes, ERC-4337 accounts, and contract accounts that clearly control a single user portfolio are
      **retained**, and the published day-of-week-skewness "human" filter is modified so it does not
      silently exclude all of them.
- [ ] Published bot heuristics and labelled MEV, sandwich, and arbitrage sets are reused where they
      exist, and every modification made to them is recorded with its reason.
- [ ] Every excluded account is attributable to a named rule; there is no unattributed exclusion
      bucket.
- [ ] Full transaction histories are extracted only for candidate wallets, not for the whole chain —
      the filter-early, enrich-late shape holds and the data cost is reported.
- [ ] Account typing on this window is spot-checked against the golden set's account-type expectations
      and agrees.
