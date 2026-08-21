"""Worked examples for the arbiter. Every expected value below was fixed before the code ran.

The fixtures are deliberately round so that a reviewer can check the verdict by eye:

    threshold           0.24   (the §8.3 worked example: 24pp, where the null pass rate hits 4%)
    windows             4      (§6.3 — the count is part of the pre-registration, not a parameter)
    columns             leader · follower_adjusted
    design capital      $1,500,000 and $2,000,000 (§3.1 — the two levels that gate)

Three of the four windows pass both columns, so ``evaluate_windows`` returns ``(3, 4)`` and the
project-level rule (§7.4, "at least 3 of 4") is satisfied by exactly one window's margin. That
margin is the point: every test below that flips a single condition must move the count to 2 and
the outcome to STOP.

Numeric expectations are evaluated **inside** ``localcontext(CALCULATION_CONTEXT)`` — including the
subtraction and the division — because the module runs at the frozen 38 digits while Python's
default context is 28, and two values that agree to 28 digits and then diverge fail an exact
comparison.
"""

from decimal import Decimal, localcontext

import pytest

from contracts import (
    CALCULATION_CONTEXT,
    NUMERIC_POLICY_VERSION,
    REPORTING_SCHEMA_VERSION,
    EdgeOriginStatus,
    FreezeViolation,
    GateOutcome,
    PermutationResult,
    ValidationStatus,
    WindowScore,
    artifact_envelope,
    canonical_hash,
    divide,
    to_canonical_json,
)
from gate_validation import (
    BUY_QUALITY_ABSOLUTE_TOLERANCE_PP,
    DESIGN_CAPITAL_LEVELS,
    EXPECTED_WINDOWS,
    FIRST_HOUR_EDGE_SHARE_MAX,
    FOLLOWER_COLUMN,
    InconsistentEdgeOrigin,
    InconsistentNullSummary,
    GOVERNANCE_ORDER,
    LEADER_COLUMN,
    MIN_PASSING_WINDOWS,
    RECONCILIATION_CONDITIONS,
    REQUIRED_MODULES,
    USD_RELATIVE_TOLERANCE,
    VALIDATION_GATE_CONDITIONS,
    VALIDATION_LAYER_ORDER,
    ConflictingResults,
    DiagnosticInputRefused,
    FieldSpec,
    RunEvidence,
    RunStatus,
    ToleranceSpec,
    assess_capital_feasibility,
    check_exact_fields,
    check_freeze_manifest,
    check_freeze_manifest_detail,
    check_layer_order,
    check_numeric_fields,
    check_numeric_fields_detail,
    check_reconciliation_coverage,
    check_schema,
    check_state_sequence,
    check_validation_gate,
    emit_decision,
    emit_decision_detail,
    evaluate_windows,
    evaluate_windows_detail,
    invalidate,
    register_code_version,
    require_current_version,
    verify_envelope,
)

D = Decimal

THRESHOLD = D("0.24")
CODE_VERSION = "a" * 40


# -- fixtures -------------------------------------------------------------------


def score(window, column, mean, median, status=EdgeOriginStatus.VALID, share="0.20",
          contribution="0.30"):
    """One window-column result. ``share`` must be None exactly when status is INDETERMINATE."""
    return WindowScore(
        window=window,
        column=column,
        mean_advantage=D(mean),
        median_advantage=D(median),
        first_hour_edge_share=None if share is None else D(share),
        positive_edge_contribution=D(contribution),
        edge_origin_status=status,
    )


def passing_scores():
    """Windows 1, 2 and 4 pass both columns; window 3's follower column misses the threshold.

    Window 4's leader mean sits exactly on the threshold, so the ``>=`` in §7.1 condition 1 is
    exercised by the fixture rather than only by a boundary test.
    """
    return [
        score(1, LEADER_COLUMN, "0.30", "0.05"),
        score(1, FOLLOWER_COLUMN, "0.26", "0.02"),
        score(2, LEADER_COLUMN, "0.31", "0.06"),
        score(2, FOLLOWER_COLUMN, "0.27", "0.03"),
        score(3, LEADER_COLUMN, "0.29", "0.04"),
        score(3, FOLLOWER_COLUMN, "0.10", "0.01"),
        score(4, LEADER_COLUMN, "0.24", "0.07"),
        score(4, FOLLOWER_COLUMN, "0.25", "0.02"),
    ]


def manifest(**overrides):
    pinned = {
        "source_commit": CODE_VERSION,
        "dataset_snapshot": "snapshot-" + "1" * 8,
        "golden_set_version": "golden-v3",
        "protocol_coverage_version": "coverage-v2",
        "decoder_version": "decoder-v7",
        "model_version": "model-v1",
        "config_hash": "c" * 64,
        "master_seed": "seed-0001",
        "known_answer_fixture_hash": "k" * 64,
        "validation_report_hash": "v" * 64,
        "numeric_policy_version": NUMERIC_POLICY_VERSION,
        "reporting_schema_version": REPORTING_SCHEMA_VERSION,
    }
    pinned.update(overrides)
    return pinned


def module_versions(**overrides):
    versions = {name: "{}-{}".format(name, "0" * 8) for name in REQUIRED_MODULES}
    versions.update(overrides)
    return versions


def evidence(**overrides):
    fields = dict(
        manifest=manifest(),
        observed=manifest(),
        pinned_module_versions=module_versions(),
        observed_module_versions=module_versions(),
        validation_status=ValidationStatus.EXTERNALLY_REVIEWED,
        governance_states=GOVERNANCE_ORDER[:GOVERNANCE_ORDER.index("MAIN_TEST_EXECUTED") + 1],
        locked_threshold=THRESHOLD,
        run_status=RunStatus(code_version=CODE_VERSION),
        result_code_version=CODE_VERSION,
    )
    fields.update(overrides)
    return RunEvidence(**fields)


def null(column, observed="0.30", percentile="0.019",
         p="0.047619047619047619047619047619047619048"):
    """§7.3, on a distribution that can actually produce the verdict it claims.

    These used to be three runs — 0.10, 0.15, 0.20 — declaring ``empirical_p`` of 0.01 for the
    significant case. Three runs cannot report a p-value below 1/(3+1) = 0.25, so ``p <= 0.05`` was
    unreachable and the fixture simply asserted it. Nothing objected, because the arbiter read the
    declared field and never the statistics sitting beside it.

    Twenty runs are the minimum that can honestly clear the gate: the smallest p at n runs is
    1/(n+1), so n >= 19. With the observed statistic above every null, the count is zero and p is
    exactly 1/21. The percentile is nearest-rank at n = 20 — ``ceil(0.95 * 20) = 19``, so the 19th
    of the ascending twenty, which is 0.019.
    """
    nulls = tuple(divide(n, 1000) for n in range(1, 21))
    return PermutationResult(
        column=column,
        observed_statistic=D(observed),
        null_statistics=nulls,
        n_runs=20,
        percentile_95=D(percentile),
        empirical_p=D(p),
        null_pass_rate=D("0.04"),
    )


def feasible_capital(a="0.05", b="0.03"):
    return assess_capital_feasibility({
        DESIGN_CAPITAL_LEVELS[0]: None if a is None else D(a),
        DESIGN_CAPITAL_LEVELS[1]: None if b is None else D(b),
    })


# -- §7.1 / §7.4 window evaluation ----------------------------------------------


def test_three_of_four_windows_pass_the_reference_fixture():
    """Windows 1, 2, 4 pass both columns; window 3's follower column misses 0.24."""
    assert evaluate_windows(passing_scores(), THRESHOLD) == (3, 4)


def test_the_count_is_windows_not_column_results():
    """Eight scores, four windows. Counting column results would report 7 of 8 and pass a gate."""
    evaluation = evaluate_windows_detail(passing_scores(), THRESHOLD)
    assert evaluation.total == EXPECTED_WINDOWS
    assert len(evaluation.verdicts) == EXPECTED_WINDOWS
    assert [v.window for v in evaluation.verdicts] == [1, 2, 3, 4]


def test_the_leader_column_alone_passes_all_four():
    """Gate 1 is measured on the leader column only — that is what makes CONDITIONAL_REVIEW
    distinguishable from STOP."""
    evaluation = evaluate_windows_detail(passing_scores(), THRESHOLD)
    assert evaluation.passed_for(LEADER_COLUMN) == 4
    assert evaluation.passed_for(FOLLOWER_COLUMN) == 3


def test_mean_exactly_on_the_threshold_passes():
    """§7.1 condition 1 is ``>=``. Window 4's leader mean is 0.24 against a 0.24 threshold."""
    verdict = evaluate_windows_detail(passing_scores(), THRESHOLD).verdict_for(4)
    assert verdict.passed
    assert verdict.column_for(LEADER_COLUMN).mean_advantage == THRESHOLD


def test_median_exactly_zero_fails():
    """§7.1 condition 2 is strict: ``> 0``. A zero median is not a positive one.

    Condition 2 exists because one token returning 1000% can carry a basket in which 90% of the
    buys lost money; a median sitting exactly on zero is precisely that basket's boundary case.
    """
    scores = [s for s in passing_scores() if s.window != 1]
    scores += [score(1, LEADER_COLUMN, "0.30", "0"), score(1, FOLLOWER_COLUMN, "0.26", "0.02")]
    assert evaluate_windows(scores, THRESHOLD) == (2, 4)


def test_one_failing_column_fails_the_whole_window():
    """§7: a window is PASSED only if **both** gates pass."""
    verdict = evaluate_windows_detail(passing_scores(), THRESHOLD).verdict_for(3)
    assert not verdict.passed
    assert verdict.column_for(LEADER_COLUMN).passed
    assert not verdict.column_for(FOLLOWER_COLUMN).passed


def test_a_failing_column_says_which_condition_failed():
    verdict = evaluate_windows_detail(passing_scores(), THRESHOLD).verdict_for(3)
    reasons = " ".join(verdict.column_for(FOLLOWER_COLUMN).reasons)
    assert "mean advantage" in reasons
    assert "0.10" in reasons and "0.24" in reasons


def test_a_passing_column_carries_no_reasons():
    verdict = evaluate_windows_detail(passing_scores(), THRESHOLD).verdict_for(1)
    assert verdict.column_for(LEADER_COLUMN).reasons == ()
    assert verdict.reasons == ()


# -- INDETERMINATE is never a pass ----------------------------------------------


def test_indeterminate_fails_even_against_an_absurd_threshold():
    """§7.1's small-denominator guard. This is the invariant the whole module exists for.

    The threshold below is -10^9: every mean advantage clears it, and the median is positive. The
    only thing standing between an unmeasurable window and a green dashboard is the status.
    """
    scores = [s for s in passing_scores() if s.window != 1]
    scores += [
        score(1, LEADER_COLUMN, "0.30", "0.05",
              status=EdgeOriginStatus.INDETERMINATE, share=None, contribution="0.03"),
        score(1, FOLLOWER_COLUMN, "0.26", "0.02"),
    ]
    passed, total = evaluate_windows(scores, D("-1000000000"))
    assert total == 4
    assert passed == 3  # windows 2, 3, 4 — window 1 cannot pass at any threshold


def test_indeterminate_says_so():
    scores = [
        score(1, LEADER_COLUMN, "0.30", "0.05",
              status=EdgeOriginStatus.INDETERMINATE, share=None, contribution="0.03"),
        score(1, FOLLOWER_COLUMN, "0.26", "0.02"),
    ]
    verdict = evaluate_windows_detail(scores, THRESHOLD).verdict_for(1)
    assert not verdict.passed
    assert "INDETERMINATE" in " ".join(verdict.column_for(LEADER_COLUMN).reasons)


def test_uncopyable_dominated_is_a_hard_failure():
    """§7.1 condition 3: first-hour edge share above 40% fails the window outright."""
    scores = [
        score(1, LEADER_COLUMN, "0.90", "0.50",
              status=EdgeOriginStatus.UNCOPYABLE_DOMINATED, share="0.62"),
        score(1, FOLLOWER_COLUMN, "0.90", "0.50"),
    ]
    assert evaluate_windows(scores, THRESHOLD) == (0, 1)


def test_a_window_missing_a_column_cannot_pass():
    """A window with no follower-adjusted result has not passed both gates; it has one result."""
    scores = [score(1, LEADER_COLUMN, "0.30", "0.05")]
    verdict = evaluate_windows_detail(scores, THRESHOLD).verdict_for(1)
    assert not verdict.passed
    assert verdict.missing_columns == (FOLLOWER_COLUMN,)


def test_two_results_for_the_same_window_and_column_are_refused():
    """Nothing may select between two answers to the same question."""
    scores = passing_scores() + [score(3, FOLLOWER_COLUMN, "0.99", "0.99")]
    with pytest.raises(ConflictingResults) as excinfo:
        evaluate_windows(scores, THRESHOLD)
    assert "window 3" in str(excinfo.value)
    assert FOLLOWER_COLUMN in str(excinfo.value)


def test_a_diagnostic_column_cannot_reach_the_gate():
    """§10: reporting a diagnostic and then using it to overturn a gate is the failure mode this
    whole protocol exists to prevent. The engine refuses to read one at all."""
    scores = passing_scores() + [score(1, "absolute_profit_ranking", "9", "9")]
    with pytest.raises(DiagnosticInputRefused) as excinfo:
        evaluate_windows(scores, THRESHOLD)
    assert "absolute_profit_ranking" in str(excinfo.value)


# -- §7.2 capital feasibility ----------------------------------------------------


def test_capital_is_feasible_only_when_both_design_levels_are_positive():
    assert feasible_capital().feasible
    assert not feasible_capital(a="0.05", b="0").feasible
    assert not feasible_capital(a="-0.01", b="0.03").feasible


def test_a_missing_design_level_is_a_failure_not_an_abstention():
    """Ticket 33: INDETERMINATE resolves to failure, not abstention."""
    assessment = assess_capital_feasibility({DESIGN_CAPITAL_LEVELS[0]: D("0.05")})
    assert not assessment.feasible
    assert assessment.missing_levels == (DESIGN_CAPITAL_LEVELS[1],)


def test_an_unmeasured_design_level_is_a_failure():
    assessment = feasible_capital(a="0.05", b=None)
    assert not assessment.feasible
    assert "2000000" in " ".join(assessment.reasons)


def test_the_three_non_gating_levels_are_recorded_but_do_not_decide():
    """§3.1 simulates five levels; only $1.5M and $2.0M gate."""
    assessment = assess_capital_feasibility({
        D("100000"): D("-0.50"),
        D("250000"): D("-0.40"),
        D("500000"): D("-0.20"),
        DESIGN_CAPITAL_LEVELS[0]: D("0.05"),
        DESIGN_CAPITAL_LEVELS[1]: D("0.03"),
    })
    assert assessment.feasible
    assert assessment.excess_by_level[D("100000")] == D("-0.50")


# -- §9.6 freeze manifest --------------------------------------------------------


def test_a_consistent_manifest_reports_nothing():
    assert check_freeze_manifest(manifest(), manifest()) == []


def test_a_changed_dataset_snapshot_is_named():
    findings = check_freeze_manifest(manifest(), manifest(dataset_snapshot="snapshot-9999"))
    assert len(findings) == 1
    assert "dataset_snapshot" in findings[0]
    assert "snapshot-11111111" in findings[0] and "snapshot-9999" in findings[0]


def test_an_unpinned_field_is_reported():
    pinned = manifest()
    del pinned["decoder_version"]
    findings = check_freeze_manifest(pinned, manifest())
    assert any("decoder_version" in f and "not pinned" in f for f in findings)


def test_an_empty_pin_is_not_a_pin():
    findings = check_freeze_manifest(manifest(master_seed=""), manifest(master_seed=""))
    assert any("master_seed" in f for f in findings)


def test_an_unobserved_field_is_not_a_match():
    observed = manifest()
    del observed["model_version"]
    findings = check_freeze_manifest(manifest(), observed)
    assert any("model_version" in f and "not observed" in f for f in findings)


def test_a_numeric_policy_from_another_experiment_is_refused():
    """A manifest pinned under a different decimal policy describes different arithmetic."""
    findings = check_freeze_manifest(
        manifest(numeric_policy_version="decimal-v0"),
        manifest(numeric_policy_version="decimal-v0"),
    )
    assert any("numeric_policy_version" in f for f in findings)


def test_the_manifest_hash_is_the_identifier_every_result_binds_to():
    check = check_freeze_manifest_detail(manifest(), manifest())
    assert check.ok
    assert check.manifest_hash == canonical_hash(check.pinned)
    assert check.manifest_hash != check_freeze_manifest_detail(
        manifest(model_version="model-v2"), manifest(model_version="model-v2")
    ).manifest_hash


# -- artifact envelopes ----------------------------------------------------------


def test_a_freshly_written_envelope_verifies():
    envelope = artifact_envelope("window_scores", "scoring", {"window": 1, "mean": D("0.30")})
    assert verify_envelope(envelope) == []


def test_a_tampered_payload_is_caught_by_the_hash():
    envelope = artifact_envelope("window_scores", "scoring", {"window": 1, "mean": D("0.30")})
    envelope["payload"]["mean"] = "0.99"
    findings = verify_envelope(envelope)
    assert any("payload_hash" in f for f in findings)


def test_an_envelope_from_an_older_enum_schema_is_refused():
    envelope = artifact_envelope("window_scores", "scoring", {"window": 1}, schema_version=0)
    assert any("schema_version" in f for f in verify_envelope(envelope))


def test_an_envelope_missing_its_provenance_is_refused():
    envelope = artifact_envelope("window_scores", "scoring", {"window": 1})
    del envelope["produced_by"]
    assert any("produced_by" in f for f in verify_envelope(envelope))


# -- schema validity -------------------------------------------------------------


WINDOW_SCHEMA = (
    FieldSpec("window", "int_string"),
    FieldSpec("column", "enum", allowed=(LEADER_COLUMN, FOLLOWER_COLUMN)),
    FieldSpec("mean_advantage", "decimal_string"),
    FieldSpec("first_hour_edge_share", "decimal_string", optional=True),
    FieldSpec("copyable", "bool"),
)


def test_a_well_formed_payload_reports_nothing():
    payload = {
        "window": "1",
        "column": LEADER_COLUMN,
        "mean_advantage": "0.30",
        "first_hour_edge_share": None,
        "copyable": True,
    }
    assert check_schema(payload, WINDOW_SCHEMA) == []


def test_a_json_number_where_a_decimal_belongs_is_a_schema_violation():
    """The single most valuable schema check here: a JSON number is a double in nearly every
    reader, which reintroduces the float the whole seam design exists to avoid."""
    payload = {
        "window": "1",
        "column": LEADER_COLUMN,
        "mean_advantage": 0.30,
        "first_hour_edge_share": None,
        "copyable": True,
    }
    findings = check_schema(payload, WINDOW_SCHEMA)
    assert any("mean_advantage" in f and "JSON number" in f for f in findings)


def test_an_absent_field_is_not_an_optional_one():
    """``None`` is a state (INDETERMINATE). Absence is a missing field, and they differ."""
    payload = {"window": "1", "column": LEADER_COLUMN, "mean_advantage": "0.30", "copyable": True}
    assert any("first_hour_edge_share" in f and "absent" in f
               for f in check_schema(payload, WINDOW_SCHEMA))


def test_a_null_in_a_required_field_is_refused():
    payload = {
        "window": "1", "column": LEADER_COLUMN, "mean_advantage": None,
        "first_hour_edge_share": None, "copyable": True,
    }
    assert any("mean_advantage" in f and "null" in f for f in check_schema(payload, WINDOW_SCHEMA))


def test_an_unknown_enum_value_is_refused():
    payload = {
        "window": "1", "column": "diagnostic", "mean_advantage": "0.30",
        "first_hour_edge_share": None, "copyable": True,
    }
    assert any("column" in f for f in check_schema(payload, WINDOW_SCHEMA))


def test_a_raw_quantity_that_is_not_an_integer_string_is_refused():
    payload = {
        "window": "1.5", "column": LEADER_COLUMN, "mean_advantage": "0.30",
        "first_hour_edge_share": None, "copyable": True,
    }
    assert any("window" in f for f in check_schema(payload, WINDOW_SCHEMA))


# -- §9.2 exact deterministic fields ---------------------------------------------


GOLDEN_EVENT = {
    "transaction_hash": "0x" + "ab" * 32,
    "block_number": "18000000",
    "wallet_address": "0x" + "cd" * 20,
    "token_address": "0x" + "ef" * 20,
    "pool_address": "0x" + "12" * 20,
    "direction": "VALID_BUY",
    "raw_token_quantity": "1000000000000000000000",
    "raw_quote_quantity": "5000000000",
    "fifo_lot_assignment": "lot-1",
    "realized_status": "REALIZED",
}


def test_an_identical_event_reports_nothing():
    assert check_exact_fields(GOLDEN_EVENT, dict(GOLDEN_EVENT)) == []


def test_a_raw_quantity_off_by_one_wei_fails():
    """§9.2: raw token amounts match at the raw-unit level, with no percentage tolerance."""
    observed = dict(GOLDEN_EVENT, raw_token_quantity="1000000000000000000001")
    findings = check_exact_fields(GOLDEN_EVENT, observed)
    assert len(findings) == 1
    assert "raw_token_quantity" in findings[0]


def test_a_different_fifo_lot_assignment_fails():
    observed = dict(GOLDEN_EVENT, fifo_lot_assignment="lot-2")
    assert any("fifo_lot_assignment" in f for f in check_exact_fields(GOLDEN_EVENT, observed))


def test_an_absent_deterministic_field_fails():
    observed = dict(GOLDEN_EVENT)
    del observed["pool_address"]
    assert any("pool_address" in f for f in check_exact_fields(GOLDEN_EVENT, observed))


# -- §9.2 tolerance-controlled numeric fields ------------------------------------


USD_SPEC = ToleranceSpec("event_value_usd", USD_RELATIVE_TOLERANCE, relative=True)
BQ_SPEC = ToleranceSpec("buy_quality_pp", BUY_QUALITY_ABSOLUTE_TOLERANCE_PP, relative=False)


def test_a_relative_error_inside_half_a_percent_passes():
    """0.01 / 3 = 0.00333..., which needs the frozen 38-digit context to state exactly."""
    with localcontext(CALCULATION_CONTEXT):
        expected_relative = +(divide(D("0.01"), D("3")))

    check = check_numeric_fields_detail({"event_value_usd": D("3")},
                                        {"event_value_usd": D("3.01")}, (USD_SPEC,))
    comparison = check.comparison_for("event_value_usd")

    assert comparison.relative_error == expected_relative
    assert comparison.within
    assert check.ok


def test_a_relative_error_above_half_a_percent_fails():
    """100 -> 100.6 is 0.006, above the 0.005 ceiling. Hand-computed: 0.6 / 100."""
    with localcontext(CALCULATION_CONTEXT):
        expected_relative = +(divide(+(D("100.6") - D("100")), D("100")))
    assert expected_relative == D("0.006")

    check = check_numeric_fields_detail({"event_value_usd": D("100")},
                                        {"event_value_usd": D("100.6")}, (USD_SPEC,))
    assert not check.ok
    assert check.comparison_for("event_value_usd").relative_error == expected_relative
    assert any("event_value_usd" in f and "0.006" in f for f in check.messages)


def test_the_tolerance_boundary_itself_passes():
    """Exactly 0.5% is inside the ceiling: §9.2 says 'maximum relative error 0.5%'."""
    assert check_numeric_fields({"event_value_usd": D("100")},
                                {"event_value_usd": D("100.5")}, (USD_SPEC,)) == []


def test_buy_quality_uses_an_absolute_tolerance_in_percentage_points():
    """§9.2: 0.5 **percentage points**, not 0.5% relative. A 12.0pp expectation against 12.4pp is
    inside; against a relative rule it would be too, which is exactly why the units are pinned."""
    assert check_numeric_fields({"buy_quality_pp": D("12.0")},
                                {"buy_quality_pp": D("12.4")}, (BQ_SPEC,)) == []
    assert check_numeric_fields({"buy_quality_pp": D("12.0")},
                                {"buy_quality_pp": D("12.6")}, (BQ_SPEC,)) != []


def test_a_relative_tolerance_against_a_zero_baseline_demands_exactness():
    """A ratio with a zero denominator has no value, and both tempting fallbacks are wrong:
    zero passes everything, infinity fails everything. Exact equality is the only honest rule."""
    check = check_numeric_fields_detail({"event_value_usd": D("0")},
                                        {"event_value_usd": D("0.0001")}, (USD_SPEC,))
    assert check.comparison_for("event_value_usd").relative_error is None
    assert not check.ok

    assert check_numeric_fields({"event_value_usd": D("0")},
                                {"event_value_usd": D("0")}, (USD_SPEC,)) == []


def test_an_unreported_numeric_field_never_passes():
    assert any("event_value_usd" in f
               for f in check_numeric_fields({"event_value_usd": D("3")}, {}, (USD_SPEC,)))


# -- §9.8 validation gate summary ------------------------------------------------


def clean_validation_report(**overrides):
    report = {
        "golden_set_precision": D("1"),
        "golden_set_recall": D("1"),
        "known_answer_pass_rate": D("1"),
        "raw_quantity_mismatches": 0,
        "fifo_assignment_mismatches": 0,
        "max_per_event_usd_relative_error": D("0.004"),
        "max_wallet_buy_quality_difference_pp": D("0.4"),
        "reconciliation_event_agreement": D("0.996"),
        "unexplained_golden_set_differences": 0,
        "independent_review_completed": True,
    }
    report.update(overrides)
    return report


def test_the_ten_conditions_all_hold_on_a_clean_report():
    assert len(VALIDATION_GATE_CONDITIONS) == 10
    assert check_validation_gate(clean_validation_report()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("golden_set_precision", D("0.999")),
        ("golden_set_recall", D("0.999")),
        ("known_answer_pass_rate", D("0.99")),
        ("raw_quantity_mismatches", 1),
        ("fifo_assignment_mismatches", 1),
        ("max_per_event_usd_relative_error", D("0.006")),
        ("max_wallet_buy_quality_difference_pp", D("0.6")),
        ("reconciliation_event_agreement", D("0.994")),
        ("unexplained_golden_set_differences", 1),
        ("independent_review_completed", False),
    ],
)
def test_failing_any_single_condition_fails_the_gate(field, value):
    """§9.8: failure of **any** condition leaves the null and the main test unauthorised."""
    findings = check_validation_gate(clean_validation_report(**{field: value}))
    assert len(findings) == 1
    assert field in findings[0]


def test_an_unreported_condition_is_a_failure_not_a_pass():
    report = clean_validation_report()
    del report["independent_review_completed"]
    assert any("independent_review_completed" in f and "not reported" in f
               for f in check_validation_gate(report))


def test_reconciliation_coverage_on_the_golden_set_must_be_total():
    """§9.4: 100% supported coverage, zero unexplained missing or extra trades."""
    clean = {
        "supported_transaction_coverage": D("1"),
        "unexplained_missing_trades": 0,
        "unexplained_extra_trades": 0,
        "raw_balance_delta_mismatches": 0,
        "sample_event_agreement": D("0.996"),
        "sample_notional_agreement": D("0.997"),
    }
    assert len(RECONCILIATION_CONDITIONS) == 6
    assert check_reconciliation_coverage(clean) == []
    assert any("unexplained_missing_trades" in f
               for f in check_reconciliation_coverage(dict(clean, unexplained_missing_trades=1)))


# -- ordering --------------------------------------------------------------------


def test_the_prescribed_governance_prefix_is_accepted():
    assert check_state_sequence(GOVERNANCE_ORDER) == []
    assert check_state_sequence(GOVERNANCE_ORDER[:4]) == []


def test_a_skipped_stage_is_caught():
    """§9.1 is binding: the null cannot be built before validation passes, because the null is
    computed by the same code and a shared bug is invisible to it."""
    states = ("PARAMETERS_OPEN", "PARAMETERS_FROZEN", "NULL_COMPLETE")
    findings = check_state_sequence(states)
    assert any("VALIDATION_PASSED" in f for f in findings)


def test_a_repeated_stage_is_caught():
    states = ("PARAMETERS_OPEN", "PARAMETERS_FROZEN", "PARAMETERS_FROZEN")
    assert check_state_sequence(states) != []


def test_a_run_that_never_started_is_caught():
    assert any("no" in f.lower() for f in check_state_sequence(()))


def test_the_validation_layers_must_run_in_the_written_order():
    assert check_layer_order(VALIDATION_LAYER_ORDER) == []
    swapped = (VALIDATION_LAYER_ORDER[1], VALIDATION_LAYER_ORDER[0]) + VALIDATION_LAYER_ORDER[2:]
    assert check_layer_order(swapped) != []


# -- §9.7 invalidation -----------------------------------------------------------


def test_an_invalidated_run_emits_nothing():
    status = invalidate(RunStatus(code_version=CODE_VERSION), "FIFO rule was wrong")
    assert status.invalidated
    assert not status.permits_decision

    with pytest.raises(FreezeViolation) as excinfo:
        emit_decision(
            evidence(run_status=status),
            evaluate_windows_detail(passing_scores(), THRESHOLD),
            feasible_capital(),
            null(LEADER_COLUMN),
            null(FOLLOWER_COLUMN),
        )
    assert "run_status" in str(excinfo.value)


def test_registering_a_new_version_clears_the_invalidation_and_discards_the_old_result():
    invalidated = invalidate(RunStatus(code_version=CODE_VERSION), "FIFO rule was wrong")
    fixed = register_code_version(invalidated, "b" * 40)

    assert not fixed.invalidated
    assert fixed.code_version == "b" * 40
    assert fixed.discarded_versions == (CODE_VERSION,)
    assert fixed.permits_decision


def test_re_registering_the_same_version_is_a_patch_and_is_refused():
    invalidated = invalidate(RunStatus(code_version=CODE_VERSION), "FIFO rule was wrong")
    with pytest.raises(FreezeViolation) as excinfo:
        register_code_version(invalidated, CODE_VERSION)
    assert "patch" in str(excinfo.value).lower()


def test_registering_a_version_on_a_valid_run_is_refused():
    with pytest.raises(FreezeViolation):
        register_code_version(RunStatus(code_version=CODE_VERSION), "b" * 40)


def test_a_result_from_a_discarded_version_can_never_be_quoted_again():
    """§9.7: selectively using the old or the new result is prohibited."""
    fixed = register_code_version(
        invalidate(RunStatus(code_version=CODE_VERSION), "bug"), "b" * 40
    )
    assert require_current_version(fixed, "b" * 40) is True
    with pytest.raises(FreezeViolation) as excinfo:
        require_current_version(fixed, CODE_VERSION)
    assert CODE_VERSION in str(excinfo.value)


# -- §7.5 the three-state outcome ------------------------------------------------


def emit(**overrides):
    args = dict(
        evidence=evidence(),
        evaluation=evaluate_windows_detail(passing_scores(), THRESHOLD),
        capital_feasibility=feasible_capital(),
        leader_null=null(LEADER_COLUMN),
        follower_null=null(FOLLOWER_COLUMN),
    )
    args.update(overrides)
    return emit_decision(**args)


def test_three_of_four_windows_both_columns_significant_is_go():
    decision = emit()
    assert decision.outcome is GateOutcome.GO
    assert (decision.windows_passed, decision.windows_total) == (MIN_PASSING_WINDOWS, 4)
    assert decision.leader_significant and decision.follower_significant
    assert not decision.capital_feasibility_failed


def test_leader_passes_but_capital_feasibility_fails_is_conditional_review():
    """§7.5: a raw positive leader edge may not conceal an execution-capacity failure."""
    decision = emit(capital_feasibility=feasible_capital(a="0.05", b="-0.02"))
    assert decision.outcome is GateOutcome.CONDITIONAL_REVIEW
    assert decision.capital_feasibility_failed
    assert any("reduce_design_capital" in r for r in decision.reasons)


def test_an_unmeasured_design_level_also_produces_conditional_review():
    decision = emit(capital_feasibility=feasible_capital(a="0.05", b=None))
    assert decision.outcome is GateOutcome.CONDITIONAL_REVIEW


def test_two_of_four_windows_is_stop():
    scores = [s for s in passing_scores() if s.window != 1]
    scores += [score(1, LEADER_COLUMN, "0.10", "0.05"), score(1, FOLLOWER_COLUMN, "0.10", "0.02")]
    decision = emit(evaluation=evaluate_windows_detail(scores, THRESHOLD))
    assert decision.outcome is GateOutcome.STOP
    assert decision.windows_passed == 2


def test_an_insignificant_follower_column_is_stop_not_conditional_review():
    """Insignificance is not a capital-feasibility failure, so there is nothing to review."""
    decision = emit(follower_null=null(FOLLOWER_COLUMN, observed="0.010", p="0.57142857142857142857142857142857142857"))
    assert decision.outcome is GateOutcome.STOP
    assert not decision.follower_significant


def test_an_insignificant_leader_column_is_stop():
    decision = emit(leader_null=null(LEADER_COLUMN, observed="0.010", p="0.57142857142857142857142857142857142857"))
    assert decision.outcome is GateOutcome.STOP


def test_a_stop_carries_the_preregistered_negative_wording():
    """§11.3: the conclusion is scoped to Ethereum Mainnet and this capital profile."""
    decision = emit(leader_null=null(LEADER_COLUMN, observed="0.010", p="0.57142857142857142857142857142857142857"))
    joined = " ".join(decision.reasons)
    assert "No sufficient persistent and copyable wallet-selection edge was found" in joined
    assert "Ethereum Mainnet" in joined


def test_a_null_distribution_from_the_wrong_column_is_refused():
    """Ticket 33: leader against the leader null, never borrowing the other's."""
    with pytest.raises(FreezeViolation) as excinfo:
        emit(leader_null=null(FOLLOWER_COLUMN))
    assert "leader_null" in str(excinfo.value)


def test_a_window_count_other_than_four_is_refused():
    scores = [s for s in passing_scores() if s.window != 4]
    with pytest.raises(FreezeViolation) as excinfo:
        emit(evaluation=evaluate_windows_detail(scores, THRESHOLD))
    assert "windows_total" in str(excinfo.value)


# -- the prerequisites, one refusal at a time -----------------------------------


def test_not_independent_validation_blocks_the_main_test():
    """§9.5. The block is governance, not a note in a report."""
    with pytest.raises(FreezeViolation) as excinfo:
        emit(evidence=evidence(validation_status=ValidationStatus.NOT_INDEPENDENT))
    assert "validation_status" in str(excinfo.value)


def test_machine_independent_validation_is_permitted_and_recorded():
    """Addendum §3: weaker than external review, stronger than none — and it does not block."""
    record = emit_decision_detail(
        evidence(validation_status=ValidationStatus.MACHINE_INDEPENDENT),
        evaluate_windows_detail(passing_scores(), THRESHOLD),
        feasible_capital(),
        null(LEADER_COLUMN),
        null(FOLLOWER_COLUMN),
    )
    assert record.decision.outcome is GateOutcome.GO
    assert record.decision.validation_status is ValidationStatus.MACHINE_INDEPENDENT


def test_a_changed_dataset_snapshot_blocks_the_decision():
    with pytest.raises(FreezeViolation) as excinfo:
        emit(evidence=evidence(observed=manifest(dataset_snapshot="snapshot-rebuilt")))
    assert "dataset_snapshot" in str(excinfo.value)


def test_a_missing_module_version_blocks_the_decision():
    pinned = module_versions()
    del pinned["fifo"]
    with pytest.raises(FreezeViolation) as excinfo:
        emit(evidence=evidence(pinned_module_versions=pinned))
    assert "fifo" in str(excinfo.value)


def test_a_mismatched_module_version_blocks_the_decision():
    with pytest.raises(FreezeViolation) as excinfo:
        emit(evidence=evidence(observed_module_versions=module_versions(marking="marking-9999")))
    assert "marking" in str(excinfo.value)


def test_an_unlocked_threshold_blocks_the_decision():
    with pytest.raises(FreezeViolation) as excinfo:
        emit(evidence=evidence(locked_threshold=None))
    assert "locked_threshold" in str(excinfo.value)


def test_a_threshold_changed_after_the_lock_blocks_the_decision():
    """§8.4 step 7: after observing the main result, nothing changes."""
    with pytest.raises(FreezeViolation) as excinfo:
        emit(evidence=evidence(locked_threshold=D("0.15")))
    assert "threshold" in str(excinfo.value)
    assert "0.15" in str(excinfo.value) and "0.24" in str(excinfo.value)


def test_a_main_test_that_ran_before_the_threshold_was_locked_blocks_the_decision():
    states = ("PARAMETERS_OPEN", "PARAMETERS_FROZEN", "VALIDATION_PASSED",
              "CODE_AND_DATA_FROZEN", "NULL_COMPLETE", "MAIN_TEST_EXECUTED")
    with pytest.raises(FreezeViolation) as excinfo:
        emit(evidence=evidence(governance_states=states))
    assert "governance_states" in str(excinfo.value)


def test_a_main_test_that_never_ran_blocks_the_decision():
    with pytest.raises(FreezeViolation) as excinfo:
        emit(evidence=evidence(governance_states=GOVERNANCE_ORDER[:6]))
    assert "MAIN_TEST_EXECUTED" in str(excinfo.value)


def test_a_result_from_a_superseded_code_version_blocks_the_decision():
    fixed = register_code_version(invalidate(RunStatus(code_version=CODE_VERSION), "bug"), "b" * 40)
    with pytest.raises(FreezeViolation) as excinfo:
        emit(evidence=evidence(run_status=fixed, result_code_version=CODE_VERSION))
    assert CODE_VERSION in str(excinfo.value)


def test_a_manifest_commit_that_disagrees_with_the_running_code_blocks_the_decision():
    with pytest.raises(FreezeViolation) as excinfo:
        emit(evidence=evidence(manifest=manifest(source_commit="z" * 40),
                               observed=manifest(source_commit="z" * 40)))
    assert "source_commit" in str(excinfo.value)


def test_every_refusal_names_a_field_and_none_of_them_warn():
    """A warning that still emits is worse than no check: it certifies the result anyway."""
    with pytest.raises(FreezeViolation) as excinfo:
        emit(evidence=evidence(locked_threshold=None,
                               validation_status=ValidationStatus.NOT_INDEPENDENT))
    message = str(excinfo.value)
    assert "locked_threshold" in message and "validation_status" in message


# -- the record ------------------------------------------------------------------


def test_the_record_binds_the_decision_to_the_manifest_hash():
    """Ticket 43: the outcome cannot be quoted detached from the experiment that produced it."""
    record = emit_decision_detail(
        evidence(),
        evaluate_windows_detail(passing_scores(), THRESHOLD),
        feasible_capital(),
        null(LEADER_COLUMN),
        null(FOLLOWER_COLUMN),
    )
    assert record.manifest_hash == canonical_hash(check_freeze_manifest_detail(
        manifest(), manifest()).pinned)
    assert record.decision.manifest.dataset_snapshot == manifest()["dataset_snapshot"]


def test_the_record_survives_canonical_serialization():
    """A leaked float raises inside ``canonicalise``; this is where it would surface."""
    record = emit_decision_detail(
        evidence(),
        evaluate_windows_detail(passing_scores(), THRESHOLD),
        feasible_capital(),
        null(LEADER_COLUMN),
        null(FOLLOWER_COLUMN),
    )
    encoded = to_canonical_json(record)
    assert '"outcome":"GO"' in encoded
    assert to_canonical_json(record) == encoded


def test_the_decision_itself_survives_canonical_serialization():
    encoded = to_canonical_json(emit())
    assert '"windows_passed":"3"' in encoded
    assert '"windows_total":"4"' in encoded


def test_a_tolerance_discrepancy_reports_the_difference_at_full_precision():
    """The message is the arbiter's evidence, so it may not round what the comparison did not.

        observed  1.2345678901234567890123456789012345678   (38 digits)
        expected  0.1
        -------------------------------------------------
        difference 1.1345678901234567890123456789012345678

    ``_compare`` computes that inside the frozen block and stores all 38 digits on the
    ``NumericComparison``. The sentence built from it must carry the same number: a reviewer who
    subtracts the two quoted operands has to land on the quoted difference, and a difference
    truncated to the ambient 28 digits does not reconcile against the expected and observed values
    printed beside it.
    """
    spec = ToleranceSpec("event_value_usd", D("0.001"), relative=False)

    check = check_numeric_fields_detail(
        {"event_value_usd": "0.1"},
        {"event_value_usd": "1.2345678901234567890123456789012345678"},
        (spec,),
    )

    detail = check.report.discrepancies[0].detail
    assert "1.1345678901234567890123456789012345678" in detail
    assert check.comparisons[0].difference == D("1.1345678901234567890123456789012345678")


# -- §7.1's third condition: the pair must be capable of both being true ---------


def test_a_valid_status_with_a_share_above_the_limit_is_refused():
    """The gap ticket 33's audit found, closed.

    §7.1's third condition reaches the arbiter as ``edge_origin_status``, an enum ``scoring``
    computed, and ``first_hour_edge_share`` arrives in the same object. Nothing compared them — so a
    scoring defect stamping ``VALID`` on a first-hour share of 0.95 produced a GO that no test in
    this package could distinguish from a real one, while the number that would have exposed it sat
    unread one attribute away.

    This is **not** the arbiter growing a second copy of the gate rule, which this module's own
    docstring rightly forbids. No verdict is derived: the two supplied fields are checked against
    each other, and an impossible pair raises rather than being resolved. Choosing a side is the
    thing that publishes a number nobody can defend.
    """
    score = WindowScore(
        window=1, column=LEADER_COLUMN,
        mean_advantage=D("0.30"), median_advantage=D("0.20"),
        first_hour_edge_share=D("0.95"),
        positive_edge_contribution=D("0.50"),
        edge_origin_status=EdgeOriginStatus.VALID,
    )

    with pytest.raises(InconsistentEdgeOrigin) as caught:
        evaluate_windows_detail([score], D("0.15"))

    message = str(caught.value)
    assert "cannot both be true" in message
    assert "0.95" in message and "0.40" in message
    assert "Refusing rather than choosing one" in message


def test_an_uncopyable_status_within_the_limit_is_refused_too():
    """The other direction, and it costs a finding rather than manufacturing one.

    A window wrongly marked ``UNCOPYABLE_DOMINATED`` while its share is inside the limit fails a
    window that should have passed. That is the safer error, and it is still refused — the arbiter
    does not know which of the two fields is the defect, and silently trusting the status here would
    be trusting it in the dangerous direction too.
    """
    score = WindowScore(
        window=1, column=LEADER_COLUMN,
        mean_advantage=D("0.30"), median_advantage=D("0.20"),
        first_hour_edge_share=D("0.10"),
        positive_edge_contribution=D("0.50"),
        edge_origin_status=EdgeOriginStatus.UNCOPYABLE_DOMINATED,
    )

    with pytest.raises(InconsistentEdgeOrigin) as caught:
        evaluate_windows_detail([score], D("0.15"))
    assert "costs a finding rather than manufacturing one" in str(caught.value)


def test_exactly_forty_percent_is_consistent_with_valid():
    """Ticket 09 resolved §7.1 as *strictly greater than* 40% fails, so 40% is a passing share.

    The boundary, on the side that matters: a check written with ``>=`` would refuse a window the
    pre-registration admits, and the refusal would look like a scoring defect.
    """
    score = WindowScore(
        window=1, column=LEADER_COLUMN,
        mean_advantage=D("0.30"), median_advantage=D("0.20"),
        first_hour_edge_share=FIRST_HOUR_EDGE_SHARE_MAX,
        positive_edge_contribution=D("0.50"),
        edge_origin_status=EdgeOriginStatus.VALID,
    )

    evaluation = evaluate_windows_detail([score], D("0.15"))
    assert evaluation.verdicts[0].columns[0].passed is True


def test_indeterminate_carries_no_share_and_is_exempt():
    """Nothing to be consistent with. The share could not be measured, which is the status."""
    score = WindowScore(
        window=1, column=LEADER_COLUMN,
        mean_advantage=D("0.30"), median_advantage=D("0.20"),
        first_hour_edge_share=None,
        positive_edge_contribution=D("0.001"),
        edge_origin_status=EdgeOriginStatus.INDETERMINATE,
    )

    evaluation = evaluate_windows_detail([score], D("0.15"))
    assert evaluation.verdicts[0].columns[0].passed is False


def test_the_arbiter_holds_the_limit_itself_rather_than_reading_it_from_the_builder():
    """Ticket 33's criterion 10, as far as the lane rule permits.

    Before this the package had **no first-hour limit at all** — grep found no 0.40 anywhere in
    ``src/gate_validation/``. It could not have checked the condition even in principle. The
    constant is a copy, because importing ``phase0`` would let the arbiter reach the lane it
    judges; it is held equal to the frozen ``gate.first_hour_edge_share_max`` by a test in
    ``tests/hand_computed/test_parameters.py``, which is what this boundary allows.
    """
    assert FIRST_HOUR_EDGE_SHARE_MAX == D("0.40")


# -- §7.3: the arbiter recomputes the bounds it was handed -----------------------


def test_a_declared_p_value_the_distribution_cannot_reach_is_refused():
    """The other half of ticket 33's headline finding.

    §7.3's two bounds arrive as *fields* the caller declares, while ``null_statistics`` — the
    distribution both are derived from — arrives in the same object. Until this check existed the
    arbiter read the fields and never the statistics, so a null summary off by one rung produced a
    GO indistinguishable from a real one.

    The case that made this concrete: the fixtures in this very file declared ``empirical_p`` of
    0.01 over a three-run distribution. Three runs cannot report below 1/(3+1) = 0.25, so ``p <=
    0.05`` was arithmetically unreachable and the suite simply asserted it. **The §7.3 path had
    never been exercised on data that could legitimately be significant.**
    """
    honest = null(LEADER_COLUMN)
    lying = PermutationResult(
        column=LEADER_COLUMN,
        observed_statistic=honest.observed_statistic,
        null_statistics=honest.null_statistics,
        n_runs=honest.n_runs,
        percentile_95=honest.percentile_95,
        empirical_p=D("0.008"),
        null_pass_rate=honest.null_pass_rate,
    )

    with pytest.raises(InconsistentNullSummary) as caught:
        emit(leader_null=lying)

    message = str(caught.value)
    assert "smallest p-value 20 runs can report" in message
    assert "a claim the evidence does not reach" in message


def test_a_declared_percentile_the_distribution_does_not_support_is_refused():
    """The percentile decides which observed values clear §7.3 at all.

    Nearest-rank is a genuine degree of freedom — at n = 1,000 it is the 950th value, where the
    linear conventions land between the 950th and 951st — so a declared percentile that the
    distribution does not produce is a gate decided on a number nothing measured.
    """
    honest = null(LEADER_COLUMN)
    lying = PermutationResult(
        column=LEADER_COLUMN,
        observed_statistic=honest.observed_statistic,
        null_statistics=honest.null_statistics,
        n_runs=honest.n_runs,
        percentile_95=D("0.0001"),
        empirical_p=honest.empirical_p,
        null_pass_rate=honest.null_pass_rate,
    )

    with pytest.raises(InconsistentNullSummary) as caught:
        emit(leader_null=lying)
    assert "nearest-rank 95th percentile of its own" in str(caught.value)


def test_twenty_runs_is_the_smallest_distribution_that_can_clear_the_gate():
    """1/(n+1) <= 0.05 requires n >= 19, and the fixtures now sit at 20.

    Stated as a test because it is the fact the old fixtures violated, and because it is the reason
    a "significant" case cannot be written smaller. The floor is not a convention — it is what the
    +1 permutation correction means: a distribution no run beat still cannot claim p = 0.
    """
    from gate_validation.decision import _empirical_p

    nineteen = tuple(divide(n, 1000) for n in range(1, 20))
    assert _empirical_p(D("1"), nineteen) == divide(1, 20)
    assert divide(1, 20) <= D("0.05")

    eighteen = tuple(divide(n, 1000) for n in range(1, 19))
    assert _empirical_p(D("1"), eighteen) > D("0.05"), (
        "eighteen runs cannot reach p <= 0.05 even when no run beats the observed value"
    )
