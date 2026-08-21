"""Worked examples for ``scoring``. Every expectation below was derived from the §4.4 / §7.1
formulas before the module existed, and none of it comes from the experiment's own data.

Two families of expectation appear here, and the difference matters.

**Closed-form.** The Edge Origin arithmetic is products and sums of short decimals, so the answers
are written as literals — ``0.10 x 0.40 = 0.04``, and so on. Those assertions are exact equality,
because nothing in them needs more than a handful of digits.

**Evaluated under the frozen policy.** Anything involving ``ln`` cannot be written as a literal, so
the expectation is *re-derived* from the same formula inside ``localcontext(CALCULATION_CONTEXT)``.
This is not a convenience. ``Decimal`` arithmetic at Python's default 28-digit context and at the
frozen 38-digit one agree to 28 digits and then diverge, so an expectation computed outside the
block disagrees with the module in the 29th digit and the comparison fails. The subtraction and the
division have to be inside the block too — a single ``divide()`` call does not help if the
arithmetic that follows lands back in the default context.

A third fact is recorded rather than worked around: at 38 digits a weighted mean over *equal*
weights is not bit-identical to the plain mean of the same returns. ``sum(w_i r_i) / sum(w_i)``
rounds at every step and ``sum(r_i) / n`` does not. §9.2 accepts 0.5 percentage points on buy
quality; the gap here is ~1e-38, twenty-nine orders of magnitude inside it. See
``test_equal_weights_reduce_to_the_plain_mean_but_not_bit_for_bit``.
"""

from decimal import Decimal, localcontext

import pytest

from contracts import (
    CALCULATION_CONTEXT,
    FIRST_HOUR_BUCKETS,
    USDC,
    BuyQuality,
    ClassificationStatus,
    EdgeOriginStatus,
    NetTradeResult,
    TokenAgeBucket,
    divide,
    to_canonical_json,
)
from scoring import (
    BUCKET_ORDER,
    COLUMNS,
    FIRST_HOUR_EDGE_SHARE_MAX,
    MIN_TOTAL_POSITIVE_EDGE,
    BenchmarkBucketMissing,
    UnscorableWallet,
    arithmetic_mean,
    buy_outcome,
    buy_quality,
    buy_quality_detail,
    edge_origin,
    evaluate_window,
    median,
    score_window,
    trade_weight,
    weighted_mean,
)

# Imported privately on purpose: the property under test is that the row holds the frozen
# context itself rather than inheriting it from ``edge_origin``, and that is invisible through
# ``edge_origin``, which always wraps it.
from scoring.edge import _bucket_edge

D = Decimal

WALLET = "0x" + "11" * 20
BENCHMARK = "0x" + "22" * 20
TOKEN = "0x" + "aa" * 20

A = TokenAgeBucket.A
B = TokenAgeBucket.B
C = TokenAgeBucket.C
DD = TokenAgeBucket.D


def _tx(n):
    return "0x{:064x}".format(n)


def a_buy(n, bucket=DD, owner=WALLET):
    """A minimal VALID_BUY. Only the fields scoring reads carry meaning."""
    return NetTradeResult(
        tx_hash=_tx(n),
        portfolio_owner=owner,
        status=ClassificationStatus.VALID_BUY,
        sold_asset=USDC,
        bought_asset=TOKEN,
        sold_raw_amount=1_000_000,
        bought_raw_amount=10 ** 18,
        quote_asset=USDC,
        quote_usd=D("1000"),
        # Seam rule: a timestamp is always paired with a block number. 12s slots.
        block_number=18_000_000 + n,
        timestamp=1_695_000_000 + 12 * n,
        token_age_bucket=bucket,
    )


def an_outcome(n, value_usd, return_pct, bucket=DD, realized="0", marked="0", dead="0"):
    return buy_outcome(
        a_buy(n, bucket=bucket),
        trade_value_usd=D(value_usd),
        return_pct=D(return_pct),
        realized_usd=D(realized),
        marked_usd=D(marked),
        dead_usd=D(dead),
    )


def a_quality(wallet, weights, values, value="0", shares=("1", "0", "0")):
    """A :class:`contracts.BuyQuality` with chosen bucket weights — the Edge Origin input.

    Constructed directly rather than scored from outcomes so the edge arithmetic is exact short
    decimals: the point of these cases is the decomposition, not the ``ln``.
    """
    return BuyQuality(
        wallet=wallet,
        value=D(value),
        n_buys=len(values) or 1,
        realized_share=D(shares[0]),
        marked_share=D(shares[1]),
        dead_share=D(shares[2]),
        bucket_weights={k: D(v) for k, v in weights.items()},
        bucket_values={k: D(v) for k, v in values.items()},
    )


# -- trade weight ---------------------------------------------------------------


def test_trade_weight_of_a_worthless_trade_is_zero():
    """ln(1 + 0) = 0. A trade with no value cannot move a weighted mean, and does not."""
    assert trade_weight(D("0")) == D("0")


def test_trade_weight_of_one_dollar_is_ln_two():
    """ln 2 to 38 significant digits — the frozen internal precision.

    0.693147180559945309417232121458176568075500... rounds at the 38th digit to ...808.
    """
    assert trade_weight(D("1")) == D("0.69314718055994530941723212145817656808")


def test_trade_weight_grows_sublinearly_so_no_whale_purchase_dominates():
    """§4.4's stated purpose. A $1,000,000 buy carries ~2.5x the weight of a $100 buy, not 10,000x."""
    small = trade_weight(D("100"))
    whale = trade_weight(D("1000000"))

    assert whale > small
    assert whale < 3 * small  # linear weighting would make this 10,000x


def test_trade_weight_refuses_a_negative_trade_value():
    with pytest.raises(ValueError):
        trade_weight(D("-1"))


def test_trade_weight_refuses_float():
    """calc() refuses float on sight: it has already lost precision before it arrives."""
    with pytest.raises(TypeError):
        trade_weight(1000.0)


# -- weighted mean --------------------------------------------------------------


def test_weighted_mean_is_sum_wr_over_sum_w():
    with localcontext(CALCULATION_CONTEXT):
        w1 = (D("1") + D("999")).ln()
        w2 = (D("1") + D("9")).ln()
        expected = +((w1 * D("0.5") + w2 * D("-0.2")) / (w1 + w2))

    assert weighted_mean([(w1, D("0.5")), (w2, D("-0.2"))]) == expected


def test_weighted_mean_refuses_a_zero_total_weight():
    """divide() refuses zero rather than returning one; the caller must classify the case."""
    with pytest.raises(ZeroDivisionError):
        weighted_mean([(D("0"), D("0.5"))])


def test_arithmetic_mean_and_median_on_an_odd_count():
    values = [D("0.3"), D("-0.1"), D("0.5")]

    assert arithmetic_mean(values) == divide(D("0.7"), D("3"))
    assert median(values) == D("0.3")


def test_median_on_an_even_count_is_the_midpoint_of_the_two_middle_values():
    values = [D("0.5"), D("0.1"), D("-0.3"), D("0.3")]

    assert median(values) == D("0.2")  # (0.1 + 0.3) / 2


# -- buy quality ----------------------------------------------------------------


def test_buy_quality_over_two_buys_in_one_bucket():
    """The §4.4 aggregation, re-derived under the frozen context.

    Buy 1: $999 at +50%   -> w = ln(1000)
    Buy 2: $9   at -20%   -> w = ln(10)
    """
    outcomes = [
        an_outcome(1, "999", "0.5", realized="999"),
        an_outcome(2, "9", "-0.2", marked="9"),
    ]

    with localcontext(CALCULATION_CONTEXT):
        w1 = (D("1") + D("999")).ln()
        w2 = (D("1") + D("9")).ln()
        expected = +((w1 * D("0.5") + w2 * D("-0.2")) / (w1 + w2))

    quality = buy_quality(outcomes, WALLET)

    assert quality.wallet == WALLET
    assert quality.n_buys == 2
    assert quality.value == expected


def test_equal_weights_reduce_to_the_plain_mean_but_not_bit_for_bit():
    """Recorded, not worked around.

    Three buys of the same size score the plain mean of their returns — to within one unit in the
    38th place. ``sum(w_i r_i) / sum(w_i)`` rounds at each of five steps; ``sum(r_i) / 3`` rounds
    once. Both are correct under the frozen policy and the module publishes the weighted form,
    because that is the pre-registered formula. §9.2 accepts 0.5 percentage points on buy quality.
    """
    outcomes = [
        an_outcome(1, "999", "0.5", realized="10"),
        an_outcome(2, "999", "-0.25", marked="10"),
        an_outcome(3, "999", "0.75", dead="10"),
    ]

    quality = buy_quality(outcomes, WALLET)
    plain = divide(D("0.5") + D("-0.25") + D("0.75"), D("3"))

    assert quality.value != plain
    assert abs(quality.value - plain) < D("1e-37")


def test_a_single_buy_scores_its_own_return():
    outcomes = [an_outcome(1, "500", "0.4", realized="500")]

    quality = buy_quality(outcomes, WALLET)

    # w*r/w is r up to one 38th-place rounding step, not by algebraic identity.
    assert abs(quality.value - D("0.4")) < D("1e-37")


def test_value_basis_shares_are_reported_and_sum_to_one():
    """§10. A score resting 80% on marking is not credible however positive it looks."""
    outcomes = [
        an_outcome(1, "1000", "0.5", realized="200"),
        an_outcome(2, "1000", "0.3", marked="700"),
        an_outcome(3, "1000", "-1", dead="100"),
    ]

    quality = buy_quality(outcomes, WALLET)

    assert quality.realized_share == D("0.2")
    assert quality.marked_share == D("0.7")
    assert quality.dead_share == D("0.1")
    assert quality.realized_share + quality.marked_share + quality.dead_share == D("1")


def test_bucket_weights_are_each_bucket_share_of_total_buy_weight():
    """Same log weighting as the primary metric — §7.1 requires the same basis."""
    outcomes = [
        an_outcome(1, "999", "0.5", bucket=A, realized="10"),
        an_outcome(2, "999", "0.5", bucket=B, realized="10"),
        an_outcome(3, "999", "0.1", bucket=DD, realized="10"),
    ]

    with localcontext(CALCULATION_CONTEXT):
        w = (D("1") + D("999")).ln()
        expected_share = +(w / (w + w + w))

    quality = buy_quality(outcomes, WALLET)

    assert quality.bucket_weights[A] == expected_share
    assert quality.bucket_weights[B] == expected_share
    assert C not in quality.bucket_weights  # no buys: absent, never a zero-weight entry
    assert abs(quality.bucket_values[DD] - D("0.1")) < D("1e-37")


def test_bucket_value_is_the_buy_quality_of_that_bucket_alone():
    outcomes = [
        an_outcome(1, "999", "1.0", bucket=A, realized="10"),
        an_outcome(2, "9", "0.0", bucket=A, realized="10"),
        an_outcome(3, "999", "-0.5", bucket=DD, realized="10"),
    ]

    with localcontext(CALCULATION_CONTEXT):
        w1 = (D("1") + D("999")).ln()
        w2 = (D("1") + D("9")).ln()
        expected_a = +((w1 * D("1.0") + w2 * D("0.0")) / (w1 + w2))

    quality = buy_quality(outcomes, WALLET)

    assert quality.bucket_values[A] == expected_a


def test_buy_quality_refuses_an_empty_outcome_set():
    """A wallet with no buys has no buy quality. Zero would read as flat performance."""
    with pytest.raises(UnscorableWallet):
        buy_quality([], WALLET)


def test_buy_quality_refuses_a_basket_whose_whole_volume_priced_at_zero():
    """Every weight is ln(1) = 0, so the weighted mean has no denominator."""
    with pytest.raises(UnscorableWallet):
        buy_quality([an_outcome(1, "0", "0.5", realized="10")], WALLET)


def test_buy_quality_refuses_a_basket_with_no_recorded_value_basis():
    """§10 requires the mix reported. Inventing shares that sum to 1 is the alternative, so no."""
    with pytest.raises(UnscorableWallet):
        buy_quality([an_outcome(1, "999", "0.5")], WALLET)


def test_the_detail_carries_what_a_reviewer_needs_to_reproduce_the_number():
    outcomes = [
        an_outcome(1, "999", "0.5", bucket=A, realized="30"),
        an_outcome(2, "9", "-0.2", bucket=DD, marked="70"),
    ]

    detail = buy_quality_detail(outcomes, WALLET)

    with localcontext(CALCULATION_CONTEXT):
        w1 = (D("1") + D("999")).ln()
        w2 = (D("1") + D("9")).ln()
        total = +(w1 + w2)

    assert detail.total_weight == total
    assert {b.bucket for b in detail.buckets} == set(BUCKET_ORDER)
    by_bucket = {b.bucket: b for b in detail.buckets}
    assert by_bucket[A].n_buys == 1 and by_bucket[A].weight == w1
    assert by_bucket[C].n_buys == 0 and by_bucket[C].value is None
    assert detail.basis_total_usd == D("100")
    assert detail.quality == buy_quality(outcomes, WALLET)


def test_buy_outcome_takes_its_bucket_from_the_trade_when_not_given():
    """§4.7: each buy is assigned exactly one non-overlapping bucket, and never none."""
    outcome = buy_outcome(a_buy(1, bucket=B), D("100"), D("0.1"), realized_usd=D("100"))

    assert outcome.bucket is B


def test_buy_outcome_refuses_a_trade_carrying_no_bucket():
    unbucketed = NetTradeResult(
        tx_hash=_tx(9),
        portfolio_owner=WALLET,
        status=ClassificationStatus.VALID_BUY,
        sold_asset=USDC,
        bought_asset=TOKEN,
        sold_raw_amount=1,
        bought_raw_amount=1,
        quote_asset=USDC,
    )

    with pytest.raises(ValueError):
        buy_outcome(unbucketed, D("100"), D("0.1"), realized_usd=D("100"))


def test_buy_outcome_refuses_a_sell():
    sell = NetTradeResult(
        tx_hash=_tx(9),
        portfolio_owner=WALLET,
        status=ClassificationStatus.VALID_SELL,
        sold_asset=TOKEN,
        bought_asset=USDC,
        sold_raw_amount=1,
        bought_raw_amount=1,
        quote_asset=USDC,
        token_age_bucket=DD,
    )

    with pytest.raises(ValueError):
        buy_outcome(sell, D("100"), D("0.1"), realized_usd=D("100"))


# -- edge origin ----------------------------------------------------------------
#
# Weights and values are chosen so every contribution is exact:
#
#   bucket    weight   selected   benchmark   advantage   contribution
#   A          0.10      0.50       0.10        0.40         0.04
#   B          0.20      0.40       0.10        0.30         0.06
#   C          0.30      0.20       0.10        0.10         0.03
#   D          0.40      0.10       0.10        0.00         0.00
#                                                total       0.13
#   first hour = 0.04 + 0.06 = 0.10   ->  share = 0.10 / 0.13 = 0.769...


DOMINATED_WEIGHTS = {A: "0.10", B: "0.20", C: "0.30", DD: "0.40"}
DOMINATED_SELECTED = {A: "0.50", B: "0.40", C: "0.20", DD: "0.10"}
FLAT_BENCHMARK = {A: "0.10", B: "0.10", C: "0.10", DD: "0.10"}


def test_bucket_edge_contributions_are_weight_times_advantage():
    result = edge_origin(
        a_quality(WALLET, DOMINATED_WEIGHTS, DOMINATED_SELECTED),
        a_quality(BENCHMARK, DOMINATED_WEIGHTS, FLAT_BENCHMARK),
    )

    assert [b.contribution for b in result.buckets] == [
        D("0.04"), D("0.06"), D("0.03"), D("0.00"),
    ]
    assert result.total_positive_contribution == D("0.13")
    assert result.first_hour_contribution == D("0.10")


def test_a_first_hour_share_above_forty_percent_is_a_hard_failure():
    result = edge_origin(
        a_quality(WALLET, DOMINATED_WEIGHTS, DOMINATED_SELECTED),
        a_quality(BENCHMARK, DOMINATED_WEIGHTS, FLAT_BENCHMARK),
    )

    assert result.share == divide(D("0.10"), D("0.13"))
    assert result.share > FIRST_HOUR_EDGE_SHARE_MAX
    assert result.status is EdgeOriginStatus.UNCOPYABLE_DOMINATED
    assert not result.status.passes


def test_exactly_forty_percent_passes():
    """The boundary is ``> 40%`` fails, so 40% itself is measurable and permitted.

    weights   A 0.10  B 0.10  C 0.30  D 0.50
    advantage A 0.20  B 0.20  C 0.20  D 0.00
    ->        A 0.02  B 0.02  C 0.06  D 0.00   total 0.10, first hour 0.04, share 0.40
    """
    selected = a_quality(
        WALLET,
        {A: "0.10", B: "0.10", C: "0.30", DD: "0.50"},
        {A: "0.30", B: "0.30", C: "0.30", DD: "0.10"},
    )
    benchmark = a_quality(BENCHMARK, {}, {A: "0.10", B: "0.10", C: "0.10", DD: "0.10"})

    result = edge_origin(selected, benchmark)

    assert result.total_positive_contribution == D("0.10")
    assert result.share == D("0.4")
    assert result.share == FIRST_HOUR_EDGE_SHARE_MAX
    assert result.status is EdgeOriginStatus.VALID


def test_a_hair_over_forty_percent_fails():
    selected = a_quality(
        WALLET,
        {A: "0.10", B: "0.10", C: "0.30", DD: "0.50"},
        {A: "0.305", B: "0.30", C: "0.30", DD: "0.10"},
    )
    benchmark = a_quality(BENCHMARK, {}, {A: "0.10", B: "0.10", C: "0.10", DD: "0.10"})

    result = edge_origin(selected, benchmark)

    # A 0.0205 + B 0.02 = 0.0405 over a total of 0.1005.
    assert result.total_positive_contribution == D("0.1005")
    assert result.share == divide(D("0.0405"), D("0.1005"))
    assert result.share > FIRST_HOUR_EDGE_SHARE_MAX
    assert result.status is EdgeOriginStatus.UNCOPYABLE_DOMINATED


def test_negative_bucket_advantages_contribute_zero_not_a_negative_number():
    """``max(0, ...)``. A bucket where the selected basket lost to the benchmark cannot subsidise
    the denominator and make the first-hour share look smaller than it is."""
    selected = a_quality(
        WALLET,
        {A: "0.25", B: "0.25", C: "0.25", DD: "0.25"},
        {A: "0.50", B: "0.50", C: "-2.00", DD: "-2.00"},
    )
    benchmark = a_quality(BENCHMARK, {}, {A: "0.10", B: "0.10", C: "0.10", DD: "0.10"})

    result = edge_origin(selected, benchmark)

    assert [b.contribution for b in result.buckets] == [D("0.1"), D("0.1"), D("0"), D("0")]
    assert result.total_positive_contribution == D("0.2")
    # Every positive contribution is in the first hour, and nothing offsets it.
    assert result.share == D("1")
    assert result.status is EdgeOriginStatus.UNCOPYABLE_DOMINATED


def test_below_five_percentage_points_is_indeterminate_and_carries_no_share():
    """The most dangerous bug in the project, asserted directly.

    Returning Decimal("0") here would convert an unmeasurable window into a passing one.
    """
    selected = a_quality(
        WALLET,
        {A: "0.25", B: "0.25", C: "0.25", DD: "0.25"},
        {A: "0.14", B: "0.14", C: "0.14", DD: "0.14"},
    )
    benchmark = a_quality(BENCHMARK, {}, {A: "0.10", B: "0.10", C: "0.10", DD: "0.10"})

    result = edge_origin(selected, benchmark)

    assert result.total_positive_contribution == D("0.04")  # 4pp, below the 5pp floor
    assert result.total_positive_contribution < MIN_TOTAL_POSITIVE_EDGE
    assert result.share is None
    assert result.status is EdgeOriginStatus.INDETERMINATE
    assert not result.status.passes


def test_exactly_five_percentage_points_is_measurable():
    """The guard is ``< 5pp``, so 5pp itself is measured rather than abstained on."""
    selected = a_quality(
        WALLET,
        {A: "0.25", B: "0.25", C: "0.25", DD: "0.25"},
        {A: "0.10", B: "0.10", C: "0.30", DD: "0.10"},
    )
    benchmark = a_quality(BENCHMARK, {}, {A: "0.10", B: "0.10", C: "0.10", DD: "0.10"})

    result = edge_origin(selected, benchmark)

    # Bucket C alone: 0.25 x 0.20 = 0.05.
    assert result.total_positive_contribution == MIN_TOTAL_POSITIVE_EDGE == D("0.05")
    assert result.share == D("0")
    assert result.status is EdgeOriginStatus.VALID


def test_zero_total_contribution_is_indeterminate_rather_than_a_division_by_zero():
    selected = a_quality(
        WALLET,
        {A: "0.5", DD: "0.5"},
        {A: "0.10", DD: "0.10"},
    )
    benchmark = a_quality(BENCHMARK, {}, {A: "0.10", DD: "0.10"})

    result = edge_origin(selected, benchmark)

    assert result.total_positive_contribution == D("0")
    assert result.share is None
    assert result.status is EdgeOriginStatus.INDETERMINATE


def test_a_bucket_the_selected_basket_never_traded_needs_no_benchmark_value():
    """Weight zero forces contribution zero, so an absent benchmark bucket is not an obstacle."""
    selected = a_quality(WALLET, {C: "0.4", DD: "0.6"}, {C: "0.30", DD: "0.30"})
    benchmark = a_quality(BENCHMARK, {}, {C: "0.10", DD: "0.10"})

    result = edge_origin(selected, benchmark)

    assert [b.contribution for b in result.buckets] == [D("0"), D("0"), D("0.08"), D("0.12")]
    assert result.share == D("0")
    assert result.status is EdgeOriginStatus.VALID


def test_a_missing_benchmark_bucket_the_selected_basket_did_trade_refuses():
    """No number is invented for an absent benchmark. A zero would read as "the benchmark broke
    even in the first hour", which is a measurement nobody made."""
    selected = a_quality(WALLET, {A: "0.4", DD: "0.6"}, {A: "0.30", DD: "0.30"})
    benchmark = a_quality(BENCHMARK, {}, {DD: "0.10"})

    with pytest.raises(BenchmarkBucketMissing):
        edge_origin(selected, benchmark)


def test_bucket_a_is_reported_in_isolation_as_a_diagnostic():
    """Ticket 32: the gate condition applies to the whole first hour; A is reported alongside."""
    result = edge_origin(
        a_quality(WALLET, DOMINATED_WEIGHTS, DOMINATED_SELECTED),
        a_quality(BENCHMARK, DOMINATED_WEIGHTS, FLAT_BENCHMARK),
    )

    assert result.bucket_a_contribution == D("0.04")
    assert result.bucket_a_share == divide(D("0.04"), D("0.13"))


def test_the_partial_defence_limitation_travels_with_the_result():
    result = edge_origin(
        a_quality(WALLET, DOMINATED_WEIGHTS, DOMINATED_SELECTED),
        a_quality(BENCHMARK, DOMINATED_WEIGHTS, FLAT_BENCHMARK),
    )

    assert result.limitations
    assert any("partial defence" in note for note in result.limitations)


def test_first_hour_buckets_are_a_and_b_in_that_order():
    """The frozen seam names them; scoring must not re-derive its own first hour."""
    assert FIRST_HOUR_BUCKETS == (A, B)
    assert BUCKET_ORDER[:2] == FIRST_HOUR_BUCKETS


# -- window score ---------------------------------------------------------------


def dominated_edge():
    return edge_origin(
        a_quality(WALLET, DOMINATED_WEIGHTS, DOMINATED_SELECTED),
        a_quality(BENCHMARK, DOMINATED_WEIGHTS, FLAT_BENCHMARK),
    )


def valid_edge():
    selected = a_quality(
        WALLET,
        {A: "0.10", B: "0.10", C: "0.30", DD: "0.50"},
        {A: "0.30", B: "0.30", C: "0.30", DD: "0.10"},
    )
    return edge_origin(selected, a_quality(BENCHMARK, {}, FLAT_BENCHMARK))


def indeterminate_edge():
    selected = a_quality(
        WALLET,
        {A: "0.25", B: "0.25", C: "0.25", DD: "0.25"},
        {A: "0.14", B: "0.14", C: "0.14", DD: "0.14"},
    )
    return edge_origin(selected, a_quality(BENCHMARK, {}, FLAT_BENCHMARK))


def test_a_window_score_carries_the_three_seventy_one_quantities():
    score = score_window(1, "leader", [D("0.3"), D("0.1"), D("0.5")], valid_edge())

    assert score.window == 1
    assert score.column == "leader"
    assert score.mean_advantage == divide(D("0.9"), D("3"))
    assert score.median_advantage == D("0.3")
    assert score.first_hour_edge_share == D("0.4")
    assert score.positive_edge_contribution == D("0.10")
    assert score.edge_origin_status is EdgeOriginStatus.VALID


def test_all_three_conditions_must_hold_for_a_window_to_pass():
    edge = valid_edge()

    assert score_window(1, "leader", [D("0.3"), D("0.2"), D("0.4")], edge).passes(D("0.15"))
    # mean below the threshold
    assert not score_window(1, "leader", [D("0.1"), D("0.1"), D("0.1")], edge).passes(D("0.15"))
    # median not positive, though the mean clears easily
    assert not score_window(
        1, "leader", [D("-0.1"), D("-0.1"), D("2.0")], edge
    ).passes(D("0.15"))


def test_an_indeterminate_window_carries_no_share_and_cannot_pass():
    score = score_window(2, "leader", [D("5"), D("5"), D("5")], indeterminate_edge())

    assert score.first_hour_edge_share is None
    assert score.edge_origin_status is EdgeOriginStatus.INDETERMINATE
    assert not score.passes(D("0.15"))
    assert not score.passes(D("-100"))  # not even a threshold nobody could fail


def test_an_uncopyable_dominated_window_cannot_pass_however_large_the_advantage():
    score = score_window(3, "leader", [D("10"), D("10"), D("10")], dominated_edge())

    assert score.first_hour_edge_share is not None  # measurable, and it measured badly
    assert score.edge_origin_status is EdgeOriginStatus.UNCOPYABLE_DOMINATED
    assert not score.passes(D("0.15"))


def test_a_window_needs_at_least_one_selected_wallet():
    with pytest.raises(ValueError):
        score_window(1, "leader", [], valid_edge())


def test_an_unknown_column_is_refused():
    assert COLUMNS == ("leader", "follower_adjusted")
    with pytest.raises(ValueError):
        score_window(1, "raw", [D("0.3")], valid_edge())


def test_the_evaluation_reduces_to_the_seam_score():
    evaluation = evaluate_window(1, "follower_adjusted", [D("0.3"), D("0.4")], valid_edge())

    assert evaluation.score == score_window(1, "follower_adjusted", [D("0.3"), D("0.4")],
                                            valid_edge())
    assert evaluation.n_selected == 2
    assert evaluation.passes(D("0.15")) is evaluation.score.passes(D("0.15"))


# -- serialization --------------------------------------------------------------


def test_every_output_survives_canonical_serialization():
    """A leaked float raises in ``canonicalise``; this is where it would surface."""
    outcomes = [
        an_outcome(1, "999", "0.5", bucket=A, realized="30"),
        an_outcome(2, "9", "-0.2", bucket=DD, marked="70"),
    ]
    detail = buy_quality_detail(outcomes, WALLET)
    edge = valid_edge()
    evaluation = evaluate_window(1, "leader", [D("0.3"), D("0.4")], edge)

    for payload in (detail, detail.quality, edge, evaluation, evaluation.score):
        rendered = to_canonical_json(payload)
        assert rendered == to_canonical_json(payload)  # deterministic
        # Decimals are strings, never JSON numbers: a JSON number is read back as a double.
        assert '"0.' in rendered or '"-0.' in rendered


def test_an_indeterminate_share_serializes_as_null_not_zero():
    score = score_window(2, "leader", [D("0.3")], indeterminate_edge())

    rendered = to_canonical_json(score)

    assert '"first_hour_edge_share":null' in rendered
    assert '"edge_origin_status":"INDETERMINATE"' in rendered


def test_a_bucket_row_does_not_depend_on_the_caller_s_decimal_context():
    """``_bucket_edge`` carried "Must be called inside the frozen context" as a docstring sentence.

    A sentence is not a guarantee. One bucket, full weight, and an advantage that needs 38 digits:

        selected_value  1.2345678901234567890123456789012345678
        benchmark_value 0.1
        ---------------------------------------------------------
        advantage       1.1345678901234567890123456789012345678
        contribution    1 x advantage = the same number

    Called from the ambient 28-digit context both come back as
    ``1.134567890123456789012345679`` — ten digits shorter, entirely plausible-looking, and
    straight into the numerator of the first-hour edge share.
    """
    bucket = TokenAgeBucket.A
    advantage = D("1.1345678901234567890123456789012345678")

    def basket(wallet, value):
        return BuyQuality(
            wallet=wallet, value=D("1"), n_buys=1,
            realized_share=D("1"), marked_share=D("0"), dead_share=D("0"),
            bucket_weights={bucket: D("1")},
            bucket_values={bucket: value},
        )

    selected = basket("0x" + "11" * 20, D("1.2345678901234567890123456789012345678"))
    benchmark = basket("0x" + "22" * 20, D("0.1"))

    row = _bucket_edge(bucket, selected, benchmark)

    assert row.raw_advantage == advantage
    assert row.contribution == advantage
