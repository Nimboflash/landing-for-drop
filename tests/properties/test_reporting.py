"""Invariants for ``reporting``, over generated populations.

These are the properties a wrong implementation can satisfy every hand-computed case without
holding. Five carry the most weight:

* **a diagnostic can never acquire gate relevance**, for every name, every scope and every value —
  the field has one permitted value and there is no argument that produces a second;
* **every churn wallet lands in exactly one state**, so the three counts always partition the
  population. A wallet that belongs to no state, or to two, makes every rate in the block a
  different number from the one it claims to be;
* **``forward_valid_buys == 0`` is Inactive, always**, whatever the ratio would have said. The
  ratio at zero forward buys is also below the threshold, so an implementation that tested the
  ratio first would classify §10's clearest case as merely reduced;
* **quantization never moves a value by more than half a scale unit**, and the result always sits
  exactly on the scale. Together those say the boundary rounds rather than truncates, drops, or
  re-scales;
* **an unmeasurable figure is ``None`` and never zero** — Copy Retention below the threshold, a
  positive-trade rate over no executable trades, a first-hour share on an INDETERMINATE window.

``derandomize=True`` throughout: the house rule forbids unseeded randomness, and a property suite
that fails only on Tuesdays is worse than none.
"""

from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from contracts import (
    AssetTier,
    BuyQuality,
    CopySimulation,
    EdgeOriginStatus,
    TokenAgeBucket,
    WindowScore,
    add,
    divide,
    sub,
)
from reporting import (
    COPY_RETENTION_MIN_RAW_QUALITY,
    DIAGNOSTIC_NAMES,
    DIAGNOSTIC_ONLY,
    GATING_COLUMNS,
    REDUCED_ACTIVITY_RATIO,
    ChurnState,
    Diagnostic,
    DiagnosticPromotionRefused,
    DiagnosticScope,
    ValueBasisAmounts,
    WalletActivity,
    WalletCapitalOutcome,
    diagnostic,
    mean,
    median,
    output_pp,
    output_ratio,
    output_usd,
    profit_ranking,
    report_basket,
    report_capital_level,
    report_churn,
    report_wallet,
    report_window,
    scale_for,
)

D = Decimal

DETERMINISTIC = settings(derandomize=True, max_examples=200, deadline=None)

SCOPE = DiagnosticScope(chain="ethereum", window=1, population="selected")

LEVEL = D("500000")


def _wallet(index):
    return "0x{:040x}".format(index + 1)


decimals = st.decimals(
    min_value=D("-1000000"),
    max_value=D("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=10,
)

small_decimals = st.decimals(
    min_value=D("-2"), max_value=D("2"), allow_nan=False, allow_infinity=False, places=12
)

positive_usd = st.decimals(
    min_value=D("0"), max_value=D("10000000"), allow_nan=False, allow_infinity=False, places=6
)


# -- the boundary ---------------------------------------------------------------


@DETERMINISTIC
@given(decimals)
def test_quantization_lands_exactly_on_the_declared_scale(value):
    for render, kind in (
        (output_usd, "usd"),
        (output_ratio, "ratio"),
        (output_pp, "percentage_points"),
    ):
        rendered = render(value)
        assert rendered == rendered.quantize(scale_for(kind))


@DETERMINISTIC
@given(decimals)
def test_quantization_never_moves_a_value_by_more_than_half_a_scale_unit(value):
    """Rounding, not truncation and not re-scaling.

    ``copy_abs()`` rather than ``abs()``: the difference is carried at 38 digits and ``abs()``
    would round it to the ambient 28 before the comparison, which is the defect this repository
    has shipped three times.
    """
    for render, kind in (
        (output_usd, "usd"),
        (output_ratio, "ratio"),
        (output_pp, "percentage_points"),
    ):
        drift = sub(render(value), value).copy_abs()
        assert drift <= divide(scale_for(kind), 2)


@DETERMINISTIC
@given(st.lists(small_decimals, min_size=1, max_size=12))
def test_the_mean_lies_within_its_own_inputs(values):
    assert min(values) <= mean(values) <= max(values)


@DETERMINISTIC
@given(st.lists(small_decimals, min_size=1, max_size=12))
def test_the_median_lies_within_its_own_inputs(values):
    assert min(values) <= median(values) <= max(values)


@DETERMINISTIC
@given(st.lists(small_decimals, min_size=1, max_size=11).filter(lambda v: len(v) % 2 == 1))
def test_an_odd_count_median_is_one_of_the_values(values):
    assert median(values) in values


# -- churn ----------------------------------------------------------------------


activity = st.builds(
    lambda baseline, baseline_days, forward, forward_days: (
        baseline,
        baseline_days,
        forward,
        forward_days,
    ),
    st.integers(min_value=1, max_value=1000),
    st.integers(min_value=1, max_value=400),
    st.integers(min_value=0, max_value=1000),
    st.integers(min_value=1, max_value=400),
)


@DETERMINISTIC
@given(activity)
def test_no_forward_buy_is_always_inactive(counts):
    baseline, baseline_days, _forward, forward_days = counts
    wallet = WalletActivity(_wallet(0), baseline, baseline_days, 0, forward_days)
    assert wallet.state is ChurnState.INACTIVE


@DETERMINISTIC
@given(activity)
def test_the_three_states_are_decided_by_the_ratio_and_nothing_else(counts):
    """The state machine, restated as a total function of the two facts it may consult."""
    baseline, baseline_days, forward, forward_days = counts
    wallet = WalletActivity(_wallet(0), baseline, baseline_days, forward, forward_days)

    if forward == 0:
        expected = ChurnState.INACTIVE
    elif wallet.activity_ratio < REDUCED_ACTIVITY_RATIO:
        expected = ChurnState.REDUCED_ACTIVITY
    else:
        expected = ChurnState.ACTIVE
    assert wallet.state is expected


@DETERMINISTIC
@given(st.lists(activity, min_size=1, max_size=20))
def test_the_three_states_partition_the_population(population):
    records = tuple(
        WalletActivity(_wallet(index), *counts) for index, counts in enumerate(population)
    )
    report = report_churn(records)

    assert report.n_wallets == len(records)
    assert report.n_active + report.n_reduced_activity + report.n_inactive == len(records)
    assert len(report.states) == len(records)


@DETERMINISTIC
@given(st.lists(activity, min_size=1, max_size=20))
def test_the_churn_rate_is_the_inactive_share_for_every_population(population):
    """§10's formula is the Inactive share exactly, never the effectively-dead one."""
    records = tuple(
        WalletActivity(_wallet(index), *counts) for index, counts in enumerate(population)
    )
    report = report_churn(records)

    assert report.churn_rate == report.inactive_rate
    assert report.effectively_dead_rate >= report.churn_rate


@DETERMINISTIC
@given(st.lists(activity, min_size=1, max_size=20))
def test_the_three_rates_sum_to_one_within_the_output_scale(population):
    """Quantized rates need not sum to exactly 1 — three thirds render as ``0.99999999`` — so the
    bound is the number of terms times one scale unit, and that is the honest statement."""
    records = tuple(
        WalletActivity(_wallet(index), *counts) for index, counts in enumerate(population)
    )
    report = report_churn(records)

    summed = add(add(report.active_rate, report.reduced_activity_rate), report.inactive_rate)
    assert sub(summed, D("1")).copy_abs() <= D("0.00000003")


# -- value basis ----------------------------------------------------------------


amounts = st.builds(
    lambda realized, marked, dead: (realized, marked, dead),
    positive_usd,
    positive_usd,
    positive_usd,
).filter(lambda triple: sum(triple) > 0)


@DETERMINISTIC
@given(amounts)
def test_the_three_shares_always_sum_to_one(triple):
    basis = ValueBasisAmounts(*triple)
    summed = add(add(basis.realized_share, basis.marked_share), basis.dead_share)
    assert sub(summed, D("1")).copy_abs() <= D("1e-30")


def _quality_from(wallet, value, basis):
    return BuyQuality(
        wallet=wallet,
        value=value,
        n_buys=5,
        realized_share=basis.realized_share,
        marked_share=basis.marked_share,
        dead_share=basis.dead_share,
        bucket_weights={TokenAgeBucket.D: D("1")},
        bucket_values={TokenAgeBucket.D: value},
    )


@DETERMINISTIC
@given(st.lists(st.tuples(amounts, small_decimals), min_size=1, max_size=8))
def test_the_basket_shares_always_sum_to_one_and_lie_within_the_wallet_shares(entries):
    prepared = []
    for index, (triple, value) in enumerate(entries):
        basis = ValueBasisAmounts(*triple)
        prepared.append((_quality_from(_wallet(index), value, basis), basis))

    basket = report_basket(prepared)

    summed = add(add(basket.realized_share, basket.marked_share), basket.dead_share)
    assert sub(summed, D("1")).copy_abs() <= D("0.00000003")

    # A value-weighted mean cannot escape the values it averages. One output-scale unit of slack
    # each way, because the bounds are rendered too. ``sub``/``add`` rather than bare operators:
    # the shares are carried at 38 digits and a bare operator would compare them at 28.
    wallet_realized = [basis.realized_share for _, basis in prepared]
    lower = sub(output_ratio(min(wallet_realized)), D("0.00000001"))
    upper = add(output_ratio(max(wallet_realized)), D("0.00000001"))
    assert lower <= basket.realized_share <= upper


@DETERMINISTIC
@given(amounts, small_decimals)
def test_a_wallet_line_never_renders_a_share_outside_zero_to_one(triple, value):
    basis = ValueBasisAmounts(*triple)
    report = report_wallet(_quality_from(_wallet(0), value, basis), basis)
    for rendered in (report.realized_share, report.marked_share, report.dead_share):
        assert D("0") <= rendered <= D("1")


# -- capital levels -------------------------------------------------------------


@DETERMINISTIC
@given(small_decimals, small_decimals)
def test_copy_retention_is_reported_exactly_when_raw_quality_clears_the_threshold(raw, follower):
    outcome = WalletCapitalOutcome(_wallet(0), raw, follower)
    if raw >= COPY_RETENTION_MIN_RAW_QUALITY:
        assert outcome.copy_retention == divide(follower, raw)
    else:
        assert outcome.copy_retention is None


@DETERMINISTIC
@given(
    st.integers(min_value=0, max_value=8),
    st.integers(min_value=0, max_value=8),
    st.integers(min_value=0, max_value=8),
)
def test_the_two_trade_denominators_never_disagree_with_their_counts(positive, other, unexecutable):
    executable = positive + other
    assume(executable + unexecutable > 0)

    sims = []
    for index in range(executable):
        sims.append(
            CopySimulation(
                capital_level=LEVEL,
                tier=AssetTier.MAJOR,
                intended_order_usd=D("10000"),
                filled_order_usd=D("10000"),
                execution_cost_pct=D("0.005"),
                follower_return=D("0.10") if index < positive else D("-0.10"),
                copyable=True,
            )
        )
    for _ in range(unexecutable):
        sims.append(
            CopySimulation(
                capital_level=LEVEL,
                tier=AssetTier.MAJOR,
                intended_order_usd=D("10000"),
                filled_order_usd=D("0"),
                execution_cost_pct=D("0.05"),
                follower_return=None,
                copyable=False,
                rejection_reason="cost cap exceeded",
            )
        )

    report = report_capital_level(
        LEVEL,
        (WalletCapitalOutcome(_wallet(0), D("0.10"), D("0.05")),),
        tuple(sims),
        ValueBasisAmounts(D("200"), D("700"), D("100")),
    )

    assert report.n_simulated == executable + unexecutable
    assert report.n_executable == executable
    assert report.n_positive == positive
    # The construction check on CapitalLevelReport already refuses a rate over no executable
    # trades; this states the other half — that a zero never stands in for one.
    if executable == 0:
        assert report.positive_trade_rate is None
        assert report.mean_execution_cost_pct is None
    else:
        assert report.positive_trade_rate == output_ratio(divide(positive, executable))
    assert report.unexecutable_trade_share == output_ratio(
        divide(unexecutable, executable + unexecutable)
    )


# -- windows --------------------------------------------------------------------


statuses = st.sampled_from(
    (EdgeOriginStatus.VALID, EdgeOriginStatus.UNCOPYABLE_DOMINATED, EdgeOriginStatus.INDETERMINATE)
)


@DETERMINISTIC
@given(small_decimals, small_decimals, statuses)
def test_the_first_hour_share_is_none_exactly_when_the_window_is_indeterminate(
    mean_advantage, median_advantage, status
):
    measurable = status is not EdgeOriginStatus.INDETERMINATE
    score = WindowScore(
        window=1,
        column=GATING_COLUMNS[0],
        mean_advantage=mean_advantage,
        median_advantage=median_advantage,
        first_hour_edge_share=D("0.25") if measurable else None,
        positive_edge_contribution=D("0.08"),
        edge_origin_status=status,
    )
    column = report_window((score,)).column_for(GATING_COLUMNS[0])

    assert (column.first_hour_edge_share is None) is (status is EdgeOriginStatus.INDETERMINATE)


@DETERMINISTIC
@given(small_decimals, small_decimals)
def test_the_stored_sign_always_matches_the_unrounded_value(mean_advantage, median_advantage):
    """The rendered figure may be ``0.0000``; the sign never is.

    §7.1 conditions 1 and 2 are strict inequalities on the unrounded number, so a report whose sign
    came from the rendered value would disagree with the gate for every advantage smaller than half
    a percentage-point unit.
    """
    score = WindowScore(
        window=1,
        column=GATING_COLUMNS[0],
        mean_advantage=mean_advantage,
        median_advantage=median_advantage,
        first_hour_edge_share=D("0.25"),
        positive_edge_contribution=D("0.08"),
        edge_origin_status=EdgeOriginStatus.VALID,
    )
    column = report_window((score,)).column_for(GATING_COLUMNS[0])

    assert column.mean_advantage_is_positive is (mean_advantage > 0)
    assert column.median_advantage_is_positive is (median_advantage > 0)


# -- diagnostics ----------------------------------------------------------------


@DETERMINISTIC
@given(st.sampled_from(DIAGNOSTIC_NAMES), small_decimals)
def test_a_diagnostic_always_carries_the_only_permitted_label(name, value):
    assume(name != "absolute_profit_ranking")
    item = diagnostic(name, SCOPE, value)
    assert item.gate_relevance == DIAGNOSTIC_ONLY


@DETERMINISTIC
@given(st.text(min_size=1, max_size=20), st.sampled_from(DIAGNOSTIC_NAMES), small_decimals)
def test_no_label_other_than_diagnostic_only_can_be_constructed(label, name, value):
    assume(label != DIAGNOSTIC_ONLY)
    with pytest.raises(DiagnosticPromotionRefused):
        Diagnostic(name=name, scope=SCOPE, kind="ratio", value=value, gate_relevance=label)


@DETERMINISTIC
@given(small_decimals, small_decimals)
def test_a_diagnostic_can_never_be_compared_against_a_threshold(value, threshold):
    item = diagnostic("buy_win_rate", SCOPE, value)
    for compare in (
        lambda: item > threshold,
        lambda: item >= threshold,
        lambda: item < threshold,
        lambda: item <= threshold,
    ):
        with pytest.raises(DiagnosticPromotionRefused):
            compare()


@DETERMINISTIC
@given(st.lists(st.decimals(min_value=D("-1e6"), max_value=D("1e6"), places=7), min_size=1, max_size=10))
def test_a_profit_ranking_is_monotone_and_covers_every_wallet(profits):
    rows = tuple((_wallet(index), profit) for index, profit in enumerate(profits))
    ranking = profit_ranking(SCOPE, rows)

    assert len(ranking.rows) == len(rows)
    assert {row.wallet for row in ranking.rows} == {wallet for wallet, _ in rows}
    # Competition ranking: the rank never decreases down the list and the first is always 1.
    assert ranking.rows[0].rank == 1
    ranks = [row.rank for row in ranking.rows]
    assert ranks == sorted(ranks)

    # Monotonicity is asserted against the **unquantized** profits the ranking was built from,
    # not by ordering one rendered payload against the next. Two reasons, and both matter:
    #
    # * a diagnostic payload refuses ordering outright, in either direction. Comparing two of them
    #   is exactly how a threshold gets laundered — wrap it as a diagnostic, compare, branch on the
    #   bool — so the refusal has no same-type exemption for the ranking to lean on;
    # * ordering the rendered figures is the weaker claim anyway. Two profits that differ below the
    #   USD output scale render identically, so `>=` on the payloads holds for a ranking that got
    #   the order wrong, which is the defect `profit_ranking` sorts unquantized to avoid.
    by_wallet = {wallet: profit for wallet, profit in rows}
    ordered = [by_wallet[row.wallet] for row in ranking.rows]
    assert ordered == sorted(ordered, reverse=True)

    # Equality is permitted where ordering is not, so the tie rule is still assertable: rows that
    # share a rank are rows whose published figures agree.
    for earlier, later in zip(ranking.rows, ranking.rows[1:]):
        if earlier.rank == later.rank:
            assert earlier.value == later.value
