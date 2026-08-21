"""Governance wired to execution — the exact outcome of each path, computed by hand.

``phase0`` could refuse a stage and it could open a run record. Nothing in it ever ran one, so the
two halves had never met: the ordering rules were proven against a state machine nobody called, and
the run record was proven to exist rather than to precede anything.

This file pins the four outcomes of :func:`phase0.execution.execute_stage` — completed, refused,
held, crashed — as literal states, literal audit sequences and literal refusal text. Every expected
value below is written out rather than recomputed from the module under test: a test that asks
``execute_stage`` what it did cannot detect ``execute_stage``.

The load-bearing orderings, each with its own case:

* the start gate is checked **before** the run record is written — a refused stage leaves no run
  record at all, because nothing was about to happen and there is nothing to reproduce;
* the run record is written **before** the runner is called — a crashed stage leaves one, because
  there was, and the record says under which pinned inputs;
* the transition is performed **after** the runner returns — a crashed stage leaves the state where
  it was.
"""

import pytest

from phase0 import governance as gov
from phase0.errors import StageNotCompleted
from phase0.execution import (
    COMPLETED,
    CRASHED,
    HELD,
    MANUAL_TRANSITIONS,
    REFUSED,
    STAGE_AUTHORITY,
    companion_stages,
    execute_stage,
    wire,
)
from phase0.preconditions import PRECONDITION_KEYS
from phase0.runs import STAGES
from phase0.seeds import derive_child_seed

COMMIT = "abc1234"
SNAPSHOT = "dune-2026-07-31"

#: ``new_master_seed(entropy="fixed-for-test")``. Written out so a change to the derivation is a
#: failure rather than a silently different number.
FIXED_MASTER_SEED = "0fcc1123113d55052444ed4939f2c3bd6975fc57b7855c58b116a0e929b90968"

#: ``derive_child_seed(FIXED_MASTER_SEED, "abc1234", "null.leader.window1", 0)``.
FIXED_CHILD_SEED = (
    40779456037990887603260200485097951287016898647870486619633624091610815767726
)


@pytest.fixture
def w(tmp_path):
    return wire(str(tmp_path / "state"))


def satisfy_preconditions(w, requester="Research Owner"):
    for key in PRECONDITION_KEYS:
        w.preconditions.record(key, "recorded-for-test", requester)
    return w


class Spy(object):
    """A trivial injected runner that records that it was called.

    ``phase0`` is SHARED and cannot import a builder package, so it takes the runner as an
    argument and never learns what a stage does. Every runner in this file is therefore a stand-in,
    and the only thing the tests ever assert about one is whether it ran.
    """

    def __init__(self, value="ok", raises=None, before_returning=None):
        self.value = value
        self.raises = raises
        self.before_returning = before_returning
        self.calls = 0
        self.contexts = []

    def __call__(self, context):
        self.calls += 1
        self.contexts.append(context)
        if self.before_returning is not None:
            self.before_returning(context)
        if self.raises is not None:
            raise self.raises
        return self.value


def run(w, stage, runner=None, requester="primary-builder", commit=COMMIT,
        snapshot=SNAPSHOT, config=None, master_seed=None):
    return execute_stage(
        stage, runner if runner is not None else Spy(), requester,
        governance=w.governance, preconditions=w.preconditions, runs=w.runs, audit=w.audit,
        commit=commit, dataset_snapshot=snapshot, config=config, master_seed=master_seed,
    )


def actions(w):
    return [e.action for e in w.audit.entries()]


def advance_to(w, target, requester="Research Owner"):
    """Walk the governance chain by hand, for tests that need the run to start somewhere."""
    start = gov.position(w.governance.state) + 1
    for state in gov.ORDER[start:gov.position(target) + 1]:
        w.governance.transition(state, requester)
    return w


# -- the register itself --------------------------------------------------------
#
# The register is what makes ``execute_stage`` generic. If a stage can be absent from it, a stage
# can escape governance by omission, which is the same hole ``test_lane_independence`` closes for
# packages.


def test_every_stage_declares_its_governance_authority():
    undeclared = sorted(set(STAGES) - set(STAGE_AUTHORITY))
    assert not undeclared, (
        "these stages have no entry in STAGE_AUTHORITY: {}. An undeclared stage would run under "
        "no ordering rule at all.".format(", ".join(undeclared))
    )
    assert sorted(STAGE_AUTHORITY) == sorted(STAGES)


def test_every_state_after_the_first_is_either_earned_or_declared_manual():
    """No state may be reachable by neither route, and none by both.

    ``PARAMETERS_FROZEN`` and ``CODE_AND_DATA_FROZEN`` record human acts — a freeze is a decision,
    not a computation — so they are entered directly. Every other state is *earned* by a stage
    completing. A state that were both would let the chain be walked without anything running.
    """
    earned = {a.advances for a in STAGE_AUTHORITY.values() if a.advances is not None}
    manual = set(MANUAL_TRANSITIONS)

    assert earned == {
        gov.VALIDATION_PASSED,
        gov.NULL_COMPLETE,
        gov.THRESHOLD_LOCKED,
        gov.MAIN_TEST_EXECUTED,
        gov.DECISION_EMITTED,
    }
    assert manual == {gov.PARAMETERS_FROZEN, gov.CODE_AND_DATA_FROZEN}
    assert not (earned & manual)
    assert earned | manual == set(gov.ORDER[1:])


@pytest.mark.parametrize("stage", sorted(STAGE_AUTHORITY))
def test_an_advancing_stage_requires_the_state_immediately_before_its_target(stage):
    """Otherwise the authorisation check and the transition would disagree about what is legal."""
    authority = STAGE_AUTHORITY[stage]
    if authority.advances is None:
        pytest.skip("only advancing stages constrain their own floor")
    assert authority.requires == gov.ORDER[gov.position(authority.advances) - 1]


def test_the_two_null_stages_share_one_transition():
    assert companion_stages("null.leader") == ("null.follower", "null.leader")
    assert companion_stages("null.follower") == ("null.follower", "null.leader")
    assert companion_stages("main_test") == ("main_test",)
    assert companion_stages("pipeline.buy_quality") == ()


# -- the start gate, before anything is written ---------------------------------


def test_a_stage_is_refused_while_a_precondition_is_missing(w):
    w.preconditions.record("primary_builder", "A. Builder", "Research Owner")
    spy = Spy()

    result = run(w, "step0.universe", spy)

    assert result.status == REFUSED
    assert result.stage == "step0.universe"
    assert result.requester == "primary-builder"
    assert result.run_id is None
    assert result.advanced_to is None
    assert "Independent Validator assigned (ticket 02)" in result.reason
    assert "10-12 week capacity reserved (ticket 04)" in result.reason
    assert "Primary Builder" not in result.reason
    assert spy.calls == 0


def test_the_start_gate_is_checked_before_the_run_record_is_written(w):
    """A refused stage leaves no run record: nothing was about to happen."""
    result = run(w, "step0.universe")

    assert result.status == REFUSED
    assert w.runs.list_runs() == []
    assert actions(w) == ["stage.refused"]
    assert w.audit.entries()[0].requester == "primary-builder"
    assert w.audit.entries()[0].detail["stage"] == "step0.universe"
    assert w.audit.entries()[0].detail["run_id"] is None
    assert w.audit.verify()


def test_a_refused_stage_holds_the_governance_state_exactly(w):
    advance_to(w, gov.PARAMETERS_FROZEN)
    result = run(w, "step0.universe")

    assert result.status == REFUSED
    assert result.state_before == gov.PARAMETERS_FROZEN
    assert result.state_after == gov.PARAMETERS_FROZEN
    assert w.governance.state == gov.PARAMETERS_FROZEN


# -- governance ordering --------------------------------------------------------


def test_a_stage_out_of_order_is_refused_with_the_reason_governance_already_produces(w):
    satisfy_preconditions(w)
    spy = Spy()

    result = run(w, "main_test", spy)

    assert result.status == REFUSED
    assert spy.calls == 0
    assert result.reason == (
        "Refused transition PARAMETERS_OPEN -> MAIN_TEST_EXECUTED: out of order — "
        "PARAMETERS_FROZEN, VALIDATION_PASSED, CODE_AND_DATA_FROZEN, NULL_COMPLETE, "
        "THRESHOLD_LOCKED must complete first. the main test runs once, against a locked "
        "threshold; a threshold chosen after the result is not a threshold"
    )
    assert result.error_type == "TransitionError"


def test_a_non_advancing_stage_is_refused_below_its_floor(w):
    """``step0.universe`` completes no transition, so its refusal names the floor it needs."""
    satisfy_preconditions(w)

    result = run(w, "step0.universe")

    assert result.status == REFUSED
    assert result.reason == (
        "Refused transition PARAMETERS_OPEN -> Stage step0.universe: out of order — "
        "PARAMETERS_FROZEN must complete first. the parameter set must be open and complete "
        "before it can be frozen"
    )


def test_a_completed_stage_advances_exactly_one_state(w):
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")

    result = run(w, "validation.independent")

    assert result.status == COMPLETED
    assert result.state_before == gov.PARAMETERS_FROZEN
    assert result.state_after == gov.VALIDATION_PASSED
    assert result.advanced_to == gov.VALIDATION_PASSED
    assert result.pending == ()
    assert w.governance.state == gov.VALIDATION_PASSED


def test_a_build_lane_stage_completes_without_moving_the_state(w):
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")

    result = run(w, "pipeline.buy_quality")

    assert result.status == COMPLETED
    assert result.advanced_to is None
    assert result.state_after == gov.PARAMETERS_FROZEN


def test_a_build_lane_stage_may_run_again_and_an_execution_lane_stage_may_not(w):
    """The retry policy the orchestration guide sets per lane, made mechanical.

    A build-lane stage is bounded by a floor, so it may be re-run. An execution-lane stage *is* a
    transition, and a transition into a state already occupied is refused — so ticket 42's "runs
    once" needs no separate rule.
    """
    satisfy_preconditions(w)
    advance_to(w, gov.THRESHOLD_LOCKED)

    assert run(w, "pipeline.buy_quality").status == COMPLETED
    assert run(w, "pipeline.buy_quality").status == COMPLETED

    assert run(w, "main_test").status == COMPLETED
    second = run(w, "main_test")
    assert second.status == REFUSED
    assert second.reason == (
        "Refused transition MAIN_TEST_EXECUTED -> MAIN_TEST_EXECUTED: already in this state"
    )


# -- the run record, before the runner ------------------------------------------


def test_the_run_record_exists_by_the_time_the_runner_is_called(w):
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")
    seen = {}

    def inspect(context):
        record = w.runs.get(context.run_id)
        seen["record"] = record.to_dict() if record is not None else None
        return "ok"

    result = run(w, "step0.universe", Spy(before_returning=inspect),
                 config={"window": 1, "min_valid_buys": 20})

    assert result.status == COMPLETED
    assert seen["record"] is not None, "the run record must be on disk before the runner runs"
    assert seen["record"]["stage"] == "step0.universe"
    assert seen["record"]["commit"] == COMMIT
    assert seen["record"]["dataset_snapshot"] == SNAPSHOT
    assert seen["record"]["requester"] == "primary-builder"
    assert seen["record"]["seed_rule"].startswith("child_seed = HMAC-SHA256")


def test_the_context_carries_the_pinned_inputs_and_no_way_to_move_the_run(w):
    """The runner is handed what it needs to reproduce itself and nothing that decides."""
    satisfy_preconditions(w)
    advance_to(w, gov.CODE_AND_DATA_FROZEN)
    spy = Spy()

    assert run(w, "null.leader", spy, master_seed=FIXED_MASTER_SEED).status == COMPLETED
    context = spy.contexts[0]

    assert context.stage == "null.leader"
    assert context.commit == COMMIT
    assert context.dataset_snapshot == SNAPSHOT
    assert context.master_seed == FIXED_MASTER_SEED
    assert context.requester == "primary-builder"
    assert context.child_seed("null.leader.window1", 0) == FIXED_CHILD_SEED
    assert context.child_seed("null.leader.window1", 0) == derive_child_seed(
        FIXED_MASTER_SEED, COMMIT, "null.leader.window1", 0
    )

    for forbidden in ("governance", "transition", "advance", "halt", "record_gate_outcome"):
        assert not hasattr(context, forbidden), (
            "the stage context exposes {!r}; a runner that can move the state machine is a "
            "runner that can authorise itself".format(forbidden)
        )


def test_the_context_config_is_a_copy(w):
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")
    config = {"window": 1}
    spy = Spy()

    run(w, "step0.universe", spy, config=config)
    spy.contexts[0].config["window"] = 999

    assert config == {"window": 1}


# -- crash ----------------------------------------------------------------------


def test_a_crashing_runner_leaves_the_record_and_does_not_advance_the_state(w):
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")
    boom = RuntimeError("the swap decoder does not know this router")

    result = run(w, "validation.independent", Spy(raises=boom))

    assert result.status == CRASHED
    assert result.error is boom
    assert result.error_type == "RuntimeError"
    assert result.reason == "RuntimeError: the swap decoder does not know this router"
    assert result.advanced_to is None
    assert result.state_before == gov.PARAMETERS_FROZEN
    assert result.state_after == gov.PARAMETERS_FROZEN
    assert w.governance.state == gov.PARAMETERS_FROZEN

    records = w.runs.list_runs()
    assert len(records) == 1
    assert records[0].stage == "validation.independent"
    assert records[0].commit == COMMIT
    assert records[0].dataset_snapshot == SNAPSHOT
    assert records[0].run_id == result.run_id


def test_a_crash_is_audited_in_exactly_this_order(w):
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")

    run(w, "validation.independent", Spy(raises=ValueError("bad price")))

    assert actions(w) == [
        "precondition.record",
        "precondition.record",
        "precondition.record",
        "precondition.record",
        "governance.transition",
        "run.open",
        "stage.crashed",
    ]
    last = w.audit.entries()[-1]
    assert last.requester == "primary-builder"
    assert last.detail["stage"] == "validation.independent"
    assert last.detail["error_type"] == "ValueError"
    assert last.detail["reason"] == "ValueError: bad price"
    assert last.detail["state"] == gov.PARAMETERS_FROZEN
    assert w.audit.verify()


def test_a_crashed_stage_publishes_no_value(w):
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")

    result = run(w, "step0.universe", Spy(raises=RuntimeError("boom")))

    assert not result.completed
    with pytest.raises(StageNotCompleted) as exc:
        result.value
    assert "step0.universe" in str(exc.value)
    assert CRASHED in str(exc.value)


def test_a_keyboard_interrupt_is_recorded_and_re_raised(w):
    """Evidence for any abrupt exit; control-flow exceptions are still not swallowed."""
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")

    with pytest.raises(KeyboardInterrupt):
        run(w, "step0.universe", Spy(raises=KeyboardInterrupt()))

    assert actions(w)[-1] == "stage.crashed"
    assert w.audit.entries()[-1].detail["error_type"] == "KeyboardInterrupt"
    assert len(w.runs.list_runs()) == 1
    assert w.governance.state == gov.PARAMETERS_FROZEN


# -- halt -----------------------------------------------------------------------


def test_halt_before_a_stage_refuses_it_and_never_calls_the_runner(w):
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")
    w.governance.halt("ops", "infrastructure failure")
    spy = Spy()

    result = run(w, "validation.independent", spy)

    assert result.status == REFUSED
    assert spy.calls == 0
    assert w.runs.list_runs() == []
    assert result.reason == (
        "Run is HALTED by operations. Stage validation.independent is refused until it is "
        "resumed. A halt holds state; it does not advance, revert, or change anything."
    )


def test_halt_mid_stage_holds_the_outcome_without_advancing(w):
    """The runner finishes; the halt arrives while it is running; nothing is committed."""
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")
    spy = Spy(value="a validated answer",
              before_returning=lambda ctx: w.governance.halt("ops", "security"))

    result = run(w, "validation.independent", spy)

    assert spy.calls == 1
    assert result.status == HELD
    assert result.advanced_to is None
    assert result.state_before == gov.PARAMETERS_FROZEN
    assert result.state_after == gov.PARAMETERS_FROZEN
    assert w.governance.state == gov.PARAMETERS_FROZEN
    assert "HALTED" in result.reason

    with pytest.raises(StageNotCompleted):
        result.value

    assert actions(w)[-1] == "stage.held"
    assert w.audit.entries()[-1].requester == "primary-builder"
    assert w.audit.entries()[-1].detail["run_id"] == result.run_id


def test_a_halt_arriving_mid_stage_cannot_mutate_a_recorded_result(w):
    """The gate outcome written before the halt is exactly the gate outcome after it."""
    satisfy_preconditions(w)
    advance_to(w, gov.MAIN_TEST_EXECUTED)
    w.governance.record_gate_outcome(gov.GATE_STOP, "governance")

    result = run(w, "decision.emit",
                 Spy(before_returning=lambda ctx: w.governance.halt("ops", "held")))

    assert result.status == HELD
    assert w.governance.gate_outcome == gov.GATE_STOP
    assert w.governance.state == gov.MAIN_TEST_EXECUTED


def test_an_invalidation_arriving_mid_stage_also_holds_the_outcome(w):
    """The condition is 'governance no longer authorises this', not 'someone pressed halt'."""
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")
    spy = Spy(before_returning=lambda ctx: w.governance.invalidate(
        "independent-validator", "FIFO lot matching was wrong for partial sells"))

    result = run(w, "validation.independent", spy)

    assert result.status == HELD
    assert result.advanced_to is None
    assert w.governance.state == gov.PARAMETERS_FROZEN
    assert "INVALIDATED" in result.reason


def test_an_invalidated_run_refuses_a_stage_outright(w):
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")
    w.governance.invalidate("independent-validator", "netting dropped fee-on-transfer legs")
    spy = Spy()

    result = run(w, "validation.independent", spy)

    assert result.status == REFUSED
    assert spy.calls == 0
    assert "INVALIDATED" in result.reason
    assert w.runs.list_runs() == []


# -- one transition, two stages -------------------------------------------------


def test_neither_null_stage_advances_null_complete_on_its_own(w):
    satisfy_preconditions(w)
    advance_to(w, gov.CODE_AND_DATA_FROZEN)

    leader = run(w, "null.leader")
    assert leader.status == COMPLETED
    assert leader.advanced_to is None
    assert leader.pending == ("null.follower",)
    assert w.governance.state == gov.CODE_AND_DATA_FROZEN

    follower = run(w, "null.follower")
    assert follower.status == COMPLETED
    assert follower.advanced_to == gov.NULL_COMPLETE
    assert follower.pending == ()
    assert w.governance.state == gov.NULL_COMPLETE


def test_the_order_of_the_two_null_stages_does_not_matter(w):
    satisfy_preconditions(w)
    advance_to(w, gov.CODE_AND_DATA_FROZEN)

    assert run(w, "null.follower").advanced_to is None
    assert run(w, "null.leader").advanced_to == gov.NULL_COMPLETE
    assert w.governance.state == gov.NULL_COMPLETE


def test_a_crashed_null_stage_does_not_count_toward_the_transition(w):
    satisfy_preconditions(w)
    advance_to(w, gov.CODE_AND_DATA_FROZEN)

    assert run(w, "null.leader", Spy(raises=RuntimeError("out of memory"))).status == CRASHED
    follower = run(w, "null.follower")

    assert follower.advanced_to is None
    assert follower.pending == ("null.leader",)
    assert w.governance.state == gov.CODE_AND_DATA_FROZEN


def test_registering_a_new_code_version_discards_earlier_stage_completions(w):
    """A re-run after an invalidation is a new experiment, and its null starts from nothing."""
    satisfy_preconditions(w)
    advance_to(w, gov.CODE_AND_DATA_FROZEN)
    assert run(w, "null.leader").status == COMPLETED

    w.governance.invalidate("independent-validator", "bug found after the freeze")
    w.governance.register_code_version("def5678", "primary-builder")
    advance_to(w, gov.CODE_AND_DATA_FROZEN)

    follower = run(w, "null.follower", commit="def5678")
    assert follower.advanced_to is None, "the pre-invalidation null.leader must not count"
    assert follower.pending == ("null.leader",)


# -- the audit records every outcome --------------------------------------------


@pytest.mark.parametrize("outcome,expected_action", [
    ("refused", "stage.refused"),
    ("completed", "stage.completed"),
    ("held", "stage.held"),
    ("crashed", "stage.crashed"),
])
def test_every_outcome_appends_to_the_audit_with_its_requester(tmp_path, outcome,
                                                               expected_action):
    w = wire(str(tmp_path / "state"))
    if outcome != "refused":
        satisfy_preconditions(w)
        w.governance.freeze_parameters("Research Owner")

    runner = Spy()
    if outcome == "held":
        runner = Spy(before_returning=lambda ctx: w.governance.halt("ops", "security"))
    elif outcome == "crashed":
        runner = Spy(raises=RuntimeError("boom"))

    before = len(w.audit.entries())
    run(w, "validation.independent", runner, requester="agent-7")
    entries = w.audit.entries()[before:]

    assert entries[-1].action == expected_action
    assert entries[-1].requester == "agent-7"
    assert entries[-1].detail["stage"] == "validation.independent"
    assert entries[-1].ts
    assert w.audit.verify()


def test_a_completed_stage_records_what_it_advanced(w):
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")

    result = run(w, "validation.independent", requester="independent-validator")

    entry = w.audit.entries()[-1]
    assert entry.action == "stage.completed"
    assert entry.detail["advanced_to"] == gov.VALIDATION_PASSED
    assert entry.detail["run_id"] == result.run_id
    assert entry.detail["pending"] == []

    transition = w.audit.entries()[-2]
    assert transition.action == "governance.transition"
    assert transition.detail["to"] == gov.VALIDATION_PASSED
    assert transition.detail["run_id"] == result.run_id, (
        "the transition belongs to the run record the stage opened, not to whatever run_id the "
        "machine was constructed with"
    )


# -- programming errors are not governance refusals -----------------------------


def test_an_unknown_stage_is_a_programming_error(w):
    satisfy_preconditions(w)
    with pytest.raises(ValueError) as exc:
        run(w, "just.try.it")
    assert "just.try.it" in str(exc.value)
    assert w.audit.entries()[-1].action == "precondition.record"


def test_a_runner_that_is_not_callable_is_a_programming_error(w):
    satisfy_preconditions(w)
    with pytest.raises(TypeError):
        run(w, "step0.universe", runner="not a function")


def test_a_stage_must_name_its_requester(w):
    satisfy_preconditions(w)
    for bad in ("", "   "):
        with pytest.raises(ValueError):
            run(w, "step0.universe", requester=bad)


# -- the result object ----------------------------------------------------------


def test_a_completed_result_publishes_its_value(w):
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")

    result = run(w, "step0.universe", Spy(value={"wallets": 812}))

    assert result.completed
    assert result.value == {"wallets": 812}
    assert result.raise_for_status() is result


@pytest.mark.parametrize("status", [REFUSED, HELD, CRASHED])
def test_no_uncompleted_status_publishes_a_value(tmp_path, status):
    """The guard is on the condition — 'this stage did not complete' — not on one status.

    A caller that reads ``.value`` without reading ``.status`` is the failure mode; making each
    non-completed outcome raise means there is no status for which that caller silently gets
    ``None``.
    """
    w = wire(str(tmp_path / "state"))
    runner = Spy()
    if status is REFUSED:
        pass  # preconditions unmet
    else:
        satisfy_preconditions(w)
        w.governance.freeze_parameters("Research Owner")
        if status is HELD:
            runner = Spy(before_returning=lambda ctx: w.governance.halt("ops", "security"))
        else:
            runner = Spy(raises=RuntimeError("boom"))

    result = run(w, "validation.independent", runner)

    assert result.status == status
    assert not result.completed
    with pytest.raises(StageNotCompleted):
        result.value
    with pytest.raises(StageNotCompleted):
        result.raise_for_status()


def test_the_result_serialises_without_the_value(w):
    """A stage's output is the lane's business; the governance record is not a place to put it."""
    satisfy_preconditions(w)
    w.governance.freeze_parameters("Research Owner")

    result = run(w, "step0.universe", Spy(value={"secret": "payload"}))
    payload = result.to_dict()

    assert payload["stage"] == "step0.universe"
    assert payload["status"] == COMPLETED
    assert payload["run_id"] == result.run_id
    assert "value" not in payload
    assert "payload" not in repr(payload)
