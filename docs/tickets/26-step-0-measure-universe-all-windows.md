# 26 — Step 0: measure the eligible universe in all four windows

**What to build:** The mandatory measurement that must complete before any ranking, before the null
distribution, and before any forward measurement. The funnel numbers in the original specification are
illustrative; this ticket replaces them with measured ones, per window, together with the
distributions that later matching depends on. It also contains a stopping condition with teeth: a
window whose eligible universe is under 10,000 accounts is not valid, and the four-window design must
be revised **before** the main test rather than after seeing data.

**Blocked by:** 25

**Status:** ready-for-agent

- [ ] For each of the four windows — train Jan–Jun 2023, Jul–Dec 2023, Jan–Jun 2024, Jul–Dec 2024 —
      the following are measured and recorded: total active accounts; accounts with at least one valid
      buy; accounts with 20–1,000 valid buys; eligible EOAs; eligible Safes; eligible ERC-4337
      accounts; excluded infrastructure contracts; final eligible universe size.
- [ ] Distributions are recorded per window for valid buy count, trading volume, active days, wallet
      age, and EOA versus smart-account share.
- [ ] Any window whose eligible universe is below 10,000 accounts is marked
      `INSUFFICIENT CANDIDATE UNIVERSE`, and the governance module refuses to advance to ranking until
      the four-window design is explicitly revised.
- [ ] A replacement window may not be selected after seeing data unless the replacement rule was
      pre-registered; the system refuses an unregistered replacement.
- [ ] Step 0 completion is recorded as a governance precondition for ranking, so ranking cannot run
      first by accident.
- [ ] Counts are reproducible from the frozen dataset snapshot: a re-run returns identical numbers.
- [ ] The measured universe sizes are compared against the base-rate expectation that the target
      wallet population may simply not exist at the size assumed, and that comparison is reported
      rather than left implicit.
- [ ] No wallet ranking, no scoring of candidates against each other, and no forward-window number is
      produced in this ticket.
