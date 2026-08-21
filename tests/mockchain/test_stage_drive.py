"""Thirteen stages, driven on the synthetic source, and the exact point where the run stops.

``tests/integration/test_stage_runners.py`` walks the same thirteen with toy fixtures **and lifts
the validation gate by hand** to reach the five stages behind it. This file walks them on the
generated chain and does not lift anything, which is the whole question: how far does a run get when
nothing is permitted to claim that a person acted or that a gate passed?

The answer, pinned below: it reaches the validation gate and stops there. Five build-lane stages
complete, two blocked stages crash naming their tickets, and the six that would complete a Phase 0
transition are refused before a run record exists. That is where a real run stops too — for the same
reason, which is that ``src/groundtruth/`` does not exist.

**Two of these tests used to demonstrate an attack succeeding.** ``phase0.execute_stage`` is
public, so a caller who does not import ``tools/mockchain`` walked past every refusal in it and
reached ``VALIDATION_PASSED`` and then the whole execution lane. ``src/phase0/`` owns the rule now,
and those two tests pin the refusal firing for a caller that never heard of this package — plus the
one thing that is still open, which is that ``GovernanceMachine.transition`` can only check a
snapshot it is given and this driver deliberately withholds one. A test suite that only
demonstrated the refusals working would be a suite claiming a guarantee nobody makes.
"""

import json
import os

import pytest

from phase0 import governance as gov
from phase0.errors import NotAMeasurementError, TransitionError
from phase0.execution import COMPLETED, CRASHED, HELD, REFUSED, execute_stage
from phase0.runs import STAGES
from pipeline.stages import BLOCKED_STAGES, runner_for
from pipeline.stages.decide import StageBlocked

from tools.mockchain import generate_chain
from tools.mockchain.governance import GOVERNANCE_GAP, SyntheticRunRefused
from tools.mockchain.provenance import is_synthetic_snapshot
from tools.mockchain import stages as stage_module
from tools.mockchain.stages import (
    BEHIND_THE_GATE,
    REFUSED_BY_HARNESS,
    SYNTHETIC_COMMIT,
    confirm_blocked,
    drive_synthetic_phase0,
    synthetic_wiring,
    tripwire_runner,
)

from conftest import SEED


@pytest.fixture(scope="module")
def drive(tmp_path_factory, run):
    """One full drive, reusing the session's :func:`synthetic_report`. ~1.7s on top of it."""
    return drive_synthetic_phase0(SEED, tmp_path_factory.mktemp("drive"), run=run)


# -- the table -------------------------------------------------------------------


def test_every_one_of_the_thirteen_stages_is_requested_in_order(drive):
    assert tuple(o.stage for o in drive.outcomes) == STAGES


def test_the_stage_table_is_exactly_this(drive):
    """The claim the whole drive exists to make, pinned as literals rather than as a shape.

    Five of the ten live stages complete. ``validation.independent`` is live in the sense that it
    is not in ``BLOCKED_STAGES``... it is not: it is one of the three blocked ones, and it is here
    among the refused because the harness refuses it *before* its own blocker can speak. See
    :func:`test_the_blocked_stages_still_refuse_on_synthetic_data`.
    """
    assert drive.statuses == {
        "step0.universe": COMPLETED,
        "golden_set.trace": CRASHED,
        "known_answer.battery": COMPLETED,
        "pipeline.buy_quality": COMPLETED,
        "benchmark.match": COMPLETED,
        "follower.adjust": COMPLETED,
        "reconciliation.cross_source": CRASHED,
        "validation.independent": REFUSED_BY_HARNESS,
        "null.leader": REFUSED_BY_HARNESS,
        "null.follower": REFUSED_BY_HARNESS,
        "threshold.calibrate": REFUSED_BY_HARNESS,
        "main_test": REFUSED_BY_HARNESS,
        "decision.emit": REFUSED_BY_HARNESS,
    }


def test_each_stage_published_the_value_its_key_says(drive):
    """Measured from the run, then written down. Not recomputed from the code under test."""
    assert drive.outcome("step0.universe").value == (
        "4 windows measured, permits_ranking=False, "
        "insufficient: W1_2023H1, W2_2023H2, W3_2024H1, W4_2024H2"
    )
    assert drive.outcome("known_answer.battery").value == (
        "16/16 frozen cases pass, pass rate 1"
    )
    assert drive.outcome("pipeline.buy_quality").value == (
        "9 wallets scored, 1041 buys, 0 quarantined, 0 excluded"
    )
    assert drive.outcome("benchmark.match").value == "9 selected, 9 matched, 0 unmatched"
    assert drive.outcome("follower.adjust").value == "5 capital levels, 5 reportable"


def test_a_run_record_exists_for_every_stage_that_was_about_to_run_and_for_no_other(drive):
    """§05's ordering, observed rather than described.

    A stage refused before step 3 leaves no run record, because nothing was about to happen. A
    stage that crashed leaves one, because something was. ``None`` in this table is a fact.
    """
    assert {o.stage: o.run_id for o in drive.outcomes} == {
        "step0.universe": "synthetic-01",
        "golden_set.trace": "synthetic-02",
        "known_answer.battery": "synthetic-03",
        "pipeline.buy_quality": "synthetic-04",
        "benchmark.match": "synthetic-05",
        "follower.adjust": "synthetic-06",
        "reconciliation.cross_source": "synthetic-07",
        "validation.independent": None,
        "null.leader": None,
        "null.follower": None,
        "threshold.calibrate": None,
        "main_test": None,
        "decision.emit": None,
    }


# -- nothing advanced ------------------------------------------------------------


def test_the_synthetic_run_advances_nothing(drive):
    assert drive.final_state == gov.PARAMETERS_FROZEN
    assert [o.advanced_to for o in drive.outcomes] == [None] * len(STAGES)


def test_without_the_parameter_freeze_the_machine_refuses_every_stage(tmp_path, run):
    """What a synthetic run gets when it tells no lie about the human act.

    Every stage ``REFUSED`` at governance, no run record anywhere, nothing computed. The freeze is
    the fiction that buys the five completions in the table above, and this is what it bought.
    """
    honest = drive_synthetic_phase0(SEED, tmp_path / "honest", freeze_parameters=False, run=run)

    assert honest.final_state == gov.PARAMETERS_OPEN
    assert set(honest.statuses.values()) == {REFUSED, REFUSED_BY_HARNESS}
    assert [o.run_id for o in honest.outcomes] == [None] * len(STAGES)
    assert honest.outcome("pipeline.buy_quality").status == REFUSED
    assert "PARAMETERS_FROZEN" in honest.outcome("pipeline.buy_quality").reason


def test_the_fictions_are_carried_on_the_drive_and_not_buried(drive):
    assert len(drive.fictions) == 3
    joined = "\n".join(drive.fictions)
    assert "ticket 03 no data budget or vendor access" in joined
    assert "PARAMETERS_FROZEN is entered by hand" in joined
    assert "drawn from the seed" in joined


# -- the three blocked stages ----------------------------------------------------


def test_the_two_reachable_blocked_stages_crash_naming_their_tickets(drive):
    golden = drive.outcome("golden_set.trace")
    assert golden.status == CRASHED and golden.run_id is not None
    assert "ticket 03" in golden.reason
    assert "authenticated archival node" in golden.reason

    reconciliation = drive.outcome("reconciliation.cross_source")
    assert reconciliation.status == CRASHED
    for ticket in ("ticket 03", "ticket 12", "ticket 13"):
        assert ticket in reconciliation.reason


def test_the_blocked_stages_still_refuse_on_synthetic_data():
    """Synthetic data does not unblock a blocked stage, and this asks the runner directly.

    It has to ask the runner directly for ``validation.independent``: that stage completes
    ``VALIDATION_PASSED``, so the harness refuses it before ``execute_stage`` is ever called and its
    own blocker never gets to speak. The stage table records the harness's refusal for it, which is
    true and is not the whole truth.
    """
    assert sorted(BLOCKED_STAGES) == [
        "golden_set.trace", "reconciliation.cross_source", "validation.independent",
    ]
    for stage in BLOCKED_STAGES:
        blocked = confirm_blocked(stage)
        assert isinstance(blocked, StageBlocked)

    validation = str(confirm_blocked("validation.independent"))
    assert "ticket 02" in validation and "Independent Validator" in validation
    assert "ticket 36" in validation and "src/groundtruth/ does not exist" in validation


def test_a_blocked_stage_that_returned_a_value_would_be_reported_as_the_finding(monkeypatch):
    """:func:`confirm_blocked`'s own guard. A value from a blocked stage must never read as a pass."""
    monkeypatch.setattr(stage_module, "runner_for", lambda stage: (lambda context: 0))
    with pytest.raises(AssertionError) as raised:
        confirm_blocked("validation.independent")
    assert "returned 0 instead of refusing" in str(raised.value)


# -- where the chain stops -------------------------------------------------------


def test_the_five_execution_lane_stages_are_refused_before_a_runner_is_called(drive):
    assert BEHIND_THE_GATE == (
        "null.leader", "null.follower", "threshold.calibrate", "main_test", "decision.emit",
    )
    for stage in BEHIND_THE_GATE:
        outcome = drive.outcome(stage)
        assert outcome.status == REFUSED_BY_HARNESS
        assert outcome.run_id is None
        assert "may execute stages and record their outcomes" in outcome.reason


def test_the_tripwire_says_what_went_wrong_rather_than_returning_a_number():
    """If an execution-lane stage is ever reached, the loudest possible outcome is the only honest one."""
    class _Context(object):
        dataset_snapshot = "SYNTHETIC-probe"

    with pytest.raises(AssertionError) as raised:
        tripwire_runner("main_test")(_Context())
    message = str(raised.value)
    assert "was actually run under dataset snapshot" in message
    assert "src/groundtruth/ does not exist" in message
    assert "Nothing was computed" in message


def test_with_the_harness_bypassed_governance_refuses_the_execution_lane_anyway(tmp_path):
    """The harness is not the only thing stopping the five. Measured, because it matters which.

    ``phase0.execute_stage`` called directly, with a synthetic snapshot and a real registered
    runner: every execution-lane stage is refused as out of order, and no run record is written.
    The gate was never lifted, so the machine stops in the same place the harness does — for a
    different reason, in a different module, and that redundancy is the finding.
    """
    wiring = synthetic_wiring(tmp_path / "bypass")
    wiring.governance.transition(gov.PARAMETERS_FROZEN, "bypass")
    snapshot = generate_chain(SEED).snapshot

    for stage in BEHIND_THE_GATE:
        result = execute_stage(
            stage, tripwire_runner(stage), "bypass",
            governance=wiring.governance, preconditions=wiring.preconditions,
            runs=wiring.runs, audit=wiring.audit,
            commit=SYNTHETIC_COMMIT, dataset_snapshot=snapshot,
        )
        assert result.status == REFUSED
        assert result.run_id is None
        assert "out of order" in result.reason
        assert "VALIDATION_PASSED" in result.reason
    assert wiring.governance.state == gov.PARAMETERS_FROZEN


def test_validation_independent_is_the_stage_the_chain_stops_at(tmp_path):
    """Bypass the harness entirely and the stage still cannot pass. It crashes; the state holds."""
    wiring = synthetic_wiring(tmp_path / "gate")
    wiring.governance.transition(gov.PARAMETERS_FROZEN, "bypass")

    result = execute_stage(
        "validation.independent", runner_for("validation.independent"), "bypass",
        governance=wiring.governance, preconditions=wiring.preconditions,
        runs=wiring.runs, audit=wiring.audit,
        commit=SYNTHETIC_COMMIT, dataset_snapshot=generate_chain(SEED).snapshot,
    )

    assert result.status == CRASHED
    assert result.run_id is not None, "the run record says what it was about to do"
    assert result.advanced_to is None
    assert wiring.governance.state == gov.PARAMETERS_FROZEN
    assert "ticket 36" in result.reason


# -- the gap, now closed, and the residue that is not ----------------------------


def test_a_caller_who_does_not_import_this_package_is_refused_by_phase0_itself(tmp_path):
    """The attack that used to succeed. It is refused now, by the identifier alone.

    ``execute_stage`` takes the runner as an argument and still knows nothing about synthetic
    *chains*, so a caller who supplies their own runner for ``validation.independent`` runs it and
    gets its value computed. What it no longer gets is the transition: the snapshot declares itself
    not a measurement, so the outcome is ``HELD`` and ``VALIDATION_PASSED`` is not reached — which
    also means ``CODE_AND_DATA_FROZEN`` is out of order and the execution lane never opens.

    Every refusal in ``tools/mockchain`` is on the other side of an import this caller never made.
    That is exactly why the refusal had to move to ``src/phase0/``.
    """
    wiring = synthetic_wiring(tmp_path / "gap")
    snapshot = generate_chain(SEED).snapshot
    wiring.governance.transition(gov.PARAMETERS_FROZEN, "anybody at all")

    held = execute_stage(
        "validation.independent", lambda context: {"validation": "passed"}, "anybody at all",
        governance=wiring.governance, preconditions=wiring.preconditions,
        runs=wiring.runs, audit=wiring.audit,
        commit=SYNTHETIC_COMMIT, dataset_snapshot=snapshot,
    )
    assert held.status == HELD
    assert held.advanced_to is None
    assert wiring.governance.state == gov.PARAMETERS_FROZEN
    assert snapshot in held.reason

    # And the lane behind it stays shut: CODE_AND_DATA_FROZEN is two steps away now, not one.
    with pytest.raises(TransitionError):
        wiring.governance.transition(gov.CODE_AND_DATA_FROZEN, "anybody at all")

    assert "src/phase0/execution.py, in execute_stage" in GOVERNANCE_GAP
    assert "NOT_REAL_PREFIXES" in GOVERNANCE_GAP


def test_the_parameter_freeze_is_reached_only_by_withholding_the_snapshot(tmp_path):
    """The residue, demonstrated. ``PARAMETERS_FROZEN`` is a human act and a manual transition.

    No stage advances it, so the harness's pre-flight check never sees it, and
    ``GovernanceMachine.transition`` can only check a snapshot it is *given*. This driver holds one
    and does not pass it, which is the single thing ``src/phase0/`` cannot close — pass it and the
    same call is refused. The freeze stays a fiction, recorded as one, because a driver that hid it
    would be worse than one that performs it in the open.
    """
    wiring = synthetic_wiring(tmp_path / "freeze")
    snapshot = generate_chain(SEED).snapshot

    with pytest.raises(NotAMeasurementError):
        wiring.governance.transition(gov.PARAMETERS_FROZEN, "nobody", dataset_snapshot=snapshot)
    assert wiring.governance.state == gov.PARAMETERS_OPEN

    assert wiring.governance.transition(gov.PARAMETERS_FROZEN, "nobody") == gov.PARAMETERS_FROZEN
    assert "that has a snapshot and withholds it" in GOVERNANCE_GAP


# -- the marker ------------------------------------------------------------------


def test_every_run_record_says_the_run_was_synthetic(drive):
    """The identifier travels verbatim into the record and the log. There is no flag to drop."""
    records = _run_records(drive.root)
    assert len(records) == 7
    for record in records:
        assert is_synthetic_snapshot(record["dataset_snapshot"])
        assert record["dataset_snapshot"] == drive.snapshot
        assert record["commit"] == SYNTHETIC_COMMIT
        assert "NOT A MEASUREMENT" in record["requester"]


def test_the_audit_log_carries_the_snapshot_and_verifies(drive):
    entries = drive.audit.entries()
    assert drive.audit.verify() is True

    opened = [e for e in entries if e.action == "run.open"]
    assert len(opened) == 7
    for entry in opened:
        assert entry.detail["dataset_snapshot"] == drive.snapshot

    frozen = [e for e in entries if e.action == "governance.transition"]
    assert len(frozen) == 1, "one transition, and it is the parameter freeze"
    assert frozen[0].detail["to"] == gov.PARAMETERS_FROZEN
    assert frozen[0].detail["detail"]["dataset_snapshot"] == drive.snapshot
    assert "PERFORMED BY A SYNTHETIC RUN" in frozen[0].detail["detail"]["note"]


def test_the_precondition_register_records_that_it_was_not_satisfied(drive):
    with open(os.path.join(drive.root, "preconditions.json"), encoding="utf-8") as fh:
        recorded = json.load(fh)
    assert sorted(recorded) == [
        "capacity_reserved", "data_budget", "independent_validator", "primary_builder",
    ]
    for key, attribution in recorded.items():
        assert attribution.startswith("RECORDED BY A SYNTHETIC RUN, NOT SATISFIED")
    assert "ticket 03" in recorded["data_budget"]


def test_the_published_artifact_is_the_report_and_the_drive_publishes_nothing(drive):
    """The drive has no artifact of its own, and every value it renders is a line of text."""
    assert not hasattr(drive, "payload_hash")
    for outcome in drive.outcomes:
        assert isinstance(outcome.value, str)
    assert is_synthetic_snapshot(drive.run.snapshot)


def test_the_drive_refuses_a_chain_whose_snapshot_is_not_marked(tmp_path, monkeypatch):
    """The one guard :func:`drive_synthetic_phase0` owns: it will not drive an unmarked snapshot."""
    chain = generate_chain(SEED)
    object.__setattr__(chain, "snapshot", "mainnet-2026-08-01")
    monkeypatch.setattr(stage_module, "generate_chain", lambda seed: chain)

    with pytest.raises(SyntheticRunRefused) as raised:
        drive_synthetic_phase0(SEED, tmp_path / "unmarked")
    assert "does not declare itself synthetic" in str(raised.value)
    assert not (tmp_path / "unmarked" / "runs").exists()


# -- determinism ------------------------------------------------------------------


def test_two_drives_of_one_seed_are_byte_identical(tmp_path, run):
    """No clock and no unseeded run identifier, so the evidence directory itself reproduces."""
    first = drive_synthetic_phase0(SEED, tmp_path / "a", run=run)
    second = drive_synthetic_phase0(SEED, tmp_path / "b", run=run)

    assert first.table() == second.table()
    assert _read(first.root, "audit.jsonl") == _read(second.root, "audit.jsonl")
    assert _read(first.root, "governance.json") == _read(second.root, "governance.json")
    assert _run_records(first.root) == _run_records(second.root)


def test_a_different_seed_moves_the_snapshot_and_not_the_shape(tmp_path):
    other = drive_synthetic_phase0(8, tmp_path / "eight")
    assert other.snapshot != generate_chain(SEED).snapshot
    assert tuple(o.stage for o in other.outcomes) == STAGES
    assert other.statuses["pipeline.buy_quality"] == COMPLETED
    assert other.final_state == gov.PARAMETERS_FROZEN


# -- helpers ----------------------------------------------------------------------


def _read(root, name):
    with open(os.path.join(str(root), name), encoding="utf-8") as fh:
        return fh.read()


def _run_records(root):
    directory = os.path.join(str(root), "runs")
    out = []
    for name in sorted(os.listdir(directory)):
        with open(os.path.join(directory, name), encoding="utf-8") as fh:
            out.append(json.load(fh))
    return out
