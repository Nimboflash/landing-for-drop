"""Invariants for ``scoring``, over generated baskets and decompositions.

These are the properties a wrong implementation satisfies every hand-computed case without
violating. Four carry the most weight:

* the bucket contributions sum to the total positive contribution **exactly** — not to within a
  tolerance. The total is what the 5pp guard compares against, so a total that is not the sum of
  its parts is a guard applied to a different quantity than the one reported;
* ``WindowScore.passes`` is False whenever the status is not ``VALID``, **for every threshold,
  including negative ones**. A threshold nobody could fail must still not rescue an unmeasurable
  window;
* the first-hour share is ``None`` exactly when the status is ``INDETERMINATE``, and is never a
  zero standing in for one;
* buy quality lies between the smallest and the largest return in the basket. A weighted mean that
  escapes its own inputs is a weighting bug, and one that lands *above* every input is the specific
  shape a whale-dominated score would take.

``derandomize=True`` throughout: the house rule forbids unseeded randomness, and a property suite
that fails only on Tuesdays is worse than none.
"""

from decimal import Decimal, localcontext

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from contracts import (
    CALCULATION_CONTEXT,
    FIRST_HOUR_BUCKETS,
    USDC,
    BuyQuality,
    ClassificationStatus,
    EdgeOriginStatus,
    NetTradeResult,
    TokenAgeBucket,
    quantize_ratio,
    to_canonical_json,
)
from scoring import (
    BUCKET_ORDER,
    FIRST_HOUR_EDGE_SHARE_MAX,
    MIN_TOTAL_POSITIVE_EDGE,
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
)

D = Decimal

DETERMINISTIC = settings(derandomize=True, max_examples=200, deadline=None)

WALLET = "0x" + "11" * 20
BENCHMARK = "0x" + "22" * 20
TOKEN = "0x" + "aa" * 20

#: Trade values across the range a real basket spans: dust through a $10m clip. Built from ints so
#: no float is ever constructed — ``calc`` refuses one on sight, and this suite must exercise the
#: numeric path rather than the guard on it.
trade_values = st.integers(min_value=0, max_value=10 ** 9).map(lambda n: D(n) / D("100"))

#: Returns from -100% (a total loss, the floor) to +2000%.
returns = st.integers(min_value=-100, max_value=2000).map(lambda n: D(n) / D("100"))

usd_amounts = st.integers(min_value=0, max_value=10 ** 10).map(lambda n: D(n) / D("100"))

buckets = st.sampled_from(BUCKET_ORDER)

#: Bucket-level qualities and weights for the Edge Origin decomposition, as short decimals so the
#: exactness properties are about the accumulation and not about generator noise.
bucket_qualities = st.integers(min_value=-100, max_value=500).map(lambda n: D(n) / D("100"))
bucket_weights = st.integers(min_value=0, max_value=1000).map(lambda n: D(n) / D("1000"))


def _tx(n):
    return "0x{:064x}".format(n)


def a_buy(n, bucket):
    return NetTradeResult(
        tx_hash=_tx(n),
        portfolio_owner=WALLET,
        status=ClassificationStatus.VALID_BUY,
        sold_asset=USDC,
        bought_asset=TOKEN,
        sold_raw_amount=1_000_000,
        bought_raw_amount=10 ** 18,
        quote_asset=USDC,
        block_number=18_000_000 + n,
        timestamp=1_695_000_000 + 12 * n,
        token_age_bucket=bucket,
    )


@st.composite
def outcomes(draw, min_size=1, max_size=8):
    """A basket of buys with at least some priced volume and some recorded value basis."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    built = []
    for i in range(n):
        built.append(
            buy_outcome(
                a_buy(i, draw(buckets)),
                trade_value_usd=draw(trade_values),
                return_pct=draw(returns),
                realized_usd=draw(usd_amounts),
                marked_usd=draw(usd_amounts),
                dead_usd=draw(usd_amounts),
            )
        )
    assume(any(o.weight > 0 for o in built))
    assume(any(o.realized_usd + o.marked_usd + o.dead_usd > 0 for o in built))
    return built


@st.composite
def qualities(draw, wallet=WALLET, covered=None):
    """A :class:`contracts.BuyQuality` with chosen bucket weights and values.

    ``covered`` forces a bucket to carry a value even at zero weight, which is how the benchmark
    side is built: a benchmark missing a bucket the selected basket traded is a refusal, tested
    separately in the hand-computed suite.
    """
    weights = {}
    values = {}
    for bucket in BUCKET_ORDER:
        weight = draw(bucket_weights)
        if weight > 0 or (covered and bucket in covered):
            values[bucket] = draw(bucket_qualities)
        if weight > 0:
            weights[bucket] = weight
    return BuyQuality(
        wallet=wallet,
        value=draw(bucket_qualities),
        n_buys=max(len(values), 1),
        realized_share=D("1"),
        marked_share=D("0"),
        dead_share=D("0"),
        bucket_weights=weights,
        bucket_values=values,
    )


@st.composite
def decompositions(draw):
    selected = draw(qualities(wallet=WALLET))
    benchmark = draw(qualities(wallet=BENCHMARK, covered=set(selected.bucket_weights)))
    return edge_origin(selected, benchmark)


# -- trade weight ---------------------------------------------------------------


@DETERMINISTIC
@given(trade_values)
def test_trade_weight_is_non_negative_and_finite(value):
    weight = trade_weight(value)

    assert weight >= 0
    assert weight.is_finite()


@DETERMINISTIC
@given(trade_values, trade_values)
def test_trade_weight_is_monotone_in_trade_value(a, b):
    """A larger trade never weighs less. Nothing else about the curve is relied on."""
    assume(a < b)

    assert trade_weight(a) < trade_weight(b)


@DETERMINISTIC
@given(st.integers(min_value=1, max_value=10 ** 6))
def test_log_weighting_compresses_the_range_it_is_there_to_compress(dollars):
    """§4.4's stated purpose: size matters without one whale purchase dominating.

    A hundred-fold larger trade never carries a hundred-fold larger weight.
    """
    small = trade_weight(D(dollars))
    large = trade_weight(D(dollars) * 100)

    assert large > small
    assert large < small * 100


# -- buy quality ----------------------------------------------------------------


@DETERMINISTIC
@given(outcomes())
def test_buy_quality_lies_between_the_smallest_and_largest_return(basket):
    """A weighted mean cannot escape its own inputs.

    Escaping upward is the shape a whale-dominated or sign-flipped weighting takes, and it is
    invisible to any single hand-computed case.

    The allowance is one unit in the 38th significant place, and it is real rather than defensive:
    a basket with a single priced buy computes ``w*r/w``, which rounds twice and lands one ulp
    either side of ``r`` for some ``r``. §9.2 accepts 0.5 percentage points on buy quality; this
    is 1e-36.

    The comparison is written on the *difference* rather than as ``low - tol <= v <= high + tol``.
    Test arithmetic runs at Python's default 28-digit context, where ``2.66 + 2.66e-36`` is just
    ``2.66`` again — the tolerance would silently vanish and the assertion would be exact equality
    wearing a tolerance's clothes.
    """
    quality = buy_quality(basket, WALLET)
    priced = [o.return_pct for o in basket if o.weight > 0]
    ulp = max(abs(min(priced)), abs(max(priced)), D("1")) * D("1e-36")

    assert quality.value - max(priced) <= ulp
    assert min(priced) - quality.value <= ulp


@DETERMINISTIC
@given(outcomes())
def test_the_three_value_basis_shares_sum_to_one(basket):
    """§10, and :class:`contracts.BuyQuality` refuses construction without it."""
    quality = buy_quality(basket, WALLET)
    total = quality.realized_share + quality.marked_share + quality.dead_share

    assert all(s >= 0 for s in (quality.realized_share, quality.marked_share, quality.dead_share))
    # Three independent divisions at 38 digits need not sum to a bit-exact one; the seam's own
    # tolerance is 1e-4 and the gap here is ~1e-37.
    assert abs(total - D("1")) < D("1e-36")


@DETERMINISTIC
@given(outcomes(min_size=2), st.data())
def test_reordering_the_basket_cannot_change_the_reported_score(basket, data):
    """Order moves the answer in the 38th place and nowhere a reader can see.

    Asserted at the reporting scale rather than in memory, because that is the claim that matters:
    §9.2 requires the published number to be reproducible, and quantize_ratio is where publishing
    happens.
    """
    permuted = data.draw(st.permutations(basket))

    assert quantize_ratio(buy_quality(basket, WALLET).value) == quantize_ratio(
        buy_quality(permuted, WALLET).value
    )


@DETERMINISTIC
@given(outcomes())
def test_every_bucket_appears_in_the_detail_and_only_weighted_ones_reach_the_seam(basket):
    detail = buy_quality_detail(basket, WALLET)
    quality = detail.quality

    assert tuple(b.bucket for b in detail.buckets) == BUCKET_ORDER
    assert set(quality.bucket_weights) == set(quality.bucket_values)
    for row in detail.buckets:
        # A bucket carries a value exactly when it carries weight. Anything else would let the
        # decomposition difference a benchmark against a quality nobody computed.
        assert (row.value is None) == (row.weight == 0)


@DETERMINISTIC
@given(outcomes())
def test_bucket_weight_shares_sum_to_one(basket):
    quality = buy_quality(basket, WALLET)
    with localcontext(CALCULATION_CONTEXT):
        total = sum(quality.bucket_weights.values(), D("0"))

    assert abs(total - D("1")) < D("1e-36")


@DETERMINISTIC
@given(outcomes())
def test_a_bucket_holding_the_whole_basket_scores_the_whole_basket(basket):
    """When every buy sits in one bucket, that bucket's quality is the wallet's quality."""
    single = [
        buy_outcome(
            o.buy,
            trade_value_usd=D(0) if o.weight == 0 else (o.weight.exp() - D("1")),
            return_pct=o.return_pct,
            realized_usd=o.realized_usd,
            marked_usd=o.marked_usd,
            dead_usd=o.dead_usd,
            bucket=TokenAgeBucket.C,
        )
        for o in basket
    ]
    detail = buy_quality_detail(single, WALLET)
    by_bucket = {b.bucket: b for b in detail.buckets}

    assert by_bucket[TokenAgeBucket.C].n_buys == len(basket)
    # exp/ln round-trips at 38 digits, so the weights are equal to within a few ulps rather than
    # bit-identical; the reported number is the claim.
    assert quantize_ratio(by_bucket[TokenAgeBucket.C].value) == quantize_ratio(detail.value)


@DETERMINISTIC
@given(outcomes())
def test_a_scored_wallet_always_survives_canonical_serialization(basket):
    """A leaked float raises in ``canonicalise``. This is where it would surface."""
    detail = buy_quality_detail(basket, WALLET)

    assert to_canonical_json(detail) == to_canonical_json(detail)
    assert to_canonical_json(detail.quality)


# -- edge origin ----------------------------------------------------------------


@DETERMINISTIC
@given(decompositions())
def test_bucket_contributions_sum_to_the_total_positive_contribution_exactly(origin):
    """Exactly, not within a tolerance.

    The total is what the 5pp guard compares against and what the window publishes. If it is not
    the sum of the parts, the guard is applied to a quantity the decomposition does not explain.
    """
    with localcontext(CALCULATION_CONTEXT):
        recomputed = D("0")
        for row in origin.buckets:  # BUCKET_ORDER, the same accumulation order the module uses
            recomputed += row.contribution

    assert +recomputed == origin.total_positive_contribution


@DETERMINISTIC
@given(decompositions())
def test_the_first_hour_contribution_is_the_prefix_of_that_same_accumulation(origin):
    first_hour = set(FIRST_HOUR_BUCKETS)
    with localcontext(CALCULATION_CONTEXT):
        recomputed = D("0")
        for row in origin.buckets:
            if row.bucket not in first_hour:
                break
            recomputed += row.contribution

    assert +recomputed == origin.first_hour_contribution
    assert origin.first_hour_contribution <= origin.total_positive_contribution


@DETERMINISTIC
@given(decompositions())
def test_no_contribution_is_ever_negative(origin):
    """``max(0, ...)``. A negative term in the denominator would inflate the share."""
    assert all(row.contribution >= 0 for row in origin.buckets)
    assert origin.total_positive_contribution >= 0


@DETERMINISTIC
@given(decompositions())
def test_the_share_is_none_exactly_when_the_status_is_indeterminate(origin):
    """The most dangerous bug in the project, stated as an invariant.

    A zero share on an unmeasurable window is a pass where there should be a failure.
    """
    assert (origin.share is None) is (origin.status is EdgeOriginStatus.INDETERMINATE)
    assert (origin.total_positive_contribution < MIN_TOTAL_POSITIVE_EDGE) is (origin.share is None)


@DETERMINISTIC
@given(decompositions())
def test_a_measurable_share_is_a_share(origin):
    assume(origin.share is not None)

    assert D("0") <= origin.share <= D("1")
    assert (origin.status is EdgeOriginStatus.UNCOPYABLE_DOMINATED) is (
        origin.share > FIRST_HOUR_EDGE_SHARE_MAX
    )
    assert origin.status.passes is (origin.share <= FIRST_HOUR_EDGE_SHARE_MAX)


@DETERMINISTIC
@given(decompositions())
def test_bucket_a_never_accounts_for_more_than_the_whole_first_hour(origin):
    assume(origin.share is not None)

    assert origin.bucket_a_contribution <= origin.first_hour_contribution
    assert origin.bucket_a_share <= origin.share


@DETERMINISTIC
@given(decompositions())
def test_the_limitation_travels_with_every_decomposition(origin):
    assert origin.limitations
    assert to_canonical_json(origin) == to_canonical_json(origin)


# -- window score ---------------------------------------------------------------


@DETERMINISTIC
@given(
    decompositions(),
    st.lists(returns, min_size=1, max_size=12),
    st.sampled_from(["leader", "follower_adjusted"]),
    returns,
)
def test_a_window_never_passes_unless_its_edge_origin_is_valid(origin, advantages, column, threshold):
    """For every threshold, including negative ones nobody could fail.

    ``EdgeOriginStatus.passes`` is True for ``VALID`` alone, and this is the assertion that stops
    an ``if window.passed:`` somewhere downstream from quietly absorbing the other two.
    """
    score = score_window(1, column, advantages, origin)

    if origin.status is not EdgeOriginStatus.VALID:
        assert not score.passes(threshold)
        assert not score.passes(D("-1000000"))


@DETERMINISTIC
@given(decompositions(), st.lists(returns, min_size=1, max_size=12), returns)
def test_passing_means_all_three_conditions_held(origin, advantages, threshold):
    score = score_window(1, "leader", advantages, origin)

    if score.passes(threshold):
        assert score.edge_origin_status is EdgeOriginStatus.VALID
        assert score.mean_advantage >= threshold
        assert score.median_advantage > 0
        assert score.first_hour_edge_share <= FIRST_HOUR_EDGE_SHARE_MAX


@DETERMINISTIC
@given(st.lists(returns, min_size=1, max_size=12))
def test_the_mean_and_median_stay_inside_the_advantages(values):
    assert min(values) <= arithmetic_mean(values) <= max(values)
    assert min(values) <= median(values) <= max(values)


@DETERMINISTIC
@given(st.lists(returns, min_size=1, max_size=12), st.data())
def test_the_median_does_not_depend_on_input_order(values, data):
    permuted = data.draw(st.permutations(values))

    assert median(values) == median(permuted)


@DETERMINISTIC
@given(decompositions(), st.lists(returns, min_size=1, max_size=12))
def test_a_window_score_always_survives_canonical_serialization(origin, advantages):
    evaluation = evaluate_window(2, "follower_adjusted", advantages, origin)
    rendered = to_canonical_json(evaluation.score)

    assert rendered == to_canonical_json(evaluation.score)
    if origin.status is EdgeOriginStatus.INDETERMINATE:
        # A meaningful state, not a missing field.
        assert '"first_hour_edge_share":null' in rendered


# -- the refusals ---------------------------------------------------------------


@DETERMINISTIC
@given(st.lists(returns, min_size=1, max_size=4))
def test_a_basket_whose_whole_volume_priced_at_zero_is_refused(rets):
    basket = [
        buy_outcome(a_buy(i, TokenAgeBucket.D), D("0"), r, realized_usd=D("10"))
        for i, r in enumerate(rets)
    ]

    with pytest.raises(UnscorableWallet):
        buy_quality(basket, WALLET)


@DETERMINISTIC
@given(st.lists(returns, min_size=1, max_size=4))
def test_a_basket_with_no_recorded_value_basis_is_refused(rets):
    basket = [
        buy_outcome(a_buy(i, TokenAgeBucket.D), D("1000"), r) for i, r in enumerate(rets)
    ]

    with pytest.raises(UnscorableWallet):
        buy_quality(basket, WALLET)
