# 38 — Validation gate summary and the transition to VALIDATION_PASSED

**What to build:** The single place where all four validation layers resolve into one authorisation.
Ten conditions, all of which must hold; failure of any one leaves the null distribution and the main
test unauthorised. This is the ticket that makes "the pipeline proves itself correct before it computes
anything that matters" a machine-enforced fact — and it matters because the null distribution cannot
detect implementation bugs. A wrong FIFO rule corrupts the selected basket and all 1,000 random
baskets identically and shows up as nothing at all.

**Blocked by:** 34, 35, 36, 37

**Status:** ready-for-agent

- [ ] The summary evaluates all ten conditions and requires every one: golden-set buy/sell precision
      100%; recall 100%; known-answer tests 100%; raw quantity mismatches 0; FIFO assignment
      mismatches 0; per-event USD error ≤ 0.5%; wallet buy quality difference ≤ 0.5 pp; random
      reconciliation event agreement ≥ 99.5%; unexplained golden-set differences 0; independent review
      completed.
- [ ] Failure of any condition produces `Validation Gate: FAILED`, `Null Distribution: NOT
      AUTHORIZED`, `Main Test: NOT AUTHORIZED`, and the governance module refuses the corresponding
      transitions.
- [ ] The prescribed layer order is verifiable from the audit log: golden set, then known-answer
      tests, then reconciliation, then independent validation — a summary produced from out-of-order
      layers is rejected.
- [ ] The failure policy is enforced as written: golden-set discrepancy is a hard failure,
      known-answer failure is a hard failure, unsupported population events are quarantined and
      counted, unexplained dropped events are prohibited.
- [ ] On full pass, the governance state advances to `VALIDATION_PASSED` with an audit record naming
      the requester.
- [ ] The validation report is machine-readable and is pinned by the freeze manifest.
- [ ] No stage after this point can execute without `VALIDATION_PASSED`, proven by a rejection test.
