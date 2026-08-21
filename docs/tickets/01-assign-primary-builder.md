# 01 — Assign and record the Primary Builder

**What to build:** Phase 0 has a status of `DESIGNED, NOT READY FOR EXECUTION` and one of the four
reasons is that nobody is assigned to build it. This ticket ends with a named Primary Builder recorded
in a machine-readable precondition register, with their capability assessed against the required skill
profile and any gap written down as a named risk. The register is the thing later tickets read; a
verbal "yes, I'll do it" does not satisfy this ticket. The most likely recorded cause of death for
this project is "two people were not found" — this ticket is half of that.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A named Primary Builder is recorded with a start date and a commitment level, and the commitment
      is full-time for the whole 10–12 week window.
- [ ] The record states, per skill, whether the assignee has it: advanced warehouse SQL over spellbook
      models; Python for processing, simulation and statistical testing; EVM internals including event
      logs, traces and balance deltas; DEX pools and concentrated liquidity; FIFO position accounting;
      backtest design without look-ahead bias; bootstrap and null-distribution testing; reproducible
      versioned pipelines.
- [ ] Every gap in that list is recorded as a named risk with a named mitigation. Gaps are not left
      implicit and are not resolved by assertion.
- [ ] If the assignee is an AI agent, the record says so explicitly and names the human who is
      accountable for its output, because this affects the validation-independence status later.
- [ ] The register entry is machine-readable and exposes `primary_builder: ASSIGNED | UNASSIGNED`.
- [ ] Overall Phase 0 status still reads `DESIGNED, NOT READY FOR EXECUTION` while any of the other
      three preconditions is unmet — assigning a builder alone does not start the project.
- [ ] No downstream ticket is started on the strength of a provisional, part-time, or shared
      assignment.
