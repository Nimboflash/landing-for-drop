# 42 — Run the main test, once

**What to build:** The experiment. The selected baskets meet their forward windows for the first time,
both gates are evaluated per window against the locked threshold and each column's own null, and the
full required output set is produced. This is the only ticket in the programme that produces a forward
number for a selected basket, and it runs exactly once. After observing the result, nothing changes —
that is not a guideline here, it is enforced by the state machine.

**Blocked by:** 41

**Status:** ready-for-agent

- [ ] The run is authorised only from `THRESHOLD_LOCKED`, executes from the frozen commit and dataset
      snapshot, and is recorded as `MAIN_TEST_EXECUTED` on completion.
- [ ] A second main-test execution is refused, with an audit record, regardless of requester.
- [ ] Per window, Gate 1 is evaluated on all three conditions and Gate 2 on both $1.5M and $2M, each
      against the 95th percentile of its own null with empirical p ≤ 0.05.
- [ ] The project-level result is computed as Gate 1 AND Gate 2 AND significance in at least 3 of 4
      windows.
- [ ] The full required output set is produced: realized / marked / dead shares per wallet and per
      basket; churn in three states; per-capital-level raw buy quality, follower-adjusted buy quality,
      mean and median Copy Retention, positive trade rate, valuation-basis shares, and unexecutable
      trade share.
- [ ] The diagnostics pack is produced alongside and is visibly unable to have influenced any gate.
- [ ] The standing data-integrity metrics accompany the result: decoder coverage gap, unexplained
      reconciliation difference, realized versus marked share, attribution fallback rate.
- [ ] Every number carries its scope — chain, window, capital level, liquidity band, population.
- [ ] If a real bug is discovered at any point during or after this run, the result is marked
      `INVALIDATED` and the whole sequence repeats; the result is not patched.
