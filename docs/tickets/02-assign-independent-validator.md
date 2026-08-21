# 02 — Assign and record the Independent Validator

**What to build:** The second of the four start preconditions. This ticket ends with a named
Independent Validator recorded in the same precondition register, joining in week 1 rather than at the
end, and with the independence constraint written down as a binding condition: the validator must not
write the pipeline's transaction classification, FIFO, or valuation logic, must work from raw chain
data and the specification only, and must produce expected outputs before seeing the builder's
results. Bringing a validator in at the end to sign a report is not independent validation and this
ticket must make that structurally impossible rather than discouraged.

**Blocked by:** None — can start immediately.

**Status:** register built; **no validator is assigned**. Naming one is the project owner's act and
nothing in `src/phase0/validator.py` fabricates, defaults, or infers a name. `phase0 status` reads
`independent_validator: UNASSIGNED`, `validation status today: NOT INDEPENDENT`.

> **Direction settled 2026-08-16: an AI validator, capped at `MACHINE-INDEPENDENT`.** The record
> still needs a name and a named accountable human, so this ticket is not closed — but the *shape*
> is decided, and two things follow immediately.
>
> **The external specialist review is now load-bearing rather than a formality.** With a human
> validator it narrows a shared prior; with an AI one it is the only thing that narrows it at all.
> `EXTERNAL_REVIEW_BUDGET.quoted_usd` is `None` — nobody has obtained a quote, which is a different
> claim from `$0` — and a quote is being sought. Until it is booked the status caps regardless of
> who is named, and `is_optional` is a property that is always `False` rather than a field, so there
> is no state in which this gets skipped.
>
> **It cost ticket 13 its implementation.** `src/groundtruth/` was built the same day and removed
> when this landed: a reference the validator did not write is the correlated-error problem at its
> sharpest. See `docs/tickets/13-raw-chain-ground-truth-reader.md`.

- [x] A named Independent Validator is recorded with a start date in week 1 and a part-time commitment
      covering the golden-set build, reconciliation, and sign-off.
      — `ValidatorAssignment` (`src/phase0/validator.py`). `start_date` is checked against
      `project_start` and `WEEK_ONE_DAYS = 7`, so "joined in week 1" is a fact the record carries
      rather than a claim in a document; a later date is refused. `covers` must be all of
      `REQUIRED_SCOPE = (golden_set, reconciliation, sign_off)`, and a sign-off-only commitment is
      refused by name. `COMMITMENT_LEVELS` has no value meaning "available when we need them".
- [x] The record binds the validator to: a separate implementation path; no reuse of the builder's
      classification, FIFO, or valuation functions; expected outputs derived from raw chain data and
      the specification only, never from the builder's code or intermediate artefacts; and reasoning
      recorded before any comparison.
      — `INDEPENDENCE_CONSTRAINTS`, four records carrying the requirement, why it exists, and
      **what actually enforces it**. Not a constructor parameter: there is no argument by which a
      caller could supply three, so an assignment not bound to all four is not a state this package
      can represent. `ValidatorAssignment.ordering_refusal(sealed_at, compared_at)` is the
      reasoning-before-comparison constraint in a form ticket 36 can check — equal timestamps and
      missing ones are refused as well as inverted ones.
- [x] The record names which validation status the assignment can reach today —
      `MACHINE-INDEPENDENT`, `EXTERNALLY REVIEWED`, or `NOT INDEPENDENT` — and states that
      `NOT INDEPENDENT` blocks the main test.
      — `validation_status()` derives it; no constructor, method or serialised field accepts one, and
      a tampered `validation_status` key in the stored JSON is recomputed rather than trusted.
      `NOT INDEPENDENT` blocks the main test **through the governed stage list**:
      `VALIDATION_GATED_STAGES` in `src/phase0/execution.py` refuses `validation.independent` and the
      five execution-lane stages, and since `validation.independent` is the only stage that reaches
      `VALIDATION_PASSED`, the block propagates by governance's own ordering. The build lane is not
      refused — the validator's golden-set work is a build-lane stage.
- [x] If the validator is an AI agent, the record states that two agents from the same base model make
      correlated errors, and that the status is therefore `MACHINE-INDEPENDENT` at best until the
      external specialist review is booked.
      — `CORRELATED_ERROR_NOTE`, carried on every AI assignment and printed by `phase0 status`.
      Booking the review does not delete it: the note gains `EXTERNAL_REVIEW_RESIDUE`, which says the
      review covers the flagged complex accounts and not the whole run, so the shared prior is
      narrowed rather than removed.
- [x] The budget line for the external specialist review of 10–15 complex accounts is recorded here as
      a cost to pay, not an option to consider.
      — `EXTERNAL_REVIEW_BUDGET`. It has no `declined`, `waived` or `optional` field — `is_optional`
      is a property that is always `False`, because a field could be set — so its only states are
      *booked* and *not yet booked*, and "not yet booked" caps the status rather than excusing it.
      `quoted_usd` is `None`, meaning **nobody has obtained a quote**; that is a different claim from
      `$0`, which would say someone checked and it is free.
- [x] The register entry is machine-readable and exposes
      `independent_validator: ASSIGNED | UNASSIGNED` plus the validation status it can currently
      support.
      — `PreconditionRegister.independent_validator_state()` and `.validation_status()`, stored in the
      same JSON file and the same hash-chained audit log as the other three preconditions.
      `ValidatorAssignment.as_dict()` carries both, the four constraints, the budget line and the
      correlated-error note.

## What is structurally impossible, and what is not

The ticket says bringing a validator in at the end to sign a report "must be structurally impossible
rather than discouraged". The full ledger is in the module docstring of `src/phase0/validator.py`.
The short form:

**Impossible.** An assignment without the four constraints; a start date outside week 1; a
sign-off-only commitment; a status reached by assertion; an AI validator reading as full
independence; a placeholder name; an AI validator with no named accountable human; a review booked
by the validator, the human accountable for it, or the recorded Primary Builder; a bare attribution
overwriting a ticket-02 record.

**Not achieved.** Reasoning-before-comparison is *checkable*, not enforced — nothing in `phase0`
observes when a validator read the builder's output, and the copy channel is outside the process.
"No reuse of the builder's functions" is enforced by `tests/test_lane_independence.py`, a static
check over committed code; the record names it rather than replacing it. Whether the external
specialist is human, external, or reviewed anything is not knowable from here. And a bare
attribution recorded through the generic `record()` still satisfies §15.4's start gate: it reads
`UNASSIGNED` / `NOT INDEPENDENT` in the report, and it does **not** refuse a stage — a check that
refused on an empty register would refuse every stage in every rehearsal of this machine.
