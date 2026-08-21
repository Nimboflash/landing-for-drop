"""A snapshot that declares itself not a measurement may not advance a real state.

Found by driving the machine on generated data and measuring what happened, not by reading it::

    phase0.execute_stage("validation.independent", ..., dataset_snapshot="SYNTHETIC-...")
    -> COMPLETED, advanced_to == VALIDATION_PASSED, and the machine really moved.

Four of the eight governance states record a **human act about a real experiment** — a person froze
the pre-registration (ticket 11), the four-layer validation gate passed against real data, a person
froze code and data (ticket 39), a decision was emitted about a hypothesis. Advancing one of those
on data that was never measured is a machine asserting that a person did something. The other three
record computations, and ``MAIN_TEST_EXECUTED`` is write-once, so reaching it on generated input
would consume the single main-test execution the whole pre-registration is built around and the
real one would afterwards be refused as *"already in this state"*.

What is tested here, and in what order
--------------------------------------

1. **The vocabulary**, pinned as literals. :mod:`phase0.snapshots` owns a *table* of prefixes, not
   one string, so that adding a kind of not-real data is a data change. The literals are pinned so
   a silent rename of ``SYNTHETIC-`` cannot pass.
2. **Each of the four human-act states, refused.** Two are reached through a stage and are ``HELD``
   by ``execute_stage``; two are ``MANUAL_TRANSITIONS`` and are raised on by
   ``GovernanceMachine.transition``. Both routes, because they are different code.
3. **The same four reached on an ordinary snapshot.** Without these the refusals above could be a
   guard that simply broke governance, which would look identical from one side.
4. **What the refusal says** — the snapshot, the rule, the state, and what it costs.
5. **The two edges** that are easy to get wrong: a stage whose companion is still outstanding (it
   advances nothing *this call*, and must still be held, because ``completed_stages`` counts it
   from the audit log and a later stage would advance on the strength of it), and a stage that
   completes no transition at all (it must still run and still be recorded — a run under generated
   data is entitled to execute stages).

Nothing here imports ``tools/mockchain``. That is the point: the caller the harness could never
bind is the caller this refusal exists for, and the rule is about the identifier rather than about
where the data came from.
"""

import pytest

from phase0 import governance as gov
from phase0.cli import main
from phase0.errors import NotAMeasurementError, StageNotCompleted, TransitionError
from phase0.execution import (
    COMPLETED,
    HELD,
    MANUAL_TRANSITIONS,
    MANUAL_TRANSITIONS_WITH_A_DATASET,
    STAGE_AUTHORITY,
    execute_stage,
    wire,
)
from phase0.preconditions import PRECONDITION_KEYS
from phase0.snapshots import (
    NOT_REAL_PREFIXES,
    declaration_clause,
    declared_not_real,
    is_declared_not_real,
)

COMMIT = "abc1234"

#: What a real run's snapshot looks like: an archival-node extract, named by its date.
REAL = "dune-2026-07-31"

#: One not-real snapshot, spelled out rather than imported. A test that asked ``tools/mockchain``
#: for this string would be testing that two modules agree, not that the rule holds.
SYNTHETIC = "SYNTHETIC-mockchain-v1-seed-7-c610779940e0-NOT-A-MEASUREMENT"

#: The state each of the four human-act states is entered from, and how.
HUMAN_ACT_ROUTES = (
    (gov.PARAMETERS_FROZEN, "manual"),
    (gov.VALIDATION_PASSED, "stage"),
    (gov.CODE_AND_DATA_FROZEN, "manual"),
    (gov.DECISION_EMITTED, "stage"),
)

#: The stage that earns each of the two stage-earned human-act states.
STAGE_FOR = {
    gov.VALIDATION_PASSED: "validation.independent",
    gov.DECISION_EMITTED: "decision.emit",
}


@pytest.fixture
def w(tmp_path):
    """A wiring on disk with the §15.4 start gate satisfied and nothing else done."""
    state = wire(str(tmp_path / "state"))
    for key, who in zip(PRECONDITION_KEYS, ("A. Builder", "V. Alidator, contract #7",
                                            "PO-1234", "capacity reserved, weeks 1-12")):
        state.preconditions.record(key, who, "Research Owner")
    return state


def runner(context):
    """A trivial injected runner. ``phase0`` never learns what a stage does; neither does a test."""
    return {"stage": context.stage, "snapshot": context.dataset_snapshot}


def walk_to(w, state):
    """Advance the machine to the state just before ``state``, by hand and without a snapshot.

    Uses the unchecked ``transition`` path deliberately: this is scaffolding to place the machine,
    not the thing under test, and routing it through stages would make every test here depend on
    the whole stage register.
    """
    for step in gov.ORDER[1:gov.position(state)]:
        w.governance.transition(step, "Research Owner")
    return w.governance.state


def run(w, stage, snapshot, requester="primary-builder"):
    return execute_stage(
        stage, runner, requester,
        governance=w.governance, preconditions=w.preconditions, runs=w.runs, audit=w.audit,
        commit=COMMIT, dataset_snapshot=snapshot, config={"stage": stage},
    )


# -- 1. the vocabulary, pinned as literals ---------------------------------------


def test_the_table_is_exactly_these_four_prefixes():
    """A table rather than a constant, so adding a kind is data. Pinned so a rename cannot pass.

    ``NOT-PREREGISTERED-`` was added by ticket 21 (``tools/hyperliquid``) as a line of data and no
    branch of code anywhere: every test below this one is parametrised over the table or reads the
    whole of it, so the row arrived already covered by the refusal tests. That is the property the
    table exists for, and adding the row is what demonstrates it.

    It is also the row whose claim is the narrowest, and the description says so: the data behind
    such an identifier is real, and what is not real is its relationship to *this* experiment.
    """
    assert sorted(NOT_REAL_PREFIXES) == [
        "DRYRUN-", "NOT-PREREGISTERED-", "REPLAY-", "SYNTHETIC-",
    ]
    assert NOT_REAL_PREFIXES["SYNTHETIC-"] == "generated by a source that never read a chain"
    assert NOT_REAL_PREFIXES["REPLAY-"] == (
        "replayed from a recorded fixture rather than read from a chain"
    )
    assert NOT_REAL_PREFIXES["DRYRUN-"] == "a rehearsal of the machinery, not a run of the experiment"
    assert NOT_REAL_PREFIXES["NOT-PREREGISTERED-"] == (
        "measured off a real source that the pre-registration did not name; the data is real and "
        "the venue is not the one §11.1 fixed, and §11.2 forbids introducing one after the fact"
    )


@pytest.mark.parametrize("prefix", sorted(NOT_REAL_PREFIXES))
def test_every_prefix_in_the_table_is_recognised(prefix):
    """Parametrised over the table, so a row added tomorrow is covered without editing a test."""
    assert declared_not_real(prefix + "whatever-2026") == prefix
    assert is_declared_not_real(prefix + "whatever-2026")


@pytest.mark.parametrize("identifier,expected", [
    ("dune-2026-07-31", None),
    ("mainnet-2026-08-01", None),
    ("", None),
    ("archive-node-synthetic-comparison-2026", None),   # mentions it; does not declare it
    ("synthetic-lowercase-1", "SYNTHETIC-"),            # the rule does not turn on the shift key
    ("  SYNTHETIC-leading-space", "SYNTHETIC-"),
    ("RePlAy-2026", "REPLAY-"),
])
def test_what_counts_as_a_declaration(identifier, expected):
    assert declared_not_real(identifier) == expected


@pytest.mark.parametrize("value", [None, 7, b"SYNTHETIC-bytes", ["SYNTHETIC-list"]])
def test_a_non_string_declares_nothing(value):
    """This module reports what an identifier declares; ``RunStore.open_run`` polices the type."""
    assert declared_not_real(value) is None


# -- 2. each of the four human-act states, refused --------------------------------


def test_validation_passed_is_held_not_advanced(w):
    """The gate that the whole design's worth rests on, attempted on data nobody measured."""
    walk_to(w, gov.VALIDATION_PASSED)
    assert w.governance.state == gov.PARAMETERS_FROZEN

    result = run(w, "validation.independent", SYNTHETIC)

    assert result.status == HELD
    assert result.advanced_to is None
    assert w.governance.state == gov.PARAMETERS_FROZEN
    assert result.run_id is not None, "the stage ran, so its run record stands"
    with pytest.raises(StageNotCompleted):
        result.value


def test_decision_emitted_is_held_not_advanced(w):
    """The last state, and the one a published GO would be read off."""
    walk_to(w, gov.DECISION_EMITTED)
    assert w.governance.state == gov.MAIN_TEST_EXECUTED

    result = run(w, "decision.emit", SYNTHETIC)

    assert result.status == HELD
    assert result.advanced_to is None
    assert w.governance.state == gov.MAIN_TEST_EXECUTED


@pytest.mark.parametrize("state", MANUAL_TRANSITIONS)
def test_the_two_manual_human_acts_raise_when_the_caller_names_its_data(w, state):
    """No stage advances these, so ``transition`` is the only place they can be refused."""
    walk_to(w, state)
    before = w.governance.state

    with pytest.raises(NotAMeasurementError):
        w.governance.transition(state, "Research Owner", dataset_snapshot=SYNTHETIC)

    assert w.governance.state == before, "a refused transition wrote nothing"


def test_freeze_parameters_passes_its_snapshot_through(w):
    """The convenience wrapper must not be a way around the rule it wraps."""
    with pytest.raises(NotAMeasurementError):
        w.governance.freeze_parameters("Research Owner", dataset_snapshot=SYNTHETIC)
    assert w.governance.state == gov.PARAMETERS_OPEN


@pytest.mark.parametrize("state,route", HUMAN_ACT_ROUTES,
                         ids=[s for s, _ in HUMAN_ACT_ROUTES])
def test_each_of_the_four_states_that_record_a_human_act_is_refused(w, state, route):
    """The claim of this whole file, over all four, whichever route each is reached by."""
    walk_to(w, state)
    before = w.governance.state

    if route == "manual":
        with pytest.raises(NotAMeasurementError):
            w.governance.transition(state, "Research Owner", dataset_snapshot=SYNTHETIC)
    else:
        assert run(w, STAGE_FOR[state], SYNTHETIC).status == HELD

    assert w.governance.state == before
    assert state in gov.HUMAN_ACT_STATES


@pytest.mark.parametrize("state", gov.COMPUTED_STATES)
def test_the_three_computed_states_are_refused_too(w, state):
    """Wider than the four on purpose. MAIN_TEST_EXECUTED is write-once: reaching it here would
    consume the single main-test execution and the real one would be refused afterwards."""
    walk_to(w, state)
    before = w.governance.state

    with pytest.raises(NotAMeasurementError):
        w.governance.transition(state, "Research Owner", dataset_snapshot=SYNTHETIC)

    assert w.governance.state == before
    assert state in gov.NOT_REAL_MAY_NOT_ADVANCE


def test_an_unknown_state_is_still_reported_as_unknown(w):
    """The refusal is scoped to states that exist, so it cannot mask a caller's typo.

    Without that scope, ``transition("VALIDATON_PASSED", ..., dataset_snapshot=SYNTHETIC)`` would
    raise "this snapshot may not advance" about a state that is not in the machine at all, and the
    caller would spend the afternoon on the snapshot.
    """
    with pytest.raises(TransitionError) as raised:
        w.governance.transition("VALIDATON_PASSED", "builder", dataset_snapshot=SYNTHETIC)
    assert "unknown state" in str(raised.value)


def test_a_state_added_without_a_stated_reason_is_refused_and_still_explained(monkeypatch):
    """The direction the rule is derived in, pinned. A new state is covered before anyone covers it.

    ``NOT_REAL_MAY_NOT_ADVANCE`` comes from ``ORDER`` rather than a list, so a state added to the
    machine is refused by default; this stands in for that state and checks the refusal still says
    something true about it rather than falling through to a blank reason.
    """
    monkeypatch.setattr(gov, "NOT_REAL_MAY_NOT_ADVANCE",
                        gov.NOT_REAL_MAY_NOT_ADVANCE | {"SOMETHING_NEW"})
    refusal = gov.advancement_refusal(SYNTHETIC, "SOMETHING_NEW")

    assert refusal is not None
    assert "SOMETHING_NEW" in refusal
    assert "refused by default" in refusal


def test_the_refused_set_is_every_state_but_the_one_the_machine_starts_in():
    """Derived from ORDER, so a state added to the machine is refused rather than permitted."""
    assert gov.NOT_REAL_MAY_NOT_ADVANCE == frozenset(gov.ORDER) - {gov.PARAMETERS_OPEN}
    assert set(gov.HUMAN_ACT_STATES) | set(gov.COMPUTED_STATES) == gov.NOT_REAL_MAY_NOT_ADVANCE
    assert set(gov.HUMAN_ACT_STATES) & set(gov.COMPUTED_STATES) == set()


@pytest.mark.parametrize("prefix", sorted(NOT_REAL_PREFIXES))
def test_the_rule_is_the_class_and_not_the_one_string(w, prefix):
    """A replayed snapshot and a dry run are refused by the same rule, with no code added."""
    walk_to(w, gov.VALIDATION_PASSED)
    result = run(w, "validation.independent", prefix + "2026-07-31")
    assert result.status == HELD
    assert w.governance.state == gov.PARAMETERS_FROZEN


# -- 3. the controls: the same states, on an ordinary snapshot --------------------


def test_validation_passed_is_reached_on_an_ordinary_snapshot(w):
    walk_to(w, gov.VALIDATION_PASSED)
    result = run(w, "validation.independent", REAL)

    assert result.status == COMPLETED
    assert result.advanced_to == gov.VALIDATION_PASSED
    assert w.governance.state == gov.VALIDATION_PASSED
    assert result.value["snapshot"] == REAL


def test_decision_emitted_is_reached_on_an_ordinary_snapshot(w):
    walk_to(w, gov.DECISION_EMITTED)
    result = run(w, "decision.emit", REAL)

    assert result.status == COMPLETED
    assert result.advanced_to == gov.DECISION_EMITTED
    assert w.governance.state == gov.DECISION_EMITTED


@pytest.mark.parametrize("state", MANUAL_TRANSITIONS)
def test_the_two_manual_human_acts_are_reached_on_an_ordinary_snapshot(w, state):
    walk_to(w, state)
    assert w.governance.transition(state, "Research Owner", dataset_snapshot=REAL) == state
    assert w.governance.state == state


@pytest.mark.parametrize("state", MANUAL_TRANSITIONS)
def test_a_manual_transition_that_names_no_snapshot_still_works(w, state):
    """``PARAMETERS_FROZEN`` precedes any dataset, so ``None`` cannot be made to mean 'refuse'.

    Pinned because it is the honest limit of the backstop, not an oversight: a caller that
    withholds a snapshot it holds is indistinguishable from one that has none.
    """
    walk_to(w, state)
    assert w.governance.transition(state, "Research Owner") == state


@pytest.mark.parametrize("stage", sorted(
    stage for stage, authority in STAGE_AUTHORITY.items() if authority.advances is not None))
def test_every_advancing_stage_completes_on_an_ordinary_snapshot(w, stage):
    """The guard must not have broken governance. Every one of them, not a sample."""
    walk_to(w, STAGE_AUTHORITY[stage].advances)
    assert run(w, stage, REAL).status == COMPLETED


# -- 4. what the refusal says -----------------------------------------------------


def test_the_held_reason_names_the_snapshot_the_rule_and_the_cost(w):
    walk_to(w, gov.VALIDATION_PASSED)
    reason = run(w, "validation.independent", SYNTHETIC).reason

    assert SYNTHETIC in reason, "the refusal must quote the input it refused"
    assert "SYNTHETIC-" in reason, "and the prefix that made it refuse"
    assert "declares itself not a measurement" in reason
    assert "validation.independent" in reason
    assert gov.VALIDATION_PASSED in reason
    assert "records a human act about a real experiment" in reason
    assert "may not leave the governance machine in a state that says the experiment progressed" in (
        reason
    )
    # A HALT is resumed and the stage re-run; this is not that, and the reason says which.
    assert "nothing here to resume or retry" in reason
    assert "re-running against a real dataset snapshot" in reason


def test_the_refusal_teaches_the_whole_vocabulary(w):
    """A reader of one refusal learns the rule, so an added prefix is visible in the refusals."""
    clause = declaration_clause(SYNTHETIC)
    for prefix, why in NOT_REAL_PREFIXES.items():
        assert prefix in clause
        assert why in clause


def test_the_raised_refusal_says_which_computation_it_is_protecting(w):
    walk_to(w, gov.MAIN_TEST_EXECUTED)
    with pytest.raises(NotAMeasurementError) as raised:
        w.governance.transition(gov.MAIN_TEST_EXECUTED, "builder", dataset_snapshot=SYNTHETIC)

    message = str(raised.value)
    assert SYNTHETIC in message
    assert "write-once" in message
    assert "consume the single main-test execution" in message


def test_a_held_stage_is_recorded_in_the_audit_log_and_the_chain_verifies(w):
    walk_to(w, gov.VALIDATION_PASSED)
    result = run(w, "validation.independent", SYNTHETIC)

    entries = w.audit.entries()
    assert w.audit.verify() is True

    held = [e for e in entries if e.action == "stage.held"]
    assert len(held) == 1
    assert held[0].detail["status"] == HELD
    assert held[0].detail["advanced_to"] is None
    assert held[0].detail["run_id"] == result.run_id
    assert SYNTHETIC in held[0].detail["reason"]

    opened = [e for e in entries if e.action == "run.open"]
    assert len(opened) == 1, "the run record was written before the runner, as on any other path"
    assert opened[0].detail["dataset_snapshot"] == SYNTHETIC


# -- 5. the two edges -------------------------------------------------------------


def test_a_stage_whose_companion_is_outstanding_is_held_rather_than_completed(w):
    """The subtle one. ``null.leader`` advances nothing on its own — ``null.follower`` is still
    outstanding — so a check written as "would this call advance?" would let it COMPLETE. It must
    not: ``completed_stages`` counts completions from the audit log, so a COMPLETED entry here is
    exactly what a later real ``null.follower`` would advance ``NULL_COMPLETE`` on the strength of.
    """
    walk_to(w, gov.NULL_COMPLETE)
    result = run(w, "null.leader", SYNTHETIC)

    assert result.status == HELD
    assert result.pending == (), "a held stage completed nothing, so it is waiting on nothing"
    assert w.governance.state == gov.CODE_AND_DATA_FROZEN

    # And the follower cannot then advance on the strength of a leader that was never committed.
    assert run(w, "null.follower", SYNTHETIC).status == HELD
    assert w.governance.state == gov.CODE_AND_DATA_FROZEN


@pytest.mark.parametrize("stage", sorted(
    stage for stage, authority in STAGE_AUTHORITY.items() if authority.advances is None))
def test_a_stage_that_moves_nothing_still_runs_and_is_still_recorded(w, stage):
    """"Execute but do not advance" is the existing sequence with one step withheld, not a lockout.

    A run over generated data is entitled to execute stages and record what they produced; what it
    may not do is leave the machine claiming the experiment moved. A guard that refused these too
    would have broken the only thing a synthetic source is for.
    """
    walk_to(w, gov.VALIDATION_PASSED)
    result = run(w, stage, SYNTHETIC)

    assert result.status == COMPLETED
    assert result.advanced_to is None
    assert result.value["snapshot"] == SYNTHETIC
    assert w.governance.state == gov.PARAMETERS_FROZEN
    assert "stage.completed" in [e.action for e in w.audit.entries()]


# -- 6. the command line, which is where the manual half is actually reached ------


def test_the_command_line_refuses_a_freeze_on_a_not_real_snapshot(tmp_path, capsys):
    root = str(tmp_path / "state")

    code = main(["--root", root, "freeze", "PARAMETERS_FROZEN", "--requester", "owner",
                 "--dataset-snapshot", SYNTHETIC])
    err = capsys.readouterr().err

    assert code == 2
    assert "REFUSED" in err
    assert SYNTHETIC in err
    assert "declares itself not a measurement" in err
    assert wire(root).governance.state == gov.PARAMETERS_OPEN


def test_the_command_line_requires_the_dataset_for_the_freeze_that_is_about_data(tmp_path, capsys):
    """Ticket 39 freezes code *and data*. A freeze that does not name its data cannot be checked."""
    assert MANUAL_TRANSITIONS_WITH_A_DATASET == (gov.CODE_AND_DATA_FROZEN,)

    root = str(tmp_path / "state")
    main(["--root", root, "freeze", "PARAMETERS_FROZEN", "--requester", "owner"])
    w = wire(root)
    w.governance.transition(gov.VALIDATION_PASSED, "Research Owner")
    capsys.readouterr()

    code = main(["--root", root, "freeze", "CODE_AND_DATA_FROZEN", "--requester", "owner"])
    err = capsys.readouterr().err

    assert code == 2
    assert "--dataset-snapshot is required for this state" in err
    assert w.governance.state == gov.VALIDATION_PASSED

    code = main(["--root", root, "freeze", "CODE_AND_DATA_FROZEN", "--requester", "owner",
                 "--dataset-snapshot", SYNTHETIC])
    assert code == 2
    assert w.governance.state == gov.VALIDATION_PASSED

    code = main(["--root", root, "freeze", "CODE_AND_DATA_FROZEN", "--requester", "owner",
                 "--dataset-snapshot", REAL])
    assert code == 0
    assert w.governance.state == gov.CODE_AND_DATA_FROZEN


def test_the_parameter_freeze_still_takes_no_dataset_because_it_precedes_one(tmp_path, capsys):
    """Stated rather than implied: this transition is *unexamined* without a snapshot, not cleared.

    A parameter freeze happens before any data has been read, so requiring an identifier would only
    teach people to invent one. What the command line can do is refuse the one it is given, which
    :func:`test_the_command_line_refuses_a_freeze_on_a_not_real_snapshot` pins.
    """
    root = str(tmp_path / "state")
    assert main(["--root", root, "freeze", "PARAMETERS_FROZEN", "--requester", "owner"]) == 0
    assert wire(root).governance.state == gov.PARAMETERS_FROZEN
    assert gov.PARAMETERS_FROZEN not in MANUAL_TRANSITIONS_WITH_A_DATASET


def test_the_freeze_records_the_snapshot_it_was_given_in_the_audit_log(tmp_path):
    root = str(tmp_path / "state")
    main(["--root", root, "freeze", "PARAMETERS_FROZEN", "--requester", "owner",
          "--dataset-snapshot", REAL])

    w = wire(root)
    transitions = [e for e in w.audit.entries() if e.action == "governance.transition"]
    assert len(transitions) == 1
    assert transitions[0].detail["detail"]["dataset_snapshot"] == REAL


def test_the_transition_error_for_a_missing_dataset_is_a_refusal_not_a_crash(tmp_path):
    """It is governance refusing to write an unverifiable record, so it carries the same type as
    every other ordering refusal and both command lines print it rather than tracebacking."""
    root = str(tmp_path / "state")
    main(["--root", root, "freeze", "PARAMETERS_FROZEN", "--requester", "owner"])
    w = wire(root)
    w.governance.transition(gov.VALIDATION_PASSED, "Research Owner")

    from phase0.cli import build_parser, cmd_freeze
    args = build_parser().parse_args(
        ["--root", root, "freeze", "CODE_AND_DATA_FROZEN", "--requester", "owner"])
    with pytest.raises(TransitionError):
        cmd_freeze(args)
