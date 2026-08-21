"""Invariants for the arbiter, over generated scores, thresholds, manifests, and artifacts.

The headline property is the one this module exists for:

    **INDETERMINATE can never satisfy a Boolean pass condition.**

For every generated set of window scores and every threshold — including thresholds no calibration
would ever produce, like -10^30 — a window whose edge-origin status is not VALID never counts
toward the passing total. Stated over the whole generated space rather than over chosen examples,
because the shape that breaks it is always the one nobody thought to write down: a threshold so low
that every mean advantage clears it, a median comfortably positive, and a status field that some
future ``if window.passed:`` quietly absorbs. That is how an unmeasurable result becomes a green
dashboard, and it is the single most dangerous bug available in this path.

The rest are the invariants a wrong implementation passes the hand-computed cases without
violating: monotonicity in the threshold, determinism of the canonical form, the tolerance rule's
behaviour at zero, and the fact that every envelope mutation is caught by the hash.

``derandomize=True`` throughout: the house rule forbids unseeded randomness, and a property suite
that fails only on Tuesdays is worse than none.
"""

from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from contracts import (
    NUMERIC_POLICY_VERSION,
    REPORTING_SCHEMA_VERSION,
    EdgeOriginStatus,
    FreezeViolation,
    GateOutcome,
    PermutationResult,
    ValidationStatus,
    WindowScore,
    artifact_envelope,
    divide,
    to_canonical_json,
)
from gate_validation import (
    DESIGN_CAPITAL_LEVELS,
    EXPECTED_WINDOWS,
    FIRST_HOUR_EDGE_SHARE_MAX,
    FOLLOWER_COLUMN,
    GOVERNANCE_ORDER,
    LEADER_COLUMN,
    MIN_PASSING_WINDOWS,
    REQUIRED_MANIFEST_FIELDS,
    REQUIRED_MODULES,
    RunEvidence,
    RunStatus,
    ToleranceSpec,
    assess_capital_feasibility,
    check_freeze_manifest,
    check_numeric_fields_detail,
    emit_decision,
    emit_decision_detail,
    evaluate_windows,
    evaluate_windows_detail,
    invalidate,
    register_code_version,
    require_current_version,
    verify_envelope,
)

DETERMINISTIC = settings(derandomize=True, max_examples=200, deadline=None)

D = Decimal

#: Four decimal places over a plausible advantage range, built through the frozen ``divide`` so the
#: generated values are exactly what the module would compute rather than what Python's default
#: 28-digit context would.
advantages = st.integers(min_value=-20_000, max_value=20_000).map(lambda n: divide(n, 10 ** 4))

shares = st.integers(min_value=0, max_value=10_000).map(lambda n: divide(n, 10 ** 4))

#: Split at §7.1's limit, so a status and its share can both be true. Exactly 40% belongs to the
#: passing side: ticket 09 resolved the condition as *strictly greater than* 40% fails.
_LIMIT_TENTHS_OF_A_BASIS_POINT = int(FIRST_HOUR_EDGE_SHARE_MAX * 10 ** 4)
within_limit = st.integers(min_value=0, max_value=_LIMIT_TENTHS_OF_A_BASIS_POINT).map(
    lambda n: divide(n, 10 ** 4))
above_limit = st.integers(
    min_value=_LIMIT_TENTHS_OF_A_BASIS_POINT + 1, max_value=10_000).map(
    lambda n: divide(n, 10 ** 4))

contributions = st.integers(min_value=0, max_value=100_000).map(lambda n: divide(n, 10 ** 4))

statuses = st.sampled_from(list(EdgeOriginStatus))

#: Ordinary thresholds, plus absurd ones. The invariant must hold at every one of them: a threshold
#: of -10^30 makes conditions 1 and 2 trivially satisfiable, leaving the status as the only thing
#: standing between an unmeasurable window and a pass.
thresholds = st.one_of(
    st.integers(min_value=-20_000, max_value=20_000).map(lambda n: divide(n, 10 ** 4)),
    st.sampled_from([D("-1E+30"), D("0"), D("1E+30"), D("-0.0001"), D("1")]),
)


@st.composite
def column_scores(draw, window, column):
    """A score whose status and first-hour share can both be true.

    The share used to be drawn independently of the status, so the strategy produced ``VALID``
    alongside a share of 0.95 — a pair §7.1 makes impossible — and the suite asserted invariants
    about it. That is how the arbiter came to certify §7.1's third condition without ever examining
    it: the one input that would have exposed the gap was generated inconsistently and never
    compared, so no property could see the difference.

    ``evaluate_windows`` now refuses an impossible pair, so the strategy draws the share on the
    side of the limit its status claims. The limit is imported from ``gate_validation`` rather than
    written here, because a test asserting a boundary against its own copy of that boundary pins
    nothing about the module.
    """
    status = draw(statuses)
    if status is EdgeOriginStatus.INDETERMINATE:
        # The seam refuses a share alongside INDETERMINATE, which is itself the invariant made
        # structural: a window with no measurable share cannot carry one.
        share = None
    elif status is EdgeOriginStatus.VALID:
        share = draw(within_limit)
    else:
        share = draw(above_limit)
    return WindowScore(
        window=window,
        column=column,
        mean_advantage=draw(advantages),
        median_advantage=draw(advantages),
        first_hour_edge_share=share,
        positive_edge_contribution=draw(contributions),
        edge_origin_status=status,
    )


@st.composite
def score_sets(draw, windows=None, columns=(LEADER_COLUMN, FOLLOWER_COLUMN)):
    """A set of scores with at most one result per (window, column), by construction."""
    if windows is None:
        windows = draw(st.lists(st.integers(min_value=1, max_value=6), min_size=1, max_size=4,
                                unique=True))
    scores = []
    for window in sorted(windows):
        for column in columns:
            scores.append(draw(column_scores(window, column)))
    return scores


# -- the headline invariant ------------------------------------------------------


@DETERMINISTIC
@given(scores=score_sets(), threshold=thresholds)
def test_a_non_valid_status_never_counts_toward_the_passing_total(scores, threshold):
    """The invariant that stops an unmeasurable result becoming a green dashboard."""
    evaluation = evaluate_windows_detail(scores, threshold)

    for verdict in evaluation.verdicts:
        unmeasurable = [c for c in verdict.columns
                        if c.edge_origin_status is not EdgeOriginStatus.VALID]
        for column in unmeasurable:
            assert not column.passed, (
                "window {} column {} passed with status {}".format(
                    column.window, column.column, column.edge_origin_status)
            )
        if unmeasurable:
            assert not verdict.passed


@DETERMINISTIC
@given(scores=score_sets(), threshold=thresholds)
def test_indeterminate_cannot_be_rescued_by_any_threshold(scores, threshold):
    """Every INDETERMINATE column fails, and says so, at every threshold generated."""
    for verdict in evaluate_windows_detail(scores, threshold).verdicts:
        for column in verdict.columns:
            if column.edge_origin_status is EdgeOriginStatus.INDETERMINATE:
                assert not column.passed
                assert any("INDETERMINATE" in r for r in column.reasons)
                assert column.first_hour_edge_share is None


@DETERMINISTIC
@given(scores=score_sets(), threshold=thresholds)
def test_downgrading_a_status_can_only_lower_the_count(scores, threshold):
    """Replacing any column's status with INDETERMINATE never increases the passing total.

    This is the directional form of the invariant, and it is the one that catches a status check
    written the wrong way round — a bug that a fixture with only VALID rows cannot see.
    """
    before, total = evaluate_windows(scores, threshold)

    downgraded = []
    for score in scores:
        if score.window == scores[0].window and score.column == scores[0].column:
            downgraded.append(WindowScore(
                window=score.window,
                column=score.column,
                mean_advantage=score.mean_advantage,
                median_advantage=score.median_advantage,
                first_hour_edge_share=None,
                positive_edge_contribution=score.positive_edge_contribution,
                edge_origin_status=EdgeOriginStatus.INDETERMINATE,
            ))
        else:
            downgraded.append(score)

    after, after_total = evaluate_windows(downgraded, threshold)
    assert after_total == total
    assert after <= before


# -- counting -------------------------------------------------------------------


@DETERMINISTIC
@given(scores=score_sets(), threshold=thresholds)
def test_the_count_never_exceeds_the_number_of_windows(scores, threshold):
    passed, total = evaluate_windows(scores, threshold)
    assert 0 <= passed <= total
    assert total == len({s.window for s in scores})


@DETERMINISTIC
@given(scores=score_sets(), low=advantages, high=advantages)
def test_raising_the_threshold_never_raises_the_count(scores, low, high):
    """§8.3 raises the threshold until the null pass rate falls; a harder bar cannot pass more."""
    assume(low <= high)
    assert evaluate_windows(scores, high)[0] <= evaluate_windows(scores, low)[0]


@DETERMINISTIC
@given(scores=score_sets(), threshold=thresholds)
def test_a_window_passes_exactly_when_every_required_column_does(scores, threshold):
    for verdict in evaluate_windows_detail(scores, threshold).verdicts:
        expected = not verdict.missing_columns and all(c.passed for c in verdict.columns)
        assert verdict.passed is expected


@DETERMINISTIC
@given(scores=score_sets(), threshold=thresholds)
def test_a_verdict_and_its_explanation_never_disagree(scores, threshold):
    """A passing column carries no reasons; a failing one always names at least one condition.

    ``ColumnVerdict`` refuses the contradiction at construction, so this proves the restatement is
    *total* over the generated space rather than merely consistent on the fixtures.
    """
    for verdict in evaluate_windows_detail(scores, threshold).verdicts:
        for column in verdict.columns:
            assert bool(column.reasons) != column.passed


@DETERMINISTIC
@given(scores=score_sets(), threshold=thresholds)
def test_only_the_leader_column_decides_gate_one(scores, threshold):
    evaluation = evaluate_windows_detail(scores, threshold)
    assert evaluation.passed <= evaluation.passed_for(LEADER_COLUMN)
    assert evaluation.passed <= evaluation.passed_for(FOLLOWER_COLUMN)


@DETERMINISTIC
@given(scores=score_sets(), threshold=advantages)
def test_the_evaluation_is_deterministic_and_serialisable(scores, threshold):
    """Same input, byte-identical canonical output. A leaked float raises inside canonicalise."""
    first = to_canonical_json(evaluate_windows_detail(scores, threshold))
    second = to_canonical_json(evaluate_windows_detail(list(scores), threshold))
    assert first == second


# -- §7.2 capital feasibility ----------------------------------------------------


@DETERMINISTIC
@given(a=st.one_of(st.none(), advantages), b=st.one_of(st.none(), advantages))
def test_feasibility_requires_both_levels_measured_and_strictly_positive(a, b):
    assessment = assess_capital_feasibility({
        DESIGN_CAPITAL_LEVELS[0]: a, DESIGN_CAPITAL_LEVELS[1]: b,
    })
    expected = a is not None and b is not None and a > 0 and b > 0
    assert assessment.feasible is expected
    assert bool(assessment.reasons) is not expected


@DETERMINISTIC
@given(a=advantages, b=advantages, extra=advantages)
def test_non_gating_capital_levels_never_change_the_verdict(extra, a, b):
    """§3.1: five levels are simulated, two gate. The other three are reported and inert."""
    gating = {DESIGN_CAPITAL_LEVELS[0]: a, DESIGN_CAPITAL_LEVELS[1]: b}
    with_extra = dict(gating)
    with_extra[D("500000")] = extra
    assert (assess_capital_feasibility(gating).feasible
            is assess_capital_feasibility(with_extra).feasible)


# -- §9.2 tolerances -------------------------------------------------------------

values = st.integers(min_value=-10 ** 9, max_value=10 ** 9).map(lambda n: divide(n, 10 ** 4))
tolerances = st.integers(min_value=0, max_value=10 ** 6).map(lambda n: divide(n, 10 ** 6))


@DETERMINISTIC
@given(value=values, tolerance=tolerances, relative=st.booleans())
def test_an_exact_match_is_always_within_tolerance(value, tolerance, relative):
    spec = ToleranceSpec("v", tolerance, relative=relative)
    check = check_numeric_fields_detail({"v": value}, {"v": value}, (spec,))
    assert check.ok
    assert check.comparison_for("v").within


@DETERMINISTIC
@given(expected=values, observed=values, tolerance=tolerances, relative=st.booleans())
def test_the_comparison_is_symmetric_in_the_direction_of_the_error(
        expected, observed, tolerance, relative):
    """Over- and under-stating by the same amount are equally in or out of tolerance.

    A one-sided rule would let a systematic bias in the cheap direction pass — and the whole point
    of a reconciliation tolerance is that neither side is presumed correct.
    """
    spec = ToleranceSpec("v", tolerance, relative=relative)
    delta = observed - expected
    mirrored = expected - delta

    within_a = check_numeric_fields_detail({"v": expected}, {"v": observed},
                                           (spec,)).comparison_for("v").within
    within_b = check_numeric_fields_detail({"v": expected}, {"v": mirrored},
                                           (spec,)).comparison_for("v").within
    assert within_a is within_b


@DETERMINISTIC
@given(observed=values, tolerance=tolerances)
def test_a_zero_baseline_demands_exactness_at_every_tolerance(observed, tolerance):
    """A relative tolerance against zero has no value, so no tolerance may substitute for one."""
    spec = ToleranceSpec("v", tolerance, relative=True)
    check = check_numeric_fields_detail({"v": D("0")}, {"v": observed}, (spec,))
    assert check.comparison_for("v").relative_error is None
    assert check.ok is (observed == 0)


@DETERMINISTIC
@given(expected=values, observed=values)
def test_the_relative_error_is_never_negative(expected, observed):
    assume(expected != 0)
    spec = ToleranceSpec("v", D("0.005"), relative=True)
    comparison = check_numeric_fields_detail({"v": expected}, {"v": observed},
                                            (spec,)).comparison_for("v")
    assert comparison.relative_error >= 0


# -- §9.6 the manifest -----------------------------------------------------------

pins = st.text(alphabet="0123456789abcdef", min_size=4, max_size=16)


@st.composite
def manifests(draw):
    pinned = {}
    for field in REQUIRED_MANIFEST_FIELDS:
        pinned[field] = draw(pins)
    pinned["numeric_policy_version"] = NUMERIC_POLICY_VERSION
    pinned["reporting_schema_version"] = REPORTING_SCHEMA_VERSION
    return pinned


@DETERMINISTIC
@given(pinned=manifests())
def test_a_manifest_agrees_with_itself_and_with_nothing_else(pinned):
    assert check_freeze_manifest(pinned, dict(pinned)) == []


@DETERMINISTIC
@given(pinned=manifests(), index=st.integers(min_value=0, max_value=100), replacement=pins)
def test_changing_exactly_one_pinned_field_produces_exactly_one_finding(
        pinned, index, replacement):
    """No collateral findings, so a refusal points at the input that actually moved."""
    changeable = [f for f in REQUIRED_MANIFEST_FIELDS if f not in
                  ("numeric_policy_version", "reporting_schema_version")]
    field = changeable[index % len(changeable)]
    assume(pinned[field] != replacement)

    observed = dict(pinned)
    observed[field] = replacement
    findings = check_freeze_manifest(pinned, observed)

    assert len(findings) == 1
    assert findings[0].startswith(field + ":")


@DETERMINISTIC
@given(pinned=manifests(), index=st.integers(min_value=0, max_value=100))
def test_dropping_any_pin_is_always_reported(pinned, index):
    field = REQUIRED_MANIFEST_FIELDS[index % len(REQUIRED_MANIFEST_FIELDS)]
    incomplete = dict(pinned)
    del incomplete[field]
    assert any(f.startswith(field + ":") for f in check_freeze_manifest(incomplete, pinned))


# -- artifact envelopes ----------------------------------------------------------

payload_values = st.one_of(
    st.text(alphabet="abcdef0123456789", max_size=12),
    st.integers(min_value=-10 ** 12, max_value=10 ** 12),
    st.integers(min_value=-10 ** 8, max_value=10 ** 8).map(lambda n: divide(n, 10 ** 4)),
    st.none(),
    st.booleans(),
)

payloads = st.dictionaries(
    st.text(alphabet="abcdefghij_", min_size=1, max_size=8), payload_values,
    min_size=1, max_size=6,
)


@DETERMINISTIC
@given(payload=payloads)
def test_a_freshly_written_envelope_always_verifies(payload):
    assert verify_envelope(artifact_envelope("scores", "scoring", payload)) == []


@DETERMINISTIC
@given(payload=payloads, tampered=st.text(alphabet="xyz", min_size=1, max_size=6))
def test_every_payload_edit_is_caught_by_the_recomputed_hash(payload, tampered):
    envelope = artifact_envelope("scores", "scoring", payload)
    key = sorted(envelope["payload"])[0]
    assume(envelope["payload"][key] != tampered)

    envelope["payload"][key] = tampered
    assert any("payload_hash" in f for f in verify_envelope(envelope))


# -- §9.7 invalidation -----------------------------------------------------------

versions = st.text(alphabet="0123456789abcdef", min_size=8, max_size=12)


@DETERMINISTIC
@given(first=versions, second=versions, reason=st.text(min_size=1, max_size=40))
def test_a_superseded_version_is_refused_forever(first, second, reason):
    assume(first != second)
    fixed = register_code_version(invalidate(RunStatus(code_version=first), reason), second)

    assert require_current_version(fixed, second) is True
    with pytest.raises(FreezeViolation):
        require_current_version(fixed, first)


@DETERMINISTIC
@given(version=versions, reason=st.text(min_size=1, max_size=40))
def test_an_invalidated_run_never_permits_a_decision(version, reason):
    status = invalidate(RunStatus(code_version=version), reason)
    assert not status.permits_decision
    with pytest.raises(FreezeViolation):
        register_code_version(status, version)


# -- §7.5 the outcome ------------------------------------------------------------


def manifest_for(version):
    pinned = {f: "pin-" + f for f in REQUIRED_MANIFEST_FIELDS}
    pinned["source_commit"] = version
    pinned["numeric_policy_version"] = NUMERIC_POLICY_VERSION
    pinned["reporting_schema_version"] = REPORTING_SCHEMA_VERSION
    return pinned


def evidence_for(threshold, version="c0ffee"):
    return RunEvidence(
        manifest=manifest_for(version),
        observed=manifest_for(version),
        pinned_module_versions={m: m + "-v1" for m in REQUIRED_MODULES},
        observed_module_versions={m: m + "-v1" for m in REQUIRED_MODULES},
        validation_status=ValidationStatus.EXTERNALLY_REVIEWED,
        governance_states=GOVERNANCE_ORDER[:GOVERNANCE_ORDER.index("MAIN_TEST_EXECUTED") + 1],
        locked_threshold=threshold,
        run_status=RunStatus(code_version=version),
        result_code_version=version,
    )


def permutation(column, significant):
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
        observed_statistic=D("0.30") if significant else D("0.010"),
        null_statistics=nulls,
        n_runs=20,
        percentile_95=D("0.019"),
        empirical_p=D("0.047619047619047619047619047619047619048") if significant else D("0.57142857142857142857142857142857142857"),
        null_pass_rate=D("0.04"),
    )


@DETERMINISTIC
@given(
    scores=score_sets(windows=[1, 2, 3, 4]),
    threshold=advantages,
    a=st.one_of(st.none(), advantages),
    b=st.one_of(st.none(), advantages),
    leader_significant=st.booleans(),
    follower_significant=st.booleans(),
)
def test_the_outcome_obeys_the_three_state_rule(scores, threshold, a, b,
                                                leader_significant, follower_significant):
    """Every generated combination lands in exactly one of the three states, correctly.

    In particular ``GO`` never coexists with a capital-feasibility failure. The seam's
    ``GateDecision.__post_init__`` refuses that pair outright, so a violation here would surface as
    a ValueError rather than a wrong verdict — which is the point of enforcing it twice.
    """
    capital = assess_capital_feasibility({
        DESIGN_CAPITAL_LEVELS[0]: a, DESIGN_CAPITAL_LEVELS[1]: b,
    })
    evaluation = evaluate_windows_detail(scores, threshold)

    decision = emit_decision(
        evidence_for(threshold),
        evaluation,
        capital,
        permutation(LEADER_COLUMN, leader_significant),
        permutation(FOLLOWER_COLUMN, follower_significant),
    )

    assert decision.outcome in (GateOutcome.GO, GateOutcome.CONDITIONAL_REVIEW, GateOutcome.STOP)
    assert decision.windows_total == EXPECTED_WINDOWS
    assert decision.capital_feasibility_failed is (not capital.feasible)

    if decision.outcome is GateOutcome.GO:
        assert not decision.capital_feasibility_failed
        assert decision.windows_passed >= MIN_PASSING_WINDOWS
        assert leader_significant and follower_significant
    elif decision.outcome is GateOutcome.CONDITIONAL_REVIEW:
        assert decision.capital_feasibility_failed
        assert leader_significant
        assert evaluation.passed_for(LEADER_COLUMN) >= MIN_PASSING_WINDOWS


@DETERMINISTIC
@given(
    scores=score_sets(windows=[1, 2, 3, 4]),
    threshold=advantages,
    a=st.one_of(st.none(), advantages),
    b=st.one_of(st.none(), advantages),
)
def test_every_emitted_record_survives_canonical_serialization(scores, threshold, a, b):
    """A leaked float anywhere in the record raises here rather than reaching a consumer."""
    record = emit_decision_detail(
        evidence_for(threshold),
        evaluate_windows_detail(scores, threshold),
        assess_capital_feasibility({
            DESIGN_CAPITAL_LEVELS[0]: a, DESIGN_CAPITAL_LEVELS[1]: b,
        }),
        permutation(LEADER_COLUMN, True),
        permutation(FOLLOWER_COLUMN, True),
    )
    encoded = to_canonical_json(record)
    assert to_canonical_json(record) == encoded
    assert record.decision.reasons


@DETERMINISTIC
@given(scores=score_sets(windows=[1, 2, 3, 4]), threshold=advantages, other=advantages)
def test_a_threshold_other_than_the_locked_one_is_always_refused(scores, threshold, other):
    """§8.4 step 7. There is no size of discrepancy small enough to wave through."""
    assume(threshold != other)
    with pytest.raises(FreezeViolation):
        emit_decision(
            evidence_for(other),
            evaluate_windows_detail(scores, threshold),
            assess_capital_feasibility({
                DESIGN_CAPITAL_LEVELS[0]: D("0.05"), DESIGN_CAPITAL_LEVELS[1]: D("0.03"),
            }),
            permutation(LEADER_COLUMN, True),
            permutation(FOLLOWER_COLUMN, True),
        )
