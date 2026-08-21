"""Ticket 06 acceptance.

The headline requirement is "a rejection test exists for every out-of-order transition in the
matrix". Rather than hand-writing 57 cases and hoping none was missed, the matrix is generated
from ``ORDER`` — so the coverage is complete by construction and stays complete if a state is
ever added.
"""

import itertools

import pytest

from phase0 import governance as gov
from phase0.audit import AuditLog
from phase0.errors import (
    FrozenError, HaltedError, InvalidatedError, TransitionError,
)
from phase0.governance import GovernanceMachine

ORDER = gov.ORDER
VALID_STEPS = {(ORDER[i], ORDER[i + 1]) for i in range(len(ORDER) - 1)}
ALL_PAIRS = set(itertools.product(ORDER, ORDER))
INVALID_STEPS = sorted(ALL_PAIRS - VALID_STEPS)


@pytest.fixture
def machine(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    return GovernanceMachine(tmp_path / "governance.json", log, run_id="run-test")


def advance_to(machine, target, requester="test"):
    """Walk the legal path to ``target``."""
    for state in ORDER[1:gov.position(target) + 1]:
        machine.transition(state, requester)
    return machine


# -- the full rejection matrix -------------------------------------------------

@pytest.mark.parametrize("from_state,to_state", INVALID_STEPS)
def test_every_out_of_order_transition_is_rejected(tmp_path, from_state, to_state):
    log = AuditLog(tmp_path / "audit.jsonl")
    m = GovernanceMachine(tmp_path / "gov.json", log, run_id="r")
    advance_to(m, from_state)
    assert m.state == from_state

    with pytest.raises(TransitionError):
        m.transition(to_state, requester="someone")

    assert m.state == from_state, "a refused transition must not change state"


def test_matrix_covers_every_pair():
    """Guard the guard: the parametrisation really is the whole matrix."""
    assert len(ALL_PAIRS) == len(ORDER) ** 2 == 64
    assert len(VALID_STEPS) == 7
    assert len(INVALID_STEPS) == 57


def test_the_legal_path_runs_end_to_end(machine):
    for state in ORDER[1:]:
        assert machine.transition(state, "builder") == state
    assert machine.state == gov.DECISION_EMITTED


# -- the two load-bearing unreachability properties ---------------------------

def test_null_complete_is_unreachable_without_validation_passed(machine):
    machine.transition(gov.PARAMETERS_FROZEN, "owner")
    assert machine.state == gov.PARAMETERS_FROZEN

    with pytest.raises(TransitionError) as exc:
        machine.transition(gov.NULL_COMPLETE, "builder")

    assert gov.VALIDATION_PASSED in str(exc.value)
    assert machine.state == gov.PARAMETERS_FROZEN


def test_main_test_is_unreachable_without_threshold_locked(machine):
    advance_to(machine, gov.NULL_COMPLETE)

    with pytest.raises(TransitionError) as exc:
        machine.transition(gov.MAIN_TEST_EXECUTED, "builder")

    assert gov.THRESHOLD_LOCKED in str(exc.value)
    assert machine.state == gov.NULL_COMPLETE


def test_a_completed_stage_cannot_be_revisited(machine):
    advance_to(machine, gov.CODE_AND_DATA_FROZEN)
    with pytest.raises(TransitionError) as exc:
        machine.transition(gov.PARAMETERS_FROZEN, "builder")
    assert "one-way" in str(exc.value)


# -- parameter freeze ----------------------------------------------------------

def test_parameters_are_writable_before_the_freeze(machine):
    machine.write_parameter("mean_threshold_pp", 15, "owner")
    assert machine.parameters()["mean_threshold_pp"] == 15


def test_every_parameter_write_is_rejected_once_frozen(machine):
    machine.write_parameter("mean_threshold_pp", 15, "owner")
    machine.freeze_parameters("owner")

    with pytest.raises(FrozenError):
        machine.write_parameter("mean_threshold_pp", 24, "owner")


def test_even_a_widening_clarification_is_rejected_once_frozen(machine):
    """A clarification is indistinguishable from a result-driven edit, so both are refused."""
    machine.freeze_parameters("owner")
    with pytest.raises(FrozenError) as exc:
        machine.write_parameter("dead_pool_note", "clarify: 30 days means calendar days", "owner")
    assert "clarification" in str(exc.value)


def test_parameters_stay_frozen_for_the_rest_of_the_run(machine):
    advance_to(machine, gov.THRESHOLD_LOCKED)
    with pytest.raises(FrozenError):
        machine.write_parameter("anything", 1, "builder")


# -- gate outcome: write-once, no override ------------------------------------

def test_gate_outcome_cannot_be_written_before_the_main_test(machine):
    advance_to(machine, gov.THRESHOLD_LOCKED)
    with pytest.raises(TransitionError):
        machine.record_gate_outcome(gov.GATE_GO, "owner")


def test_gate_outcome_is_write_once(machine):
    advance_to(machine, gov.MAIN_TEST_EXECUTED)
    machine.record_gate_outcome(gov.GATE_STOP, "governance")
    assert machine.gate_outcome == gov.GATE_STOP

    with pytest.raises(FrozenError):
        machine.record_gate_outcome(gov.GATE_GO, "owner")

    assert machine.gate_outcome == gov.GATE_STOP


def test_a_failed_gate_cannot_be_reinterpreted_by_anyone(machine):
    """The requirement names 'a person or an AI agent'. Neither has a path."""
    advance_to(machine, gov.MAIN_TEST_EXECUTED)
    machine.record_gate_outcome(gov.GATE_STOP, "governance")

    for requester in ("Research Owner", "primary-builder-agent", "root", "ops"):
        with pytest.raises(FrozenError):
            machine.record_gate_outcome(gov.GATE_GO, requester)

    assert machine.gate_outcome == gov.GATE_STOP


def test_an_unknown_outcome_is_rejected(machine):
    advance_to(machine, gov.MAIN_TEST_EXECUTED)
    with pytest.raises(ValueError):
        machine.record_gate_outcome("PASSED_WITH_NOTES", "owner")


# -- halt ----------------------------------------------------------------------

def test_halt_stops_transitions_in_any_state(machine):
    for target in (gov.PARAMETERS_FROZEN, gov.VALIDATION_PASSED, gov.CODE_AND_DATA_FROZEN):
        machine.transition(target, "builder")
        machine.halt("ops", "infrastructure failure")
        with pytest.raises(HaltedError):
            machine.transition(ORDER[gov.position(target) + 1], "builder")
        machine.resume("ops", "restored")


def test_halt_does_not_change_state_or_results(machine):
    advance_to(machine, gov.MAIN_TEST_EXECUTED)
    machine.record_gate_outcome(gov.GATE_STOP, "governance")

    machine.halt("ops", "security")
    assert machine.state == gov.MAIN_TEST_EXECUTED
    assert machine.gate_outcome == gov.GATE_STOP

    machine.resume("ops", "cleared")
    assert machine.state == gov.MAIN_TEST_EXECUTED
    assert machine.gate_outcome == gov.GATE_STOP


def test_halt_cannot_be_used_to_write_a_result(machine):
    advance_to(machine, gov.MAIN_TEST_EXECUTED)
    machine.halt("ops", "held")
    with pytest.raises(HaltedError):
        machine.record_gate_outcome(gov.GATE_GO, "ops")


# -- invalidation --------------------------------------------------------------

def test_invalidated_run_blocks_every_transition(machine):
    advance_to(machine, gov.NULL_COMPLETE)
    machine.invalidate("validator", "FIFO lot matching was wrong for partial sells")

    with pytest.raises(InvalidatedError):
        machine.transition(gov.THRESHOLD_LOCKED, "builder")


def test_invalidated_run_blocks_parameter_writes_too(machine):
    machine.invalidate("validator", "bug")
    with pytest.raises(InvalidatedError):
        machine.write_parameter("k", 1, "owner")


def test_registering_a_new_code_version_rewinds_to_the_parameter_freeze(machine):
    advance_to(machine, gov.NULL_COMPLETE)
    machine.invalidate("validator", "netting dropped fee-on-transfer legs")

    state = machine.register_code_version("abc1234", "builder", note="fixed netting")

    assert state == gov.PARAMETERS_FROZEN
    assert not machine.invalidated
    assert machine.state == gov.PARAMETERS_FROZEN


def test_rewinding_does_not_reopen_the_parameter_set(machine):
    """Re-opening parameters after a result was seen is the one thing that must never happen."""
    advance_to(machine, gov.NULL_COMPLETE)
    machine.invalidate("validator", "bug")
    machine.register_code_version("abc1234", "builder")

    with pytest.raises(FrozenError):
        machine.write_parameter("mean_threshold_pp", 5, "owner")


def test_an_invalidated_run_discards_its_gate_outcome(machine):
    advance_to(machine, gov.MAIN_TEST_EXECUTED)
    machine.record_gate_outcome(gov.GATE_GO, "governance")
    machine.invalidate("validator", "bug found after the freeze")
    machine.register_code_version("def5678", "builder")

    assert machine.gate_outcome is None, "the old result must not survive an invalidation"


def test_code_version_cannot_be_registered_without_an_invalidation(machine):
    with pytest.raises(InvalidatedError):
        machine.register_code_version("abc1234", "builder")


# -- audit ---------------------------------------------------------------------

def test_every_transition_is_audited_with_requester_and_run(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    m = GovernanceMachine(tmp_path / "gov.json", log, run_id="run-42")
    m.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    entries = log.entries()
    assert len(entries) == 1
    assert entries[0].requester == "Research Owner"
    assert entries[0].detail["from"] == gov.PARAMETERS_OPEN
    assert entries[0].detail["to"] == gov.PARAMETERS_FROZEN
    assert entries[0].detail["run_id"] == "run-42"
    assert entries[0].ts
    log.verify()


def test_refused_transitions_do_not_pollute_the_audit_log(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    m = GovernanceMachine(tmp_path / "gov.json", log, run_id="r")
    with pytest.raises(TransitionError):
        m.transition(gov.MAIN_TEST_EXECUTED, "builder")
    assert len(log) == 0
