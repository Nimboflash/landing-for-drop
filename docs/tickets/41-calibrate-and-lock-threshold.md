# 41 — Calibrate and lock the final mean threshold

**What to build:** Set the bar from the measured null rather than from intuition, and then close it.
The final mean threshold is the smallest value at which the null pass rate is at or below 5%. 15pp is
the starting value, not a sacred number: if calibration shows it is loose, it is raised — even though
that makes the project harder to pass. Once locked, the threshold cannot move, and the main test
becomes a single run against a bar that was set before any real result existed.

**Blocked by:** 40

**Status:** ready-for-agent

- [ ] `Null Pass Rate = null runs passing the full gate / total null runs` is computed across the
      threshold sweep.
- [ ] `Final Mean Threshold = the smallest threshold at which Null Pass Rate ≤ 5%` and the sweep that
      produced it is reported in full, not only the chosen value.
- [ ] If the calibrated threshold exceeds 15pp, it is raised without discussion or exception, and the
      raise is recorded.
- [ ] The 95th percentile and the empirical p-value machinery are derived from each column's own null
      distribution, leader against leader and follower against follower.
- [ ] The threshold is written into the frozen parameter set and the governance state advances to
      `THRESHOLD_LOCKED`.
- [ ] After locking, any attempt to change the threshold is rejected with an audit record, including
      attempts framed as corrections or clarifications.
- [ ] The calibration is reproducible from the master seed and the frozen commit.
- [ ] The main test remains unauthorised until this transition completes, proven by a rejection test.
