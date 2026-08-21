# 06 — Governance state machine: ordering enforcement and post-freeze write rejection

**What to build:** The governance module is listed last in the module map but is upstream of every
other module at runtime: no stage may execute that governance has not authorised. This ticket makes
the experiment's ordering a property of the system rather than of people's memory. The demo is a
sequence of refusals — an attempt to run the null before validation passes is rejected, an attempt to
change a threshold after the parameter freeze is rejected, an attempt to run the main test before the
threshold is locked is rejected — each with an audit record naming the requester.

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] The state machine implements exactly this order and rejects any transition that arrives out of
      it:

      PARAMETERS_OPEN → PARAMETERS_FROZEN → VALIDATION_PASSED → CODE_AND_DATA_FROZEN
      → NULL_COMPLETE → THRESHOLD_LOCKED → MAIN_TEST_EXECUTED → DECISION_EMITTED

- [ ] Every write to the parameter set is rejected once the state is `PARAMETERS_FROZEN`, including
      writes that only widen or clarify a definition.
- [ ] `NULL_COMPLETE` is unreachable without `VALIDATION_PASSED`, and `MAIN_TEST_EXECUTED` is
      unreachable without `THRESHOLD_LOCKED`. Both are proven by a rejection test, not by inspection.
- [ ] A rejection test exists for every out-of-order transition in the matrix, and all of them pass.
- [ ] Every transition records its requester, timestamp, and the run record it belongs to.
- [ ] A request from a person or an AI agent to reinterpret a failed gate as a successful result is
      rejected by the same mechanism as any other unauthorised write, with no override path.
- [ ] The operations `HALT` capability can stop a stage in any state and cannot advance, revert, or
      mutate a state or a result.
- [ ] An `INVALIDATED` run status exists and, once set, prevents any further transition until a new
      code version is registered — the full invalidation drill is exercised later, but the state
      exists now.
