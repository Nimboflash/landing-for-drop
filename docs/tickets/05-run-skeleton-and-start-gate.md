# 05 — Run skeleton, precondition register, and the start gate

**What to build:** The prefactoring ticket, and the first thing that actually executes. A single
command reports Phase 0's status by reading the precondition register, and refuses to run any pipeline
stage while the status is `DESIGNED, NOT READY FOR EXECUTION`. The same skeleton establishes the
objects every later ticket depends on: a run record carrying commit, configuration, dataset snapshot
identifier and seed; a master seed with deterministic child seeds; and an append-only audit log of who
or what requested each action. Nothing computes a metric in this ticket — the demo is that a stage
request is refused with a legible reason, and then accepted once the register is complete.

**Blocked by:** 01, 02, 03, 04

**Status:** ready-for-agent

- [ ] A status command prints the four preconditions and the derived Phase 0 status, and prints
      `DESIGNED, NOT READY FOR EXECUTION` when any one of them is unmet.
- [ ] A request to run any pipeline stage is refused while the status is not ready, with the specific
      unmet precondition named in the refusal.
- [ ] With all four preconditions satisfied, the same request is accepted and opens a run record.
- [ ] Every run record carries source commit, configuration hash, dataset snapshot identifier, master
      seed, and the child seed derivation rule, and is written before the stage executes rather than
      after.
- [ ] Child seeds are derived deterministically from the master seed such that the same master seed
      and commit reproduce the same child seeds exactly.
- [ ] Every state-changing request records its requester — human or agent — in an append-only audit
      log that the skeleton cannot rewrite.
- [ ] An operations `HALT` capability exists that stops execution and holds state, and it is
      demonstrably unable to change any recorded value.
- [ ] The skeleton has no capability to mutate a result, only to start, refuse, halt, and record.
