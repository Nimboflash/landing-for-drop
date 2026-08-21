"""A whole run, start to decision, driven only through governance.

The unit tests fix each rule. This fixes the thing the rules exist for: that the twelve weeks of
work can actually be walked from ``PARAMETERS_OPEN`` to ``DECISION_EMITTED`` without anyone being
able to skip a step, and that the audit log left behind is a complete and verifiable account of who
asked for what.

Three whole-run scenarios:

* **the clean run** — every stage in order, ending in a recorded gate outcome and a decision;
* **the invalidation drill** (ticket 39) — a bug found after the freeze rewinds the run to the
  parameter freeze, and the null it had already built no longer counts;
* **the halt** — operations stops a run mid-stage, nothing advances, and resuming lets it continue.

Plus the command line, where the refusal and the acceptance are both demonstrable.
"""

import json

import pytest

from phase0 import governance as gov
from phase0.cli import main
from phase0.errors import FrozenError, HaltedError, TransitionError
from phase0.execution import COMPLETED, CRASHED, HELD, REFUSED, execute_stage, wire
from phase0.preconditions import PRECONDITION_KEYS
from phase0.runs import STAGES

COMMIT = "abc1234"
SNAPSHOT = "dune-2026-07-31"

#: A whole Phase 0, in the order the tickets run it. The two freezes are human acts and are not
#: stages; everything else is earned.
SCRIPT = (
    ("freeze", gov.PARAMETERS_FROZEN),
    ("stage", "step0.universe"),
    ("stage", "golden_set.trace"),
    ("stage", "known_answer.battery"),
    ("stage", "pipeline.buy_quality"),
    ("stage", "benchmark.match"),
    ("stage", "follower.adjust"),
    ("stage", "reconciliation.cross_source"),
    ("stage", "validation.independent"),
    ("freeze", gov.CODE_AND_DATA_FROZEN),
    ("stage", "null.leader"),
    ("stage", "null.follower"),
    ("stage", "threshold.calibrate"),
    ("stage", "main_test"),
    ("gate", gov.GATE_STOP),
    ("stage", "decision.emit"),
)


@pytest.fixture
def w(tmp_path):
    state = wire(str(tmp_path / "state"))
    for key, who in zip(PRECONDITION_KEYS, ("A. Builder", "V. Alidator, contract #7",
                                            "PO-1234", "capacity reserved, weeks 1-12")):
        state.preconditions.record(key, who, "Research Owner")
    return state


def stage_runner(payload):
    """A trivial injected runner. ``phase0`` never learns what a stage does; neither does a test."""
    def runner(context):
        return dict(payload, stage=context.stage, run_id=context.run_id,
                    seed=context.child_seed("{}.window1".format(context.stage), 0))
    return runner


def run_stage(w, stage, runner=None, requester="primary-builder", commit=COMMIT):
    return execute_stage(
        stage, runner if runner is not None else stage_runner({}), requester,
        governance=w.governance, preconditions=w.preconditions, runs=w.runs, audit=w.audit,
        commit=commit, dataset_snapshot=SNAPSHOT, config={"stage": stage},
    )


def play(w, script, requester="primary-builder"):
    results = []
    for kind, argument in script:
        if kind == "freeze":
            w.governance.transition(argument, "Research Owner")
        elif kind == "gate":
            w.governance.record_gate_outcome(argument, "governance")
        else:
            results.append(run_stage(w, argument, requester=requester))
    return results


# -- the clean run ---------------------------------------------------------------


def test_a_whole_run_walks_from_open_to_decision(w):
    assert w.governance.state == gov.PARAMETERS_OPEN

    results = play(w, SCRIPT)

    assert [r.status for r in results] == [COMPLETED] * 13
    assert w.governance.state == gov.DECISION_EMITTED
    assert w.governance.gate_outcome == gov.GATE_STOP


def test_every_stage_in_the_run_left_exactly_one_run_record(w):
    play(w, SCRIPT)

    records = w.runs.list_runs()
    assert len(records) == 13
    assert sorted(r.stage for r in records) == sorted(STAGES)
    for record in records:
        assert record.commit == COMMIT
        assert record.dataset_snapshot == SNAPSHOT
        assert record.requester == "primary-builder"
        assert record.master_seed
        assert record.seed_rule.startswith("child_seed = HMAC-SHA256")


def test_the_audit_is_a_complete_and_verifiable_account_of_the_run(w):
    play(w, SCRIPT)

    assert w.audit.verify()
    entries = w.audit.entries()
    assert [e.seq for e in entries] == list(range(len(entries)))
    assert all(e.requester for e in entries)

    counts = {}
    for entry in entries:
        counts[entry.action] = counts.get(entry.action, 0) + 1

    assert counts == {
        "precondition.record": 4,
        "run.open": 13,
        "stage.completed": 13,
        # five earned by a stage, two freezes performed by hand
        "governance.transition": 7,
        "governance.gate_outcome": 1,
    }

    advanced = [e.detail["advanced_to"] for e in entries
                if e.action == "stage.completed" and e.detail["advanced_to"]]
    assert advanced == [
        gov.VALIDATION_PASSED,
        gov.NULL_COMPLETE,
        gov.THRESHOLD_LOCKED,
        gov.MAIN_TEST_EXECUTED,
        gov.DECISION_EMITTED,
    ]


def test_every_earned_transition_names_the_run_record_that_earned_it(w):
    results = play(w, SCRIPT)
    by_run = {r.run_id: r for r in results}

    for entry in w.audit.entries():
        if entry.action != "governance.transition":
            continue
        stage = entry.detail["detail"].get("stage")
        if stage is None:
            continue  # a freeze, performed by hand
        assert entry.detail["run_id"] in by_run
        assert by_run[entry.detail["run_id"]].stage == stage


def test_the_run_cannot_be_walked_without_the_stages(w):
    """Skipping a stage does not skip its transition — there is no other way to earn one."""
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    with pytest.raises(TransitionError):
        w.governance.transition(gov.CODE_AND_DATA_FROZEN, "someone-in-a-hurry")

    assert w.governance.state == gov.PARAMETERS_FROZEN
    assert run_stage(w, "main_test").status == REFUSED
    assert w.governance.state == gov.PARAMETERS_FROZEN


def test_the_main_test_cannot_be_run_a_second_time(w):
    play(w, SCRIPT[:SCRIPT.index(("gate", gov.GATE_STOP))])
    assert w.governance.state == gov.MAIN_TEST_EXECUTED

    again = run_stage(w, "main_test")

    assert again.status == REFUSED
    assert "already in this state" in again.reason
    assert len(w.runs.list_runs()) == 12, "a refused re-run opens no second record"


# -- the invalidation drill ------------------------------------------------------


def test_a_bug_found_after_the_freeze_rewinds_the_run_and_voids_its_null(w):
    play(w, SCRIPT[:SCRIPT.index(("stage", "threshold.calibrate"))])
    assert w.governance.state == gov.NULL_COMPLETE
    records_before = len(w.runs.list_runs())

    w.governance.invalidate("independent-validator", "FIFO was wrong for partial sells")
    assert run_stage(w, "threshold.calibrate").status == REFUSED

    w.governance.register_code_version("def5678", "primary-builder", note="fixed fifo")
    assert w.governance.state == gov.PARAMETERS_FROZEN

    # The null must be rebuilt from nothing: the completions recorded before the new code version
    # belong to a different experiment, exactly as its child seeds do.
    w.governance.transition(gov.VALIDATION_PASSED, "independent-validator")
    w.governance.transition(gov.CODE_AND_DATA_FROZEN, "Research Owner")

    leader = run_stage(w, "null.leader", commit="def5678")
    assert leader.advanced_to is None
    assert leader.pending == ("null.follower",)

    follower = run_stage(w, "null.follower", commit="def5678")
    assert follower.advanced_to == gov.NULL_COMPLETE

    assert len(w.runs.list_runs()) == records_before + 2
    assert w.audit.verify()


def test_the_run_record_of_a_crashed_stage_survives_the_invalidation_that_followed(w):
    """The evidence of what was about to run is what makes the invalidation legible later."""
    play(w, SCRIPT[:SCRIPT.index(("stage", "validation.independent"))])

    def explode(context):
        raise RuntimeError("the validator's expected outputs do not parse")

    crashed = run_stage(w, "validation.independent", explode)
    assert crashed.status == CRASHED

    w.governance.invalidate("independent-validator", "validator harness broken")
    w.governance.register_code_version("def5678", "primary-builder")

    record = w.runs.get(crashed.run_id)
    assert record is not None
    assert record.stage == "validation.independent"
    assert record.commit == COMMIT
    assert record.dataset_snapshot == SNAPSHOT
    assert w.audit.verify()


# -- the halt --------------------------------------------------------------------


def test_a_halt_holds_the_run_and_resuming_lets_it_continue(w):
    play(w, SCRIPT[:SCRIPT.index(("stage", "validation.independent"))])
    assert w.governance.state == gov.PARAMETERS_FROZEN

    def halt_then_finish(context):
        w.governance.halt("ops", "vendor credential rotated mid-run")
        return {"expected": "outputs"}

    held = run_stage(w, "validation.independent", halt_then_finish)
    assert held.status == HELD
    assert w.governance.state == gov.PARAMETERS_FROZEN

    assert run_stage(w, "validation.independent").status == REFUSED

    w.governance.resume("ops", "credential restored")
    resumed = run_stage(w, "validation.independent")

    assert resumed.status == COMPLETED
    assert resumed.advanced_to == gov.VALIDATION_PASSED
    assert w.governance.state == gov.VALIDATION_PASSED
    assert w.audit.verify()


def test_operations_can_hold_a_run_but_never_change_its_result(w):
    play(w, SCRIPT)
    assert w.governance.gate_outcome == gov.GATE_STOP

    w.governance.halt("ops", "we do not like this answer")
    assert w.governance.state == gov.DECISION_EMITTED
    assert w.governance.gate_outcome == gov.GATE_STOP

    with pytest.raises(HaltedError):
        w.governance.record_gate_outcome(gov.GATE_GO, "ops")

    w.governance.resume("ops", "cleared")
    with pytest.raises(FrozenError):
        w.governance.record_gate_outcome(gov.GATE_GO, "ops")

    assert w.governance.gate_outcome == gov.GATE_STOP
    assert w.audit.verify()


# -- the command line ------------------------------------------------------------


def satisfy_via_cli(root):
    for key in PRECONDITION_KEYS:
        main(["--root", root, "record-precondition", key, "recorded", "--requester", "owner"])


def test_the_command_line_refuses_a_stage_while_a_precondition_is_missing(tmp_path, capsys):
    root = str(tmp_path / "state")
    main(["--root", root, "record-precondition", "primary_builder", "A. Builder",
          "--requester", "owner"])

    code = main(["--root", root, "run", "step0.universe", "--requester", "builder",
                 "--commit", COMMIT, "--dataset-snapshot", SNAPSHOT])
    out = capsys.readouterr().out

    assert code == 2
    assert "REFUSED" in out
    assert "Independent Validator assigned (ticket 02)" in out
    assert "none written" in out


def test_the_command_line_refuses_a_stage_that_is_out_of_order(tmp_path, capsys):
    root = str(tmp_path / "state")
    satisfy_via_cli(root)

    code = main(["--root", root, "run", "main_test", "--requester", "builder",
                 "--commit", COMMIT, "--dataset-snapshot", SNAPSHOT])
    out = capsys.readouterr().out

    assert code == 2
    assert "REFUSED" in out
    assert "out of order" in out
    assert "a threshold chosen after the result is not a threshold" in out


def test_the_command_line_accepts_the_same_stage_once_governance_authorises_it(tmp_path, capsys):
    root = str(tmp_path / "state")
    satisfy_via_cli(root)
    assert main(["--root", root, "freeze", "PARAMETERS_FROZEN", "--requester", "owner"]) == 0

    code = main(["--root", root, "run", "step0.universe", "--requester", "builder",
                 "--commit", COMMIT, "--dataset-snapshot", SNAPSHOT])
    out = capsys.readouterr().out

    assert code == 0
    assert "COMPLETED  step0.universe" in out
    assert "PARAMETERS_FROZEN" in out

    runs = list((tmp_path / "state" / "runs").glob("*.json"))
    assert len(runs) == 1
    assert json.loads(runs[0].read_text())["stage"] == "step0.universe"


def test_the_command_line_reports_a_crash_without_advancing_the_run(tmp_path, capsys):
    root = str(tmp_path / "state")
    satisfy_via_cli(root)
    main(["--root", root, "freeze", "PARAMETERS_FROZEN", "--requester", "owner"])
    capsys.readouterr()

    code = main(["--root", root, "run", "validation.independent", "--requester", "builder",
                 "--commit", COMMIT, "--dataset-snapshot", SNAPSHOT,
                 "--crash", "the decoder does not know this router"])
    out = capsys.readouterr().out

    assert code == 4
    assert "CRASHED  validation.independent" in out
    assert "RuntimeError: the decoder does not know this router" in out
    assert len(list((tmp_path / "state" / "runs").glob("*.json"))) == 1

    main(["--root", root, "status"])
    assert "Governance state:  PARAMETERS_FROZEN" in capsys.readouterr().out


def test_the_command_line_reports_a_halt_arriving_mid_stage(tmp_path, capsys):
    root = str(tmp_path / "state")
    satisfy_via_cli(root)
    main(["--root", root, "freeze", "PARAMETERS_FROZEN", "--requester", "owner"])
    capsys.readouterr()

    code = main(["--root", root, "run", "validation.independent", "--requester", "ops",
                 "--commit", COMMIT, "--dataset-snapshot", SNAPSHOT, "--halt-mid-stage"])
    out = capsys.readouterr().out

    assert code == 3
    assert "HELD  validation.independent" in out
    assert "HALTED" in out

    main(["--root", root, "status"])
    status = capsys.readouterr().out
    assert "Operations:        HALTED" in status
    assert "Governance state:  PARAMETERS_FROZEN" in status


def test_the_command_line_offers_no_way_to_advance_the_run_by_hand(tmp_path, capsys):
    """``freeze`` takes the two human acts and nothing else; every other state must be earned."""
    root = str(tmp_path / "state")
    satisfy_via_cli(root)

    for state in (gov.VALIDATION_PASSED, gov.NULL_COMPLETE, gov.THRESHOLD_LOCKED,
                  gov.MAIN_TEST_EXECUTED, gov.DECISION_EMITTED):
        with pytest.raises(SystemExit):
            main(["--root", root, "freeze", state, "--requester", "someone-in-a-hurry"])
    capsys.readouterr()

    main(["--root", root, "status"])
    assert "Governance state:  PARAMETERS_OPEN" in capsys.readouterr().out


def test_the_command_line_audit_verifies_after_a_mixed_session(tmp_path, capsys):
    root = str(tmp_path / "state")
    satisfy_via_cli(root)
    main(["--root", root, "run", "step0.universe", "--requester", "builder",
          "--commit", COMMIT, "--dataset-snapshot", SNAPSHOT])
    main(["--root", root, "freeze", "PARAMETERS_FROZEN", "--requester", "owner"])
    main(["--root", root, "run", "step0.universe", "--requester", "builder",
          "--commit", COMMIT, "--dataset-snapshot", SNAPSHOT])
    main(["--root", root, "run", "step0.universe", "--requester", "builder",
          "--commit", COMMIT, "--dataset-snapshot", SNAPSHOT, "--crash", "boom"])
    capsys.readouterr()

    assert main(["--root", root, "audit"]) == 0
    out = capsys.readouterr().out

    assert "Hash chain verified over" in out
    assert "stage.refused" in out
    assert "stage.completed" in out
    assert "stage.crashed" in out
