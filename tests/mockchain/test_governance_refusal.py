"""``governance.py`` claims a synthetic run advances nothing. This tests the claim, and its limits.

The claim has three parts and they are not equally strong, so they are tested separately:

* **the prediction** — :func:`refuse_if_synthetic_would_advance` reads ``STAGE_AUTHORITY`` and
  refuses before the runner is called, so nothing is written at all. Tested over *every* registered
  stage rather than a sample, in both directions: every stage that completes a transition is
  refused under a synthetic snapshot, and every stage that completes none is permitted.
* **the observation** — :func:`execute_synthetic_stage` reads the governance state before and after
  and refuses if it moved, whatever the register said. Tested with a stage the register calls
  harmless and a runner that moves the machine anyway, which is the case the prediction is blind to.
* **the closed gap** — both live in ``tools/``, and ``phase0.execute_stage`` is public and
  exported, so a caller who does not import this package used to walk past everything here. That is
  no longer true: ``src/phase0/`` owns the rule now (``phase0.snapshots.NOT_REAL_PREFIXES``,
  ``phase0.governance.advancement_refusal``), and the last tests here pin the *division of labour*
  — what this package still adds, what phase0 does instead, and the narrower residue that is left.

Four of the eight states record a human act about a real experiment. Two of them —
``PARAMETERS_FROZEN`` and ``CODE_AND_DATA_FROZEN`` — are not any stage's ``advances`` at all: they
are ``phase0.execution.MANUAL_TRANSITIONS``, entered through ``GovernanceMachine.freeze_parameters``
from the command line. No amount of care in this package can refuse them, which is why
``GovernanceMachine.transition`` had to become the backstop rather than ``execute_stage`` being
treated as sufficient. That asymmetry is pinned below, because it is the part of the rule a reader
is most likely to assume away. ``tests/hand_computed/test_not_real_snapshots.py`` and
``tests/integration/test_not_real_snapshots.py`` test the refusal itself, without importing this
package at all — which is the point of where it now lives.
"""

import pytest

from phase0 import governance as gov
from phase0.errors import NotAMeasurementError, StageNotCompleted
from phase0.execution import (
    COMPLETED,
    HELD,
    MANUAL_TRANSITIONS,
    STAGE_AUTHORITY,
    execute_stage,
    wire,
)
from phase0.preconditions import PRECONDITION_KEYS
from phase0.snapshots import NOT_REAL_PREFIXES, declared_not_real

from tools.mockchain.governance import (
    COMPUTED_STATES,
    GOVERNANCE_GAP,
    HUMAN_ACT_STATES,
    SYNTHETIC_MAY_NOT_ADVANCE,
    SyntheticRunRefused,
    execute_synthetic_stage,
    refuse_if_synthetic_would_advance,
)
from tools.mockchain.provenance import SNAPSHOT_PREFIX, is_synthetic_snapshot, snapshot_id

from conftest import SEED

SYNTHETIC_SNAPSHOT = snapshot_id(SEED)

#: What a real run's snapshot looks like: an archival-node extract, named by its date.
REAL_SNAPSHOT = "dune-2026-07-31"

COMMIT = "abc1234"

#: Stages that complete a transition, and the state each completes.
ADVANCING = tuple(sorted(
    (stage, authority.advances) for stage, authority in STAGE_AUTHORITY.items()
    if authority.advances is not None
))

#: Stages that compute something and move nothing.
NON_ADVANCING = tuple(sorted(
    stage for stage, authority in STAGE_AUTHORITY.items() if authority.advances is None
))


@pytest.fixture
def wiring(tmp_path):
    """A real ``phase0`` wiring on disk, with the §15.4 start gate satisfied."""
    state = wire(str(tmp_path / "state"))
    for key, who in zip(
        PRECONDITION_KEYS,
        ("A. Builder", "V. Alidator, contract #7", "PO-1234", "capacity reserved, weeks 1-12"),
    ):
        state.preconditions.record(key, who, "Research Owner")
    state.governance.freeze_parameters("Research Owner")
    return state


def _runner(value=None):
    def run(context):
        return {"stage": context.stage, "snapshot": context.dataset_snapshot, "value": value}
    return run


# -- what the rule covers -------------------------------------------------------


def test_the_refused_set_is_every_state_except_the_initial_one():
    assert SYNTHETIC_MAY_NOT_ADVANCE == frozenset(gov.ORDER) - {gov.PARAMETERS_OPEN}
    assert len(SYNTHETIC_MAY_NOT_ADVANCE) == 7
    assert gov.PARAMETERS_OPEN not in SYNTHETIC_MAY_NOT_ADVANCE


def test_every_refused_state_has_one_of_the_two_stated_reasons():
    assert set(HUMAN_ACT_STATES) | set(COMPUTED_STATES) == SYNTHETIC_MAY_NOT_ADVANCE
    assert set(HUMAN_ACT_STATES) & set(COMPUTED_STATES) == set()
    assert HUMAN_ACT_STATES == (
        gov.PARAMETERS_FROZEN, gov.VALIDATION_PASSED, gov.CODE_AND_DATA_FROZEN,
        gov.DECISION_EMITTED,
    )
    assert COMPUTED_STATES == (
        gov.NULL_COMPLETE, gov.THRESHOLD_LOCKED, gov.MAIN_TEST_EXECUTED,
    )


# -- the prediction, over every registered stage --------------------------------


@pytest.mark.parametrize("stage,advances", ADVANCING, ids=[s for s, _ in ADVANCING])
def test_every_advancing_stage_is_refused_under_a_synthetic_snapshot(stage, advances):
    with pytest.raises(SyntheticRunRefused) as raised:
        refuse_if_synthetic_would_advance(stage, SYNTHETIC_SNAPSHOT)
    message = str(raised.value)
    assert stage in message
    assert advances in message
    assert SYNTHETIC_SNAPSHOT in message
    # The refusal must say *which kind* of claim it is refusing, not merely that it refuses.
    if advances in HUMAN_ACT_STATES:
        assert "records a human act about a real experiment" in message
    else:
        assert "records a computation over the experiment's data" in message


@pytest.mark.parametrize("stage", NON_ADVANCING)
def test_a_stage_that_moves_nothing_is_permitted_and_says_so(stage):
    """A synthetic run may execute stages. `None` means "allowed, and moves nothing"."""
    assert refuse_if_synthetic_would_advance(stage, SYNTHETIC_SNAPSHOT) is None


@pytest.mark.parametrize("stage,advances", ADVANCING, ids=[s for s, _ in ADVANCING])
def test_the_same_stage_under_a_real_snapshot_is_permitted(stage, advances):
    """The refusal is about the snapshot. Nothing here refuses a real run."""
    assert refuse_if_synthetic_would_advance(stage, REAL_SNAPSHOT) == advances


def test_an_unregistered_stage_raises_rather_than_being_waved_through():
    with pytest.raises(ValueError) as raised:
        refuse_if_synthetic_would_advance("pipeline.synthetic_smoke_test", SYNTHETIC_SNAPSHOT)
    assert "unknown stage" in str(raised.value)
    assert "Refusing to guess" in str(raised.value)


# -- the four human-act states, and which of them this package can actually reach --


def test_two_of_the_four_human_act_states_are_reachable_through_a_stage_and_are_refused():
    reachable = {advances for _stage, advances in ADVANCING} & set(HUMAN_ACT_STATES)
    assert reachable == {gov.VALIDATION_PASSED, gov.DECISION_EMITTED}
    for stage, advances in ADVANCING:
        if advances in reachable:
            with pytest.raises(SyntheticRunRefused):
                refuse_if_synthetic_would_advance(stage, SYNTHETIC_SNAPSHOT)


def test_the_other_two_are_manual_transitions_that_no_stage_can_refuse():
    """The sharpest half of the rule is the half ``tools/`` cannot enforce. Pinned, not implied."""
    unreachable = set(HUMAN_ACT_STATES) - {advances for _stage, advances in ADVANCING}
    assert unreachable == {gov.PARAMETERS_FROZEN, gov.CODE_AND_DATA_FROZEN}
    assert set(MANUAL_TRANSITIONS) == unreachable
    assert "PARAMETERS_FROZEN and CODE_AND_DATA_FROZEN, two of the" in GOVERNANCE_GAP


def test_this_packages_prefix_is_one_row_of_the_table_phase0_owns():
    """The conformance the gap text claims. ``phase0`` is the authority; this package follows.

    If these ever disagree, every refusal in ``src/phase0/`` stops seeing this generator's
    snapshots while every refusal here goes on firing — which reads, from the outside, exactly like
    a working guard.
    """
    assert SNAPSHOT_PREFIX in NOT_REAL_PREFIXES
    assert is_synthetic_snapshot(SYNTHETIC_SNAPSHOT)
    assert declared_not_real(SYNTHETIC_SNAPSHOT) == SNAPSHOT_PREFIX


def test_the_manual_freeze_is_now_refused_when_the_caller_names_its_snapshot(wiring):
    """The backstop, demonstrated on the two states no stage can reach.

    ``GovernanceMachine.transition`` takes a ``dataset_snapshot`` now, so a person at the command
    line who names synthetic data is refused where before they froze code and data exactly as on a
    real run. The stage in the middle is ``HELD`` rather than ``COMPLETED``, so the machine never
    even arrives at ``VALIDATION_PASSED`` to be frozen from.
    """
    assert wiring.governance.state == gov.PARAMETERS_FROZEN
    held = execute_stage(
        "validation.independent", _runner(), "primary-builder",
        governance=wiring.governance, preconditions=wiring.preconditions, runs=wiring.runs,
        audit=wiring.audit, commit=COMMIT, dataset_snapshot=SYNTHETIC_SNAPSHOT,
    )
    assert held.status == HELD
    assert wiring.governance.state == gov.PARAMETERS_FROZEN

    with pytest.raises(NotAMeasurementError) as raised:
        wiring.governance.transition(gov.CODE_AND_DATA_FROZEN, "Research Owner",
                                     dataset_snapshot=SYNTHETIC_SNAPSHOT)
    assert SYNTHETIC_SNAPSHOT in str(raised.value)
    assert wiring.governance.state == gov.PARAMETERS_FROZEN


# -- the wired refusal ----------------------------------------------------------


def test_the_refusal_fires_before_anything_is_written(wiring):
    runner_calls = []

    def runner(context):
        runner_calls.append(context.stage)
        return None

    entries_before = len(wiring.audit.entries())
    with pytest.raises(SyntheticRunRefused):
        execute_synthetic_stage(
            "validation.independent", runner, "primary-builder",
            governance=wiring.governance, preconditions=wiring.preconditions, runs=wiring.runs,
            audit=wiring.audit, commit=COMMIT, dataset_snapshot=SYNTHETIC_SNAPSHOT,
        )
    assert runner_calls == [], "the runner ran; the refusal was not a pre-flight refusal"
    assert wiring.governance.state == gov.PARAMETERS_FROZEN
    assert len(wiring.audit.entries()) == entries_before, (
        "a refused synthetic stage left an audit entry. Nothing was about to happen, so there is "
        "nothing to record."
    )
    assert list(wiring.runs.list_runs()) == [], (
        "a refused synthetic stage opened a run record. A run record for a stage that never ran "
        "is evidence of a fiction."
    )


def test_the_same_stage_completes_and_advances_under_a_real_snapshot(wiring):
    """The control. Without it, the refusal above could be a broken wiring rather than a rule."""
    result = execute_synthetic_stage(
        "validation.independent", _runner("ok"), "primary-builder",
        governance=wiring.governance, preconditions=wiring.preconditions, runs=wiring.runs,
        audit=wiring.audit, commit=COMMIT, dataset_snapshot=REAL_SNAPSHOT,
    )
    assert result.status == COMPLETED
    assert result.advanced_to == gov.VALIDATION_PASSED
    assert wiring.governance.state == gov.VALIDATION_PASSED


def test_a_synthetic_run_may_execute_a_non_advancing_stage_and_record_it(wiring):
    """"Execute but do not advance" is the existing sequence with one step withheld."""
    result = execute_synthetic_stage(
        "step0.universe", _runner("universe"), "primary-builder",
        governance=wiring.governance, preconditions=wiring.preconditions, runs=wiring.runs,
        audit=wiring.audit, commit=COMMIT, dataset_snapshot=SYNTHETIC_SNAPSHOT,
    )
    assert result.status == COMPLETED
    assert result.advanced_to is None
    assert result.value["snapshot"] == SYNTHETIC_SNAPSHOT
    assert wiring.governance.state == gov.PARAMETERS_FROZEN
    actions = [entry.action for entry in wiring.audit.entries()]
    assert "stage.completed" in actions, "the outcome must still be recorded"


def test_the_observation_catches_a_state_that_moved_when_the_register_said_it_would_not(wiring):
    """The half that survives a change to ``STAGE_AUTHORITY``.

    ``step0.universe`` advances nothing, so the prediction permits it. The runner moves the machine
    anyway — standing in for a stage added tomorrow whose ``advances`` this module has never heard
    of — and the after-the-fact read refuses. The refusal says it is a detector, because the state
    has already moved by the time it fires.
    """
    def runner(context):
        wiring.governance.transition(gov.VALIDATION_PASSED, "runaway-stage")
        return "moved"

    with pytest.raises(SyntheticRunRefused) as raised:
        execute_synthetic_stage(
            "step0.universe", runner, "primary-builder",
            governance=wiring.governance, preconditions=wiring.preconditions, runs=wiring.runs,
            audit=wiring.audit, commit=COMMIT, dataset_snapshot=SYNTHETIC_SNAPSHOT,
        )
    message = str(raised.value)
    assert gov.PARAMETERS_FROZEN in message and gov.VALIDATION_PASSED in message
    assert "the wrong lock, not a lock" in message
    assert "GOVERNANCE_GAP" in message
    # And the damage is real: this is a detector, so the state did move.
    assert wiring.governance.state == gov.VALIDATION_PASSED


# -- the gap, demonstrated and quoted -------------------------------------------


def test_the_public_entry_point_no_longer_walks_past_the_rule(wiring):
    """The gap this file used to demonstrate. ``execute_stage`` now holds instead of advancing.

    Nothing in this call imports ``tools/mockchain``: it is the caller the harness could never
    bind, and it is refused by ``src/phase0/`` on the strength of the identifier alone. The
    evidence is still written — that is what ``HELD`` means and what a synthetic run is entitled to.
    """
    result = execute_stage(
        "validation.independent", _runner(), "primary-builder",
        governance=wiring.governance, preconditions=wiring.preconditions, runs=wiring.runs,
        audit=wiring.audit, commit=COMMIT, dataset_snapshot=SYNTHETIC_SNAPSHOT,
    )
    assert result.status == HELD
    assert result.advanced_to is None
    assert wiring.governance.state == gov.PARAMETERS_FROZEN
    assert result.run_id is not None, "the stage ran; its run record stands"
    assert "stage.held" in [entry.action for entry in wiring.audit.entries()]

    with pytest.raises(StageNotCompleted):
        result.value


def test_the_gap_text_says_where_the_refusal_lives_and_what_is_still_open():
    """Quoted verbatim so the note cannot rot into a description of code that has moved on."""
    for fragment in (
        "src/phase0/execution.py, in execute_stage, between step 5 (governance re-checked) and",
        "src/phase0/governance.py, in GovernanceMachine.transition, which takes a",
        "src/phase0/snapshots.py, NOT_REAL_PREFIXES, a table of the",
        "WHY THE STAGE PATH IS HELD AND NOT REFUSED",
        "WHAT IS STILL OPEN, AND IT IS NOT NOTHING",
    ):
        assert fragment in GOVERNANCE_GAP, fragment
    # The residue it names, and the fact that this package is itself an instance of it.
    assert "drive_synthetic_phase0 performs its" in GOVERNANCE_GAP
    assert "it binds callers who use this package's entry point, and it binds nobody" in (
        GOVERNANCE_GAP
    )
