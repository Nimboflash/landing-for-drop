"""Ticket 02 wired to the stage list and the command line.

``NOT INDEPENDENT`` has to block the main test *through governance*, not through a note in a
report. The mechanism is small and worth stating: ``validation.independent`` is the only stage that
advances ``VALIDATION_PASSED``, ``VALIDATION_PASSED`` gates ``CODE_AND_DATA_FROZEN``, and that
gates the five execution-lane stages. So refusing the validation-gated stages when the recorded
validator does not reach an independent status blocks the main test by the machine's own ordering
rather than by a second rule that could disagree with the first.

The build lane is deliberately *not* refused. The validator's own golden-set work is a build-lane
stage, and a register that refused it would refuse the validator the work that earns the status.
"""

import pytest

from contracts.core import ValidationStatus
from phase0 import governance as gov
from phase0.cli import main
from phase0.errors import NotIndependentError, StageNotCompleted
from phase0.execution import (
    COMPLETED,
    REFUSED,
    STAGE_AUTHORITY,
    VALIDATION_GATED_STAGES,
    execute_stage,
    wire,
)
from phase0.preconditions import PRECONDITION_KEYS
from phase0.validator import AI_AGENT, HUMAN, PART_TIME, REQUIRED_SCOPE, ValidatorAssignment

COMMIT = "abc1234"
SNAPSHOT = "dune-2026-07-31"
PROJECT_START = "2026-01-05"


def assignment(kind=HUMAN, **over):
    kwargs = dict(
        name="V. Alidator" if kind == HUMAN else "Validator Agent V",
        kind=kind, start_date="2026-01-07", project_start=PROJECT_START,
        commitment=PART_TIME, covers=REQUIRED_SCOPE,
        accountable_human=None if kind == HUMAN else "R. Owner",
    )
    kwargs.update(over)
    return ValidatorAssignment(**kwargs)


@pytest.fixture
def w(tmp_path):
    state = wire(str(tmp_path / "state"))
    for key in PRECONDITION_KEYS:
        state.preconditions.record(key, "recorded-for-test", "Research Owner")
    return state


def run(w, stage, requester="primary-builder"):
    return execute_stage(
        stage, lambda context: "ok", requester,
        governance=w.governance, preconditions=w.preconditions, runs=w.runs, audit=w.audit,
        commit=COMMIT, dataset_snapshot=SNAPSHOT, config={},
    )


def advance_to(w, target, requester="Research Owner"):
    start = gov.position(w.governance.state) + 1
    for state in gov.ORDER[start:gov.position(target) + 1]:
        w.governance.transition(state, requester)
    return w


# -- which stages stand on the validation gate ----------------------------------

def test_the_gated_stages_are_the_five_execution_lane_stages_and_the_gate_itself():
    assert VALIDATION_GATED_STAGES == (
        "decision.emit",
        "main_test",
        "null.follower",
        "null.leader",
        "threshold.calibrate",
        "validation.independent",
    )


def test_no_build_lane_stage_is_gated():
    build_lane = sorted(name for name, authority in STAGE_AUTHORITY.items()
                        if authority.advances is None)
    assert build_lane == [
        "benchmark.match", "follower.adjust", "golden_set.trace", "known_answer.battery",
        "pipeline.buy_quality", "reconciliation.cross_source", "step0.universe",
    ]
    assert not set(build_lane) & set(VALIDATION_GATED_STAGES), (
        "the validator's own golden-set work is a build-lane stage; refusing it would refuse the "
        "validator the work that earns the status")


def test_the_gate_stage_is_the_only_one_that_advances_validation_passed():
    advancing = [name for name, a in STAGE_AUTHORITY.items()
                 if a.advances == gov.VALIDATION_PASSED]
    assert advancing == ["validation.independent"]


# -- a NOT INDEPENDENT validator blocks the main test ---------------------------

def test_a_not_independent_validator_refuses_the_gate_stage(w):
    w.preconditions.record_validator(assignment(HUMAN), "R. Owner")
    advance_to(w, gov.PARAMETERS_FROZEN)

    result = run(w, "validation.independent")

    assert result.status == REFUSED
    assert "validation status is NOT INDEPENDENT" in result.reason
    assert result.error_type == "NotIndependentError"
    assert w.governance.state == gov.PARAMETERS_FROZEN, "nothing advanced"


def test_a_refused_stage_leaves_no_run_record(w):
    """Same invariant as the start gate: nothing was about to happen, so nothing is on disk."""
    w.preconditions.record_validator(assignment(HUMAN), "R. Owner")
    advance_to(w, gov.PARAMETERS_FROZEN)

    result = run(w, "validation.independent")

    assert result.run_id is None
    assert w.runs.list_runs() == []


def test_every_gated_stage_is_refused(w):
    w.preconditions.record_validator(assignment(HUMAN), "R. Owner")
    advance_to(w, gov.PARAMETERS_FROZEN)

    for stage in VALIDATION_GATED_STAGES:
        assert run(w, stage).status == REFUSED, stage


def test_the_main_test_is_unreachable_because_the_gate_stage_is(w):
    """The block is the machine's own ordering, not a second rule about ``main_test``."""
    w.preconditions.record_validator(assignment(HUMAN), "R. Owner")
    advance_to(w, gov.PARAMETERS_FROZEN)

    assert run(w, "validation.independent").status == REFUSED
    assert w.governance.state == gov.PARAMETERS_FROZEN
    # and with VALIDATION_PASSED never reached, main_test is out of order as well as refused
    result = run(w, "main_test")
    assert result.status == REFUSED
    with pytest.raises(StageNotCompleted):
        result.value


def test_a_build_lane_stage_still_runs_under_a_not_independent_validator(w):
    w.preconditions.record_validator(assignment(HUMAN), "R. Owner")
    advance_to(w, gov.PARAMETERS_FROZEN)

    assert run(w, "golden_set.trace").status == COMPLETED
    assert run(w, "reconciliation.cross_source").status == COMPLETED


# -- the two statuses that do not block -----------------------------------------

def test_a_machine_independent_validator_does_not_block_the_gate_stage(w):
    w.preconditions.record_validator(assignment(AI_AGENT), "R. Owner")
    advance_to(w, gov.PARAMETERS_FROZEN)

    result = run(w, "validation.independent")

    assert result.status == COMPLETED
    assert result.advanced_to == gov.VALIDATION_PASSED


def test_booking_the_review_unblocks_a_human_validator(w):
    from phase0.validator import ExternalSpecialistReview

    w.preconditions.record_validator(assignment(HUMAN), "R. Owner")
    advance_to(w, gov.PARAMETERS_FROZEN)
    assert run(w, "validation.independent").status == REFUSED

    w.preconditions.book_external_review(
        ExternalSpecialistReview("S. Pecialist", 12, "2026-02-01"), "R. Owner")

    assert w.preconditions.validation_status() is ValidationStatus.EXTERNALLY_REVIEWED
    assert run(w, "validation.independent").status == COMPLETED


def test_an_empty_register_does_not_refuse_and_the_report_says_so(w):
    """The stated residue: no ticket-02 record means the check has nothing to refuse on."""
    assert w.preconditions.independence_refusal("stage main_test") is None
    advance_to(w, gov.PARAMETERS_FROZEN)
    assert run(w, "validation.independent").status == COMPLETED

    report = "\n".join(w.preconditions.validator_report())
    assert "UNASSIGNED" in report
    assert "NOT INDEPENDENT — the main test is BLOCKED" in report


def test_the_refusal_is_a_phase0_error_the_command_line_prints(w):
    w.preconditions.record_validator(assignment(HUMAN), "R. Owner")
    advance_to(w, gov.PARAMETERS_FROZEN)
    refusal = w.preconditions.independence_refusal("stage main_test")
    assert isinstance(NotIndependentError(refusal), Exception)
    assert "governed stage list refusing" in refusal


# -- phase0 status ---------------------------------------------------------------

def test_status_reports_the_validator_alongside_the_other_three(tmp_path, capsys):
    root = str(tmp_path / "state")
    assert main(["--root", root, "status"]) == 0
    out = capsys.readouterr().out

    assert "Independent Validator assigned" in out, "still one of the four §15.4 lines"
    assert "Independent Validator (ticket 02)" in out
    assert "independent_validator        UNASSIGNED" in out
    assert "validation status today      NOT INDEPENDENT — the main test is BLOCKED" in out
    assert "UNASSIGNED is not a state this code can leave on its own" in out
    assert "No pipeline stage may run" in out
    for ticket in ("01", "02", "03", "04"):
        assert "[ ] {}".format(ticket) in out


def test_status_after_recording_an_ai_validator_says_machine_independent(tmp_path, capsys):
    root = str(tmp_path / "state")
    assert main(["--root", root, "record-validator",
                 "--name", "Validator Agent V", "--kind", "AI_AGENT",
                 "--start-date", "2026-01-07", "--project-start", PROJECT_START,
                 "--commitment", "PART_TIME", "--accountable-human", "R. Owner",
                 "--requester", "R. Owner"]) == 0
    capsys.readouterr()

    main(["--root", root, "status"])
    out = capsys.readouterr().out

    assert "independent_validator        ASSIGNED" in out
    assert "validation status today      MACHINE-INDEPENDENT" in out
    assert "NOT BOOKED — A COST TO PAY, NOT AN OPTION TO CONSIDER" in out
    assert "CORRELATED errors" in out
    assert "No pipeline stage may run" in out, "one precondition does not start the project"


def test_status_after_booking_the_review_says_externally_reviewed(tmp_path, capsys):
    root = str(tmp_path / "state")
    main(["--root", root, "record-validator",
          "--name", "Validator Agent V", "--kind", "AI_AGENT",
          "--start-date", "2026-01-07", "--project-start", PROJECT_START,
          "--commitment", "PART_TIME", "--accountable-human", "R. Owner",
          "--requester", "R. Owner"])
    assert main(["--root", root, "book-external-review", "--specialist", "S. Pecialist",
                 "--accounts", "12", "--booked-on", "2026-02-01",
                 "--requester", "R. Owner"]) == 0
    capsys.readouterr()

    main(["--root", root, "status"])
    out = capsys.readouterr().out

    assert "validation status today      EXTERNALLY REVIEWED" in out
    assert "booked: S. Pecialist reviewing 12 complex accounts from 2026-02-01" in out


def test_the_command_line_cannot_record_a_sign_off_only_commitment(tmp_path):
    root = str(tmp_path / "state")
    with pytest.raises(ValueError) as exc:
        main(["--root", root, "record-validator",
              "--name", "V. Alidator", "--kind", "HUMAN",
              "--start-date", "2026-01-07", "--project-start", PROJECT_START,
              "--commitment", "PART_TIME", "--covers", "sign_off",
              "--requester", "R. Owner"])
    assert "brought in at the end to sign a report" in str(exc.value)


def test_the_command_line_cannot_record_a_late_validator(tmp_path):
    root = str(tmp_path / "state")
    with pytest.raises(ValueError) as exc:
        main(["--root", root, "record-validator",
              "--name", "V. Alidator", "--kind", "HUMAN",
              "--start-date", "2026-03-01", "--project-start", PROJECT_START,
              "--commitment", "PART_TIME", "--requester", "R. Owner"])
    assert "starts in week 1" in str(exc.value)


def test_the_command_line_has_no_default_name_or_kind(tmp_path):
    """Every field that would let the code leave UNASSIGNED on its own is required."""
    root = str(tmp_path / "state")
    for incomplete in (
        ["--kind", "HUMAN", "--start-date", "2026-01-07", "--project-start", PROJECT_START,
         "--commitment", "PART_TIME", "--requester", "R. Owner"],
        ["--name", "V. Alidator", "--start-date", "2026-01-07",
         "--project-start", PROJECT_START, "--commitment", "PART_TIME",
         "--requester", "R. Owner"],
        ["--name", "V. Alidator", "--kind", "HUMAN", "--project-start", PROJECT_START,
         "--commitment", "PART_TIME", "--requester", "R. Owner"],
        ["--name", "V. Alidator", "--kind", "HUMAN", "--start-date", "2026-01-07",
         "--commitment", "PART_TIME", "--requester", "R. Owner"],
    ):
        with pytest.raises(SystemExit):
            main(["--root", root, "record-validator"] + incomplete)
