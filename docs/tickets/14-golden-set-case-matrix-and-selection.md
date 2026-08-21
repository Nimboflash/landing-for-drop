# 14 — Golden set: case matrix and account selection

**What to build:** Choose the 30–50 accounts the entire validation gate will be judged on, and prove
that between them they cover every hard case deliberately rather than by sampling. Coverage here is
the whole point: a golden set of easy accounts proves nothing, and the cases in the list exist because
each one produced a wrong answer in a real system. This ticket ends with named accounts, the raw-chain
evidence bundle for each, and a coverage matrix showing which account covers which case — with no
empty cells.

**Blocked by:** 12, 13 (and 02 — the validator leads this)

**Status:** ready-for-agent

- [ ] Between 30 and 50 accounts are selected, 50 preferred, each identified by address and by the
      window and block range that will be traced.
- [ ] A coverage matrix maps accounts to cases and has at least one account per case: full buy and
      sell; multiple partial sells; multi-hop routes; multi-pool trades; fee-on-transfer tokens; dead
      pools; first-hour purchases; thin liquidity; failed transactions; circular arbitrage; Safe;
      ERC-4337; transfers alongside swaps; tokens with multiple pools and liquidity migration.
- [ ] No cell in the coverage matrix is empty, and the matrix is the acceptance artefact — not a
      narrative claim that coverage is good.
- [ ] For each account, a raw-chain evidence bundle is captured through the ground-truth reader and
      stored, so the trace work in the next tickets does not depend on live vendor calls.
- [ ] Account selection is made without consulting any pipeline output, and the audit log shows the
      selection predates the first pipeline run.
- [ ] The 10–15 most complex accounts are flagged now as the candidates for external specialist
      review, so that review can be booked rather than improvised.
- [ ] Accounts are chosen to include at least one case where `tx_sender` and `portfolio_owner` provably
      differ, and at least one solver-settled or aggregator-routed trade.
