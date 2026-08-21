"""Worked examples for ``reporting``. Every expectation is a literal, derived from §10, addendum
§9.3 and §3.1 before the module existed.

Three families of expectation, and the difference between them is the point of the file.

**Closed-form arithmetic.** ``3 of 10 wallets inactive`` is a churn rate of ``0.30000000`` and
nothing else. Those are written as literals and compared with exact equality.

**Rounding at the boundary.** ``ROUND_HALF_EVEN`` at each of the three scales, on values chosen to
sit exactly on a half. ``0.000000005`` renders as ``0.00000000`` and ``0.000000015`` as
``0.00000002`` — the two answers a naive "round half up" gets wrong in opposite directions, so a
test that only checked one of them would pass against it.

**Order of operations at the boundary.** The load-bearing one. ``mean(quantize(x))`` and
``quantize(mean(x))`` are different numbers, and both literals appear below so the assertion pins
which one the module produces rather than merely agreeing with whatever it happens to do. Same for
Copy Retention: ``mean(fᵢ/rᵢ)`` is ``0.5`` on the fixture below while ``mean(f)/mean(r)`` is
``0.66666667``, and only one of them is what §10 asked for.

Constants are pinned as absolute literals — ``REDUCED_ACTIVITY_RATIO == Decimal("0.25")``,
``COPY_RETENTION_MIN_RAW_QUALITY == Decimal("0.02")``, the five capital levels — *and* exercised at
their exact boundaries. A test that read the constant and then computed the boundary from it would
move with the constant and assert nothing about it.
"""

from decimal import Decimal, InvalidOperation, localcontext

import pytest

from contracts import (
    AssetTier,
    BuyQuality,
    CopySimulation,
    EdgeOriginStatus,
    TokenAgeBucket,
    WindowScore,
    divide,
)
from reporting import (
    CAPITAL_LEVELS,
    COPY_RETENTION_MIN_RAW_QUALITY,
    DIAGNOSTIC_ONLY,
    GATING_COLUMNS,
    REDUCED_ACTIVITY_RATIO,
    ActivityBand,
    ChurnInputRefused,
    ChurnState,
    ConflictingWindowResults,
    Diagnostic,
    DiagnosticPack,
    DiagnosticPromotionRefused,
    DiagnosticScope,
    EmptyPopulation,
    IncompleteCapitalLadder,
    InconsistentValueBasis,
    MismatchedCapitalLevel,
    NonGatingColumnReported,
    UnknownCapitalLevel,
    UnknownDiagnostic,
    UnreportableBasket,
    UnreportableValue,
    ValueBasisAmounts,
    WalletActivity,
    WalletCapitalOutcome,
    activity_band,
    at_output,
    diagnostic,
    diagnostic_pack,
    mean,
    median,
    output_pp,
    output_ratio,
    output_usd,
    profit_ranking,
    rate,
    report_basket,
    report_capital_ladder,
    report_capital_level,
    report_churn,
    report_wallet,
    report_window,
    share,
)

D = Decimal

W1 = "0x" + "11" * 20
W2 = "0x" + "22" * 20
W3 = "0x" + "33" * 20
W4 = "0x" + "44" * 20

SCOPE = DiagnosticScope(chain="ethereum", window=1, population="selected")


# -- the boundary ---------------------------------------------------------------


def test_half_even_at_the_ratio_scale():
    """Exactly on the half, in both directions. ``0`` is even, ``2`` is even."""
    assert output_ratio(D("0.000000005")) == D("0.00000000")
    assert output_ratio(D("0.000000015")) == D("0.00000002")
    assert output_ratio(D("0.000000025")) == D("0.00000002")


def test_half_even_at_the_usd_and_pp_scales():
    assert output_usd(D("1.0000005")) == D("1.000000")
    assert output_usd(D("1.0000015")) == D("1.000002")
    assert output_pp(D("0.00005")) == D("0.0000")
    assert output_pp(D("0.00015")) == D("0.0002")


def test_each_scale_is_the_one_the_seam_declares():
    """Six decimals for USD, eight for ratios, four for percentage points — as an exponent, so a
    value that merely compares equal to the right number does not pass."""
    assert output_usd(D("1")).as_tuple().exponent == -6
    assert output_ratio(D("1")).as_tuple().exponent == -8
    assert output_pp(D("1")).as_tuple().exponent == -4


def test_quantization_does_not_move_with_the_ambient_context():
    """The frozen context is held while quantizing, so the published figure is the same number
    whatever the caller's ``decimal`` context happens to be.

    Without the ``localcontext`` block in ``boundary.at_output``, ``Decimal.quantize`` consults the
    ambient precision and raises ``InvalidOperation`` at 28 digits for a value this size — so the
    report would be renderable or not depending on a global the package does not control. That is
    the shape of the defect that once moved the canonical hash three different ways.
    """
    expected = D("1000000000000000000000000000000.000000")
    assert output_usd(D("1E+30")) == expected
    with localcontext() as ctx:
        ctx.prec = 9
        assert output_usd(D("1E+30")) == expected
    with localcontext() as ctx:
        ctx.prec = 28
        assert output_usd(D("1E+30")) == expected
        with pytest.raises(InvalidOperation):
            D("1E+30").quantize(D("0.000001"))


def test_a_value_too_large_for_its_scale_is_refused_not_widened():
    """41 significant digits at six decimal places exceeds even the frozen 38."""
    with pytest.raises(UnreportableValue):
        output_usd(D("1E+33"))


def test_an_unknown_output_kind_is_refused_rather_than_defaulted():
    with pytest.raises(ValueError):
        at_output(D("1"), "dollars", "field")


# -- aggregation, upstream of the boundary --------------------------------------


def test_mean_and_median_are_computed_before_quantization_not_after():
    """The rule the whole package is arranged around, as two literals.

    ``(0.333333334 + 0.333333334 + 0.333333338) / 3 = 0.333333335333…``, which renders as
    ``0.33333334``. Quantizing first gives ``(0.33333333 + 0.33333333 + 0.33333334) / 3 =
    0.33333333…``, which renders as ``0.33333333``. One ULP of the output scale, from rounding in
    the wrong order — and the gap grows with the spread of the inputs.
    """
    values = (D("0.333333334"), D("0.333333334"), D("0.333333338"))

    assert output_ratio(mean(values)) == D("0.33333334")

    quantized_first = mean(tuple(output_ratio(v) for v in values))
    assert output_ratio(quantized_first) == D("0.33333333")


def test_median_of_an_even_count_is_the_midpoint():
    assert median((D("0.2"), D("0.5"), D("0.8"), D("0.1"))) == D("0.35")


def test_median_of_an_odd_count_is_the_middle_value():
    assert median((D("0.8"), D("0.1"), D("0.4"))) == D("0.4")


def test_an_empty_population_has_no_mean_no_median_and_no_rate():
    for call in (lambda: mean(()), lambda: median(()), lambda: rate(0, 0)):
        with pytest.raises(EmptyPopulation):
            call()


def test_a_share_of_a_population_that_does_not_exist_is_not_zero():
    with pytest.raises(EmptyPopulation):
        share(D("0"), D("0"))
    assert share(D("3"), D("12")) == D("0.25")


def test_a_count_outside_its_population_is_a_bookkeeping_error():
    with pytest.raises(ValueError):
        rate(11, 10)
    with pytest.raises(ValueError):
        rate(-1, 10)


# -- churn ----------------------------------------------------------------------


def test_the_reduced_activity_threshold_is_pinned():
    assert REDUCED_ACTIVITY_RATIO == D("0.25")


def test_the_wallet_that_fell_from_a_hundred_trades_to_one():
    """§10's own example. ``(1 x 180) / (100 x 180) = 0.01``, which is not Active."""
    wallet = WalletActivity(W1, 100, 180, 1, 180)
    assert wallet.activity_ratio == D("0.01")
    assert wallet.state is ChurnState.REDUCED_ACTIVITY


def test_the_reduced_activity_boundary_is_strict_and_exact():
    """``25 of 100`` is exactly the threshold and stays Active; ``24 of 100`` is 0.24 and does not.

    Both ratios are exact because the cross-product is an integer division that terminates, which
    is why the boundary is a boundary a test can stand on rather than a 38th-digit accident.
    """
    on_the_line = WalletActivity(W1, 100, 180, 25, 180)
    assert on_the_line.activity_ratio == D("0.25")
    assert on_the_line.state is ChurnState.ACTIVE

    below = WalletActivity(W2, 100, 180, 24, 180)
    assert below.activity_ratio == D("0.24")
    assert below.state is ChurnState.REDUCED_ACTIVITY


def test_no_forward_buy_is_inactive_whatever_the_ratio_would_say():
    wallet = WalletActivity(W1, 100, 180, 0, 180)
    assert wallet.activity_ratio == D("0")
    assert wallet.state is ChurnState.INACTIVE


def test_the_comparison_is_on_rates_so_unequal_periods_do_not_fake_a_collapse():
    """200 buys over 400 days is 0.5/day; 30 buys over 90 days is 0.333/day.

    ``(30 x 400) / (200 x 90) = 12000 / 18000 = 0.6666…`` — Active. Comparing raw counts would have
    read 30 against 200 as an 85% collapse produced entirely by the calendar.
    """
    wallet = WalletActivity(W1, 200, 400, 30, 90)
    assert wallet.baseline_rate == D("0.5")
    assert wallet.activity_ratio == divide(D("12000"), D("18000"))
    assert wallet.state is ChurnState.ACTIVE

    quieter = WalletActivity(W2, 200, 400, 10, 90)
    assert quieter.activity_ratio == divide(D("4000"), D("18000"))
    assert quieter.state is ChurnState.REDUCED_ACTIVITY


def test_a_selected_wallet_with_no_baseline_is_refused_not_classified():
    with pytest.raises(ChurnInputRefused):
        WalletActivity(W1, 0, 180, 5, 180)


def test_a_period_of_no_length_cannot_carry_a_rate():
    with pytest.raises(ChurnInputRefused):
        WalletActivity(W1, 100, 0, 5, 180)
    with pytest.raises(ChurnInputRefused):
        WalletActivity(W1, 100, 180, 5, 0)


def _churn_population():
    """Ten wallets: five Active, two Reduced Activity, three Inactive."""
    records = []
    for index in range(5):
        records.append(WalletActivity("0x{:040x}".format(index), 100, 180, 100, 180))
    for index in range(5, 7):
        records.append(WalletActivity("0x{:040x}".format(index), 100, 180, 1, 180))
    for index in range(7, 10):
        records.append(WalletActivity("0x{:040x}".format(index), 100, 180, 0, 180))
    return tuple(records)


def test_churn_rate_is_the_inactive_share_and_nothing_wider():
    """§10's formula verbatim: wallets with *no valid buy* in the forward period, over the total.

    Three of ten. The two Reduced Activity wallets are not folded in — widening a pre-registered
    formula to match its own prose is how a published number stops meaning what its name says.
    """
    report = report_churn(_churn_population())

    assert (report.n_active, report.n_reduced_activity, report.n_inactive) == (5, 2, 3)
    assert report.churn_rate == D("0.30000000")
    assert report.inactive_rate == D("0.30000000")
    assert report.reduced_activity_rate == D("0.20000000")
    assert report.active_rate == D("0.50000000")


def test_the_effectively_dead_share_is_reported_separately_and_named_so():
    """§10's prose — a wallet that fell from 100 trades to 1 is effectively dead — as its own
    figure. Five of ten here, against a churn rate of three of ten."""
    report = report_churn(_churn_population())
    assert report.effectively_dead_rate == D("0.50000000")
    assert report.effectively_dead_rate != report.churn_rate


def test_the_threshold_travels_with_the_report():
    report = report_churn(_churn_population())
    assert report.reduced_activity_threshold == D("0.25")


def test_a_wallet_counted_twice_is_refused():
    duplicate = (WalletActivity(W1, 100, 180, 50, 180), WalletActivity(W1, 100, 180, 50, 180))
    with pytest.raises(ChurnInputRefused):
        report_churn(duplicate)


def test_churn_over_no_wallets_is_refused_rather_than_zero():
    with pytest.raises(ChurnInputRefused):
        report_churn(())


# -- value basis and the basket -------------------------------------------------


def _quality(wallet, value, realized, marked, dead):
    total = realized + marked + dead
    return BuyQuality(
        wallet=wallet,
        value=D(value),
        n_buys=10,
        realized_share=divide(D(realized), D(total)),
        marked_share=divide(D(marked), D(total)),
        dead_share=divide(D(dead), D(total)),
        bucket_weights={TokenAgeBucket.D: D("1")},
        bucket_values={TokenAgeBucket.D: D(value)},
    )


def test_the_three_shares_come_out_of_the_usd_behind_them():
    amounts = ValueBasisAmounts(D("200"), D("700"), D("100"))
    assert amounts.total_usd == D("1000")
    assert amounts.realized_share == D("0.2")
    assert amounts.marked_share == D("0.7")
    assert amounts.dead_share == D("0.1")


def test_a_basket_with_no_recorded_value_basis_is_refused():
    with pytest.raises(UnreportableBasket):
        ValueBasisAmounts(D("0"), D("0"), D("0"))


def test_a_negative_value_basis_is_refused():
    with pytest.raises(UnreportableBasket):
        ValueBasisAmounts(D("-1"), D("700"), D("100"))


def test_the_wallet_line_renders_the_score_and_its_mix():
    quality = _quality(W1, "0.10", 200, 700, 100)
    report = report_wallet(quality, ValueBasisAmounts(D("200"), D("700"), D("100")))

    assert report.wallet == W1
    assert report.buy_quality == D("0.10000000")
    assert report.realized_share == D("0.20000000")
    assert report.marked_share == D("0.70000000")
    assert report.dead_share == D("0.10000000")
    assert report.bucket_values[TokenAgeBucket.D] == D("0.10000000")


def test_a_score_whose_shares_disagree_with_its_amounts_is_refused():
    """A derived value in an artifact is a redundant assertion, not the authority.

    The score below claims 20% realized while its amounts imply 80%. Reinterpreting one in terms of
    the other would publish whichever the reader happened to look at.
    """
    quality = _quality(W1, "0.10", 200, 700, 100)
    with pytest.raises(InconsistentValueBasis):
        report_wallet(quality, ValueBasisAmounts(D("800"), D("100"), D("100")))


def test_the_basket_aggregate_is_value_weighted_not_a_mean_of_shares():
    """Three wallets of very different size. §10 asks for the basket's mix, not the average wallet's.

        realized  200 +  8000 +  800 =  9000        9000 / 12000 = 0.75000000
        marked    700 +  1000 +  200 =  1900        1900 / 12000 = 0.15833333
        dead      100 +  1000 +    0 =  1100        1100 / 12000 = 0.09166667

    The unweighted mean of the per-wallet realized shares is ``(0.2 + 0.8 + 0.8) / 3 = 0.6``, which
    is a different number reported under §10's name — and the gap is largest exactly when the
    basket is most concentrated, which is when it matters.
    """
    entries = (
        (_quality(W1, "0.10", 200, 700, 100), ValueBasisAmounts(D("200"), D("700"), D("100"))),
        (_quality(W2, "0.30", 8000, 1000, 1000), ValueBasisAmounts(D("8000"), D("1000"), D("1000"))),
        (_quality(W3, "0.05", 800, 200, 0), ValueBasisAmounts(D("800"), D("200"), D("0"))),
    )
    basket = report_basket(entries)

    assert basket.realized_share == D("0.75000000")
    assert basket.marked_share == D("0.15833333")
    assert basket.dead_share == D("0.09166667")
    assert basket.realized_share != D("0.60000000")

    assert basket.total_usd == D("12000.000000")
    assert basket.realized_usd == D("9000.000000")
    assert basket.mean_buy_quality == D("0.15000000")
    assert basket.median_buy_quality == D("0.10000000")
    assert basket.n_wallets == 3


def test_the_basket_refuses_to_aggregate_already_rendered_wallet_lines():
    """The weights are not in a ``WalletReport`` and its shares are already rounded, so an
    aggregate built from them is an unweighted mean wearing the clothes of a value share."""
    quality = _quality(W1, "0.10", 200, 700, 100)
    rendered = report_wallet(quality, ValueBasisAmounts(D("200"), D("700"), D("100")))
    with pytest.raises(TypeError):
        report_basket((rendered,))


def test_a_wallet_in_the_basket_twice_is_refused():
    entry = (_quality(W1, "0.10", 200, 700, 100), ValueBasisAmounts(D("200"), D("700"), D("100")))
    with pytest.raises(UnreportableBasket):
        report_basket((entry, entry))


# -- capital levels -------------------------------------------------------------


def test_the_five_capital_levels_are_pinned():
    assert CAPITAL_LEVELS == (
        D("100000"),
        D("250000"),
        D("500000"),
        D("1500000"),
        D("2000000"),
    )


def test_the_copy_retention_display_threshold_is_pinned():
    assert COPY_RETENTION_MIN_RAW_QUALITY == D("0.02")


def test_copy_retention_is_displayed_exactly_on_the_two_point_threshold():
    """Addendum §9.3 says ``>=``, so a raw quality of exactly 2pp is displayed."""
    on_the_line = WalletCapitalOutcome(W1, D("0.02"), D("0.01"))
    assert on_the_line.retention_is_reportable is True
    assert on_the_line.copy_retention == D("0.5")


def test_copy_retention_is_suppressed_a_hair_below_the_threshold():
    below = WalletCapitalOutcome(W1, D("0.0199999999"), D("0.01"))
    assert below.retention_is_reportable is False
    assert below.copy_retention is None


def test_copy_retention_is_suppressed_for_a_negative_raw_quality():
    """The threshold disposes of the sign-flipped ratio too: ``-0.05 / -0.10 = 0.5`` would publish
    a wallet that lost money for its follower as having retained half the edge."""
    negative = WalletCapitalOutcome(W1, D("-0.10"), D("-0.05"))
    assert negative.copy_retention is None


def _sims(level, executable_returns, costs, unexecutable):
    sims = []
    for follower_return, cost in zip(executable_returns, costs):
        sims.append(
            CopySimulation(
                capital_level=level,
                tier=AssetTier.MAJOR,
                intended_order_usd=D("10000"),
                filled_order_usd=D("10000"),
                execution_cost_pct=cost,
                follower_return=follower_return,
                copyable=True,
            )
        )
    for _ in range(unexecutable):
        sims.append(
            CopySimulation(
                capital_level=level,
                tier=AssetTier.MAJOR,
                intended_order_usd=D("10000"),
                filled_order_usd=D("0"),
                execution_cost_pct=D("0.05"),
                follower_return=None,
                copyable=False,
                rejection_reason="cost cap exceeded",
            )
        )
    return tuple(sims)


LEVEL = D("500000")


def test_the_capital_level_block_carries_both_denominators():
    """Five simulated trades, three executable, two of those positive.

        unexecutable trade share  =  2 / 5  =  0.40000000
        positive trade rate       =  2 / 3  =  0.66666667

    Both counts travel with both rates: a 67% positive rate measured on 60% of the trades is a
    different finding from the same rate measured on all of them, and ticket 63 exists because the
    two are otherwise indistinguishable.
    """
    outcomes = (
        WalletCapitalOutcome(W1, D("0.10"), D("0.01")),
        WalletCapitalOutcome(W2, D("0.10"), D("0.04")),
    )
    sims = _sims(LEVEL, (D("0.10"), D("-0.05"), D("0.20")), (D("0.005"), D("0.010"), D("0.015")), 2)
    report = report_capital_level(LEVEL, outcomes, sims, ValueBasisAmounts(D("200"), D("700"), D("100")))

    assert report.n_simulated == 5
    assert report.n_executable == 3
    assert report.n_positive == 2
    assert report.unexecutable_trade_share == D("0.40000000")
    assert report.positive_trade_rate == D("0.66666667")
    assert report.mean_execution_cost_pct == D("0.0100")


def test_a_level_where_nothing_was_executable_reports_no_positive_rate():
    """Not zero. A zero would read as 'every trade lost money'; nothing was placed."""
    outcomes = (WalletCapitalOutcome(W1, D("0.10"), D("0.01")),)
    sims = _sims(LEVEL, (), (), 4)
    report = report_capital_level(LEVEL, outcomes, sims, ValueBasisAmounts(D("1"), D("0"), D("0")))

    assert report.unexecutable_trade_share == D("1.00000000")
    assert report.positive_trade_rate is None
    assert report.mean_execution_cost_pct is None


def test_copy_retention_is_the_mean_of_the_ratios_not_the_ratio_of_the_means():
    """Three wallets clearing the threshold, one below it.

        retentions   0.01/0.10 = 0.1   ·   0.04/0.10 = 0.4   ·   0.25/0.25 = 1.0
        mean         (0.1 + 0.4 + 1.0) / 3            = 0.50000000
        median       sorted -> 0.1, 0.4, 1.0          = 0.40000000

    The ratio of the two reported means is ``0.07625 / 0.115 = 0.66304348`` — a different number,
    from a formula §10 did not ask for. Both literals appear so the assertion pins which.
    """
    outcomes = (
        WalletCapitalOutcome(W1, D("0.10"), D("0.01")),
        WalletCapitalOutcome(W2, D("0.10"), D("0.04")),
        WalletCapitalOutcome(W3, D("0.25"), D("0.25")),
        WalletCapitalOutcome(W4, D("0.01"), D("0.005")),
    )
    sims = _sims(LEVEL, (D("0.10"),), (D("0.005"),), 0)
    report = report_capital_level(LEVEL, outcomes, sims, ValueBasisAmounts(D("200"), D("700"), D("100")))

    assert report.n_wallets == 4
    assert report.n_retention_reported == 3
    assert report.n_retention_suppressed == 1
    assert report.mean_copy_retention == D("0.50000000")
    assert report.median_copy_retention == D("0.40000000")

    assert report.mean_raw_buy_quality == D("0.11500000")
    assert report.mean_follower_adjusted_buy_quality == D("0.07625000")
    assert report.mean_copy_retention != output_ratio(divide(D("0.07625"), D("0.115")))


def test_copy_retention_is_aggregated_before_it_is_rendered():
    """The same ordering rule as the boundary test above, on the figure §10 actually publishes.

    Three retentions of ``0.333333334``, ``0.333333334`` and ``0.333333338``. Aggregating first
    gives ``0.33333334``; rendering each first and then averaging gives ``0.33333333``.
    """
    outcomes = (
        WalletCapitalOutcome(W1, D("1"), D("0.333333334")),
        WalletCapitalOutcome(W2, D("1"), D("0.333333334")),
        WalletCapitalOutcome(W3, D("1"), D("0.333333338")),
    )
    sims = _sims(LEVEL, (D("0.10"),), (D("0.005"),), 0)
    report = report_capital_level(LEVEL, outcomes, sims, ValueBasisAmounts(D("1"), D("0"), D("0")))

    assert report.mean_copy_retention == D("0.33333334")
    assert report.median_copy_retention == D("0.33333333")


def test_no_figure_in_the_capital_block_is_rounded_on_its_way_into_an_aggregate():
    """The rule the test above pins for Copy Retention, applied to every other aggregate here.

    Copy Retention was covered; the three means beside it were not, and each is one edit away from
    the same defect with nothing to notice. The dangerous condition is **"a value is quantized
    before it is aggregated rather than after"**, and it is invisible to every check on shape: the
    published figure is still a ``Decimal``, still at the declared scale, still inside a record
    whose constructor validates. Only a fixture whose inputs carry digits below the output scale
    can tell, so all three below do, at two different scales.

        raw quality       0.020000004 · 0.020000004 · 0.020000009
            sum 0.060000017 / 3 = 0.0200000056666...  ->  8dp  ->  0.02000001
            rendered first: 0.02000000 · 0.02000000 · 0.02000001, mean -> 0.02000000

        follower quality  0.010000004 · 0.010000004 · 0.010000009
            sum 0.030000017 / 3 = 0.0100000056666...  ->  8dp  ->  0.01000001
            rendered first: 0.01000000 · 0.01000000 · 0.01000001, mean -> 0.01000000

        execution cost    0.00004 · 0.00004 · 0.00009        (percentage-point scale, 4dp)
            sum 0.00017 / 3 = 0.0000566666...          ->  4dp  ->  0.0001
            rendered first: 0.0000 · 0.0000 · 0.0001, mean 0.0000333... ->  0.0000

    Both literals are written out in each case, so the assertion pins which order of operations the
    module performs rather than agreeing with whichever one it happens to have.
    """
    outcomes = (
        WalletCapitalOutcome(W1, D("0.020000004"), D("0.010000004")),
        WalletCapitalOutcome(W2, D("0.020000004"), D("0.010000004")),
        WalletCapitalOutcome(W3, D("0.020000009"), D("0.010000009")),
    )
    sims = _sims(
        LEVEL,
        (D("0.10"), D("0.20"), D("0.30")),
        (D("0.00004"), D("0.00004"), D("0.00009")),
        0,
    )
    report = report_capital_level(LEVEL, outcomes, sims, ValueBasisAmounts(D("1"), D("0"), D("0")))

    assert report.mean_raw_buy_quality == D("0.02000001")
    assert report.mean_raw_buy_quality != D("0.02000000")
    assert report.mean_follower_adjusted_buy_quality == D("0.01000001")
    assert report.mean_follower_adjusted_buy_quality != D("0.01000000")
    assert report.mean_execution_cost_pct == D("0.0001")
    assert report.mean_execution_cost_pct != D("0.0000")


def test_a_simulation_from_another_capital_level_is_refused():
    outcomes = (WalletCapitalOutcome(W1, D("0.10"), D("0.01")),)
    sims = _sims(D("2000000"), (D("0.10"),), (D("0.005"),), 0)
    with pytest.raises(MismatchedCapitalLevel):
        report_capital_level(LEVEL, outcomes, sims, ValueBasisAmounts(D("1"), D("0"), D("0")))


def test_a_capital_level_nobody_pre_registered_is_refused():
    with pytest.raises(UnknownCapitalLevel):
        report_capital_level(
            D("750000"),
            (WalletCapitalOutcome(W1, D("0.10"), D("0.01")),),
            _sims(D("750000"), (D("0.10"),), (D("0.005"),), 0),
            ValueBasisAmounts(D("1"), D("0"), D("0")),
        )


def _level_report(level):
    return report_capital_level(
        level,
        (WalletCapitalOutcome(W1, D("0.10"), D("0.05")),),
        _sims(level, (D("0.10"),), (D("0.005"),), 1),
        ValueBasisAmounts(D("200"), D("700"), D("100")),
    )


def test_the_ladder_refuses_four_of_the_five_levels():
    with pytest.raises(IncompleteCapitalLadder):
        report_capital_ladder([_level_report(l) for l in CAPITAL_LEVELS[:4]])


def test_the_ladder_reports_all_five_in_ascending_order():
    ladder = report_capital_ladder([_level_report(l) for l in reversed(CAPITAL_LEVELS)])
    assert tuple(r.capital_level for r in ladder.levels) == CAPITAL_LEVELS
    assert ladder.at(D("1.5E+6")).capital_level == D("1500000")


# -- windows --------------------------------------------------------------------


def _score(column, mean_advantage, median_advantage, share_value, status):
    return WindowScore(
        window=2,
        column=column,
        mean_advantage=mean_advantage,
        median_advantage=median_advantage,
        first_hour_edge_share=share_value,
        positive_edge_contribution=D("0.08"),
        edge_origin_status=status,
    )


def test_the_window_line_renders_at_the_percentage_point_scale():
    report = report_window(
        (
            _score("leader", D("0.0523"), D("0.0311"), D("0.25"), EdgeOriginStatus.VALID),
            _score("follower_adjusted", D("0.0210"), D("0.0100"), D("0.25"), EdgeOriginStatus.VALID),
        )
    )
    leader = report.column_for("leader")

    assert report.window == 2
    assert report.missing_columns == ()
    assert leader.mean_advantage == D("0.0523")
    assert leader.median_advantage == D("0.0311")
    assert leader.first_hour_edge_share == D("0.25000000")
    assert leader.positive_edge_contribution == D("0.08000000")


def test_the_sign_survives_a_value_that_rounds_to_zero():
    """§7.1 condition 2 is ``median_advantage > 0`` on the unrounded number.

    ``1e-9`` renders as ``0.0000`` at the percentage-point scale. Without the stored sign, a
    reconciler recomputing the condition from the published figure would conclude the window should
    have failed, and a reader would conclude the report was broken.
    """
    report = report_window(
        (_score("leader", D("0.000000001"), D("0.000000001"), D("0.25"), EdgeOriginStatus.VALID),)
    )
    leader = report.column_for("leader")

    assert leader.median_advantage == D("0.0000")
    assert leader.median_advantage_is_positive is True
    assert leader.mean_advantage_is_positive is True


def test_a_negative_advantage_that_rounds_to_zero_keeps_its_sign_too():
    report = report_window(
        (_score("leader", D("-0.000000001"), D("-0.000000001"), D("0.25"), EdgeOriginStatus.VALID),)
    )
    leader = report.column_for("leader")

    assert leader.median_advantage == D("0.0000")
    assert leader.median_advantage_is_positive is False


def test_an_indeterminate_window_carries_no_first_hour_share():
    report = report_window(
        (_score("leader", D("0.01"), D("0.01"), None, EdgeOriginStatus.INDETERMINATE),)
    )
    assert report.column_for("leader").first_hour_edge_share is None


def test_a_missing_column_is_recorded_rather_than_hidden():
    report = report_window(
        (_score("leader", D("0.0523"), D("0.0311"), D("0.25"), EdgeOriginStatus.VALID),)
    )
    assert report.missing_columns == ("follower_adjusted",)


def test_two_windows_cannot_be_rendered_into_one_row():
    """A window report describes one window. Rendering two into one row is how a window that
    failed disappears behind one that passed — and the caller who mixed them almost certainly did
    not mean to, which is exactly why it must not be silently absorbed."""
    first = _score("leader", D("0.0523"), D("0.0311"), D("0.25"), EdgeOriginStatus.VALID)
    other = WindowScore(
        window=3,
        column="follower_adjusted",
        mean_advantage=D("-0.0400"),
        median_advantage=D("-0.0200"),
        first_hour_edge_share=None,
        positive_edge_contribution=D("0.01"),
        edge_origin_status=EdgeOriginStatus.INDETERMINATE,
    )
    with pytest.raises(ConflictingWindowResults):
        report_window((first, other))


def test_two_results_for_one_column_are_refused_rather_than_chosen_between():
    """§9.7 discards a superseded result rather than comparing it with its replacement. Whichever
    of the two a report published would be decided by iteration order."""
    optimistic = _score("leader", D("0.0900"), D("0.0800"), D("0.10"), EdgeOriginStatus.VALID)
    pessimistic = _score("leader", D("0.0100"), D("0.0050"), D("0.35"), EdgeOriginStatus.VALID)
    with pytest.raises(ConflictingWindowResults):
        report_window((optimistic, pessimistic))


def test_a_non_gating_column_is_refused_by_the_window_report():
    """A diagnostic rendered beside the two gating columns is a number that looks like a gate
    result. §10's failure mode is exactly someone reading that table."""
    with pytest.raises(NonGatingColumnReported):
        report_window(
            (_score("bucket_a_only", D("0.20"), D("0.20"), D("0.25"), EdgeOriginStatus.VALID),)
        )


def test_the_gating_columns_are_pinned():
    assert GATING_COLUMNS == ("leader", "follower_adjusted")


def test_a_non_finite_advantage_is_refused_by_name_not_by_arithmetic_error():
    """``contracts.WindowScore`` does not refuse a NaN advantage, so the report must.

    A bare ``median_advantage > 0`` against ``Decimal("NaN")`` raises ``InvalidOperation`` from
    deep inside the decimal module — an untyped arithmetic error, naming nothing, at the boundary
    where the figure is about to be published. The refusal has to say which field.

    The assertion is on the *outcome*, not on which line produces it: both ``require_finite`` and
    the ``output_pp`` call refuse it. That redundancy is deliberate and is recorded in
    ``window.py`` — the explicit refusal sits above the record construction so that it does not
    depend on the order the keyword arguments happen to be written in.
    """
    score = _score("leader", D("0.05"), D("NaN"), D("0.25"), EdgeOriginStatus.VALID)
    with pytest.raises(ValueError) as excinfo:
        report_window((score,))
    assert "median_advantage" in str(excinfo.value)


def test_a_non_finite_follower_return_is_refused_by_name_too():
    """The same hole on the other seam type: ``CopySimulation`` validates the fill bounds and the
    tier but not the finiteness of ``follower_return``."""
    poisoned = CopySimulation(
        capital_level=LEVEL,
        tier=AssetTier.MAJOR,
        intended_order_usd=D("10000"),
        filled_order_usd=D("10000"),
        execution_cost_pct=D("0.005"),
        follower_return=D("NaN"),
        copyable=True,
    )
    with pytest.raises(ValueError) as excinfo:
        report_capital_level(
            LEVEL,
            (WalletCapitalOutcome(W1, D("0.10"), D("0.05")),),
            (poisoned,),
            ValueBasisAmounts(D("1"), D("0"), D("0")),
        )
    assert "follower_return" in str(excinfo.value)


# -- diagnostics ----------------------------------------------------------------


def test_a_diagnostic_cannot_be_given_gate_relevance():
    with pytest.raises(DiagnosticPromotionRefused):
        Diagnostic(
            name="buy_win_rate",
            scope=SCOPE,
            kind="ratio",
            value=D("0.61000000"),
            gate_relevance="GATE_INPUT",
        )


def test_a_diagnostic_carries_its_label_by_default():
    item = diagnostic("buy_win_rate", SCOPE, D("0.612345678"))
    assert item.gate_relevance == DIAGNOSTIC_ONLY
    assert DIAGNOSTIC_ONLY == "DIAGNOSTIC_ONLY"
    assert item.value == D("0.61234568")


def test_a_diagnostic_nobody_pre_registered_is_refused():
    with pytest.raises(UnknownDiagnostic):
        diagnostic("sharpe_ratio", SCOPE, D("1.2"))


def test_comparing_a_diagnostic_against_a_threshold_is_a_typed_refusal():
    item = diagnostic("buy_win_rate", SCOPE, D("0.61"))
    for compare in (
        lambda: item > D("0.5"),
        lambda: item >= D("0.5"),
        lambda: item < D("0.5"),
        lambda: item <= D("0.5"),
    ):
        with pytest.raises(DiagnosticPromotionRefused):
            compare()


def test_the_pack_refuses_a_gate_input_carried_among_the_diagnostics():
    score = _score("leader", D("0.05"), D("0.03"), D("0.25"), EdgeOriginStatus.VALID)
    with pytest.raises(DiagnosticPromotionRefused):
        diagnostic_pack((score,))


def test_the_pack_refuses_every_label_that_is_not_diagnostic_only():
    """The pack's own ``gate_relevance``, checked against the constant rather than merely present.

    ``test_a_diagnostic_cannot_be_given_gate_relevance`` pins the same rule on a single
    :class:`Diagnostic`; nothing pinned it on the collection, and the collection is what a reader
    consults. The dangerous condition is **"a group of diagnostics can travel under a label nobody
    chose"** — not the string ``"GATE_INPUT"``, which is merely the most inviting way to spell it.
    So: an inviting label, an empty one, the right word in the wrong case, and ``None``. All four
    are refused, and the default is still the constant.
    """
    item = diagnostic("buy_win_rate", SCOPE, D("0.61"))
    for label in ("GATE_INPUT", "", "diagnostic_only", None):
        with pytest.raises(DiagnosticPromotionRefused):
            DiagnosticPack(items=(item,), gate_relevance=label)

    assert DiagnosticPack(items=(item,)).gate_relevance == DIAGNOSTIC_ONLY
    assert diagnostic_pack((item,)).gate_relevance == "DIAGNOSTIC_ONLY"


def test_the_pack_refuses_two_answers_to_the_same_question():
    first = diagnostic("buy_win_rate", SCOPE, D("0.61"))
    second = diagnostic("buy_win_rate", SCOPE, D("0.62"))
    with pytest.raises(UnknownDiagnostic):
        diagnostic_pack((first, second))


def test_the_same_diagnostic_at_two_scopes_is_two_diagnostics():
    other = DiagnosticScope(chain="ethereum", window=2, population="selected")
    pack = diagnostic_pack(
        (diagnostic("buy_win_rate", SCOPE, D("0.61")), diagnostic("buy_win_rate", other, D("0.55")))
    )
    assert len(pack.named("buy_win_rate")) == 2


def test_the_profit_ranking_orders_on_the_unrounded_value():
    """Two wallets whose profits differ by ``0.0000001`` render identically at six decimal places
    and still rank in the right order.

    The addresses are arranged **against** the profit order on purpose. ``0xaa`` earned less than
    ``0xbb``, so an implementation that sorted on the rendered figure would see a tie, fall through
    to the alphabetical tie-break, and put ``0xaa`` first — publishing the wrong wallet at the top
    of an absolute-profit ranking. With the addresses in the same order as the profits, that bug
    produces the right answer for the wrong reason and the test sees nothing.

    ``0xcc`` and ``0xdd`` are a genuine tie, and take the same rank: an ordering claim the data
    does not support is not made just because the list has to be printed in some order.
    """
    ranking = profit_ranking(
        SCOPE,
        (
            ("0xBB" + "0" * 38, D("1000.0000002")),
            ("0xAA" + "0" * 38, D("1000.0000001")),
            ("0xDD" + "0" * 38, D("500")),
            ("0xCC" + "0" * 38, D("500")),
        ),
    )
    assert [(row.rank, row.wallet[:4], row.value) for row in ranking.rows] == [
        (1, "0xbb", D("1000.000000")),
        (2, "0xaa", D("1000.000000")),
        (3, "0xcc", D("500.000000")),
        (3, "0xdd", D("500.000000")),
    ]


def test_the_activity_bands_tile_the_eligible_range_exactly():
    assert activity_band(20) is ActivityBand.B_20_99
    assert activity_band(99) is ActivityBand.B_20_99
    assert activity_band(100) is ActivityBand.B_100_499
    assert activity_band(499) is ActivityBand.B_100_499
    assert activity_band(500) is ActivityBand.B_500_1000
    assert activity_band(1000) is ActivityBand.B_500_1000


def test_a_wallet_outside_the_eligible_range_belongs_to_no_band():
    """Below 20 it was never eligible; above 1,000 §6.2 excludes it as likely automated. Either
    would be a selection bug, and folding it into the nearest band would file it as a diagnostic."""
    with pytest.raises(ValueError):
        activity_band(19)
    with pytest.raises(ValueError):
        activity_band(1001)


def test_a_scope_without_a_population_is_refused():
    with pytest.raises(ValueError):
        DiagnosticScope(chain="ethereum", window=1, population="")


def test_a_scope_without_a_chain_is_refused():
    with pytest.raises(ValueError):
        DiagnosticScope(chain="", window=1, population="selected")
