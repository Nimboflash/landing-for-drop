"""What a synthetic run may not do to the Phase 0 state machine, and where that refusal belongs.

The rule
--------

A synthetic run may **execute** stages and **record** their outcomes. It may not leave the
governance machine in a state that claims Phase 0 progressed. Those are different claims and
``phase0`` already separates them: :func:`phase0.execution.execute_stage` calls the runner at step
4 and performs the transition at step 6, and the run record, the audit entry and the stage result
are all written whether or not step 6 happens. So "execute but do not advance" is not a new
capability — it is the existing sequence with one step withheld.

Which states, and why the list is wider than the four
-----------------------------------------------------

Four of the eight states record a **human act about a real experiment**:

    PARAMETERS_FROZEN     a person froze a pre-registration (ticket 11)
    VALIDATION_PASSED     the four-layer validation gate passed against real data
    CODE_AND_DATA_FROZEN  a person froze code and data (ticket 39)
    DECISION_EMITTED      a decision record was emitted about a hypothesis

Advancing any of them on synthetic input is a machine asserting that a person did something, or
that a gate passed on data that does not exist. That is the sharpest case and it is why
:data:`SYNTHETIC_MAY_NOT_ADVANCE` exists.

The other three — ``NULL_COMPLETE``, ``THRESHOLD_LOCKED``, ``MAIN_TEST_EXECUTED`` — record
*computations* rather than human acts, and they are refused too. A permutation null built over
generated wallets is a distribution of nothing; a threshold calibrated against it is a number with
no referent; and ``MAIN_TEST_EXECUTED`` is write-once by design, so a synthetic run that reached it
would have consumed the single main-test execution the whole pre-registration is built around and
:meth:`~phase0.governance.GovernanceMachine.transition` would refuse the real one as *"already in
this state"*. That last one is not a reputational problem, it is a destroyed experiment.

So the rule is the simple one: **a synthetic run advances nothing.** Every state past
``PARAMETERS_OPEN`` is refused, and the four above are named because they are the ones whose
refusal is not merely prudent.

Two enforcement points, and the difference between them
-------------------------------------------------------

:func:`refuse_if_synthetic_would_advance` is a *predicted* refusal: it reads
:data:`phase0.execution.STAGE_AUTHORITY` and refuses before the runner is called, so nothing is
written at all. :func:`execute_synthetic_stage` adds an *observed* one: it reads the governance
state before and after and refuses if it moved, whatever the register said. The second is the one
that survives a change to ``STAGE_AUTHORITY`` — a stage added tomorrow with an ``advances`` this
module has never heard of is caught by the observation and missed by the prediction. Neither
subsumes the other and both are kept: the prediction is what stops a write from happening, and the
observation is what notices when the prediction was wrong.

Why these are now defence in depth rather than the only lock
------------------------------------------------------------

Both live in ``tools/``, and a refusal that only exists in the harness is one anyone can route
around by not using the harness. That was the whole of :data:`GOVERNANCE_GAP`, and ``src/phase0/``
has since closed it: :mod:`phase0.snapshots` owns a table of prefixes by which a dataset snapshot
identifier declares itself not a measurement, ``phase0.execution.execute_stage`` ``HELD``\\ s any
stage that would advance under one, and ``phase0.governance.GovernanceMachine.transition`` raises
on one it is handed. ``SYNTHETIC-`` is one row of that table.

What is kept here is kept because it does something phase0's refusal does not: it refuses *before
the runner*, so a synthetic stage that would advance opens no run record at all. phase0 refuses
after, because by then the runner has produced a value and ``HELD`` is the honest status for it.
:data:`GOVERNANCE_GAP` now records where the real refusal lives, and the narrower residue that
remains — which is not nothing, and which this package is itself an example of.
"""

from phase0.execution import STAGE_AUTHORITY, execute_stage
from phase0.governance import (
    CODE_AND_DATA_FROZEN,
    DECISION_EMITTED,
    MAIN_TEST_EXECUTED,
    NULL_COMPLETE,
    ORDER,
    PARAMETERS_FROZEN,
    PARAMETERS_OPEN,
    THRESHOLD_LOCKED,
    VALIDATION_PASSED,
)

from .provenance import SNAPSHOT_PREFIX, is_synthetic_snapshot

#: Every governance state a synthetic run may not reach: all of them except the initial one.
#:
#: Derived from :data:`phase0.governance.ORDER` rather than listed, so a state added to the machine
#: is refused by default instead of being permitted by omission. That direction is deliberate — the
#: failure this whole module guards is a state advancing that nobody meant to advance, and a
#: hand-written list would silently stop covering the machine the day it grew.
SYNTHETIC_MAY_NOT_ADVANCE = frozenset(ORDER) - {PARAMETERS_OPEN}

#: The four whose refusal is not merely prudent: each records a human act about a real experiment.
#: Named separately so the refusal message can say *which* kind of claim is being refused.
HUMAN_ACT_STATES = (
    PARAMETERS_FROZEN,
    VALIDATION_PASSED,
    CODE_AND_DATA_FROZEN,
    DECISION_EMITTED,
)

#: The three that record a computation rather than a human act. Refused for a different reason,
#: spelled out in the module docstring and quoted in the refusal.
COMPUTED_STATES = (NULL_COMPLETE, THRESHOLD_LOCKED, MAIN_TEST_EXECUTED)

if set(HUMAN_ACT_STATES) | set(COMPUTED_STATES) != SYNTHETIC_MAY_NOT_ADVANCE:
    raise ImportError(
        "the two reasons for refusing a state cover {} of the {} refused states. Every refused "
        "state must have a stated reason, or the refusal message for the uncovered one says "
        "nothing about why.".format(
            len(set(HUMAN_ACT_STATES) | set(COMPUTED_STATES)), len(SYNTHETIC_MAY_NOT_ADVANCE)
        )
    )


class SyntheticRunRefused(Exception):
    """A synthetic run tried to advance, or did advance, the Phase 0 state machine.

    Deliberately not a :class:`phase0.errors.Phase0Error`: ``execute_stage`` catches those and
    converts them into a ``REFUSED`` :class:`~phase0.execution.StageResult`, which is a *recorded
    outcome of a governed run*. This is not that. It is a defect in whatever wired a synthetic
    source to the real state machine, and it must reach the caller as an exception rather than
    become a row in the audit log that a later reader could mistake for governance working.
    """


def _why(state):
    if state in HUMAN_ACT_STATES:
        return (
            "{} records a human act about a real experiment — a person froze a pre-registration, "
            "or a validation gate passed against real data, or a decision was emitted about a "
            "hypothesis. Nothing generated can be evidence that any of those happened.".format(
                state
            )
        )
    return (
        "{} records a computation over the experiment's data. A null distribution built over "
        "generated wallets is a distribution of nothing, a threshold calibrated against it has no "
        "referent, and MAIN_TEST_EXECUTED is write-once — a synthetic run that reached it would "
        "consume the single main-test execution and the real one would then be refused as "
        "'already in this state'.".format(state)
    )


def refuse_if_synthetic_would_advance(stage, dataset_snapshot):
    """Refuse, before anything is written, a synthetic stage that would complete a transition.

    :param stage: a key of :data:`phase0.execution.STAGE_AUTHORITY`. An unknown stage raises
        :class:`ValueError` rather than being waved through — an unregistered stage has no
        ``advances`` to read, and "no rule found" must not read as "no rule applies".
    :param dataset_snapshot: the snapshot identifier the stage would run under.
    :raises SyntheticRunRefused: the snapshot declares itself synthetic and the stage completes a
        transition into :data:`SYNTHETIC_MAY_NOT_ADVANCE`.

    Returns the state the stage would have advanced to when it is permitted to proceed, or ``None``
    for a stage that completes no transition — so a caller can tell "allowed, and moves nothing"
    from "allowed, and moves something", which are different facts about a permitted call.

    **What this does not check.** It says nothing about whether the stage *should* run, whether the
    start gate is met, or whether the data is any good. It answers exactly one question: would
    letting this stage complete leave the machine claiming Phase 0 progressed?
    """
    authority = STAGE_AUTHORITY.get(stage)
    if authority is None:
        raise ValueError(
            "unknown stage {!r}; expected one of {}. Refusing to guess: a stage with no entry in "
            "STAGE_AUTHORITY has no 'advances' to read, and treating a missing rule as an absent "
            "one is how an unregistered stage acquires permission it was never "
            "given.".format(stage, ", ".join(sorted(STAGE_AUTHORITY)))
        )
    if not is_synthetic_snapshot(dataset_snapshot):
        return authority.advances
    if authority.advances is None:
        return None
    raise SyntheticRunRefused(
        "stage {!r} completes the transition to {} and this run's dataset snapshot is {!r}, which "
        "declares itself synthetic (identifiers minted by tools.mockchain begin {!r}). {} "
        "A synthetic run may execute stages and record their outcomes — phase0.execute_stage "
        "writes the run record at step 3, calls the runner at step 4 and appends the audit entry "
        "at step 7 regardless — but step 6, the transition, is withheld. Nothing generated may "
        "leave the machine in a state that says the experiment moved.".format(
            stage, authority.advances, dataset_snapshot, SNAPSHOT_PREFIX,
            _why(authority.advances),
        )
    )


def execute_synthetic_stage(stage, runner, requester, *, governance, dataset_snapshot, **kwargs):
    """:func:`phase0.execution.execute_stage`, with the synthetic rule enforced on both sides.

    The prediction runs first, so a stage that would advance is refused before a run record exists.
    The observation runs last, so a state that moved anyway is refused even if the prediction had
    never heard of the transition that moved it.

    :param governance: the :class:`~phase0.governance.GovernanceMachine`, read before and after.
        Passed through to ``execute_stage`` as well; it is named here because this function has to
        read the state itself and cannot dig it out of ``kwargs`` by convention.
    :raises SyntheticRunRefused: before the runner, when the stage completes a refused transition;
        after it, when the governance state moved at all.

    **What this guarantees, and what it does not.** It guarantees that a stage run *through this
    function* leaves the governance state where it found it, and that nothing is written at all for
    one that would have advanced. It does not guarantee either of those for
    ``phase0.execute_stage``, which is public and exported — but that caller is no longer
    unguarded: phase0 now ``HELD``\\ s such a stage itself, after the runner. See
    :data:`GOVERNANCE_GAP` for the division of labour and for what is still open.

    When the observation does fire, the damage is already done: the state has moved and this raises
    *afterwards*. It is a detector, not a second lock.
    """
    refuse_if_synthetic_would_advance(stage, dataset_snapshot)
    before = governance.state
    result = execute_stage(
        stage, runner, requester,
        governance=governance, dataset_snapshot=dataset_snapshot, **kwargs
    )
    after = governance.state
    if is_synthetic_snapshot(dataset_snapshot) and after != before:
        raise SyntheticRunRefused(
            "stage {!r} ran under the synthetic snapshot {!r} and the governance state moved from "
            "{} to {}. STAGE_AUTHORITY said this stage advances {!r}, so the pre-flight refusal "
            "did not fire and the register and the machine disagree about what this stage does. "
            "The state has already moved: this is a detector reporting that the lock in "
            "tools/mockchain was the wrong lock, not a lock — and that phase0's own refusal did "
            "not see this transition either. See "
            "tools.mockchain.governance.GOVERNANCE_GAP.".format(
                stage, dataset_snapshot, before, after,
                STAGE_AUTHORITY[stage].advances,
            )
        )
    return result


#: Where the refusal lives now that ``src/phase0/`` owns it, and the narrower residue that is still
#: open. Quoted verbatim by ``tests/mockchain/test_governance_refusal.py`` so it cannot rot into a
#: stale note — as the version of it that described an unclosed gap would have.
GOVERNANCE_GAP = """\
WHERE THE REFUSAL LIVES -- it is no longer in tools/

  Primary:  src/phase0/execution.py, in execute_stage, between step 5 (governance re-checked) and
            step 6 (the transition). execute_stage is the only place that both knows the
            dataset_snapshot and decides whether to advance, so it is the only place where
            "execute but do not advance" can be expressed at all. A stage that bears on a
            transition and ran under a not-real snapshot is HELD: the run record, the stage
            outcome and the audit entry are written, and the transition is withheld.

  Backstop: src/phase0/governance.py, in GovernanceMachine.transition, which takes a
            dataset_snapshot and raises phase0.errors.NotAMeasurementError. execute_stage is not
            the only caller -- phase0/cli.py reaches transition through the MANUAL_TRANSITIONS
            path -- so this is what covers PARAMETERS_FROZEN and CODE_AND_DATA_FROZEN, two of the
            four states the rule most exists to protect and no stage's 'advances'.

  Rule:     src/phase0/governance.py, in advancement_refusal, so the two enforcement points cannot
            drift into disagreeing about what is refused. They differ only in what a refusal looks
            like at each.

WHAT src/phase0/ OWNS, NOT tools/

  The predicate. tools.mockchain.provenance.is_synthetic_snapshot could never have been the
  authority: src/ may not import tools/ (tests/test_lane_independence.py), and a rule enforced by
  a module the enforcer cannot see is not enforced. What phase0 owns is a property of the
  identifier it is already given -- src/phase0/snapshots.py, NOT_REAL_PREFIXES, a table of the
  prefixes by which a snapshot identifier declares itself not a measurement. "SYNTHETIC-" is one
  row of it; "REPLAY-" and "DRYRUN-" are others, and adding a kind is a line of data rather than
  a branch of code. tools/mockchain conforms: SNAPSHOT_PREFIX is that row.

WHY THE STAGE PATH IS HELD AND NOT REFUSED

  REFUSED means the runner was never called; on this path it was, and it produced a value the
  caller may legitimately want. HELD already means exactly "the stage ran, governance would not
  commit the outcome, nothing advanced", which is the fact. It also means StageResult.value
  raises StageNotCompleted, so a not-real result cannot be read by a caller that never checked
  the status -- the same protection the HALT path gets, for the same reason.

  The one place the analogy strains: a HALT is resumed and the stage re-run, and there is nothing
  here to resume. The reason text says so instead of leaving a reader to infer it, and the two
  conditions are documented separately on the HELD constant.

  In GovernanceMachine.transition the refusal raises rather than returning: transition has no
  status vocabulary, its contract is "advance or raise", and a transition that silently did
  nothing would be worse than either.

WHAT IS STILL OPEN, AND IT IS NOT NOTHING

  transition can only check a snapshot it is given, and dataset_snapshot defaults to None because
  PARAMETERS_FROZEN genuinely precedes any dataset -- there is normally nothing to name. A caller
  that has a snapshot and withholds it is therefore not refused, and phase0 cannot tell that case
  from the honest one. This package is such a caller: drive_synthetic_phase0 performs its
  PARAMETERS_FROZEN fiction by calling transition without passing the snapshot it is holding, and
  says so in its own docstring. Only the caller can close that, by naming its data.

  And nothing anywhere detects data that is not real and does not say so. The declaration is a
  claim the source makes about itself.

WHAT THIS PACKAGE STILL ENFORCES, AND WHY IT IS NOT REDUNDANT

  refuse_if_synthetic_would_advance refuses BEFORE the runner, so a synthetic stage that would
  advance opens no run record at all; phase0's refusal is necessarily after it. And
  execute_synthetic_stage's observation reads the state before and after and refuses if it moved,
  whatever either register said. Both are now defence in depth over a real lock rather than a
  substitute for one: it binds callers who use this package's entry point, and it binds nobody
  else -- but the caller it does not bind is now bound by src/phase0/ instead.
"""
