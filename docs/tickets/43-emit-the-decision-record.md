# 43 — Emit the decision record

**What to build:** One machine-readable outcome, bound to the freeze manifest hash, that no person and
no AI agent may reinterpret. `GO`, `CONDITIONAL REVIEW`, or `STOP`. The record carries the fixed
wording for a negative result, the scope of every claim, and an explicit statement of what Phase 0 did
**not** test — so that continuing the project is not a matter of interpretation or seniority, and a
pass is not read as more than it is.

**Blocked by:** 42

**Status:** ready-for-agent

- [ ] The decision is emitted as a signed machine-readable object with exactly one of `GO`,
      `CONDITIONAL REVIEW`, `STOP`, bound to the freeze manifest hash so it cannot be quoted detached
      from the experiment that produced it.
- [ ] A `CONDITIONAL REVIEW` outcome carries the required explicit decision before Phase 1: reduce
      design capital, restrict the token universe, restrict wallets by copy capacity, reduce base
      position size, or stop.
- [ ] A negative result uses the pre-registered wording verbatim: "No sufficient persistent and
      copyable wallet-selection edge was found for the Ethereum Mainnet target population and capital
      profile." The alternative framing "wallet-based copy trading does not work on any blockchain" is
      explicitly not available.
- [ ] The record states what Phase 0 did not test: Berk–Green capital-degradation effects;
      generalisation to Base, Arbitrum, Solana or memecoin markets; and whether the full twelve-engine
      product would be profitable.
- [ ] The record states the accepted limitations: entity clustering out of scope so address ≠ agent;
      the Edge Origin condition as a partial rather than complete defence against adversarial
      targeting; and the decoder coverage gap as a standing caveat.
- [ ] The record states that a `GO` means the edge existed historically and would have survived
      transfer to **one** follower at design capital — not that the edge will survive the product
      existing.
- [ ] Any request to reinterpret a failed gate as a successful result is rejected by the governance
      module with no override path.
- [ ] The governance state advances to `DECISION_EMITTED` and the run is closed.
