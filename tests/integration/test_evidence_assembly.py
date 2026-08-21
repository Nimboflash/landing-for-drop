"""The evidence assembler's refusal catalogue — one refusal per holder that cannot supply its part.

``pipeline.evidence.assemble_run_evidence`` collects the nine fields of a
``gate_validation.RunEvidence`` from the holders of record and derives nothing. This file walks
each way a holder can come up empty — or two holders can contradict each other — and pins that the
assembler refuses with :class:`~pipeline.evidence.EvidenceIncomplete` naming the missing piece,
rather than filling the gap with a value it computed. The complete assembly, every field pinned as
a literal, is ``tests/hand_computed/test_evidence_assembly.py``.

Two scenarios below forge audit entries or edit state files directly. That is not test convenience;
it is the only way to make the holders of record *disagree*, because ``phase0`` keeps them
consistent on every legitimate path. The assembler's job on those inputs is to refuse rather than
to pick a side, and a test that could not produce the disagreement could not pin the refusal.
"""

import json
import os
from decimal import Decimal

import pytest

from contracts import NUMERIC_POLICY_VERSION, REPORTING_SCHEMA_VERSION, ValidationStatus
from phase0 import governance as gov
from phase0.errors import AuditChainError
from phase0.execution import ACTION_COMPLETED, execute_stage, wire
from phase0.preconditions import PRECONDITION_KEYS
from phase0.runs import RunStore
from pipeline.evidence import EvidenceIncomplete, ObservedArtifacts, assemble_run_evidence

COMMIT = "b" * 40
SECOND_COMMIT = "c" * 40
SNAPSHOT = "snapshot-evidence-0002"

PINNED = {
    "attribution": "attribution-11111111",
    "contracts": "contracts-11111111",
    "depth": "depth-11111111",
    "fifo": "fifo-11111111",
    "marking": "marking-11111111",
    "matching_null": "matching_null-11111111",
    "netting": "netting-11111111",
    "scoring": "scoring-11111111",
}


def manifest():
    return {
        "source_commit": COMMIT,
        "dataset_snapshot": SNAPSHOT,
        "golden_set_version": "golden-v3",
        "protocol_coverage_version": "coverage-v2",
        "decoder_version": "decoder-v7",
        "model_version": "model-v1",
        "config_hash": "c" * 64,
        "master_seed": "d" * 64,
        "known_answer_fixture_hash": "k" * 64,
        "validation_report_hash": "v" * 64,
        "numeric_policy_version": NUMERIC_POLICY_VERSION,
        "reporting_schema_version": REPORTING_SCHEMA_VERSION,
    }


def observed_artifacts(**overrides):
    fields = dict(
        manifest=manifest(),
        module_versions=dict(PINNED),
        validation_status=ValidationStatus.EXTERNALLY_REVIEWED,
        locked_threshold=Decimal("0.41"),
    )
    fields.update(overrides)
    return ObservedArtifacts(**fields)


def spy(context):
    return "ok"


def wired(root):
    w = wire(str(root))
    for key in PRECONDITION_KEYS:
        w.preconditions.record(key, "recorded-for-test", "Research Owner")
    return w


def run(w, stage, commit=COMMIT):
    return execute_stage(
        stage, spy, "primary-builder",
        governance=w.governance, preconditions=w.preconditions, runs=w.runs, audit=w.audit,
        commit=commit, dataset_snapshot=SNAPSHOT,
    )


def freeze(w, pins=None):
    """The three manual/lifted transitions up to the ticket-39 code-and-data freeze."""
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")
    w.governance.transition(gov.VALIDATION_PASSED, "Research Owner",
                            {"note": "lifted by hand in a test; ticket 36 is not delivered"})
    w.governance.transition(gov.CODE_AND_DATA_FROZEN, "Research Owner",
                            {"module_versions": dict(PINNED)} if pins is None else pins)
    return w


def a_governed_run(w, commit=COMMIT):
    freeze(w)
    run(w, "null.leader", commit)
    run(w, "null.follower", commit)
    run(w, "threshold.calibrate", commit)
    run(w, "main_test", commit)
    return w


@pytest.fixture
def w(tmp_path):
    return a_governed_run(wired(tmp_path / "state"))


def assemble(w, observed=None, freeze_manifest=None):
    return assemble_run_evidence(
        w.governance, w.runs, w.audit,
        manifest() if freeze_manifest is None else freeze_manifest,
        observed_artifacts() if observed is None else observed,
    )


# -- a wrong collaborator is a caller defect, not a gap in the evidence -----------


def test_a_collaborator_of_the_wrong_type_is_a_TypeError_naming_the_parameter(w):
    with pytest.raises(TypeError, match="governance must be"):
        assemble_run_evidence({}, w.runs, w.audit, manifest(), observed_artifacts())
    with pytest.raises(TypeError, match="runs must be"):
        assemble_run_evidence(w.governance, {}, w.audit, manifest(), observed_artifacts())
    with pytest.raises(TypeError, match="audit must be"):
        assemble_run_evidence(w.governance, w.runs, {}, manifest(), observed_artifacts())
    with pytest.raises(TypeError, match="observed must be an ObservedArtifacts"):
        assemble_run_evidence(w.governance, w.runs, w.audit, manifest(), {"manifest": {}})


def test_a_manifest_path_is_refused_because_the_caller_does_the_file_reading(w):
    """A string path is the likely misuse, and reading the file here would move IO into the
    assembler; the refusal is a TypeError because the call is wrong, not the evidence."""
    with pytest.raises(TypeError, match="already-parsed mapping"):
        assemble_run_evidence(w.governance, w.runs, w.audit, "freeze_manifest.json",
                              observed_artifacts())


# -- the observed artifacts: each absence refused by the name of its artifact -----


def test_an_empty_freeze_manifest_is_refused_as_pinning_nothing(w):
    with pytest.raises(EvidenceIncomplete, match="freeze manifest is empty"):
        assemble(w, freeze_manifest={})


def test_a_run_that_reported_no_observed_manifest_is_refused_not_defaulted(w):
    """The assembler must never copy the pinned manifest into the observed side: the §9.6 match
    is two independent accounts or it is nothing."""
    with pytest.raises(EvidenceIncomplete, match="no observed manifest values"):
        assemble(w, observed=observed_artifacts(manifest=None))


def test_a_run_that_reported_no_module_versions_is_refused(w):
    with pytest.raises(EvidenceIncomplete, match="no module versions"):
        assemble(w, observed=observed_artifacts(module_versions=None))


def test_a_missing_validation_status_is_refused_naming_the_validator_lane(w):
    with pytest.raises(EvidenceIncomplete, match="no validation status"):
        assemble(w, observed=observed_artifacts(validation_status=None))


def test_a_missing_locked_threshold_is_refused_naming_the_calibration_artifact(w):
    with pytest.raises(EvidenceIncomplete, match="no locked threshold"):
        assemble(w, observed=observed_artifacts(locked_threshold=None))


# -- the audit log: gaps in its account of the era --------------------------------


def test_an_era_that_never_froze_code_and_data_has_no_pins_to_collect(tmp_path):
    w = wired(tmp_path / "state")
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")
    w.governance.transition(gov.VALIDATION_PASSED, "Research Owner")
    with pytest.raises(EvidenceIncomplete, match="no CODE_AND_DATA_FROZEN transition"):
        assemble(w)


def test_a_freeze_that_recorded_no_pins_froze_nothing_the_gate_can_check(tmp_path):
    w = freeze(wired(tmp_path / "state"), pins={"note": "frozen, pins forgotten"})
    with pytest.raises(EvidenceIncomplete, match="recorded no module version pins"):
        assemble(w)


def test_an_era_with_no_completed_main_test_has_no_result_to_be_evidence_about(tmp_path):
    w = freeze(wired(tmp_path / "state"))
    run(w, "null.leader")
    run(w, "null.follower")
    run(w, "threshold.calibrate")
    with pytest.raises(EvidenceIncomplete, match="no completed main_test"):
        assemble(w)


# -- the run store: gaps and disagreements in the records -------------------------


def test_an_empty_run_store_is_refused_because_nothing_has_run(tmp_path):
    w = freeze(wired(tmp_path / "state"))
    with pytest.raises(EvidenceIncomplete, match="no run records at all"):
        assemble(w)


def test_a_run_record_the_audit_log_never_witnessed_is_refused_by_run_id(w):
    """A record written around the audited path must not vote on the era's code version."""
    off_books = RunStore(os.path.join(w.root, "runs"), audit_log=None)
    record = off_books.open_run("pipeline.buy_quality", "f" * 40, {}, SNAPSHOT, "off-books")
    with pytest.raises(EvidenceIncomplete, match="never opened through the audited path"):
        assemble(w)
    with pytest.raises(EvidenceIncomplete, match=record.run_id):
        assemble(w)


def test_an_era_whose_records_pin_two_commits_is_refused_not_arbitrated(tmp_path):
    """§9.6 requires one experiment at one commit. Faced with two, the assembler must not
    choose — sorted()[0] would be a deterministic-looking derivation of the one fact this
    field exists to collect."""
    w = freeze(wired(tmp_path / "state"))
    run(w, "null.leader", commit=COMMIT)
    run(w, "null.follower", commit=SECOND_COMMIT)
    with pytest.raises(EvidenceIncomplete, match="2 different commits"):
        assemble(w)


def test_a_completed_main_test_whose_record_vanished_leaves_the_result_versionless(w):
    completed = [e for e in w.audit.entries()
                 if e.action == ACTION_COMPLETED and e.detail.get("stage") == "main_test"]
    run_id = completed[-1].detail["run_id"]
    os.remove(os.path.join(w.root, "runs", "{}.json".format(run_id)))
    with pytest.raises(EvidenceIncomplete, match="run store holds no record"):
        assemble(w)


# -- two holders of record disagreeing: refused, never arbitrated -----------------


def test_a_transition_that_does_not_chain_onto_the_sequence_is_refused(w):
    """A forged entry recorded from a state the sequence never stood at. The log must be
    repaired at its source; the assembler does not smooth its account."""
    w.audit.append("forger", "governance.transition",
                   {"from": gov.PARAMETERS_OPEN, "to": gov.PARAMETERS_FROZEN, "detail": {}})
    with pytest.raises(EvidenceIncomplete, match="do not chain"):
        assemble(w)


def test_a_machine_and_a_log_that_disagree_about_the_state_are_refused_jointly(w):
    """An extra transition that chains perfectly — but the machine never made it."""
    w.audit.append("forger", "governance.transition",
                   {"from": gov.MAIN_TEST_EXECUTED, "to": gov.DECISION_EMITTED, "detail": {}})
    with pytest.raises(EvidenceIncomplete, match="but the audit log's transitions"):
        assemble(w)


def test_an_invalidation_the_audit_log_never_recorded_is_refused_not_carried(w):
    """The machine's file says INVALIDATED; the log has no such entry this era. An invalidation
    with no recorded reason is indistinguishable from discarding a disliked result."""
    with open(w.governance.path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data["invalidated"] = True
    data["invalidation_reason"] = "edited into the state file, never audited"
    with open(w.governance.path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    with pytest.raises(EvidenceIncomplete, match="records no invalidation"):
        assemble(w)


def test_a_tampered_audit_log_propagates_its_own_chain_error_before_anything_is_read(w):
    """Collecting from a doctored log would launder it into evidence; the chain walk comes
    first and its error is phase0's own, not an EvidenceIncomplete."""
    with open(w.audit.path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    doctored = json.loads(lines[-1])
    doctored["requester"] = "somebody-else"
    lines[-1] = json.dumps(doctored, sort_keys=True) + "\n"
    with open(w.audit.path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    with pytest.raises(AuditChainError):
        assemble(w)


# -- §9.7 era scoping: a re-run quotes nothing from the discarded era -------------


def second_era(w):
    w.governance.invalidate("ops", "a documented bug in the netting rule")
    w.governance.register_code_version(SECOND_COMMIT, "Research Owner")
    w.governance.transition(gov.VALIDATION_PASSED, "Research Owner",
                            {"note": "re-run for the new code version"})
    w.governance.transition(gov.CODE_AND_DATA_FROZEN, "Research Owner",
                            {"module_versions": dict(PINNED)})
    return w


def test_a_new_era_with_no_run_records_of_its_own_cannot_quote_the_discarded_ones(w):
    with pytest.raises(EvidenceIncomplete, match="predates the last registered code version"):
        assemble(second_era(w))


def test_a_completed_second_era_assembles_with_the_first_eras_commit_discarded(w):
    """The one positive case in this file, because it is the era boundary that makes every
    refusal above meaningful: the re-run's evidence names the new commit, lists the discarded
    one, and rebuilds the full seven-state sequence from the rewind the register recorded."""
    second_era(w)
    for stage in ("null.leader", "null.follower", "threshold.calibrate", "main_test"):
        run(w, stage, commit=SECOND_COMMIT)
    evidence = assemble(w)
    assert evidence.run_status.code_version == SECOND_COMMIT
    assert evidence.run_status.invalidated is False
    assert evidence.run_status.discarded_versions == (COMMIT,)
    assert evidence.result_code_version == SECOND_COMMIT
    assert evidence.governance_states == (
        "PARAMETERS_OPEN",
        "PARAMETERS_FROZEN",
        "VALIDATION_PASSED",
        "CODE_AND_DATA_FROZEN",
        "NULL_COMPLETE",
        "THRESHOLD_LOCKED",
        "MAIN_TEST_EXECUTED",
    )
