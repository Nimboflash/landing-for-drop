"""Worked examples for the depth model. Every expected value below was computed by hand first.

The arithmetic is constant-product algebra on constructed pool states, so each expectation is
derivable in a line or two and none of it comes from the experiment's own data (ticket 30, final
checkbox). The reference pool is deliberately round:

    quote reserve   1,000,000 USDC  ->  x = $1,000,000
    asset reserve   worth the same  ->  TVL = $2,000,000  (a balanced pool)
    fee             30 bps

so that ``S/x`` reads straight off the order size:

    $10,000  = 0.5% of TVL  ->  1% average slippage
    $30,000  = 1.5% of TVL  ->  3%
    $100,000 = 5.0% of TVL  -> 10%
"""

from decimal import ROUND_UP, Context, Decimal, localcontext

import pytest

from contracts import (
    divide,
    mul,
    USDC,
    WBTC,
    WETH,
    AssetTier,
    LongTailExcludedError,
    PoolState,
    QuarantineRequired,
    to_canonical_json,
)
from depth import (
    MAX_TVL_UNDERSTATEMENT_FACTOR,
    MEASURED_SIZE_RATIO_10PCT_OVER_1PCT,
    MEASURED_TVL_UNDERSTATEMENT,
    MODEL_SIZE_RATIO_10PCT_OVER_1PCT,
    Q96,
    ExecutionSource,
    OrderBook,
    OrderBookLevel,
    OutsideValidityBand,
    PricedPool,
    QuoteAsset,
    average_slippage,
    best_public_execution,
    copier_penalty,
    copier_slippage,
    cost_cap_for,
    linear_copier_slippage,
    marginal_impact,
    measure_depth,
    own_price_impact,
    quote_execution,
    raw_to_usd,
    size_for_slippage,
    size_to_cost_cap,
    size_to_cost_cap_detail,
    virtual_reserves,
    walk_order_book,
)
from depth.amm import DepthModel

# The private helper is imported deliberately: the property under test is that it holds the
# frozen context *itself*, rather than inheriting it from the one call site that happens to wrap
# it. That is not observable through the public entry point, which always wraps it.
from depth.execution import _binding_constraint

D = Decimal

USDC_QUOTE = QuoteAsset(address=USDC, decimals=6, usd_price=D("1"))

#: x = $1,000,000 on the quote side; balanced, so TVL = $2,000,000.
QUOTE_RESERVE_RAW = 10 ** 6 * 10 ** 6
DEPTH_USD = D("1000000")


def constant_product_pool(fee_bps=30, quote_reserve_raw=QUOTE_RESERVE_RAW):
    return PricedPool(
        state=PoolState(
            address="0xpool",
            asset="0xa5e7",
            quote=USDC,
            asset_reserve_raw=10 ** 24,
            quote_reserve_raw=quote_reserve_raw,
            last_swap_block=18_000_000,
            last_swap_timestamp=1_695_000_000,
            fee_bps=fee_bps,
        ),
        quote=USDC_QUOTE,
    )


def concentrated_pool(active_liquidity, quote_reserve_raw=QUOTE_RESERVE_RAW, sqrt_price_x96=Q96):
    return PricedPool(
        state=PoolState(
            address="0xv3pool",
            asset="0xa5e7",
            quote=USDC,
            asset_reserve_raw=10 ** 24,
            quote_reserve_raw=quote_reserve_raw,
            last_swap_block=18_000_000,
            last_swap_timestamp=1_695_000_000,
            fee_bps=30,
            active_liquidity=active_liquidity,
            sqrt_price_x96=sqrt_price_x96,
        ),
        quote=USDC_QUOTE,
    )


#: The reference pool's depth reached through a quote asset that is neither $1.00 nor 6 decimals.
#: 400 WETH at $2,500 is the same $1,000,000, so every expectation below is the USDC one — which
#: is the point: the only thing that changes is the two conversion factors.
WETH_QUOTE = QuoteAsset(address=WETH, decimals=18, usd_price=D("2500"))
WETH_RESERVE_RAW = 400 * 10 ** 18

#: And once more at 8 decimals: 25 WBTC at $40,000 is also $1,000,000.
WBTC_QUOTE = QuoteAsset(address=WBTC, decimals=8, usd_price=D("40000"))
WBTC_RESERVE_RAW = 25 * 10 ** 8


def quote_asset_pool(quote, quote_reserve_raw, fee_bps=30):
    """The reference pool, quoted in something other than a $1.00 stablecoin."""
    return PricedPool(
        state=PoolState(
            address="0xnonstablepool",
            asset="0xa5e7",
            quote=quote.address,
            asset_reserve_raw=10 ** 24,
            quote_reserve_raw=quote_reserve_raw,
            last_swap_block=18_000_000,
            last_swap_timestamp=1_695_000_000,
            fee_bps=fee_bps,
        ),
        quote=quote,
    )


# -- the three formulas ---------------------------------------------------------


@pytest.mark.parametrize(
    "size_usd,expected",
    [
        ("10000", "0.01"),    # 0.5% of a $2,000,000 balanced pool
        ("30000", "0.03"),    # 1.5%
        ("100000", "0.10"),   # 5.0%
    ],
)
def test_balanced_pool_slippage_at_named_fractions_of_tvl(size_usd, expected):
    """§4.5: 1% at 0.5% of TVL, 3% at 1.5%, 10% at 5.0%. TVL = 2x on a balanced pool."""
    assert average_slippage(DEPTH_USD, D(size_usd)) == D(expected)


def test_average_slippage_is_size_over_quote_reserve():
    assert average_slippage(DEPTH_USD, D("50000")) == D("0.05")


def test_marginal_impact_is_the_square():
    """(1 + S/x)^2 - 1. At S/x = 5%: 1.05^2 - 1 = 0.1025."""
    assert marginal_impact(DEPTH_USD, D("50000")) == D("0.1025")


def test_marginal_impact_always_exceeds_average_slippage():
    """The gap between them *is* the copier penalty: the follower starts where the leader ended."""
    avg = average_slippage(DEPTH_USD, D("50000"))
    assert marginal_impact(DEPTH_USD, D("50000")) > avg


def test_arriving_after_a_leader_uses_the_product_form():
    """a = 2%, s = 3%: (1.02)(1.05) - 1 = 0.071."""
    assert copier_slippage(DEPTH_USD, D("20000"), D("30000")) == D("0.071")


# -- the required reference case ------------------------------------------------


def test_copier_at_equal_size_pays_3_1x_the_leader():
    """§4.5, verified: leader 5.000%, copier 15.500%, i.e. exactly 3.1x.

    Leader clips $50,000 into a $1,000,000 quote reserve, so a = 5%. The copier arrives at the
    first full block after and trades the same $50,000, so s = 5%.

        (1 + 0.05)(1 + 0.05 + 0.05) - 1  =  1.05 x 1.10 - 1  =  0.155
    """
    leader = average_slippage(DEPTH_USD, D("50000"))
    copier = copier_slippage(DEPTH_USD, D("50000"), D("50000"))

    assert leader == D("0.05000")
    assert copier == D("0.15500")
    assert copier / leader == D("3.1")


def test_the_two_footprints_partition_the_copier_slippage():
    """Own impact 5.0pp + inherited leader footprint 10.5pp = 15.5pp, exactly."""
    own = own_price_impact(DEPTH_USD, D("50000"))
    inherited = copier_penalty(DEPTH_USD, D("50000"), D("50000"))

    assert own == D("0.05")
    assert inherited == D("0.105")   # 2a + a^2 + as = 0.10 + 0.0025 + 0.0025
    assert own + inherited == copier_slippage(DEPTH_USD, D("50000"), D("50000"))


def test_linear_general_form_reproduces_the_reference_case_to_first_order():
    """(2 * S_leader + C) / S1, with S1 = $10,000 on this pool.

        (2 x 50,000 + 50,000) / 10,000 = 15 percentage points

    The exact form gives 15.5pp; the missing 0.5pp is the dropped ``a^2 + as``. The linear form
    exists because the double weight on the leader's size is visible in it.
    """
    s1 = size_for_slippage(DEPTH_USD, D("0.01"))
    assert s1 == D("10000")
    assert linear_copier_slippage(D("50000"), D("50000"), s1) == D("0.15")


def test_leader_size_enters_at_double_weight():
    """Doubling the leader's clip hurts exactly twice as much as doubling the copier's.

        base            (2x50,000 + 50,000)/10,000  = 15pp
        leader doubled  (2x100,000 + 50,000)/10,000 = 25pp   -> +10pp
        copier doubled  (2x50,000 + 100,000)/10,000 = 20pp   ->  +5pp
    """
    s1 = size_for_slippage(DEPTH_USD, D("0.01"))
    base = linear_copier_slippage(D("50000"), D("50000"), s1)
    leader_doubled = linear_copier_slippage(D("100000"), D("50000"), s1)
    copier_doubled = linear_copier_slippage(D("50000"), D("100000"), s1)

    assert base == D("0.15")
    assert leader_doubled == D("0.25")
    assert copier_doubled == D("0.20")
    assert (leader_doubled - base) == 2 * (copier_doubled - base)


def test_double_weight_holds_a_fortiori_in_the_exact_form():
    """The second-order terms make the leader's size hurt *more* than twice as much, never less.

        base            1.05 x 1.10 - 1 = 0.1550
        leader doubled  1.10 x 1.15 - 1 = 0.2650   -> +0.1100
        copier doubled  1.05 x 1.15 - 1 = 0.2075   -> +0.0525
    """
    base = copier_slippage(DEPTH_USD, D("50000"), D("50000"))
    leader_doubled = copier_slippage(DEPTH_USD, D("100000"), D("50000"))
    copier_doubled = copier_slippage(DEPTH_USD, D("50000"), D("100000"))

    assert base == D("0.1550")
    assert leader_doubled == D("0.2650")
    assert copier_doubled == D("0.2075")
    assert (leader_doubled - base) >= 2 * (copier_doubled - base)


# -- concentrated liquidity -----------------------------------------------------


@pytest.mark.parametrize("factor", ["5", "23"])
def test_tvl_understates_near_spot_depth_for_concentrated_pools(factor):
    """The measured 5-23x, constructed exactly.

    With ``sqrt_price_x96 = 2**96`` the price is 1 and ``y_v = L``. Setting ``L`` to N times the
    real quote reserve therefore makes near-spot depth exactly N times the TVL-implied figure.

    The direction is the point. TVL *understates* depth here; a model that assumed the usual
    direction would under-size every order and call itself conservative while being wrong.
    """
    n = int(factor)
    pool = concentrated_pool(active_liquidity=n * QUOTE_RESERVE_RAW)
    measurement = measure_depth(pool)

    assert measurement.model is DepthModel.CONCENTRATED_VIRTUAL_RESERVES
    assert measurement.quote_reserve_usd == DEPTH_USD
    assert measurement.effective_depth_usd == DEPTH_USD * n
    assert measurement.tvl_understatement_factor == D(factor)


def test_a_state_where_tvl_overstates_depth_is_quarantined_not_priced():
    """Virtual below real contradicts the measured evidence in the one direction it rules out."""
    pool = concentrated_pool(active_liquidity=QUOTE_RESERVE_RAW // 10)
    with pytest.raises(QuarantineRequired) as excinfo:
        measure_depth(pool)
    assert "understate" in str(excinfo.value)


def test_half_a_concentrated_state_is_refused_rather_than_priced_as_constant_product():
    """Silently falling back would understate depth by the whole 5-23x factor."""
    state = PoolState(
        address="0xhalf",
        asset="0xa5e7",
        quote=USDC,
        asset_reserve_raw=10 ** 24,
        quote_reserve_raw=QUOTE_RESERVE_RAW,
        last_swap_block=1,
        last_swap_timestamp=1,
        active_liquidity=5 * QUOTE_RESERVE_RAW,
    )
    with pytest.raises(ValueError) as excinfo:
        measure_depth(PricedPool(state=state, quote=USDC_QUOTE))
    assert "sqrt_price_x96" in str(excinfo.value)


def test_the_model_predicts_a_10x_size_ratio_that_was_not_measured():
    """Why there is a validity band rather than a correction factor.

    The single-band model says size(10% slippage) / size(1%) is exactly 10. Measurement said 7.6x
    for USDC/WETH and 507x for PEPE — one below, one 50x above, differing from each other by ~67x.
    No single multiplier reconciles them, so the model is bounded instead of adjusted.
    """
    at_1pct = size_for_slippage(DEPTH_USD, D("0.01"))
    at_10pct = size_for_slippage(DEPTH_USD, D("0.10"))

    assert at_10pct / at_1pct == MODEL_SIZE_RATIO_10PCT_OVER_1PCT == D("10")
    assert MEASURED_SIZE_RATIO_10PCT_OVER_1PCT["USDC/WETH"] < MODEL_SIZE_RATIO_10PCT_OVER_1PCT
    assert MEASURED_SIZE_RATIO_10PCT_OVER_1PCT["PEPE"] > MODEL_SIZE_RATIO_10PCT_OVER_1PCT * 50


def test_a_concentrated_pool_refuses_sizes_beyond_its_band():
    """$5,000,000 of near-spot depth bands at 1% = $50,000. $60,000 is refused, not extrapolated."""
    pool = concentrated_pool(active_liquidity=5 * QUOTE_RESERVE_RAW)
    band = measure_depth(pool).validity_band

    assert band.max_size_usd == D("50000")
    assert band.contains(D("50000"))
    assert not band.contains(D("60000"))

    with pytest.raises(OutsideValidityBand) as excinfo:
        quote_execution(pool, D("60000"))
    assert "validity band" in str(excinfo.value)


def test_a_constant_product_pool_has_no_model_ceiling():
    """x*y=k has no ticks to cross; the cost cap, not the model, bounds the order."""
    band = measure_depth(constant_product_pool()).validity_band
    assert band.max_size_usd is None
    assert band.contains(D("999999999"))


# -- a drained pool is data the model does not support --------------------------


def test_a_drained_concentrated_pool_is_quarantined_not_priced():
    """``quote_reserve_raw == 0`` with stale ``active_liquidity`` is $0 of pool, not $5,000,000.

    With ``sqrt_price_x96 = 2**96`` and ``L = 5 x 10^12`` the virtual quote reserve is ``L`` raw
    USDC = $5,000,000, and the band would open at 1% of it = $50,000. The pool holds nothing.

    The old quarantine guard was ``virtual_usd < real_usd``, which cannot fire when ``real_usd``
    is zero: the one state that most needs refusing was the one state the comparison could not
    reach. A drained pool must go to the reconciliation queue, not into a capacity table.
    """
    pool = concentrated_pool(active_liquidity=5 * 10 ** 12, quote_reserve_raw=0)

    with pytest.raises(QuarantineRequired) as excinfo:
        measure_depth(pool)
    assert "no quote-side reserve" in str(excinfo.value)


def test_a_drained_constant_product_pool_is_quarantined_on_the_same_terms():
    """The same input, the same classification. It is the pool that is unsupported, not the model.

    Refusing a $0 constant-product pool with a bare ``ValueError`` while pricing a $0 concentrated
    one was the asymmetry that hid the defect above; a caller draining the reconciliation queue
    has to see both.
    """
    pool = constant_product_pool(quote_reserve_raw=0)

    with pytest.raises(QuarantineRequired) as excinfo:
        measure_depth(pool)
    assert "no quote-side reserve" in str(excinfo.value)


def test_a_drained_pool_never_reaches_the_sizing_search():
    """$35,000 of copyable capacity against a pool holding $0 was the traced consequence."""
    pool = concentrated_pool(active_liquidity=5 * 10 ** 12, quote_reserve_raw=0)

    with pytest.raises(QuarantineRequired):
        size_to_cost_cap_detail(pool, AssetTier.MAJOR, D("1000000"), D("0"), D("0"))
    with pytest.raises(QuarantineRequired):
        quote_execution(pool, D("1000"))


def test_a_none_understatement_factor_means_constant_product_and_nothing_else():
    """``None`` is reserved for "the two coincide by construction", per the field's own docstring.

    It used to double as "the denominator was zero", so a reader could not tell a pool where TVL
    *is* the depth from a pool with no TVL at all. With the drained state quarantined the
    concentrated branch always divides by a positive reserve, so the two meanings no longer share
    a value.
    """
    constant = measure_depth(constant_product_pool())
    concentrated = measure_depth(concentrated_pool(active_liquidity=5 * QUOTE_RESERVE_RAW))

    assert constant.model is DepthModel.CONSTANT_PRODUCT
    assert constant.tvl_understatement_factor is None
    assert concentrated.tvl_understatement_factor == D("5")
    assert concentrated.tvl_understatement_factor >= 1


# -- the understatement band has two edges, not one -----------------------------


def test_the_ceiling_on_the_understatement_factor_is_ten_times_the_measured_maximum():
    """The bound, as literals, so that widening it fails here instead of moving with it.

        measured band          5x .. 23x
        ceiling                23 x 10  =  230x

    Ten, and not one, because the measurement is a sample of concentrated pools and not a census:
    a pool one notch tighter than anything measured must not be quarantined for it. Ten, and not a
    hundred, because the ceiling has to sit far below the failure it exists to catch — the traced
    case ran at 5x10^12, ten orders of magnitude above this line, so no plausible unmeasured
    concentrated pool and no drained-reserve artefact can end up on the same side of it.
    """
    assert MEASURED_TVL_UNDERSTATEMENT == (D("5"), D("23"))
    assert MAX_TVL_UNDERSTATEMENT_FACTOR == D("230")
    assert MAX_TVL_UNDERSTATEMENT_FACTOR == mul(D("23"), 10)


def test_the_measured_ceiling_itself_is_priced_and_one_step_past_it_is_not():
    """230x prices, 231x quarantines. The edge is a value, not an order of magnitude.

    With ``sqrt_price_x96 = 2**96`` the raw price is 1 and ``y_v = L``, so ``L = n x 10^12`` raw
    USDC against a ``10^12`` raw reserve is exactly an ``n``-fold understatement:

        real     10^12 raw / 10^6         =  $1,000,000
        n = 230  y_v = 2.30 x 10^14 raw   =  $230,000,000   ->  factor 230, band 1% = $2,300,000
        n = 231  y_v = 2.31 x 10^14 raw   =  $231,000,000   ->  refused

    A guard that fired only on astronomically large ratios would pass 231 straight through, which
    is the same mistake one level up as guarding ``real_usd == 0`` and passing one raw unit.
    """
    at_ceiling = measure_depth(concentrated_pool(active_liquidity=230 * QUOTE_RESERVE_RAW))

    assert at_ceiling.effective_depth_usd == D("230000000")
    assert at_ceiling.tvl_understatement_factor == D("230")
    assert at_ceiling.validity_band.max_size_usd == D("2300000")

    with pytest.raises(QuarantineRequired) as excinfo:
        measure_depth(concentrated_pool(active_liquidity=231 * QUOTE_RESERVE_RAW))
    assert "230" in str(excinfo.value)


def test_a_deep_pool_is_quarantined_on_the_ratio_and_not_on_the_size_of_its_reserve():
    """$5,000,000 of real reserve against $5,000,000,000 of virtual: a 1,000x understatement.

        real     5 x 10^12 raw / 10^6        =  $5,000,000
        y_v      L = 5 x 10^15 raw           =  $5,000,000,000
        factor   5,000,000,000 / 5,000,000   =  1,000x

    Nothing about this pool is drained, tiny, or near a boundary — it holds five million dollars.
    It is refused because the two readings of it disagree by 1,000x, which is the condition, and
    any guard written against a floor on the reserve or against a huge absolute depth would price
    it.
    """
    pool = concentrated_pool(
        active_liquidity=5 * 10 ** 15, quote_reserve_raw=5 * 10 ** 12
    )

    with pytest.raises(QuarantineRequired) as excinfo:
        measure_depth(pool)
    assert "reconciliation queue" in str(excinfo.value)


def test_the_ratio_is_refused_on_a_weth_quoted_pool_too():
    """Same 1,000x, reached through 18 decimals and a $2,500 quote price instead of a $1.00 one.

        real     400 x 10^18 raw / 10^18 x $2,500      =  $1,000,000
        y_v      L = 400,000 x 10^18 raw               =  $1,000,000,000
        factor                                          =  1,000x

    The bound is on the ratio, so it is invariant to the quote leg — both conversions cancel. A
    guard written in raw units against a stablecoin's six decimals would not be.
    """
    state = PoolState(
        address="0xv3weth",
        asset="0xa5e7",
        quote=WETH,
        asset_reserve_raw=10 ** 24,
        quote_reserve_raw=WETH_RESERVE_RAW,
        last_swap_block=18_000_000,
        last_swap_timestamp=1_695_000_000,
        fee_bps=30,
        active_liquidity=400_000 * 10 ** 18,
        sqrt_price_x96=Q96,
    )

    with pytest.raises(QuarantineRequired):
        measure_depth(PricedPool(state=state, quote=WETH_QUOTE))


def test_the_ratio_is_measured_off_the_quote_leg_at_a_price_other_than_one():
    """``sqrt_price_x96 = 4 * Q96`` puts the quote leg at ``4L``, so 232x arrives via the price.

        y_v      4L = 4 x 58 x 10^12 raw  =  2.32 x 10^14 raw  =  $232,000,000
        real                                                      $1,000,000
        factor                                                    232x

    Two hairs past the ceiling rather than twelve orders of magnitude, and reached at a price where
    the two virtual reserves differ by 16x — the corner every hand-computed fixture but this one
    avoids.
    """
    pool = concentrated_pool(active_liquidity=58 * 10 ** 12, sqrt_price_x96=4 * Q96)

    with pytest.raises(QuarantineRequired) as excinfo:
        measure_depth(pool)
    assert "230" in str(excinfo.value)


@pytest.mark.parametrize("raw", [1, 10, 100])
def test_one_raw_unit_of_reserve_does_not_restore_the_drained_pools_capacity(raw):
    """The traced defeat of the previous repair, refused at every reserve that reproduces it.

        L = 5 x 10^12 raw  ->  y_v = $5,000,000
        reserve 1 raw      =  $0.000001   ->  factor 5 x 10^12
        reserve 10 raw     =  $0.00001    ->  factor 5 x 10^11
        reserve 100 raw    =  $0.0001     ->  factor 5 x 10^10

    ``real_usd <= 0`` refused only the first column of that table. The pool holding a millionth of
    a dollar produced $5,000,000 of depth, a $50,000 band and $35,000 of copyable capacity —
    the reviewer's output verbatim, one raw unit to the right of the guard.
    """
    pool = concentrated_pool(active_liquidity=5 * 10 ** 12, quote_reserve_raw=raw)

    with pytest.raises(QuarantineRequired) as excinfo:
        measure_depth(pool)
    message = str(excinfo.value)
    assert "230" in message
    assert "reconciliation queue" in message


def test_a_thin_but_consistent_reserve_is_still_priced():
    """The other half of the rule: small is not the condition, *inconsistent* is.

        reserve  100 raw USDC   =  $0.0001
        y_v      L = 500 raw    =  $0.0005    ->  factor 5x, inside the measured band
        band     1% of $0.0005  =  $0.000005

    A pool holding a hundredth of a cent is a real pool and its depth is a real, tiny number. The
    fix must not turn "the reserve is small" into a refusal, or every sub-dollar pool leaves the
    population for a reason the study never pre-registered.
    """
    measurement = measure_depth(
        concentrated_pool(active_liquidity=500, quote_reserve_raw=100)
    )

    assert measurement.quote_reserve_usd == D("0.0001")
    assert measurement.effective_depth_usd == D("0.0005")
    assert measurement.tvl_understatement_factor == D("5")
    assert measurement.validity_band.max_size_usd == D("0.000005")


def test_an_out_of_band_pool_never_reaches_the_sizing_search_either():
    """$35,000 of copyable capacity against a pool holding $0.000001 was the traced consequence.

    ``measure_depth`` is the only door into both entry points, so refusing there closes both — but
    that is a claim about the code's shape, and this asserts it rather than assuming it.
    """
    pool = concentrated_pool(active_liquidity=5 * 10 ** 12, quote_reserve_raw=1)

    with pytest.raises(QuarantineRequired):
        size_to_cost_cap_detail(pool, AssetTier.MAJOR, D("1000000"), D("0"), D("0"))
    with pytest.raises(QuarantineRequired):
        quote_execution(pool, D("1000"))
    with pytest.raises(QuarantineRequired):
        size_to_cost_cap(pool, AssetTier.MAJOR, D("1000000"), D("0"), D("0"))


def test_a_refusal_message_survives_a_depth_too_large_to_quantize():
    """The refusal has to arrive as a refusal, not as an ``InvalidOperation`` from its own message.

    ``_fmt`` quantizes to four decimal places, and ``Decimal.quantize`` raises when the result
    needs more digits than the context allows — 28 ambient, 38 frozen. A virtual reserve of
    ``10^45`` raw USDC is $10^39, which needs 43, so the formatter raised out of the middle of the
    quarantine and the caller saw an arithmetic error instead of a queued pool.
    """
    pool = concentrated_pool(active_liquidity=10 ** 45)

    with pytest.raises(QuarantineRequired):
        measure_depth(pool)


def test_a_size_a_hair_outside_the_band_is_refused_rather_than_quietly_clipped():
    """``leader + order`` was added at the ambient 28-digit precision, not the frozen 38.

    The band is $50,000. ``$50,000.000000000000000000000000001`` carries 32 significant digits, so
    the ambient addition rounds it back to exactly $50,000 and ``ValidityBand.contains`` says yes —
    while the ceiling, computed under the frozen context, says the order is over. The call asked
    for no partial fill and got one anyway, band-limited at $50,000 with a 2E-32 liquidity
    limitation and no exception.
    """
    pool = concentrated_pool(active_liquidity=5 * QUOTE_RESERVE_RAW)
    just_over = D("50000.000000000000000000000000001")

    assert measure_depth(pool).validity_band.max_size_usd == D("50000")
    with pytest.raises(OutsideValidityBand):
        quote_execution(pool, just_over, allow_partial_fill=False)


# -- the quote asset carries a price, and it is not always $1.00 ----------------


def test_a_weth_quoted_pool_is_priced_in_dollars_not_in_ether():
    """400 WETH at $2,500 is $1,000,000 of depth.

        raw 400 x 10^18  /  10^18   =  400 whole WETH
        400 x $2,500                =  $1,000,000
        1% of that                  =  $10,000 of S1

    Every other fixture in this file quotes in USDC at exactly $1.00 and 6 decimals, where the
    ``* quote.usd_price`` factor is multiplication by one and invisible. Dropping it reports $400
    of depth here — a 2,500x understatement that would declare every WETH-quoted pool uncopyable,
    and WETH is the usual quote leg for exactly the volatile pairs this experiment is about.
    """
    assert raw_to_usd(WETH_RESERVE_RAW, WETH_QUOTE) == D("1000000")

    measurement = measure_depth(quote_asset_pool(WETH_QUOTE, WETH_RESERVE_RAW))

    assert measurement.quote_reserve_usd == D("1000000")
    assert measurement.effective_depth_usd == D("1000000")
    assert measurement.s1_usd == D("10000")


def test_a_wbtc_quoted_pool_converts_at_eight_decimals():
    """25 WBTC at $40,000 is $1,000,000: 25 x 10^8 raw / 10^8 = 25 whole units."""
    assert raw_to_usd(WBTC_RESERVE_RAW, WBTC_QUOTE) == D("1000000")
    assert measure_depth(quote_asset_pool(WBTC_QUOTE, WBTC_RESERVE_RAW)).effective_depth_usd \
        == D("1000000")


def test_the_sized_order_is_the_same_dollars_whatever_the_quote_leg_is():
    """0.7% of $1,000,000 = $7,000, whether the pool holds USDC, WETH or WBTC.

    The depth figure is what feeds the cap arithmetic, so a lost price factor does not stay a
    depth bug — it becomes a capacity number.
    """
    for pool in (
        constant_product_pool(),
        quote_asset_pool(WETH_QUOTE, WETH_RESERVE_RAW),
        quote_asset_pool(WBTC_QUOTE, WBTC_RESERVE_RAW),
    ):
        result = size_to_cost_cap_detail(pool, AssetTier.MAJOR, D("100000"), D("0"), D("0"))
        assert result.order_usd == D("7000")
        assert result.execution_cost_pct == D("0.01")


# -- which virtual reserve is the quote one -------------------------------------


def test_virtual_reserves_put_the_quote_leg_on_the_sqrt_price_side():
    """At ``sqrt_price_x96 = 4 * Q96`` the raw price is 16, so the two legs differ by 16x.

        x_v = L * Q96 // (4 Q96) = L/4 = 1,250,000,000,000    (asset side)
        y_v = L * 4 Q96 // Q96   = 4L  = 20,000,000,000,000   (quote side)
        x_v * y_v                = L^2 = 2.5 x 10^25          (the pool's own invariant)

    Every other concentrated fixture uses ``sqrt_price_x96 = Q96``, where ``x_v == y_v``
    identically and the orientation cannot be observed at all. This is the one input convention
    the module's docstring concedes ``contracts.PoolState`` does not pin, so it has to be pinned
    at a price where the two legs disagree.
    """
    liquidity = 5 * 10 ** 12
    asset_virtual, quote_virtual = virtual_reserves(liquidity, 4 * Q96)

    assert asset_virtual == 1_250_000_000_000
    assert quote_virtual == 20_000_000_000_000
    assert asset_virtual * quote_virtual == liquidity * liquidity


def test_depth_at_a_price_other_than_one_reads_off_the_quote_leg():
    """$20,000,000 of near-spot depth against a $1,000,000 real reserve: a 20x understatement.

    Returning the asset-side reserve instead would report $1,250,000 — still above the real
    reserve, so the existing ``virtual < real`` quarantine stays silent and the wrong number ships.
    """
    pool = concentrated_pool(active_liquidity=5 * 10 ** 12, sqrt_price_x96=4 * Q96)
    measurement = measure_depth(pool)

    assert measurement.virtual_quote_reserve_raw == 20_000_000_000_000
    assert measurement.effective_depth_usd == D("20000000")
    assert measurement.quote_reserve_usd == DEPTH_USD
    assert measurement.tvl_understatement_factor == D("20")
    assert measurement.validity_band.max_size_usd == D("200000")


def test_an_inverted_orientation_below_spot_is_still_quarantined():
    """At ``sqrt_price_x96 = Q96 // 4`` the quote leg is the *small* one: L/4 raw = $1,250,000...

    ...which is above the $1,000,000 real reserve, so this state prices. Halve the liquidity and
    the quote leg falls to $625,000, below the real reserve, and the 5-23x measured evidence rules
    it out — the direction the existing guard does catch.
    """
    priced = measure_depth(
        concentrated_pool(active_liquidity=5 * 10 ** 12, sqrt_price_x96=Q96 // 4)
    )
    assert priced.effective_depth_usd == D("1250000")

    with pytest.raises(QuarantineRequired):
        measure_depth(concentrated_pool(active_liquidity=25 * 10 ** 11, sqrt_price_x96=Q96 // 4))


# -- itemised cost --------------------------------------------------------------


def test_cost_components_are_itemised_and_sum_to_the_reported_total():
    """$500 order, $3.25 gas, 30 bps, no leader:

        fee     30/10,000                = 0.0030
        gas     3.25/500                 = 0.0065
        impact  500/1,000,000            = 0.0005
        penalty (no leader)              = 0
                                          ------
        total                             0.0100
    """
    quote = quote_execution(constant_product_pool(), D("500"), gas_usd=D("3.25"))

    assert quote.costs.dex_fee_pct == D("0.0030")
    assert quote.costs.gas_pct == D("0.0065")
    assert quote.costs.price_impact_pct == D("0.0005")
    assert quote.costs.copier_penalty_pct == 0
    assert quote.costs.total_priced_cost_pct == D("0.0100")
    assert quote.pool_depth_at_trade_usd == DEPTH_USD
    assert quote.s1_at_trade_usd == D("10000")


def test_gas_makes_the_cost_curve_convex_not_monotone():
    """$500 and $6,500 both cost exactly 1% — the curve dips between them and rises after.

    This is why the sizing search brackets a minimum before hunting the upper root: a single
    bisection assuming monotone cost would return the *lower* root and report a $500 capacity for
    a pool that supports $6,500.
    """
    pool = constant_product_pool()
    low = quote_execution(pool, D("500"), gas_usd=D("3.25")).costs.total_priced_cost_pct
    mid = quote_execution(pool, D("1800"), gas_usd=D("3.25")).costs.total_priced_cost_pct
    high = quote_execution(pool, D("6500"), gas_usd=D("3.25")).costs.total_priced_cost_pct

    assert low == D("0.0100")
    assert high == D("0.0100")
    assert mid < low


# -- sizing to the cost cap -----------------------------------------------------


def test_size_to_cost_cap_with_no_gas_and_no_leader():
    """Major cap 1%, fee 0.3%, so 0.7% is left for impact: 0.007 x $1,000,000 = $7,000."""
    result = size_to_cost_cap_detail(
        constant_product_pool(), AssetTier.MAJOR, D("100000"), D("0"), D("0")
    )

    assert result.copyable is True
    assert result.order_usd == D("7000")
    assert result.execution_cost_pct == D("0.01")
    assert result.binding_constraint == "cost_cap"


def test_size_to_cost_cap_with_gas_solves_the_upper_root():
    """With $3.25 of gas the feasible interval is [$500, $6,500]; the answer is the upper end.

    Roots of  z^2 - 7000 z + 50,000 x 65 = 0  after clearing 1e-6:
        1e-6 z^2 - 0.007 z + 3.25 = 0  ->  z = (0.007 +/- 0.006) / 2e-6  ->  500 and 6,500.
    """
    result = size_to_cost_cap_detail(
        constant_product_pool(), AssetTier.MAJOR, D("100000"), D("0"), D("3.25")
    )

    assert result.copyable is True
    assert abs(result.order_usd - D("6500")) <= D("0.000001")
    assert result.execution_cost_pct <= D("0.01")
    assert result.order_usd > D("500")


def test_size_to_cost_cap_is_bounded_by_strategy_aum():
    """§4.5's ``min(...)``: $1,000 of capital cannot place the $7,000 the pool would allow."""
    result = size_to_cost_cap_detail(
        constant_product_pool(), AssetTier.MAJOR, D("1000"), D("0"), D("0")
    )

    assert result.order_usd == D("1000")
    assert result.binding_constraint == "strategy_aum"
    assert result.execution_cost_pct < D("0.01")


def test_mid_cap_gets_the_wider_cap():
    """2% cap, 0.3% fee -> 1.7% for impact -> $17,000."""
    result = size_to_cost_cap_detail(
        constant_product_pool(), AssetTier.MID_CAP, D("100000"), D("0"), D("0")
    )
    assert result.order_usd == D("17000")


def test_a_leader_footprint_that_eats_the_budget_is_measured_not_raised():
    """Leader clips $50,000 (a = 5%): footprint 2a + a^2 = 10.25pp, against a 1pp cap.

    This is the shape of the measured long-tail result — "the leader's own footprint consumes the
    entire slippage budget before a single copier trades". It is a finding, so it is reported as
    ``copyable=False`` with a reason and must never raise.
    """
    result = size_to_cost_cap(
        constant_product_pool(), AssetTier.MAJOR, D("100000"), D("50000"), D("0")
    )

    assert result.copyable is False
    assert result.filled_order_usd == 0
    assert result.follower_return is None
    assert "footprint" in result.rejection_reason
    assert "10.2500pp" in result.rejection_reason


def test_a_small_leader_clip_still_costs_the_follower_double():
    """Leader $2,000 on $1,000,000 (a = 0.2%): footprint 0.4004pp, leaving 0.2996pp of budget.

        size = 0.002996 x 1,000,000 / 1.002 = 2,990.019960079840319361...
    """
    result = size_to_cost_cap_detail(
        constant_product_pool(), AssetTier.MAJOR, D("100000"), D("2000"), D("0")
    )

    assert result.copyable is True
    assert abs(result.order_usd - D("2990.019960079840319361")) <= D("0.000001")

    # The double weight is on the LEADER's size, not on the follower's own impact. Comparing the
    # footprint to twice the follower's impact is a different and unsupported claim — here the
    # leader ($2,000) is smaller than the follower ($2,990), so it would fail on arithmetic alone.
    # State the property that actually holds: the footprint is ~2a, and doubling the leader moves
    # it twice as far as doubling the copier.
    depth = result.pool_depth_at_trade_usd
    assert abs(result.costs.copier_penalty_pct - 2 * D("2000") / depth) < D("0.00001")

    doubled_leader = copier_penalty(depth, D("4000"), D("2990.02"))
    doubled_copier = copier_penalty(depth, D("2000"), D("5980.04"))
    assert doubled_leader - result.costs.copier_penalty_pct > \
        10 * (doubled_copier - result.costs.copier_penalty_pct)


def test_long_tail_raises_rather_than_returning_zero_capacity():
    """Zero capacity is a measured result; excluded scope is a modelling decision."""
    with pytest.raises(LongTailExcludedError):
        cost_cap_for(AssetTier.LONG_TAIL)
    with pytest.raises(LongTailExcludedError):
        size_to_cost_cap(
            constant_product_pool(), AssetTier.LONG_TAIL, D("100000"), D("0"), D("0")
        )


def test_cost_caps_are_the_pinned_ones():
    assert cost_cap_for(AssetTier.MAJOR) == D("0.01")
    assert cost_cap_for(AssetTier.MID_CAP) == D("0.02")


def test_follower_return_is_the_execution_drag_when_no_leader_return_is_supplied():
    """A $7,000 order costing exactly 1%: ``1 / 1.01 - 1``.

    Not a placeholder — it is what the copy returns when the leader's own edge is exactly zero.

    Hand computation, because ``1/1.01`` has no exact decimal form. ``1/1.01 = 100/101``, whose
    expansion is the four-digit block ``9900`` repeating::

        100/101 = 0.99009900 99009900 99009900 99009900 9900...

    The frozen context keeps 38 significant digits, and the 39th digit is a 0, so it truncates
    rather than rounding up::

        divide(1, 1.01) = 0.99009900990099009900990099009900990099   (38 digits)
        1 - that        = 0.00990099009900990099009900990099009901   (36 digits, exact)

    The literal below is that value negated. It is written out rather than recomputed with
    ``divide(D("1"), D("1.01")) - D("1")``, because a test that re-runs the implementation's own
    expression agrees with the implementation whether or not the implementation is right — which
    is how a 28-digit truncation shipped in ``LotConsumption.realized_return``. Note the digit
    count: a 28-digit ambient context would return ``-0.009900990099009900990099010`` and fail here.
    """
    result = size_to_cost_cap(
        constant_product_pool(), AssetTier.MAJOR, D("100000"), D("0"), D("0")
    )

    assert result.follower_return == D("-0.00990099009900990099009900990099009901")


def test_leader_return_is_deflated_by_the_execution_cost():
    """A 20% leader return at 1% execution cost: ``1.20 / 1.01 - 1``.

    ``1.2/1.01 = 120/101``, expansion ``1.18811881 18811881 ...`` on the two-digit block ``1188``
    after the leading ``1.``. To 38 significant digits the 39th digit is an 8, so it rounds up::

        divide(1.2, 1.01) = 1.1881188118811881188118811881188118812   (38 digits, rounded up)
        that - 1          = 0.1881188118811881188118811881188118812   (37 digits, exact)

    The 20% edge survives, reduced — that is the whole claim of §4.5: execution cost deflates a
    leader's return, it does not erase it at this depth.
    """
    result = size_to_cost_cap(
        constant_product_pool(), AssetTier.MAJOR, D("100000"), D("0"), D("0"),
        leader_return=D("0.20"),
    )

    assert result.follower_return == D("0.1881188118811881188118811881188118812")
    assert result.follower_return < D("0.20")


def test_the_seam_simulation_reports_filled_over_intended_and_not_its_complement():
    """$10,000 of capital against a pool that can take $7,000 at the cap: absorption 0.7.

        cap 1% - fee 0.3% = 0.7% of $1,000,000 of depth = $7,000
        intended_order_usd = strategy_aum                = $10,000
        7,000 / 10,000                                   = 0.7   exactly

    ``CopySimulation.fill_ratio`` is the seam field the rest of the pipeline reads, and it is the
    one shape of error that survives every other assertion in this file: inverted it reads
    ``10,000/7,000 = 1.428...``, complemented it reads ``3,000/10,000 = 0.3``, and both still look
    like a ratio. Only a case with a known numerator *and* denominator separates them.
    """
    detail = size_to_cost_cap_detail(
        constant_product_pool(), AssetTier.MAJOR, D("10000"), D("0"), D("0")
    )
    simulation = detail.simulation

    assert detail.order_usd == D("7000")
    assert detail.binding_constraint == "cost_cap"
    assert simulation.intended_order_usd == D("10000")
    assert simulation.filled_order_usd == D("7000")
    assert simulation.fill_ratio == D("0.7")
    assert detail.capital_absorption == D("0.7")


# -- order-book depth -----------------------------------------------------------


def book():
    """Three ask levels, 10 whole units each: $1,000 + $1,010 + $1,020 = $3,030 of capacity."""
    return OrderBook(
        asset_decimals=18,
        levels=(
            OrderBookLevel(price_usd=D("100"), quantity_raw=10 * 10 ** 18),
            OrderBookLevel(price_usd=D("101"), quantity_raw=10 * 10 ** 18),
            OrderBookLevel(price_usd=D("102"), quantity_raw=10 * 10 ** 18),
        ),
    )


def test_walking_two_full_levels_gives_a_hand_computable_vwap():
    """$2,010 buys 20 units across levels at $100 and $101: VWAP $100.50, slippage 0.5%."""
    fill = walk_order_book(book(), D("2010"))

    assert fill.filled_usd == D("2010")
    assert fill.acquired_raw == 20 * 10 ** 18
    assert fill.vwap_usd == D("100.5")
    assert fill.slippage_pct == D("0.005")
    assert fill.levels_consumed == 2
    assert fill.fill_ratio == 1
    assert fill.fills is True


def test_the_book_is_never_extrapolated_past_its_last_level():
    """A $4,000 order against $3,030 of book fills 75.75% — below §9.4's 90%, so it is not a fill."""
    fill = walk_order_book(book(), D("4000"))

    assert fill.filled_usd == D("3030")
    assert fill.fill_ratio == D("0.7575")
    assert fill.unfilled_share == D("0.2425")
    assert fill.fills is False


def test_partial_level_consumption_floors_the_acquired_quantity():
    """$1,500 takes level 1 whole and $500 of level 2: 10 + 500/101 units.

    Raw quantities are integers, so the partial level is floored. Both the acquired quantity and
    the amount spent shrink together, and because the floored leg is the *expensive* one ($101 vs
    $100) the average tips very slightly toward the cheap level — so flooring lowers the VWAP
    rather than raising it. The effect is ~1e-21 relative; what matters is that the direction is
    stated correctly, since "conservative" was the reason given for flooring.
    """
    fill = walk_order_book(book(), D("1500"))

    unfloored_vwap = divide(D("15150"), D("151"))

    assert fill.acquired_raw == 10 * 10 ** 18 + 4_950_495_049_504_950_495
    assert abs(fill.vwap_usd - unfloored_vwap) < D("1e-15")
    assert fill.vwap_usd <= unfloored_vwap


def test_private_liquidity_never_wins_the_route():
    """§9.4: the cheapest source is ignored when it is RFQ / market-maker inventory."""
    chosen = best_public_execution((
        ExecutionSource("single_pool", total_cost_pct=D("0.009"), fill_ratio=D("1")),
        ExecutionSource("rfq_aggregator", total_cost_pct=D("0.001"), fill_ratio=D("1"),
                        is_private=True),
    ))
    assert chosen.name == "single_pool"


def test_a_public_source_that_cannot_fill_is_not_a_source():
    """Public but 80% filled: returns None — a measured outcome for the caller to record."""
    assert best_public_execution((
        ExecutionSource("thin_pool", total_cost_pct=D("0.001"), fill_ratio=D("0.80")),
    )) is None


def test_the_cheapest_of_two_filling_public_sources_wins():
    """§9.4's "best deterministic public source" is the *cheapest* one, and saying so needs two.

    0.9% and 0.1%, both filling 100%, both public: nothing but the cost ordering can decide, so
    the answer is the 0.1% route. Every other case in this file leaves exactly one candidate
    standing after the private and 90%-fill filters, and with one candidate ``min`` and ``max``
    are the same function — the direction of the choice was asserted nowhere.
    """
    chosen = best_public_execution((
        ExecutionSource("expensive_router", total_cost_pct=D("0.009"), fill_ratio=D("1")),
        ExecutionSource("cheap_single_pool", total_cost_pct=D("0.001"), fill_ratio=D("1")),
    ))

    assert chosen.name == "cheap_single_pool"
    assert chosen.total_cost_pct == D("0.001")


def test_the_fill_rule_is_applied_before_the_cost_ordering():
    """A cheaper route that fills 89% loses to a dearer one that fills fully.

    §9.4's two rules compose in one direction only: filtering first and then minimising is "the
    cheapest source that fills"; minimising first would be "the cheapest source, if it happens to
    fill" — a different and much weaker claim.
    """
    chosen = best_public_execution((
        ExecutionSource("deep_pool", total_cost_pct=D("0.009"), fill_ratio=D("1")),
        ExecutionSource("thin_pool", total_cost_pct=D("0.001"), fill_ratio=D("0.89")),
    ))

    assert chosen.name == "deep_pool"


def test_equal_cost_sources_are_broken_by_name_not_by_input_order():
    """Determinism across runs and machines: the same set in either order gives the same route."""
    a = ExecutionSource("aaa_pool", total_cost_pct=D("0.004"), fill_ratio=D("1"))
    b = ExecutionSource("zzz_pool", total_cost_pct=D("0.004"), fill_ratio=D("1"))

    assert best_public_execution((a, b)).name == "aaa_pool"
    assert best_public_execution((b, a)).name == "aaa_pool"


# -- serialization --------------------------------------------------------------


def test_every_output_survives_canonical_json():
    """A float leaking in through any path raises here rather than reaching the freeze manifest."""
    pool = constant_product_pool()
    detail = size_to_cost_cap_detail(pool, AssetTier.MAJOR, D("100000"), D("0"), D("3.25"))

    for artifact in (
        measure_depth(pool),
        measure_depth(concentrated_pool(active_liquidity=5 * QUOTE_RESERVE_RAW)),
        quote_execution(pool, D("5000"), D("1000"), D("3.25")),
        detail,
        detail.simulation,
        walk_order_book(book(), D("2010")),
        ExecutionSource("single_pool", total_cost_pct=D("0.009"), fill_ratio=D("1")),
    ):
        payload = to_canonical_json(artifact)
        assert payload.startswith("{")
        assert "e+" not in payload.lower() or "\"e+" not in payload.lower()


def test_the_binding_constraint_does_not_depend_on_the_caller_s_decimal_context():
    """``_binding_constraint`` labels the ceiling that decided the size, and the label is reported.

    It is reached today only from inside ``localcontext(CALCULATION_CONTEXT)``, which is a property
    of one call site rather than of the function. Called from the ambient 28-digit context the
    subtraction rounds and the label changes:

        size    1.0000010000000000000000000000000001     (34 significant digits)
        ceiling 1
        size - ceiling = 0.0000010000000000000000000000000001   > BISECTION_TOLERANCE_USD (1e-6)

    so the validity band did *not* bind and the answer is ``cost_cap``. Rounded to 28 digits the
    difference becomes exactly 1e-6, ``<= tol`` holds, and the same order is reported as having
    been capped by the validity band — a different published reason for the same number.
    """
    size = D("1.0000010000000000000000000000000001")
    ceiling = D("1")
    aum = D("999999")
    cap_limited_max = D("999999")

    assert _binding_constraint(size, cap_limited_max, aum, ceiling) == "cost_cap"

    with localcontext(Context(prec=6, rounding=ROUND_UP)):
        assert _binding_constraint(size, cap_limited_max, aum, ceiling) == "cost_cap"


# -- the 90% fill boundary, pinned at exactly 90% --------------------------------


def test_a_fill_of_exactly_ninety_percent_fills():
    """Addendum §9.4 says *at least* 90%, and nothing pinned the boundary itself.

    Found by auditing ticket 30's eighth criterion. Both ``fills`` properties read
    ``fill_ratio >= MIN_FILL_RATIO``, and every existing case sits well inside the band — 0.7575 and
    0.80 below, 1.00 above. So flipping ``>=`` to ``>`` changed the answer for exactly one input,
    which no test supplied: a quote filling precisely 90% would report *unexecutable* while the
    addendum calls it filled.

    A one-character edit that survives the suite is the definition of an unpinned rule, and the
    direction it fails in discards a copyable trade rather than admitting an uncopyable one — which
    is the direction that makes the follower look worse than the model says.
    """
    from depth.orderbook import MIN_FILL_RATIO, ExecutionSource

    assert MIN_FILL_RATIO == D("0.90")

    exactly = ExecutionSource(name="public-amm", total_cost_pct=D("0.005"),
                              fill_ratio=D("0.90"))
    assert exactly.fills is True, "exactly 90% is a fill; §9.4 says at least 90%"

    hair_under = ExecutionSource(name="public-amm", total_cost_pct=D("0.005"),
                                 fill_ratio=D("0.8999999999999999999999999999999999999"))
    assert hair_under.fills is False, (
        "a fill below the floor is a partial fill, which is a different fact from a smaller trade"
    )


def test_the_order_book_fill_agrees_with_the_source_at_the_boundary():
    """The same rule lives on two types, so the boundary is pinned on both.

    ``OrderBookFill.fills`` and ``ExecutionSource.fills`` are separate properties reading one
    constant. Pinning only one leaves the other free to drift to ``>``, and a book that filled
    exactly 90% would then disagree with a source that filled exactly 90%.
    """
    from depth.orderbook import MIN_FILL_RATIO, OrderBookFill

    exactly = OrderBookFill(
        requested_usd=D("1000"), filled_usd=D("900"), acquired_raw=900,
        best_price_usd=D("1"), vwap_usd=D("1"), slippage_pct=D("0"), levels_consumed=1,
    )
    assert exactly.fill_ratio == MIN_FILL_RATIO
    assert exactly.fills is True

    under = OrderBookFill(
        requested_usd=D("1000"), filled_usd=D("899"), acquired_raw=899,
        best_price_usd=D("1"), vwap_usd=D("1"), slippage_pct=D("0"), levels_consumed=1,
    )
    assert under.fills is False
