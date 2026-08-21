"""The arbiter run the way the protocol will run it: artifacts on disk, read as data.

Every artifact below is round-tripped through ``to_canonical_json`` and ``json.loads`` before the
arbiter sees it, because that is exactly what happens in production and it is the only way to prove
the claim the package is built on: **gate_validation never imports the code it judges.** The
builder writes a file; the caller reads it; this module receives a dict. If a check here needed a
live object it would need the module that produces one, and an arbiter that can execute the code it
judges inherits that code's bug and then certifies it.

Two scenarios carry the file:

* **The clean run.** Validation layers in order, golden set exact, tolerances met, freeze manifest
  consistent, four windows scored, both columns significant — resolving to GO, bound to a manifest
  hash.
* **The invalidation drill** (§9.7, ticket 39). A real bug is found after the freeze. The run is
  invalidated, the decision is refused, a new code version is registered, and the old result
  becomes permanently unquotable. That last step is the one worth the test: both results exist on
  disk afterwards, and "selectively using the old or the new result is prohibited" means nothing
  unless something refuses to read one.
"""

import json
from decimal import Decimal

import pytest

from contracts import (
    NUMERIC_POLICY_VERSION,
    REPORTING_SCHEMA_VERSION,
    ClassificationStatus,
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
    CONDITIONAL_REVIEW_OPTIONS,
    DESIGN_CAPITAL_LEVELS,
    EXACT_MATCH_FIELDS,
    FOLLOWER_COLUMN,
    GOVERNANCE_ORDER,
    LEADER_COLUMN,
    NEGATIVE_RESULT_WORDING,
    REQUIRED_MANIFEST_FIELDS,
    REQUIRED_MODULES,
    USD_RELATIVE_TOLERANCE,
    VALIDATION_LAYER_ORDER,
    DiagnosticInputRefused,
    FieldSpec,
    RunEvidence,
    RunStatus,
    ToleranceSpec,
    assess_capital_feasibility,
    check_derived_fields,
    check_exact_fields,
    check_freeze_manifest,
    check_freeze_manifest_detail,
    check_layer_order,
    check_numeric_fields,
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
    require_conditional_review_decision,
    require_current_version,
    verify_envelope,
)

D = Decimal

THRESHOLD = D("0.24")
FROZEN_COMMIT = "3f1c9a" + "0" * 34
FIXED_COMMIT = "7b2e4d" + "0" * 34


def on_disk(value):
    """Write an artifact and read it back. The arbiter only ever sees the right-hand side."""
    return json.loads(to_canonical_json(value))


# -- the run's artifacts ---------------------------------------------------------


def freeze_manifest(commit=FROZEN_COMMIT):
    return {
        "source_commit": commit,
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


def validation_report():
    """§9.8, as the validator would write it."""
    return {
        "golden_set_precision": D("1"),
        "golden_set_recall": D("1"),
        "known_answer_pass_rate": D("1"),
        "raw_quantity_mismatches": 0,
        "fifo_assignment_mismatches": 0,
        "max_per_event_usd_relative_error": D("0.0031"),
        "max_wallet_buy_quality_difference_pp": D("0.28"),
        "reconciliation_event_agreement": D("0.9967"),
        "unexplained_golden_set_differences": 0,
        "independent_review_completed": True,
    }


def reconciliation_report():
    """§9.4, golden set plus the >=200 account random sample."""
    return {
        "supported_transaction_coverage": D("1"),
        "unexplained_missing_trades": 0,
        "unexplained_extra_trades": 0,
        "raw_balance_delta_mismatches": 0,
        "sample_event_agreement": D("0.9968"),
        "sample_notional_agreement": D("0.9974"),
    }


def golden_event(**overrides):
    """One golden-set buy, in raw units throughout — §9.2 admits no decimals conversion."""
    event = {
        "transaction_hash": "0x" + "9c" * 32,
        "block_number": 18_400_117,
        "wallet_address": "0x" + "4a" * 20,
        "token_address": "0x" + "de" * 20,
        "pool_address": "0x" + "b0" * 20,
        "direction": ClassificationStatus.VALID_BUY,
        "raw_token_quantity": 4_182_993_004_117_882_601_993,
        "raw_quote_quantity": 12_500_000_000,
        "fifo_lot_assignment": "lot-0007",
        "realized_status": "OPEN",
    }
    event.update(overrides)
    return event


def window_scores():
    """Four windows, both columns. Window 3's follower column misses the locked threshold."""
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


def permutation(column, significant=True):
    """§7.3, and every number here is the one the distribution actually produces.

    Until 2026-08-16 these fixtures declared p-values their own distributions could not reach — the
    "significant" case claimed p = 0.008 where twenty runs can report no lower than 1/21. Nothing
    checked, because the arbiter read the declared field and never the statistics beside it. So the
    §7.3 path had never been exercised on data that could legitimately be significant.

    ``divide(1, 21)`` is written out to its full 38 digits rather than computed, because a fixture
    that derives its expected value from the same helper the check uses proves only that the helper
    agrees with itself.
    """
    nulls = tuple(divide(n, 1000) for n in range(1, 21))
    return PermutationResult(
        column=column,
        observed_statistic=D("0.0410") if significant else D("0.0090"),
        null_statistics=nulls,
        n_runs=20,
        percentile_95=D("0.0190"),
        empirical_p=D("0.047619047619047619047619047619047619048") if significant
        else D("0.61904761904761904761904761904761904762"),
        null_pass_rate=D("0.041"),
    )


def evidence(commit=FROZEN_COMMIT, run_status=None, **overrides):
    fields = dict(
        manifest=on_disk(freeze_manifest(commit)),
        observed=on_disk(freeze_manifest(commit)),
        pinned_module_versions=on_disk(module_versions()),
        observed_module_versions=on_disk(module_versions()),
        validation_status=ValidationStatus.EXTERNALLY_REVIEWED,
        governance_states=GOVERNANCE_ORDER[:GOVERNANCE_ORDER.index("MAIN_TEST_EXECUTED") + 1],
        locked_threshold=THRESHOLD,
        run_status=run_status or RunStatus(code_version=commit),
        result_code_version=commit,
    )
    fields.update(overrides)
    return RunEvidence(**fields)


def feasible_capital(a="0.0362", b="0.0118"):
    return assess_capital_feasibility({
        DESIGN_CAPITAL_LEVELS[0]: None if a is None else D(a),
        DESIGN_CAPITAL_LEVELS[1]: None if b is None else D(b),
    })


# -- the clean run ---------------------------------------------------------------


def test_the_validation_layers_ran_in_the_binding_order():
    """§9.1. The pipeline proves itself correct before it computes anything that matters."""
    audit = on_disk(list(VALIDATION_LAYER_ORDER))
    assert check_layer_order(audit) == []


def test_the_governance_stages_reached_the_main_test_legitimately():
    states = on_disk(list(GOVERNANCE_ORDER[:GOVERNANCE_ORDER.index("MAIN_TEST_EXECUTED") + 1]))
    assert check_state_sequence(states) == []


def test_the_validation_gate_and_reconciliation_both_clear():
    assert check_validation_gate(on_disk(validation_report())) == []
    assert check_reconciliation_coverage(on_disk(reconciliation_report())) == []


def test_the_golden_set_event_matches_the_raw_chain_reader_exactly():
    """§9.2: raw amounts match at the raw-unit level, across a 22-digit quantity that no float
    could carry — 4,182,993,004,117,882,601,993 exceeds 2^53 by six orders of magnitude."""
    expected = on_disk(golden_event())
    observed = on_disk(golden_event())

    assert expected["raw_token_quantity"] == "4182993004117882601993"
    assert check_exact_fields(expected, observed) == []


def test_a_single_wei_of_drift_fails_the_golden_set():
    expected = on_disk(golden_event())
    observed = on_disk(golden_event(raw_token_quantity=4_182_993_004_117_882_601_994))
    findings = check_exact_fields(expected, observed)
    assert len(findings) == 1 and "raw_token_quantity" in findings[0]


def test_priced_fields_reconcile_inside_the_stated_tolerances():
    """§9.2: 0.5% relative on USD, 0.5 percentage points absolute on Buy Quality."""
    expected = on_disk({"event_value_usd": D("12500.000000"),
                        "wallet_buy_quality_pp": D("31.4000")})
    observed = on_disk({"event_value_usd": D("12531.250000"),
                        "wallet_buy_quality_pp": D("31.1200")})

    specs = (
        ToleranceSpec("event_value_usd", USD_RELATIVE_TOLERANCE, relative=True),
        ToleranceSpec("wallet_buy_quality_pp", BUY_QUALITY_ABSOLUTE_TOLERANCE_PP, relative=False),
    )
    assert check_numeric_fields(expected, observed, specs) == []

    # $12,500 -> $12,600 is 0.8%, above the 0.5% ceiling. Found and fixed, never averaged away.
    breached = on_disk({"event_value_usd": D("12600.000000"),
                        "wallet_buy_quality_pp": D("31.1200")})
    assert any("event_value_usd" in f for f in check_numeric_fields(expected, breached, specs))


def test_a_builder_artifact_verifies_end_to_end_as_a_file():
    """Schema, envelope integrity, and derived-field consistency, on one artifact read from JSON."""
    payload = {
        "capital_level": D("1500000"),
        "intended_order_usd": D("4000"),
        "filled_order_usd": D("3800"),
        "fill_ratio": divide(D("3800"), D("4000")),
        "copyable": True,
        "rejection_reason": None,
    }
    envelope = on_disk(artifact_envelope("copy_simulation", "depth", payload))

    assert verify_envelope(envelope) == []

    schema = (
        FieldSpec("capital_level", "decimal_string"),
        FieldSpec("intended_order_usd", "decimal_string"),
        FieldSpec("filled_order_usd", "decimal_string"),
        FieldSpec("fill_ratio", "decimal_string"),
        FieldSpec("copyable", "bool"),
        FieldSpec("rejection_reason", "string", optional=True),
    )
    assert check_schema(envelope["payload"], schema) == []

    # A derived field is a redundant assertion, never authoritative. Recompute it.
    recompute = {"fill_ratio": lambda p: divide(D(p["filled_order_usd"]),
                                                D(p["intended_order_usd"]))}
    assert check_derived_fields(envelope["payload"], recompute).ok


def test_an_artifact_that_claims_a_ratio_its_primitives_do_not_imply_is_caught():
    """The failure this check exists for: an artifact claiming 95% filled while carrying 3,800 of
    4,000. Every consumer downstream believes the claim unless something recomputes it."""
    payload = {
        "intended_order_usd": D("4000"),
        "filled_order_usd": D("3800"),
        "fill_ratio": D("0.99"),
    }
    envelope = on_disk(artifact_envelope("copy_simulation", "depth", payload))
    recompute = {"fill_ratio": lambda p: divide(D(p["filled_order_usd"]),
                                                D(p["intended_order_usd"]))}

    report = check_derived_fields(envelope["payload"], recompute)
    assert not report.ok
    assert "fill_ratio" in report.messages[0]


def test_the_freeze_manifest_held_across_the_run():
    check = check_freeze_manifest_detail(on_disk(freeze_manifest()), on_disk(freeze_manifest()))
    assert check.ok
    assert check.manifest_hash == canonical_hash(check.pinned)


def test_the_whole_run_resolves_to_go():
    """Three of four windows, both columns significant, capital feasible at both design levels."""
    evaluation = evaluate_windows_detail(window_scores(), THRESHOLD)
    assert evaluate_windows(window_scores(), THRESHOLD) == (3, 4)

    record = emit_decision_detail(
        evidence(),
        evaluation,
        feasible_capital(),
        permutation(LEADER_COLUMN),
        permutation(FOLLOWER_COLUMN),
    )

    assert record.decision.outcome is GateOutcome.GO
    assert record.decision.windows_passed == 3
    assert not record.decision.capital_feasibility_failed
    assert record.manifest_hash == canonical_hash(on_disk(freeze_manifest()))
    assert len(record.confirmations) == 5


def test_the_go_record_states_what_a_go_does_not_mean():
    """Ticket 43: a GO means the edge existed historically and would have survived transfer to one
    follower at design capital — not that it survives the product existing."""
    decision = emit_decision(
        evidence(), evaluate_windows_detail(window_scores(), THRESHOLD), feasible_capital(),
        permutation(LEADER_COLUMN), permutation(FOLLOWER_COLUMN),
    )
    joined = " ".join(decision.reasons)
    assert "one follower at design capital" in joined
    assert "Berk-Green" in joined


def test_the_decision_record_is_a_stable_serialisable_object():
    record = emit_decision_detail(
        evidence(), evaluate_windows_detail(window_scores(), THRESHOLD), feasible_capital(),
        permutation(LEADER_COLUMN), permutation(FOLLOWER_COLUMN),
    )
    encoded = to_canonical_json(record)
    assert json.loads(encoded)["decision"]["outcome"] == "GO"
    assert canonical_hash(record) == canonical_hash(record)


# -- the capacity failure --------------------------------------------------------


def test_a_positive_leader_edge_with_infeasible_capital_is_conditional_review():
    """§7.5, the reason there are three states. The leader edge is unchanged and real; the
    follower cannot get it at $2,000,000."""
    decision = emit_decision(
        evidence(),
        evaluate_windows_detail(window_scores(), THRESHOLD),
        feasible_capital(a="0.0362", b="-0.0044"),
        permutation(LEADER_COLUMN),
        permutation(FOLLOWER_COLUMN),
    )

    assert decision.outcome is GateOutcome.CONDITIONAL_REVIEW
    assert decision.capital_feasibility_failed
    assert any("2000000" in r for r in decision.reasons)


def test_conditional_review_requires_a_decision_from_the_closed_list():
    decision = emit_decision(
        evidence(), evaluate_windows_detail(window_scores(), THRESHOLD),
        feasible_capital(b="-0.0044"), permutation(LEADER_COLUMN), permutation(FOLLOWER_COLUMN),
    )
    assert decision.outcome is GateOutcome.CONDITIONAL_REVIEW

    assert require_conditional_review_decision("reduce_design_capital") == "reduce_design_capital"
    with pytest.raises(FreezeViolation) as excinfo:
        require_conditional_review_decision("proceed_anyway")
    assert all(option in str(excinfo.value) for option in CONDITIONAL_REVIEW_OPTIONS)


def test_a_failed_leader_column_is_stop_with_the_preregistered_wording():
    decision = emit_decision(
        evidence(), evaluate_windows_detail(window_scores(), THRESHOLD), feasible_capital(),
        permutation(LEADER_COLUMN, significant=False), permutation(FOLLOWER_COLUMN),
    )
    assert decision.outcome is GateOutcome.STOP
    assert NEGATIVE_RESULT_WORDING in decision.reasons
    assert any("does not work on any blockchain" in r for r in decision.reasons)


# -- diagnostics may never touch the gate ---------------------------------------


def test_a_diagnostic_pack_cannot_be_fed_to_the_gate():
    """§10: only buy_quality decides. The engine refuses the artifact rather than ignoring the
    column, so a diagnostic cannot arrive at the decision by being silently dropped elsewhere."""
    diagnostics = window_scores() + [
        WindowScore(1, "absolute_profit_rank", D("9"), D("9"), D("0.1"), D("1"),
                    EdgeOriginStatus.VALID),
    ]
    with pytest.raises(DiagnosticInputRefused):
        evaluate_windows(diagnostics, THRESHOLD)


def test_a_failing_gate_cannot_be_reinterpreted_by_swapping_the_null_distributions():
    """The leader null is friendlier than the follower's here; borrowing it would flip the
    outcome, so §7.3's 'its own null distribution' is enforced structurally."""
    with pytest.raises(FreezeViolation) as excinfo:
        emit_decision(
            evidence(), evaluate_windows_detail(window_scores(), THRESHOLD), feasible_capital(),
            permutation(LEADER_COLUMN), permutation(LEADER_COLUMN),
        )
    assert "follower_null" in str(excinfo.value)


# -- §9.7 the invalidation drill -------------------------------------------------


def test_the_invalidation_drill_end_to_end():
    """Ticket 39's second half, which nobody wants to run for the first time later.

    A real bug is found after the freeze. Everything downstream is discarded and redone; nothing is
    patched; and the previous result becomes permanently unavailable — including for comparison.
    """
    evaluation = evaluate_windows_detail(window_scores(), THRESHOLD)
    frozen = RunStatus(code_version=FROZEN_COMMIT)

    original = emit_decision(
        evidence(run_status=frozen), evaluation, feasible_capital(),
        permutation(LEADER_COLUMN), permutation(FOLLOWER_COLUMN),
    )
    assert original.outcome is GateOutcome.GO

    # 1. A real, documented bug surfaces after the freeze.
    invalidated = invalidate(
        frozen, "FIFO lot matching consumed the newest lot first on partial sells"
    )
    assert invalidated.invalidated

    # 2. No decision may be emitted while the run is invalidated — not even the same one.
    with pytest.raises(FreezeViolation) as excinfo:
        emit_decision(
            evidence(run_status=invalidated), evaluation, feasible_capital(),
            permutation(LEADER_COLUMN), permutation(FOLLOWER_COLUMN),
        )
    assert "run_status" in str(excinfo.value)
    assert "discarded, not patched" in str(excinfo.value)

    # 3. Patching the previous run is unavailable: recovery needs a NEW version.
    with pytest.raises(FreezeViolation):
        register_code_version(invalidated, FROZEN_COMMIT)
    fixed = register_code_version(invalidated, FIXED_COMMIT)
    assert fixed.discarded_versions == (FROZEN_COMMIT,)

    # 4. The old result is now unquotable, even for comparison.
    with pytest.raises(FreezeViolation) as excinfo:
        require_current_version(fixed, FROZEN_COMMIT)
    assert "prohibited" in str(excinfo.value)

    with pytest.raises(FreezeViolation):
        emit_decision(
            evidence(commit=FIXED_COMMIT, run_status=fixed, result_code_version=FROZEN_COMMIT),
            evaluation, feasible_capital(),
            permutation(LEADER_COLUMN), permutation(FOLLOWER_COLUMN),
        )

    # 5. The whole gate re-runs on the new version and emits its own decision, freshly bound.
    reissued = emit_decision_detail(
        evidence(commit=FIXED_COMMIT, run_status=fixed),
        evaluation, feasible_capital(),
        permutation(LEADER_COLUMN), permutation(FOLLOWER_COLUMN),
    )
    assert reissued.decision.outcome is GateOutcome.GO
    assert reissued.manifest_hash != canonical_hash(on_disk(freeze_manifest(FROZEN_COMMIT)))
    assert reissued.decision.manifest.source_commit == FIXED_COMMIT


def test_a_manifest_whose_commit_no_longer_matches_the_code_blocks_everything():
    """After a fix, a manifest still pinning the old commit is the whole bug class in one field."""
    fixed = register_code_version(
        invalidate(RunStatus(code_version=FROZEN_COMMIT), "bug"), FIXED_COMMIT
    )
    with pytest.raises(FreezeViolation) as excinfo:
        emit_decision(
            evidence(commit=FROZEN_COMMIT, run_status=fixed, result_code_version=FIXED_COMMIT),
            evaluate_windows_detail(window_scores(), THRESHOLD), feasible_capital(),
            permutation(LEADER_COLUMN), permutation(FOLLOWER_COLUMN),
        )
    assert "source_commit" in str(excinfo.value)


# -- the arbiter never touches the code it judges --------------------------------


def test_the_package_imports_only_the_seam():
    """The claim in the package docstring, checked here rather than only asserted.

    ``tests/test_lane_independence.py`` enforces the lane rule generally; this narrows it to the
    arbiter, where the consequence is specific: a gate that could import scoring could inherit
    scoring's bug and then certify it.
    """
    import ast
    import os

    import gate_validation

    root = os.path.dirname(gate_validation.__file__)
    imported = set()
    for name in sorted(os.listdir(root)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(root, name), "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])

    assert imported <= {"contracts", "dataclasses", "decimal", "typing"}, (
        "gate_validation imports {}; it may import only contracts and the standard "
        "library".format(sorted(imported - {"contracts", "dataclasses", "decimal", "typing"}))
    )


def test_every_manifest_field_the_seam_declares_is_checked():
    """A field added to ``contracts.FreezeManifest`` must not silently escape the freeze check."""
    assert set(REQUIRED_MANIFEST_FIELDS) == {
        "source_commit", "dataset_snapshot", "golden_set_version", "protocol_coverage_version",
        "decoder_version", "model_version", "config_hash", "master_seed",
        "known_answer_fixture_hash", "validation_report_hash", "numeric_policy_version",
        "reporting_schema_version",
    }
    assert set(EXACT_MATCH_FIELDS) == set(golden_event())
    assert check_freeze_manifest(freeze_manifest(), freeze_manifest()) == []
