"""``reporting`` composed the way the pipeline will compose it — and the structural separation
between what it publishes and what may decide.

Two halves.

**The run.** Three wallets, four windows, all five capital levels, a ten-wallet churn population and
a full diagnostics pack, assembled into one :class:`reporting.RunReport`, canonicalised, hashed and
wrapped in an artifact envelope. The assertions are on the composed figures, not on the parts: a
report whose blocks are each individually right and whose totals disagree is the failure this layer
exists to find.

**The separation.** §10 draws one line — *only ``buy_quality`` decides the gate* — and this file
asserts that the line is a property of the types rather than a habit of their callers. The
assertions come in four kinds, deliberately, because closing one entry point is closing an instance
and the class is "any path from a diagnostic to a gate decision":

1. :func:`contracts.calc` refuses the diagnostic types, and every numeric primitive in the seam is
   built on ``calc``. That is the class-level closure: no arithmetic anywhere in the pipeline can
   consume a diagnostic, whatever the entry point.
2. Comparison against a ``Decimal`` raises, in both directions, so a bare ``>=`` cannot work either.
3. A diagnostic is not an instance of any type the gate engine reads, so it cannot impersonate one.
4. The named gate entry points — ``evaluate_windows``, ``assess_capital_feasibility``,
   ``emit_decision``, ``WindowScore.passes``, ``scoring.score_window`` — each refuse one, which is
   the legible restatement of (1) to (3) at the places a reviewer will look.

Plus the import graph: ``gate_validation`` is in the shared lane and ``reporting`` in the builder
lane, so the arbiter cannot import this module at all, and the assertion is made directly rather
than left to be inferred from ``tests/test_lane_independence.py``.

And one more, in the other direction: churn is computed by a function whose signature contains no
gate input, and the churn block of a run report is byte-identical whether every window passed or
every window failed. §10 requires churn reported independently of the edge result, and "the
function cannot see the result" is the only version of that claim which survives a refactor.
"""

import ast
import inspect
import json
import os
from decimal import Decimal

import pytest

import reporting
import scoring
from contracts import (
    AssetTier,
    BuyQuality,
    CopySimulation,
    EdgeOriginStatus,
    GateDecision,
    PermutationResult,
    TokenAgeBucket,
    WindowScore,
    add,
    artifact_envelope,
    calc,
    canonical_hash,
    canonicalise,
    divide,
    mul,
    sub,
    to_canonical_json,
)
from gate_validation import (
    DESIGN_CAPITAL_LEVELS,
    EXACTLY,
    RECONCILIATION_CONDITIONS,
    REQUIRED_COLUMNS,
    SCHEMA,
    VALIDATION_GATE_CONDITIONS,
    assess_capital_feasibility,
    check_conditions_detail,
    evaluate_windows,
    evaluate_windows_detail,
)
from reporting import (
    CAPITAL_LEVELS,
    DIAGNOSTIC_ONLY,
    GATE_RELEVANCE_STATEMENT,
    GATING_COLUMNS,
    NOT_TESTED,
    ActivityBand,
    Diagnostic,
    DiagnosticPromotionRefused,
    DiagnosticRanking,
    DiagnosticScope,
    RunReport,
    ValueBasisAmounts,
    WalletActivity,
    WalletCapitalOutcome,
    activity_band,
    diagnostic,
    diagnostic_pack,
    profit_ranking,
    report_basket,
    report_capital_ladder,
    report_capital_level,
    report_churn,
    report_run,
    report_window,
    run_artifact,
)

D = Decimal

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

WALLETS = ("0x" + "11" * 20, "0x" + "22" * 20, "0x" + "33" * 20)
SCOPE = DiagnosticScope(chain="ethereum", window=1, population="selected")


# -- fixtures -------------------------------------------------------------------


def _quality(wallet, value, realized, marked, dead):
    whole = D(realized) + D(marked) + D(dead)
    return BuyQuality(
        wallet=wallet,
        value=D(value),
        n_buys=42,
        realized_share=divide(D(realized), whole),
        marked_share=divide(D(marked), whole),
        dead_share=divide(D(dead), whole),
        bucket_weights={TokenAgeBucket.C: D("0.4"), TokenAgeBucket.D: D("0.6")},
        bucket_values={TokenAgeBucket.C: D(value), TokenAgeBucket.D: D(value)},
    )


BASKET_ENTRIES = (
    (_quality(WALLETS[0], "0.10", 200, 700, 100), ValueBasisAmounts(D("200"), D("700"), D("100"))),
    (
        _quality(WALLETS[1], "0.30", 8000, 1000, 1000),
        ValueBasisAmounts(D("8000"), D("1000"), D("1000")),
    ),
    (_quality(WALLETS[2], "0.05", 800, 200, 0), ValueBasisAmounts(D("800"), D("200"), D("0"))),
)


def _score(window, column, mean_advantage, median_advantage, share, status):
    return WindowScore(
        window=window,
        column=column,
        mean_advantage=D(mean_advantage),
        median_advantage=D(median_advantage),
        first_hour_edge_share=None if share is None else D(share),
        positive_edge_contribution=D("0.08"),
        edge_origin_status=status,
    )


PASSING_SCORES = tuple(
    score
    for window in (1, 2, 3, 4)
    for score in (
        _score(window, "leader", "0.0523", "0.0311", "0.25", EdgeOriginStatus.VALID),
        _score(window, "follower_adjusted", "0.0210", "0.0100", "0.25", EdgeOriginStatus.VALID),
    )
)

FAILING_SCORES = tuple(
    score
    for window in (1, 2, 3, 4)
    for score in (
        _score(window, "leader", "-0.0400", "-0.0200", None, EdgeOriginStatus.INDETERMINATE),
        _score(
            window, "follower_adjusted", "-0.0600", "-0.0300", None, EdgeOriginStatus.INDETERMINATE
        ),
    )
)


def _sims(level, n_executable, n_unexecutable):
    sims = []
    for index in range(n_executable):
        sims.append(
            CopySimulation(
                capital_level=level,
                tier=AssetTier.MAJOR,
                intended_order_usd=D("10000"),
                filled_order_usd=D("9500"),
                execution_cost_pct=D("0.008"),
                follower_return=D("0.12") if index % 2 == 0 else D("-0.04"),
                copyable=True,
            )
        )
    for _ in range(n_unexecutable):
        sims.append(
            CopySimulation(
                capital_level=level,
                tier=AssetTier.MID_CAP,
                intended_order_usd=D("10000"),
                filled_order_usd=D("0"),
                execution_cost_pct=D("0.045"),
                follower_return=None,
                copyable=False,
                rejection_reason="total execution cost exceeds the 2% mid-cap cap",
            )
        )
    return tuple(sims)


#: The capacity cliff, made explicit in the fixture: at $100k almost everything is executable, at
#: $2M almost nothing is. That is the shape §10's per-level block exists to expose.
EXECUTABILITY = {
    D("100000"): (9, 1),
    D("250000"): (8, 2),
    D("500000"): (6, 4),
    D("1500000"): (3, 7),
    D("2000000"): (1, 9),
}


def _ladder():
    reports = []
    for level in CAPITAL_LEVELS:
        executable, unexecutable = EXECUTABILITY[level]
        outcomes = (
            WalletCapitalOutcome(WALLETS[0], D("0.10"), D("0.01")),
            WalletCapitalOutcome(WALLETS[1], D("0.10"), D("0.04")),
            WalletCapitalOutcome(WALLETS[2], D("0.25"), D("0.25")),
        )
        reports.append(
            report_capital_level(
                level,
                outcomes,
                _sims(level, executable, unexecutable),
                ValueBasisAmounts(D("9000"), D("1900"), D("1100")),
            )
        )
    return report_capital_ladder(reports)


def _churn_population():
    records = []
    for index in range(5):
        records.append(WalletActivity("0x{:040x}".format(index), 100, 180, 100, 180))
    for index in range(5, 7):
        records.append(WalletActivity("0x{:040x}".format(index), 100, 180, 1, 180))
    for index in range(7, 10):
        records.append(WalletActivity("0x{:040x}".format(index), 100, 180, 0, 180))
    return tuple(records)


def _diagnostics():
    items = [
        profit_ranking(
            SCOPE,
            (
                (WALLETS[0], D("125000.50")),
                (WALLETS[1], D("980000.25")),
                (WALLETS[2], D("-4000.75")),
            ),
        ),
        diagnostic("simple_wallet_return", SCOPE, D("0.184")),
        diagnostic("buy_return_7d", SCOPE, D("0.031")),
        diagnostic("buy_return_90d", SCOPE, D("0.212")),
        diagnostic("buy_win_rate", SCOPE, D("0.612345678")),
        diagnostic("median_return", SCOPE, D("0.045")),
        diagnostic("tail_loss", SCOPE, D("-0.311")),
        diagnostic("bucket_a_isolated", SCOPE, D("0.402")),
    ]
    for band in ActivityBand:
        items.append(
            diagnostic(
                "activity_band_sensitivity",
                DiagnosticScope(
                    chain="ethereum", window=1, population="selected", band=band
                ),
                D("0.05"),
            )
        )
    return diagnostic_pack(items)


def _run(scores=PASSING_SCORES, integrity=None):
    windows = tuple(
        report_window(tuple(s for s in scores if s.window == window)) for window in (1, 2, 3, 4)
    )
    return report_run(
        run_id="phase0-2026-08-01",
        chain="ethereum",
        basket=report_basket(BASKET_ENTRIES),
        windows=windows,
        capital_ladder=_ladder(),
        churn=report_churn(_churn_population()),
        diagnostics=_diagnostics(),
        integrity=integrity,
    )


# -- the composed run -----------------------------------------------------------


def test_the_run_report_carries_every_block_section_ten_requires():
    run = _run()

    assert run.basket.n_wallets == 3
    assert len(run.windows) == 4
    assert run.missing_windows == ()
    assert len(run.capital_ladder.levels) == 5
    assert run.churn.n_wallets == 10
    assert len(run.diagnostics.items) == 11


def test_the_basket_totals_agree_with_the_wallets_beneath_them():
    """The composition assertion. Every wallet line is rendered from the same amounts the aggregate
    is computed from, so ``9000 + 1900 + 1100`` must be exactly what the basket says."""
    run = _run()

    assert run.basket.realized_usd == D("9000.000000")
    assert run.basket.marked_usd == D("1900.000000")
    assert run.basket.dead_usd == D("1100.000000")
    assert run.basket.total_usd == D("12000.000000")
    assert run.basket.realized_share == D("0.75000000")
    assert tuple(w.wallet for w in run.basket.wallets) == WALLETS


def test_the_capital_ladder_shows_the_capacity_cliff():
    """§10's per-level block, doing the job ticket 63 gave it.

    At $100k one trade in ten is unexecutable; at $2M nine are. A report that carried only the
    positive-trade rate would show the two levels as comparable, which is the confusion the
    unexecutable share exists to remove.
    """
    ladder = _run().capital_ladder

    assert ladder.at(D("100000")).unexecutable_trade_share == D("0.10000000")
    assert ladder.at(D("2000000")).unexecutable_trade_share == D("0.90000000")
    assert ladder.at(D("100000")).n_executable == 9
    assert ladder.at(D("2000000")).n_executable == 1

    for level in CAPITAL_LEVELS:
        report = ladder.at(level)
        assert report.n_retention_reported == 3
        assert report.mean_copy_retention == D("0.50000000")


def test_the_report_states_what_only_buy_quality_decides_and_what_was_not_tested():
    run = _run()
    assert run.gate_relevance == GATE_RELEVANCE_STATEMENT
    assert "Only buy_quality decides the gate" in run.gate_relevance
    assert run.not_tested == NOT_TESTED
    assert any("Berk-Green" in line for line in run.not_tested)


def test_the_run_report_serialises_deterministically_and_hashes_stably():
    first = to_canonical_json(_run())
    second = to_canonical_json(_run())
    assert first == second
    assert canonical_hash(_run()) == canonical_hash(_run())


def test_no_float_survives_into_the_artifact():
    """``canonicalise`` refuses a float on sight, so a clean envelope is the assertion."""
    envelope = run_artifact(_run())
    assert envelope["kind"] == reporting.ARTIFACT_KIND
    assert envelope["produced_by"] == "reporting"
    assert len(envelope["payload_hash"]) == 64
    assert "e+" not in to_canonical_json(_run()).lower()


def test_every_diagnostic_carries_its_label_through_serialization():
    """Ticket 34: a number cannot travel without its status. A class attribute would vanish here;
    a stored field does not."""
    payload = canonicalise(_run())
    items = payload["diagnostics"]["items"]

    assert len(items) == 11
    for item in items:
        assert item["gate_relevance"] == DIAGNOSTIC_ONLY
        assert item["scope"]["chain"] == "ethereum"
        assert item["scope"]["population"] == "selected"
    assert payload["diagnostics"]["gate_relevance"] == DIAGNOSTIC_ONLY


def test_every_diagnostic_carries_the_scope_ticket_thirty_four_requires():
    pack = _run().diagnostics
    for item in pack.items:
        assert item.scope.chain
        assert item.scope.population
        assert isinstance(item.scope.window, int)
    bands = {item.scope.band for item in pack.named("activity_band_sensitivity")}
    assert bands == set(ActivityBand)


def test_a_run_missing_a_window_says_which_one_rather_than_looking_complete():
    scores = tuple(s for s in PASSING_SCORES if s.window != 3)
    windows = tuple(
        report_window(tuple(s for s in scores if s.window == window)) for window in (1, 2, 4)
    )
    run = report_run(
        run_id="phase0-partial",
        chain="ethereum",
        basket=report_basket(BASKET_ENTRIES),
        windows=windows,
        capital_ladder=_ladder(),
        churn=report_churn(_churn_population()),
        diagnostics=_diagnostics(),
    )
    assert run.missing_windows == (3,)


# -- churn is independent of the edge result ------------------------------------


def test_report_churn_has_no_parameter_through_which_a_result_could_arrive():
    """§10 reports churn independently of the edge result, and the only durable version of that
    claim is that the function cannot see the result."""
    signature = inspect.signature(report_churn)
    assert list(signature.parameters) == ["activities"]


def test_report_run_takes_no_gate_decision():
    """§10 opens with 'Beyond the gate decision, these must be reported'. The report sits beside
    the decision; a second object carrying an outcome would be a second answer to the arbiter's
    question."""
    parameters = set(inspect.signature(report_run).parameters)
    assert parameters == {
        "run_id",
        "chain",
        "basket",
        "windows",
        "capital_ladder",
        "churn",
        "diagnostics",
        # §10's four standing integrity figures. Added to the pinned surface deliberately: this
        # test exists to refuse a gate decision reaching the report, and the way it does that is by
        # naming every parameter, so a new one must be admitted here on purpose rather than by the
        # assertion loosening.
        "integrity",
    }
    for forbidden in ("decision", "outcome", "gate", "threshold", "passed"):
        assert not any(forbidden in name for name in parameters)


def test_the_churn_block_is_identical_whether_every_window_passed_or_failed():
    passing = _run(PASSING_SCORES)
    failing = _run(FAILING_SCORES)

    assert canonical_hash(passing.churn) == canonical_hash(failing.churn)
    assert passing.churn.churn_rate == D("0.30000000")
    assert failing.churn.churn_rate == D("0.30000000")
    # And the windows really did differ, so the equality above is not vacuous.
    assert canonical_hash(passing.windows) != canonical_hash(failing.windows)


def test_no_gate_outcome_appears_anywhere_in_a_run_report():
    payload = to_canonical_json(_run())
    for outcome in ("CONDITIONAL_REVIEW", "STOP"):
        assert outcome not in payload
    assert '"GO"' not in payload


# -- the diagnostic separation, closed four ways --------------------------------


def _every_diagnostic_shape():
    return (
        diagnostic("buy_win_rate", SCOPE, D("0.61")),
        profit_ranking(SCOPE, ((WALLETS[0], D("1000")),)),
        _diagnostics(),
    )


def test_the_seam_refuses_a_diagnostic_as_a_number():
    """The class-level closure. Every numeric primitive in the pipeline is built on ``calc``, so a
    type ``calc`` refuses cannot enter arithmetic anywhere — not only at the entry points below."""
    for item in _every_diagnostic_shape():
        with pytest.raises(TypeError):
            calc(item)
        for operation in (add, sub, mul, divide):
            with pytest.raises(TypeError):
                operation(item, D("1"))
            with pytest.raises(TypeError):
                operation(D("1"), item)


def test_a_diagnostic_cannot_be_compared_with_a_decimal_in_either_direction():
    for item in _every_diagnostic_shape():
        with pytest.raises(DiagnosticPromotionRefused):
            item >= D("0.5")
        # The reflected comparison lands on the diagnostic's own operator, which refuses too.
        with pytest.raises(DiagnosticPromotionRefused):
            D("0.5") <= item


def test_a_diagnostic_is_not_an_instance_of_anything_the_gate_reads():
    scalar, ranking, pack = _every_diagnostic_shape()
    assert isinstance(scalar, Diagnostic)
    assert isinstance(ranking, DiagnosticRanking)
    assert all(isinstance(item, (Diagnostic, DiagnosticRanking)) for item in pack.items)

    gate_input_types = (WindowScore, BuyQuality, CopySimulation, PermutationResult, GateDecision, Decimal)
    for item in _every_diagnostic_shape():
        for gate_type in gate_input_types:
            assert not isinstance(item, gate_type), (
                "{} is an instance of {} and could therefore reach the gate wearing its "
                "shape".format(type(item).__name__, gate_type.__name__)
            )


def test_the_gate_engine_refuses_a_diagnostic_at_every_named_entry_point():
    """The legible restatement, at the places a reviewer will actually look."""
    item = diagnostic("buy_win_rate", SCOPE, D("0.61"))

    with pytest.raises(TypeError):
        evaluate_windows((item,), D("0.02"))
    with pytest.raises(TypeError):
        evaluate_windows_detail((item,), D("0.02"))
    with pytest.raises(TypeError):
        assess_capital_feasibility({D("1500000"): item, D("2000000"): item})

    score = _score(1, "leader", "0.05", "0.03", "0.25", EdgeOriginStatus.VALID)
    with pytest.raises((TypeError, DiagnosticPromotionRefused)):
        score.passes(item)

    with pytest.raises(TypeError):
        evaluate_windows(PASSING_SCORES, item)


def test_the_scoring_engine_refuses_a_diagnostic_as_an_advantage():
    from scoring import edge_origin

    item = diagnostic("buy_win_rate", SCOPE, D("0.61"))
    with pytest.raises(TypeError):
        scoring.score_window(1, "leader", (item,), None)
    assert callable(edge_origin)


def test_the_arbiter_cannot_import_the_reporting_package():
    """The strongest control of the four: a static assertion over committed code.

    ``gate_validation`` is the arbiter and lives in the shared lane; ``reporting`` is in the builder
    lane. The arbiter that can import the code it judges can inherit its bug and then certify it,
    and here that would mean the diagnostics being reachable from the decision at all.
    """
    offenders = []
    for dirpath, _dirnames, filenames in os.walk(os.path.join(SRC, "gate_validation")):
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] == "reporting":
                            offenders.append(path)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    if node.module.split(".")[0] == "reporting":
                        offenders.append(path)

    assert not offenders, (
        "gate_validation imports reporting in {}. The arbiter must not be able to reach the "
        "diagnostics pack: §10 forbids a diagnostic from moving a gate, and an import is the one "
        "way it could.".format(offenders)
    )


def test_the_reporting_package_imports_no_other_builder_package():
    """``reporting`` is a leaf. Only ``pipeline`` composes builder packages; a leaf that reached
    sideways would make the report depend on the very code it renders."""
    builder_siblings = {
        "attribution",
        "netting",
        "fifo",
        "marking",
        "depth",
        "scoring",
        "matching_null",
        "pipeline",
    }
    offenders = []
    for dirpath, _dirnames, filenames in os.walk(os.path.join(SRC, "reporting")):
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                imported = None
                if isinstance(node, ast.Import):
                    imported = {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imported = {node.module.split(".")[0]}
                for name_ in imported or ():
                    if name_ in builder_siblings:
                        offenders.append("{} imports {}".format(path, name_))

    assert not offenders, "reporting is a leaf and must import only contracts: {}".format(offenders)


# -- the two vocabularies must not drift ----------------------------------------


def test_the_reporting_gating_columns_are_the_gate_engines_own():
    """Two copies of a column list is how a diagnostic becomes gate-relevant in one of them."""
    assert GATING_COLUMNS == REQUIRED_COLUMNS


def test_the_capital_ladder_contains_both_design_capital_levels():
    """§7.2 gates on the last two rungs; a ladder that did not contain them could not be the one
    the gate refers to."""
    for level in DESIGN_CAPITAL_LEVELS:
        assert level in CAPITAL_LEVELS
    assert CAPITAL_LEVELS[-2:] == tuple(DESIGN_CAPITAL_LEVELS)


def test_the_activity_bands_cover_the_selection_range_without_gaps():
    seen = [activity_band(n) for n in range(reporting.MIN_VALID_BUYS, reporting.MAX_VALID_BUYS + 1)]
    assert set(seen) == set(ActivityBand)
    # Monotone: the band never goes backwards as the count rises, so the bands do not interleave.
    order = {band: index for index, band in enumerate(ActivityBand)}
    assert [order[b] for b in seen] == sorted(order[b] for b in seen)


def test_a_run_report_cannot_be_built_with_a_rewritten_gate_relevance_statement():
    run = _run()
    with pytest.raises(reporting.IncompleteRunReport):
        RunReport(
            run_id=run.run_id,
            chain=run.chain,
            basket=run.basket,
            windows=run.windows,
            capital_ladder=run.capital_ladder,
            churn=run.churn,
            diagnostics=run.diagnostics,
            gate_relevance="diagnostics may be considered alongside buy_quality",
        )


def test_the_artifact_envelope_round_trips_through_the_seams_own_helper():
    report = _run()
    direct = artifact_envelope(reporting.ARTIFACT_KIND, "reporting", report)
    assert run_artifact(report) == direct


# -- the payload wall: the class the type wall left open ------------------------
#
# The type wall stopped the wrapper and not the payload. A reviewer traced one instance —
# ``diagnostic("buy_win_rate", SCOPE, D("0.61")).value`` handed to ``evaluate_windows_detail`` as a
# threshold — but the value it cited is not the condition that made it dangerous.
#
# The condition is: **a diagnostic's measured payload is reachable, by ordinary attribute access, as
# a type ``calc`` accepts.** Every fixture below satisfies that condition and none of them is the
# cited value: a different name, a different kind and sign, a row buried in a ranking, and a payload
# reached through the pack's own accessor rather than off a local variable.


def _payloads():
    """Four measured payloads, none of them the value the reviewer cited."""
    ranking = profit_ranking(
        SCOPE,
        (
            (WALLETS[0], D("125000.50")),
            (WALLETS[1], D("980000.25")),
            (WALLETS[2], D("-4000.75")),
        ),
    )
    return (
        # A different diagnostic, a negative value, still the ratio scale.
        ("tail_loss", diagnostic("tail_loss", SCOPE, D("-0.311")).value),
        # A ranking row, the USD scale, and the *last* row rather than the first.
        ("ranking row", ranking.rows[-1].value),
        # The top row, whose magnitude is large enough to pass any capital threshold.
        ("ranking top row", ranking.rows[0].value),
        # Reached through the pack accessor, which is how a report writer would actually get it.
        ("pack accessor", _diagnostics().named("median_return")[0].value),
    )


def test_a_diagnostic_payload_is_not_a_type_the_seam_will_do_arithmetic_on():
    """``calc`` is the base of every numeric primitive, so refusing there closes arithmetic
    everywhere at once rather than at the entry points somebody remembered."""
    for label, payload in _payloads():
        with pytest.raises(TypeError):
            calc(payload)
        for operation in (add, sub, mul, divide):
            with pytest.raises(TypeError):
                operation(payload, D("1"))
            with pytest.raises(TypeError):
                operation(D("1"), payload)


def test_a_diagnostic_payload_cannot_be_ordered_against_a_threshold():
    """``d > threshold`` was already refused. ``d.value > threshold`` was not, and it is the same
    promotion with one more keystroke."""
    for label, payload in _payloads():
        for compare in (
            lambda: payload > D("0.5"),
            lambda: payload >= D("0.5"),
            lambda: payload < D("0.5"),
            lambda: payload <= D("0.5"),
            # Reflected: the Decimal defers, and the refusal still lands.
            lambda: D("0.5") < payload,
            lambda: D("0.5") >= payload,
        ):
            with pytest.raises(DiagnosticPromotionRefused):
                compare()


def test_a_diagnostic_payload_is_refused_at_every_named_gate_entry_point():
    for label, payload in _payloads():
        with pytest.raises(TypeError):
            evaluate_windows_detail([], payload)
        with pytest.raises(TypeError):
            evaluate_windows_detail(PASSING_SCORES, payload)
        with pytest.raises(TypeError):
            evaluate_windows(PASSING_SCORES, payload)
        with pytest.raises(TypeError):
            assess_capital_feasibility({D("1500000"): payload, D("2000000"): payload})
        # The seam's own pass rule, with the payload standing in for the calibrated threshold.
        score = _score(1, "leader", "0.05", "0.03", "0.25", EdgeOriginStatus.VALID)
        with pytest.raises((TypeError, DiagnosticPromotionRefused)):
            score.passes(payload)


def test_a_diagnostic_payload_still_reconciles_against_a_published_figure():
    """Equality is permitted because checking a rendered figure against an expected one is the
    entire purpose of a report. It is *not* permitted because equality is never a gate rule — see
    the test below, which is the reason that actually holds."""
    item = diagnostic("buy_win_rate", SCOPE, D("0.612345678"))
    assert item.value == D("0.61234568")
    assert item.value != D("0.61234569")
    assert item.value == diagnostic("median_return", SCOPE, D("0.612345678")).value


def test_equality_is_a_gate_rule_and_calc_is_what_keeps_a_diagnostic_out_of_one():
    """The reason for permitting ``==`` had to be corrected, so the correct one is pinned here.

    ``DiagnosticValue`` used to justify permitting equality with "equality is never a gate rule".
    It is one ten times over: §9.8's validation gate and §9.4's reconciliation conditions state ten
    of their bars as ``EXACTLY``, and "golden-set precision is exactly 1" or "unexplained missing
    trades is exactly 0" are gates in every sense that matters. The outcome the false reason was
    offered in support of is nonetheless safe, for a different reason entirely: ``_check_condition``
    routes the reported figure through :func:`contracts.calc` *before* it compares anything, and
    ``calc`` refuses this type — so the condition is recorded as a ``SCHEMA`` discrepancy, never as
    one that held, whichever comparison it names.

    Both halves are asserted, because only the pair is the claim: the count of ``EXACTLY`` bars
    (which makes the old reason false) and the ``SCHEMA`` outcome at every one of them (which makes
    the guarantee true anyway).
    """
    exactly = tuple(condition
                    for condition in VALIDATION_GATE_CONDITIONS + RECONCILIATION_CONDITIONS
                    if condition.comparison == EXACTLY)
    assert len(exactly) == 10

    # A report that satisfies every one of them exactly, so the refusals below are not a report
    # that was going to fail anyway.
    passing = dict((condition.field, condition.bound) for condition in exactly)
    assert check_conditions_detail(passing, exactly, "spot").ok

    payload = diagnostic("buy_win_rate", SCOPE, D("1")).value
    assert payload == D("1")                      # equal to the bound, by the permitted operator
    for condition in exactly:
        tampered = dict(passing)
        tampered[condition.field] = payload
        detail = check_conditions_detail(tampered, (condition,), "spot")
        assert not detail.ok, condition.field
        assert [d.kind for d in detail.discrepancies] == [SCHEMA], condition.field


def test_no_attribute_of_a_diagnostic_carries_a_measurement_the_gate_would_accept():
    """The class, swept over the **whole tree** and not over its top layer.

    The previous version of this test walked ``shape.__dataclass_fields__`` one level deep, which
    reaches ``d.value`` and stops. Everything interesting is one hop further in: ``d.value.amount``
    is the number, ``d.scope.capital_level`` is a Decimal, and a new Decimal field added anywhere
    below the first level would have been invisible to it. This walks to the leaves.

    Recursing turns the assertion into a stronger one and a more honest one at the same time. The
    claim is *not* "nothing here is calc-readable" — ``DiagnosticValue.amount`` is a bare Decimal
    and ``calc`` accepts it, deliberately and documented, because a report exists to publish its
    numbers. The claim is that the calc-readable paths are exactly the ones named below and no
    others: one per payload, reached by a second differently-named step that reads as what it is in
    a diff. So the assertion is set equality, and any new calc-readable attribute anywhere in the
    tree — at any depth, on any type — fails it.
    """
    #: Names that are coordinates rather than measurements. A rank is a position, an address is an
    #: identity, a capital level is a design constant chosen in §4.5 — none of them is a figure the
    #: gate could be fed as a threshold, so none is required to be unreadable.
    coordinates = {"name", "kind", "wallet", "rank", "gate_relevance",
                   "chain", "window", "population", "capital_level", "liquidity_band", "band"}
    #: The one deliberate exit, and the whole of it. Both spellings are the same field on the same
    #: type, reached down the two shapes that carry a payload.
    documented_exits = {"items.value.amount", "items.rows.value.amount"}

    readable, refused = set(), set()

    def walk(shape, path):
        for name in shape.__dataclass_fields__:
            attribute = getattr(shape, name)
            where = path + (name,)
            if name not in coordinates:
                try:
                    calc(attribute)
                except TypeError:
                    refused.add(".".join(where))
                else:
                    readable.add(".".join(where))
            if hasattr(attribute, "__dataclass_fields__"):
                walk(attribute, where)
            elif isinstance(attribute, tuple):
                for entry in attribute:
                    if hasattr(entry, "__dataclass_fields__"):
                        walk(entry, where)

    walk(_diagnostics(), ())

    assert readable == documented_exits
    # Not vacuous: the sweep really did reach every shape, including the two wrappers whose whole
    # job is to be unreadable and the nested scope that used to be out of reach.
    assert {"items", "items.value", "items.scope", "items.rows", "items.rows.value"} <= refused


# -- the subclass wall ----------------------------------------------------------
#
# The cited value was ``class GatingDiagnostic(Diagnostic, WindowScore)``. The condition is wider:
# **any class deriving from a diagnostic type**, because deriving is also how a caller reopens
# ``__post_init__``'s label check or overrides the comparison refusals — no gate base required.


def test_a_diagnostic_type_cannot_be_subclassed_into_a_gate_input():
    for bases in (
        (Diagnostic, WindowScore),          # the cited shape
        (WindowScore, Diagnostic),          # the same shape, MRO reversed
        (DiagnosticRanking, WindowScore),   # a different diagnostic type
        (reporting.DiagnosticRankingRow, WindowScore),
        (reporting.DiagnosticPack, WindowScore),
    ):
        with pytest.raises(DiagnosticPromotionRefused):
            type("Promoted", bases, {})


def test_a_diagnostic_type_cannot_be_subclassed_at_all_even_without_a_gate_base():
    """No ``WindowScore`` anywhere: a plain subclass is enough to drop ``__post_init__`` and take
    the label the constructor refuses, or to replace the comparison refusals with ``True``."""
    with pytest.raises(DiagnosticPromotionRefused):
        type("Unchecked", (Diagnostic,), {"__post_init__": lambda self: None})
    with pytest.raises(DiagnosticPromotionRefused):
        type("Comparable", (Diagnostic,), {"__gt__": lambda self, other: True})
    with pytest.raises(DiagnosticPromotionRefused):
        type("Plain", (reporting.DiagnosticValue,), {})
    with pytest.raises(DiagnosticPromotionRefused):
        type("Scope", (DiagnosticScope,), {})


# -- what a post-construction rewrite can and cannot do -------------------------


def _run_with(pack):
    windows = tuple(
        report_window(tuple(s for s in PASSING_SCORES if s.window == window))
        for window in (1, 2, 3, 4)
    )
    return report_run(
        run_id="phase0-2026-08-01",
        chain="ethereum",
        basket=report_basket(BASKET_ENTRIES),
        windows=windows,
        capital_ladder=_ladder(),
        churn=report_churn(_churn_population()),
        diagnostics=pack,
    )


def test_object_setattr_rewrites_the_label_and_gains_nothing_by_it():
    """The limit, recorded on purpose rather than claimed away.

    ``object.__setattr__`` rewrites a field of any Python object, ``WindowScore`` included, and no
    class can prevent it. What matters is that the label was never the wall: the rewrite does not
    make the object a ``Decimal`` or a ``WindowScore``, so it buys no route to a gate — and anyone
    able to make the call already holds the number they would be promoting."""
    item = diagnostic("buy_win_rate", SCOPE, D("0.61"))
    object.__setattr__(item, "gate_relevance", "GATE")

    assert item.gate_relevance == "GATE"
    assert not isinstance(item, (WindowScore, Decimal))
    with pytest.raises(TypeError):
        calc(item)
    with pytest.raises(DiagnosticPromotionRefused):
        item > D("0.5")


#: A rewrite is refused; *which* refusal it is is the business of whichever constructor owns the
#: field. That is the point of reconstructing rather than restating — the pack does not know what
#: the checks are, so it cannot normalise their error types either.
REFUSED = (DiagnosticPromotionRefused, reporting.UnknownDiagnostic, ValueError, TypeError)


class _DuckScope(object):
    """Every attribute a ``DiagnosticScope`` has, and none of its construction."""

    chain = "ethereum"
    window = 1
    population = "selected"
    capital_level = None
    liquidity_band = None
    band = None


def _fresh_scope():
    """A scope of its own per case. The module-level ``SCOPE`` is shared by every other test in this
    file, and a case that rewrote one of its fields would fail them instead of itself."""
    return DiagnosticScope(chain="ethereum", window=1, population="selected")


def _scalar():
    return diagnostic("median_return", _fresh_scope(), D("0.045"))


def _ranking():
    return profit_ranking(_fresh_scope(), ((WALLETS[0], D("1000")), (WALLETS[1], D("2000"))))


#: One entry per check in ``Diagnostic``, ``DiagnosticValue``, ``DiagnosticScope``,
#: ``DiagnosticRankingRow`` and ``DiagnosticRanking`` — read off the constructors, not off the pack.
TAMPERS = (
    ("gate_relevance rewritten to GATE",
     _scalar, lambda d: object.__setattr__(d, "gate_relevance", "GATE")),
    ("a name nobody pre-registered",
     _scalar, lambda d: object.__setattr__(d, "name", "sharpe_ratio")),
    ("the payload replaced by a bare Decimal",
     _scalar, lambda d: object.__setattr__(d, "value", D("0.045"))),
    ("a kind outside KINDS",
     _scalar, lambda d: object.__setattr__(d, "kind", "bogus_scale")),
    ("a payload kind disagreeing with the item's",
     _scalar, lambda d: object.__setattr__(d.value, "kind", "usd")),
    ("a payload kind outside KINDS",
     _scalar, lambda d: object.__setattr__(d.value, "kind", "bogus_scale")),
    ("a non-finite payload amount",
     _scalar, lambda d: object.__setattr__(d.value, "amount", D("NaN"))),
    ("a scope replaced by a duck-typed object",
     _scalar, lambda d: object.__setattr__(d, "scope", _DuckScope())),
    ("a scope that no longer names its chain",
     _scalar, lambda d: object.__setattr__(d.scope, "chain", "")),
    ("a scope that no longer names its population",
     _scalar, lambda d: object.__setattr__(d.scope, "population", "")),
    ("a scope band that is not an ActivityBand",
     _scalar, lambda d: object.__setattr__(d.scope, "band", "20-99")),
    ("a ranking's gate_relevance rewritten to GATE",
     _ranking, lambda r: object.__setattr__(r, "gate_relevance", "GATE")),
    ("a ranking row's payload replaced by a bare Decimal",
     _ranking, lambda r: object.__setattr__(r.rows[1], "value", D("2000"))),
    ("a ranking row's payload kind rewritten",
     _ranking, lambda r: object.__setattr__(r.rows[1].value, "kind", "ratio")),
    ("a ranking row's payload amount rewritten to NaN",
     _ranking, lambda r: object.__setattr__(r.rows[1].value, "amount", D("NaN"))),
    ("a ranking row's rank rewritten below 1",
     _ranking, lambda r: object.__setattr__(r.rows[1], "rank", 0)),
    ("a ranking row that no longer names its wallet",
     _ranking, lambda r: object.__setattr__(r.rows[1], "wallet", "")),
    ("a ranking emptied of its rows",
     _ranking, lambda r: object.__setattr__(r, "rows", ())),
)


def test_a_rewritten_diagnostic_cannot_be_published():
    """What is closable is the consequence: a tampered diagnostic never reaches an artifact.

    The list is taken from the item constructors, not from the pack. That distinction is the whole
    reason this test was rewritten: the previous version rewrote ``gate_relevance``, ``value`` and
    ``name``, which are precisely the three things ``DiagnosticPack.__post_init__`` restates for
    itself — so it passed against an implementation whose ``verify()`` re-ran no item's
    ``__post_init__`` at all, and would have gone on passing while a rewritten ``kind``, a payload
    whose kind disagreed with its item's, a ``NaN`` amount and a duck-typed ``scope`` all reached an
    artifact. A test that mirrors the implementation cannot detect the implementation.
    """
    for what, build, rewrite in TAMPERS:
        item = build()
        rewrite(item)
        with pytest.raises(REFUSED):
            diagnostic_pack((item,))
        assert isinstance(item, (Diagnostic, DiagnosticRanking)), what


def test_every_tamper_is_also_refused_at_publication_and_not_only_at_collection():
    """The same list again, applied in the window ``verify()`` exists to cover.

    ``diagnostic_pack(...)`` above refuses at collection time. This one builds a *valid* pack first
    and rewrites an item afterwards, which is the sequence a real tamper has: a pack constructed
    correctly, then a field rewritten, then a report published from it. If the two lists ever
    diverge, the publication boundary is checking less than the collection boundary — which is the
    wrong way round, since publication is the moment the invariant has to hold.
    """
    for what, build, rewrite in TAMPERS:
        pack = diagnostic_pack((build(),))
        rewrite(pack.items[0])
        with pytest.raises(REFUSED):
            pack.verify()


def test_a_ranking_rows_payload_is_checked_and_not_only_a_scalars():
    """A ranking carries its figures one level down, in ``rows``, and that level is easy to skip.

    Pinned on its own because the check that reaches it — ``_check_payload``'s ``else`` arm — is a
    line the whole suite could otherwise lose without going red: a scalar diagnostic exercises the
    ``if`` arm, ``DiagnosticRanking.__post_init__`` validated the rows before the rewrite and never
    looks again, and nothing else in the pack descends into them. Replace the arm with ``[]`` and
    a ranking row carrying a bare Decimal publishes.
    """
    ranking = _ranking()
    object.__setattr__(ranking.rows[1], "value", D("2000"))
    with pytest.raises(DiagnosticPromotionRefused) as refusal:
        diagnostic_pack((ranking,))
    assert "Decimal payload" in str(refusal.value)


def test_rewriting_an_amount_to_another_finite_number_publishes_and_is_stated_as_such():
    """The bound on the guarantee above, pinned so that it stays a stated limit rather than drift.

    No invariant on a diagnostic constrains *which* finite measurement it carries — ``tail_loss``
    is negative, ``buy_return_90d`` may exceed 1 — so reconstruction cannot detect a number swapped
    for another number, and the module says so rather than implying otherwise. What the rewrite does
    not buy is standing: the figure is still a ``DiagnosticValue``, ``calc`` still refuses it, and
    the comparison operators still refuse it. It reaches a report; it does not reach a gate.
    """
    pack = _diagnostics()
    item = pack.named("buy_win_rate")[0]
    object.__setattr__(item.value, "amount", D("99999.00000000"))

    published = _run_with(pack)
    assert published.diagnostics.named("buy_win_rate")[0].value == D("99999.00000000")

    with pytest.raises(TypeError):
        calc(item.value)
    with pytest.raises(DiagnosticPromotionRefused):
        item.value > D("0.5")


def test_a_pack_rewritten_after_construction_cannot_be_reported():
    pack = _diagnostics()
    object.__setattr__(pack, "gate_relevance", "GATE")
    with pytest.raises(DiagnosticPromotionRefused):
        _run_with(pack)

    smuggled = _diagnostics()
    score = _score(1, "leader", "0.05", "0.03", "0.25", EdgeOriginStatus.VALID)
    object.__setattr__(smuggled, "items", smuggled.items + (score,))
    with pytest.raises(DiagnosticPromotionRefused):
        _run_with(smuggled)

    unlabelled = _diagnostics()
    object.__setattr__(unlabelled.items[1], "gate_relevance", "GATE")
    with pytest.raises(DiagnosticPromotionRefused):
        _run_with(unlabelled)


def test_an_untampered_pack_still_reports():
    """The refusals above are not vacuous."""
    assert len(_run_with(_diagnostics()).diagnostics.items) == 11


# -- the four standing integrity figures, §10 and addendum §8 --------------------


def test_every_run_report_carries_the_integrity_block():
    """It is required, because four packages computed these and nothing published them.

    The attribution coverage gap and fallback rate, the reconciliation queue volume and the
    unexplained reconciliation difference were each derived somewhere in ``src/`` and had no field
    in any report type. A reader of a hashed §10 artifact saw none of them — and downstream, a
    figure computed and not published is indistinguishable from a figure nobody measured.
    """
    report = _run()

    assert isinstance(report.integrity, reporting.DataIntegrity)
    assert len(reporting.NOT_MEASURED) == 4


def test_none_means_not_measured_and_never_zero():
    """The whole design of the block, in one assertion.

    A run reporting ``0`` claims somebody looked and found nothing missing. A run reporting ``None``
    says nobody looked. The first is a false claim about a finished project and the second is an
    honest one about an unfinished project, and they are one keystroke apart — so the block
    distinguishes them and names the reason for each absence.
    """
    empty = reporting.DataIntegrity()

    assert empty.decoder_coverage_gap is None
    assert not empty.fully_measured
    assert len(empty.unmeasured) == 4

    for name, reason in empty.unmeasured:
        assert reason, name
        assert len(reason) > 40, "{} gives a reason too short to be one".format(name)

    measured = reporting.DataIntegrity(decoder_coverage_gap=D("0"))
    assert measured.decoder_coverage_gap == D("0")
    assert "decoder_coverage_gap" not in dict(measured.unmeasured), (
        "a measured zero must not read as unmeasured; that is the distinction the block exists for"
    )


def test_the_unmeasured_figures_are_named_rather_than_counted():
    """"Three of four measured" says how much is missing, not which — and which is what decides
    whether the headline number can be read at all."""
    partial = reporting.DataIntegrity(attribution_fallback_rate=D("0.031"))

    names = [name for name, _reason in partial.unmeasured]
    assert names == sorted(names), "a fixed order, so two runs are comparable"
    assert "attribution_fallback_rate" not in names
    assert "decoder_coverage_gap" in names


def test_the_block_survives_into_the_hashed_artifact():
    """A block that did not serialise would publish exactly as much as no block at all.

    ``null`` for unmeasured and the exact decimal string for measured — not a float, which would
    round a volume at 2^53, and not an omitted key, which a reader could not distinguish from a
    schema they do not know.
    """
    report = _run(integrity=reporting.DataIntegrity(attribution_fallback_rate=D("0.031")))
    payload = json.loads(to_canonical_json(reporting.run_artifact(report)))

    integrity = payload["payload"]["integrity"]
    assert integrity["attribution_fallback_rate"] == "0.031"
    assert integrity["decoder_coverage_gap"] is None


def test_a_negative_integrity_figure_is_refused():
    """A negative rate or volume is a defect in whatever produced it, not a small one."""
    with pytest.raises(reporting.IncompleteRunReport):
        reporting.DataIntegrity(reconciliation_queue_volume_usd=D("-1"))


def test_a_bare_mapping_is_not_an_integrity_block():
    """The block is what distinguishes unmeasured from zero; a dict distinguishes nothing."""
    with pytest.raises(reporting.IncompleteRunReport):
        _run(integrity={"decoder_coverage_gap": None})
