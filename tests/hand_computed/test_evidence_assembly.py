"""The evidence assembler's one complete assembly, every field pinned as a literal.

``pipeline.evidence.assemble_run_evidence`` collects the nine fields of a
``gate_validation.RunEvidence`` from the holders of record: the governance machine, the run store,
the audit log, the freeze manifest, and the run's own observed artifacts. This file walks one real
governed run — the transitions through ``phase0.governance``, the stages through
``phase0.execution.execute_stage`` — and then pins what the assembler collected as **written-out
literals**, not as values read back from the holders. A test that asked the audit log what the
sequence was and asserted the assembler agrees could not detect the assembler.

The stage runners injected below compute nothing on purpose. The stages' *values* are not what the
assembler reads — governance deliberately records no value (``StageResult.to_dict`` omits it) —
so a spy runner exercises exactly the records the assembler collects from: the run records, the
transition entries, and the completion entries.

The refusal catalogue — one per missing holder — is ``tests/integration/test_evidence_assembly.py``.
"""

from decimal import Decimal

import pytest

from contracts import NUMERIC_POLICY_VERSION, REPORTING_SCHEMA_VERSION, ValidationStatus
from phase0 import governance as gov
from phase0.execution import execute_stage, wire
from phase0.preconditions import PRECONDITION_KEYS
from pipeline.evidence import ObservedArtifacts, assemble_run_evidence

COMMIT = "b" * 40
SNAPSHOT = "snapshot-evidence-0001"

#: The eight §9.6 module pins, written out. ``gate_validation.REQUIRED_MODULES`` is deliberately
#: not imported here: the point of the literal is that a module quietly leaving the pinned set
#: fails this file rather than moving with it.
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
    """A complete §9.6 manifest whose ``source_commit`` is this run's own commit."""
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
    """A runner that computes nothing: the assembler reads records, never stage values."""
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


def a_governed_run(w):
    """One era, driven to MAIN_TEST_EXECUTED through the real machinery.

    The three manual transitions are the two human freezes plus the hand-lifted validation gate,
    exactly as ``tests/integration/test_stage_runners.py`` performs them; the four execution-lane
    stages go through ``execute_stage`` so the run records and completion entries the assembler
    reads are written by the code that writes them in a real run.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")
    w.governance.transition(gov.VALIDATION_PASSED, "Research Owner",
                            {"note": "lifted by hand in a test; ticket 36 is not delivered"})
    w.governance.transition(gov.CODE_AND_DATA_FROZEN, "Research Owner",
                            {"module_versions": dict(PINNED)})
    run(w, "null.leader")
    run(w, "null.follower")
    run(w, "threshold.calibrate")
    run(w, "main_test")
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


# -- the complete assembly, field by field ----------------------------------------


def test_the_governance_sequence_is_the_seven_states_the_era_recorded(w):
    assert assemble(w).governance_states == (
        "PARAMETERS_OPEN",
        "PARAMETERS_FROZEN",
        "VALIDATION_PASSED",
        "CODE_AND_DATA_FROZEN",
        "NULL_COMPLETE",
        "THRESHOLD_LOCKED",
        "MAIN_TEST_EXECUTED",
    )


def test_the_pinned_module_versions_are_the_freeze_acts_own_record(w):
    """Collected from the CODE_AND_DATA_FROZEN transition's detail, and pinned as a literal."""
    assert assemble(w).pinned_module_versions == {
        "attribution": "attribution-11111111",
        "contracts": "contracts-11111111",
        "depth": "depth-11111111",
        "fifo": "fifo-11111111",
        "marking": "marking-11111111",
        "matching_null": "matching_null-11111111",
        "netting": "netting-11111111",
        "scoring": "scoring-11111111",
    }


def test_the_run_status_names_the_one_commit_every_record_pinned(w):
    status = assemble(w).run_status
    assert status.code_version == "b" * 40
    assert status.invalidated is False
    assert status.invalidation_reason is None
    assert status.discarded_versions == ()
    assert status.permits_decision is True


def test_the_result_code_version_is_the_main_tests_own_record_commit(w):
    assert assemble(w).result_code_version == "b" * 40


def test_the_four_observed_artifact_fields_pass_through_unrewritten(w):
    """The assembler carries the artifacts' values; it does not normalise, fill, or convert them.

    ``locked_threshold`` alone changes representation, because ``RunEvidence.__post_init__`` runs
    it through the seam's ``calc`` — the assembler still handed over the artifact's value.
    """
    evidence = assemble(w)
    assert evidence.observed == manifest()
    assert evidence.observed_module_versions == PINNED
    assert evidence.validation_status is ValidationStatus.EXTERNALLY_REVIEWED
    assert evidence.locked_threshold == Decimal("0.41")


def test_the_freeze_manifest_parameter_becomes_the_manifest_field_verbatim(w):
    assert assemble(w).manifest == manifest()


def test_an_invalidated_run_assembles_and_carries_the_reason_from_the_audit_log(w):
    """Assembling is not judging: §9.7's refusal is the arbiter's, made on this value.

    The machine holds the flag; the log holds the reason. Both collected, neither interpreted.
    """
    w.governance.invalidate("ops", "a documented bug in the netting rule")
    status = assemble(w).run_status
    assert status.invalidated is True
    assert status.invalidation_reason == "a documented bug in the netting rule"
    assert status.permits_decision is False
