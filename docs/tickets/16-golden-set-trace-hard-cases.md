# 16 — Golden set: hand-traced expected outputs, hard cases

**What to build:** The second tranche, covering the cases that actually break pipelines. Fee-on-
transfer tokens, dead pools, thin liquidity, circular arbitrage, Safe accounts, ERC-4337 accounts, and
tokens with multiple pools and liquidity migration. Same discipline as the core tranche: answers
derived from raw chain data before the pipeline exists, reasoning recorded before comparison. These
accounts are where the golden set earns its cost, and they are the accounts the external specialist
will review.

**Blocked by:** 11, 14, 15

**Status:** ready-for-agent

- [ ] Hard-case accounts are traced end to end: fee-on-transfer tokens, dead pools, thin liquidity,
      circular arbitrage, Safe, ERC-4337, and tokens with multiple pools plus liquidity migration.
- [ ] For Safe accounts, the expected `portfolio_owner` is the Safe address and signers are expressly
      not recorded as separate traders.
- [ ] For ERC-4337 accounts, the expected `portfolio_owner` is the smart account sender and the
      bundler, paymaster, and relayer are expressly not recorded as the trader.
- [ ] Circular arbitrage cases record the expected outcome as **excluded** with no position emitted,
      not as a zero-value position.
- [ ] Dead-pool cases record the expected mark as **zero**, together with the evidence for all three
      conjunction conditions: no successful swap for 30 days, executable exit value below threshold,
      and no validated replacement pool.
- [ ] Thin-but-live pool cases record both the naive spot mark and the liquidity-bounded mark, so the
      pipeline is tested on taking the minimum rather than on producing a number.
- [ ] Migration cases record the expected `token_trading_start_block` as unchanged by migration, so a
      first-block purchase cannot be laundered into a mature-token purchase.
- [ ] Fee-on-transfer cases record expected raw quantities received, not quantities sent.
- [ ] Every expected answer records its reasoning before any comparison, and no pipeline output was
      consulted.
