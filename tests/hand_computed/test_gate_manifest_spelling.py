"""Two spellings of one freeze manifest, at the confirmation that binds a decision to a commit.

Found by sweeping ``gate_validation`` for the identity-key class after the capital-level instance
was closed. This is the same class in its other direction: not two caller keys collapsing onto one
entry, but one caller *spelling* being treated as no entry at all.

``RunEvidence.manifest`` is documented as a mapping and is accepted in two forms everywhere else in
this package — ``manifest.check_freeze_manifest_detail`` and ``manifest.freeze_manifest_from`` both
run it through ``artifacts._mapping``, which takes an already-parsed ``dict`` **or** the seam's
``contracts.FreezeManifest`` reduced through ``canonicalise``. One line in
``decision.check_gate_prerequisites`` read it through ``isinstance(..., dict)`` instead, and on the
``else`` branch produced ``None`` — which the next line reads as "the manifest pins no commit", so
the confirmation was skipped rather than failed.

**What that cost, measured.** One manifest pinning ``3f1c9a…`` while ``RunStatus.code_version``
records that the run executed ``7b2e4d…``, everything else identical and clean::

    manifest as dict       ->  1 source_commit discrepancy, decision refused
    manifest as dataclass  ->  0 discrepancies, decision emitted

A run that executed code the freeze does not pin is exactly what §9.6 exists to catch, and the
caller who held the seam type — the *better*-typed caller — was the one it stopped catching it for.

The three tests below pin the two halves and their agreement. They are written against
``check_gate_prerequisites`` rather than ``emit_decision`` because the discrepancy is the thing
being pinned; ``tests/integration/test_gate_validation.py`` already covers that a non-empty report
refuses.
"""

from decimal import Decimal

import pytest

from contracts import (
    NUMERIC_POLICY_VERSION,
    REPORTING_SCHEMA_VERSION,
    FreezeManifest,
    ValidationStatus,
)
from gate_validation import (
    GOVERNANCE_ORDER,
    REQUIRED_MODULES,
    RunEvidence,
    RunStatus,
    check_gate_prerequisites,
)

D = Decimal

#: The commit the manifest pins, and the different one the run actually executed.
PINNED_COMMIT = "3f1c9a" + "0" * 34
EXECUTED_COMMIT = "7b2e4d" + "0" * 34

THRESHOLD = D("0.24")


def manifest_fields(source_commit):
    return {
        "source_commit": source_commit,
        "dataset_snapshot": "dune-2026-07-15-" + "a" * 16,
        "golden_set_version": "golden-50-accounts-v3",
        "protocol_coverage_version": "protocols-2026-07-01",
        "decoder_version": "decoder-v7",
        "model_version": "hcbq-v1",
        "config_hash": "c" * 64,
        "master_seed": "7f3c" + "0" * 60,
        "known_answer_fixture_hash": "k" * 64,
        "validation_report_hash": "v" * 64,
        "numeric_policy_version": NUMERIC_POLICY_VERSION,
        "reporting_schema_version": REPORTING_SCHEMA_VERSION,
    }


def module_versions():
    return {name: "{}-{}".format(name, "9f" * 4) for name in REQUIRED_MODULES}


def evidence(manifest, executed_commit):
    """Everything clean except, on demand, the commit the run executed.

    ``manifest`` and ``observed`` are the same object on purpose: this file is not measuring the
    manifest-versus-run comparison, it is measuring the manifest-versus-``run_status`` one, which is
    the only check that reads ``source_commit`` out of the manifest directly.
    """
    return RunEvidence(
        manifest=manifest,
        observed=manifest,
        pinned_module_versions=module_versions(),
        observed_module_versions=module_versions(),
        validation_status=ValidationStatus.EXTERNALLY_REVIEWED,
        governance_states=GOVERNANCE_ORDER[:GOVERNANCE_ORDER.index("MAIN_TEST_EXECUTED") + 1],
        locked_threshold=THRESHOLD,
        run_status=RunStatus(code_version=executed_commit),
        result_code_version=executed_commit,
    )


def source_commit_findings(manifest, executed_commit):
    report = check_gate_prerequisites(evidence(manifest, executed_commit), THRESHOLD)
    return tuple(d for d in report.discrepancies if d.field == "source_commit")


# -- the confirmation, in both spellings ------------------------------------------


def test_a_dict_manifest_catches_a_commit_the_run_did_not_execute():
    found = source_commit_findings(manifest_fields(PINNED_COMMIT), EXECUTED_COMMIT)
    assert len(found) == 1
    assert found[0].expected == EXECUTED_COMMIT
    assert found[0].observed == PINNED_COMMIT
    assert found[0].detail == "the freeze manifest pins a commit the run did not execute"


def test_a_dataclass_manifest_catches_it_identically():
    """The spelling that used to reach a published decision with the confirmation skipped.

    ``FreezeManifest`` is the seam type this package's own ``freeze_manifest_from`` produces, so a
    caller holding one is not doing anything unusual — it is the form the decision itself carries.
    """
    found = source_commit_findings(
        FreezeManifest(**manifest_fields(PINNED_COMMIT)), EXECUTED_COMMIT
    )
    assert len(found) == 1
    assert found[0].expected == EXECUTED_COMMIT
    assert found[0].observed == PINNED_COMMIT
    assert found[0].detail == "the freeze manifest pins a commit the run did not execute"


def test_the_two_spellings_produce_the_same_whole_report():
    """Not just the same finding — the same report, on the clean input and on the failing one.

    A check that agrees on the case a reviewer constructed and diverges elsewhere is the shape this
    repository has already had to undo once. Comparing the rendered messages compares every
    discrepancy the prerequisites produce, not only the one this file was written for.
    """
    for executed in (PINNED_COMMIT, EXECUTED_COMMIT):
        as_dict = check_gate_prerequisites(
            evidence(manifest_fields(PINNED_COMMIT), executed), THRESHOLD)
        as_dataclass = check_gate_prerequisites(
            evidence(FreezeManifest(**manifest_fields(PINNED_COMMIT)), executed), THRESHOLD)
        assert as_dict.messages == as_dataclass.messages


def test_a_manifest_that_pins_the_executed_commit_raises_nothing_here():
    """The bar the two tests above have to clear without help: a clean run stays clean."""
    assert source_commit_findings(manifest_fields(PINNED_COMMIT), PINNED_COMMIT) == ()
    assert source_commit_findings(
        FreezeManifest(**manifest_fields(PINNED_COMMIT)), PINNED_COMMIT) == ()


def test_a_manifest_that_is_neither_mapping_nor_dataclass_is_refused_by_name():
    """The residue of reading through ``_mapping``: it raises where the old line returned ``None``.

    That raise is not new here — ``check_freeze_manifest_detail`` runs ``_mapping`` on the same
    value earlier in the same function, so this input never reached the ``source_commit`` line under
    either spelling. Pinned so the claim in the comment beside the fix is checked rather than
    asserted.
    """
    with pytest.raises(TypeError) as excinfo:
        check_gate_prerequisites(evidence("not-a-manifest", EXECUTED_COMMIT), THRESHOLD)
    assert "manifest must be an already-parsed mapping" in str(excinfo.value)
