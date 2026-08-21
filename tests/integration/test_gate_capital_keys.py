"""The published §7 verdict, on an input whose §7.2 evidence names one capital level twice.

This is the half of the identity-key defect that mattered: not that a mapping lost an entry, but
that ``GateDecision.outcome`` — the single most load-bearing published value in the repository —
moved between **GO** and **CONDITIONAL_REVIEW** on the order a caller's dict happened to iterate in.
``CapitalFeasibility.feasible`` is read directly in ``decision.emit_decision_detail`` and is the
whole of that branch.

The three tests below are one measurement in three parts, on identical evidence:

    $1.5M excess = +0.0362 alone            ->  GO
    $1.5M excess = -0.0500 alone            ->  CONDITIONAL_REVIEW
    both, as two spellings of $1.5M         ->  refused, no decision emitted

The first two are the two answers the collapsed mapping used to choose between by iteration order.
They are pinned as literals here so the third test's refusal is anchored to a measured cost rather
than to a description of one.

The evidence fixture is built locally rather than imported from ``test_gate_validation.py``: a
shared fixture edited for one file's needs would silently change what the other file measures, and
these two files are measuring different things about the same run.
"""

from decimal import Decimal

import pytest

from contracts import (
    NUMERIC_POLICY_VERSION,
    REPORTING_SCHEMA_VERSION,
    EdgeOriginStatus,
    FreezeViolation,
    GateOutcome,
    PermutationResult,
    ValidationStatus,
    WindowScore,
    divide,
)
from gate_validation import (
    FOLLOWER_COLUMN,
    GOVERNANCE_ORDER,
    LEADER_COLUMN,
    REQUIRED_MODULES,
    ConflictingResults,
    DiagnosticInputRefused,
    RunEvidence,
    RunStatus,
    assess_capital_feasibility,
    emit_decision,
    evaluate_windows_detail,
)

D = Decimal

THRESHOLD = D("0.24")
FROZEN_COMMIT = "3f1c9a" + "0" * 34

#: The measurement at $1.5M that the collapse deleted, and the one that survived in its place.
FAILING_AT_1_5M = D("-0.0500")
PASSING_AT_1_5M = D("0.0362")
AT_2M = D("0.0118")


def freeze_manifest():
    return {
        "source_commit": FROZEN_COMMIT,
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


def evidence():
    return RunEvidence(
        manifest=freeze_manifest(),
        observed=freeze_manifest(),
        pinned_module_versions=module_versions(),
        observed_module_versions=module_versions(),
        validation_status=ValidationStatus.EXTERNALLY_REVIEWED,
        governance_states=GOVERNANCE_ORDER[:GOVERNANCE_ORDER.index("MAIN_TEST_EXECUTED") + 1],
        locked_threshold=THRESHOLD,
        run_status=RunStatus(code_version=FROZEN_COMMIT),
        result_code_version=FROZEN_COMMIT,
    )


def window_scores():
    """Four windows, both columns; three windows pass both gates at 0.24. §7.4 is satisfied."""
    return [
        WindowScore(1, LEADER_COLUMN, D("0.3140"), D("0.0620"), D("0.2210"), D("0.41"),
                    EdgeOriginStatus.VALID),
        WindowScore(1, FOLLOWER_COLUMN, D("0.2705"), D("0.0284"), D("0.2402"), D("0.36"),
                    EdgeOriginStatus.VALID),
        WindowScore(2, LEADER_COLUMN, D("0.2988"), D("0.0511"), D("0.3105"), D("0.39"),
                    EdgeOriginStatus.VALID),
        WindowScore(2, FOLLOWER_COLUMN, D("0.2611"), D("0.0193"), D("0.3380"), D("0.33"),
                    EdgeOriginStatus.VALID),
        WindowScore(3, LEADER_COLUMN, D("0.2802"), D("0.0447"), D("0.2914"), D("0.37"),
                    EdgeOriginStatus.VALID),
        WindowScore(3, FOLLOWER_COLUMN, D("0.1904"), D("0.0102"), D("0.3011"), D("0.31"),
                    EdgeOriginStatus.VALID),
        WindowScore(4, LEADER_COLUMN, D("0.2607"), D("0.0338"), D("0.2508"), D("0.35"),
                    EdgeOriginStatus.VALID),
        WindowScore(4, FOLLOWER_COLUMN, D("0.2455"), D("0.0121"), D("0.2803"), D("0.30"),
                    EdgeOriginStatus.VALID),
    ]


def permutation(column):
    nulls = tuple(divide(n, 1000) for n in range(1, 21))
    return PermutationResult(
        column=column,
        observed_statistic=D("0.0410"),
        null_statistics=nulls,
        n_runs=20,
        percentile_95=D("0.0190"),
        # 1/21 exactly: no null run reached 0.0410. See the note in
        # tests/integration/test_gate_validation.py::permutation.
        empirical_p=D("0.047619047619047619047619047619047619048"),
        null_pass_rate=D("0.041"),
    )


def decide(capital):
    return emit_decision(
        evidence(),
        evaluate_windows_detail(window_scores(), THRESHOLD),
        capital,
        permutation(LEADER_COLUMN),
        permutation(FOLLOWER_COLUMN),
    )


# -- the two answers the collapse used to choose between --------------------------


def test_the_surviving_measurement_publishes_GO():
    decision = decide(assess_capital_feasibility({
        D("1500000"): PASSING_AT_1_5M,
        D("2000000"): AT_2M,
    }))
    assert decision.outcome is GateOutcome.GO
    assert decision.capital_feasibility_failed is False


def test_the_deleted_measurement_publishes_CONDITIONAL_REVIEW():
    decision = decide(assess_capital_feasibility({
        D("1500000"): FAILING_AT_1_5M,
        D("2000000"): AT_2M,
    }))
    assert decision.outcome is GateOutcome.CONDITIONAL_REVIEW
    assert decision.capital_feasibility_failed is True
    assert any("1500000" in reason for reason in decision.reasons)


# -- and the input that used to choose between them by iteration order ------------


def test_a_merged_window_cannot_manufacture_the_fourth_passing_window():
    """The other identity key in this module, measured where it is published rather than raised.

    ``evaluate_windows_detail`` groups on ``WindowScore.window``, and ``1``, ``True`` and ``1.0``
    are one dict key. The hand-computed file pins the refusal; this pins what the merge *bought*,
    which is the reason the refusal exists.

    Eight results are supplied: windows 2, 3 and 4 carry both columns, window ``1`` carries the
    leader alone, and window ``True`` carries the follower alone. Merged, ``True`` lands on window
    1 and completes it — window 1 becomes a window that PASSES, and it is the third of the four,
    which is exactly the count §7.4 turns into GO. Measured on the code before the refusal:
    ``[(1, True), (2, True), (3, False), (4, True)]``, three of four, ``GateOutcome.GO``.

    There is no honest spelling of this input that publishes anything: stated as two windows it is
    five windows, and §6.3 pre-registers four, so ``emit_decision`` refuses on ``windows_total``.
    The merge did not resolve an ambiguity — it created a window that was not there.
    """
    merged = [s for s in window_scores() if not (s.window == 1 and s.column == FOLLOWER_COLUMN)]
    merged.append(WindowScore(True, FOLLOWER_COLUMN, D("0.2705"), D("0.0284"), D("0.2402"),
                              D("0.36"), EdgeOriginStatus.VALID))

    with pytest.raises(DiagnosticInputRefused) as refusal:
        evaluate_windows_detail(merged, THRESHOLD)
    assert "is a bool and not an int" in str(refusal.value)

    # And the honest reading of the same eight results reaches no decision either: it is five
    # windows, and the gate is pre-registered on four.
    honest = merged[:-1] + [WindowScore(5, FOLLOWER_COLUMN, D("0.2705"), D("0.0284"), D("0.2402"),
                                        D("0.36"), EdgeOriginStatus.VALID)]
    evaluation = evaluate_windows_detail(honest, THRESHOLD)
    assert evaluation.total == 5
    assert [(v.window, v.passed) for v in evaluation.verdicts] == [
        (1, False), (2, True), (3, False), (4, True), (5, False)
    ]
    with pytest.raises(FreezeViolation) as refused:
        emit_decision(
            evidence(), evaluation,
            assess_capital_feasibility({D("1500000"): PASSING_AT_1_5M, D("2000000"): AT_2M}),
            permutation(LEADER_COLUMN), permutation(FOLLOWER_COLUMN),
        )
    assert "windows_total" in str(refused.value)


def test_a_level_named_twice_emits_no_decision_at_all():
    """Both orderings. Neither publishes; the refusal is the answer.

    Refused rather than resolved, and refused rather than quarantined: two entries name $1,500,000,
    nobody can say which of them is *the* measurement at $1,500,000, and a gate that picked one
    would be publishing the caller's dict ordering under the protocol's name.
    """
    for entries in (
        [("1500000", FAILING_AT_1_5M), (D("1500000"), PASSING_AT_1_5M), (D("2000000"), AT_2M)],
        [(D("1500000"), PASSING_AT_1_5M), ("1500000", FAILING_AT_1_5M), (D("2000000"), AT_2M)],
    ):
        with pytest.raises(ConflictingResults):
            decide(assess_capital_feasibility(dict(entries)))

        with pytest.raises(ConflictingResults):
            decide(assess_capital_feasibility(entries))
