"""Invariants for ``depth``, over generated pool states, sizes and quote assets.

The module states its own central invariant in ``amm.py``: ``execution_price_ratio`` is *monotone
non-decreasing in size*, and "that is the invariant the whole module rests on". Until this file
existed it was asserted nowhere — ``execution_price_ratio`` had zero references in the entire test
tree, and flipping ``+(ONE + copier_slippage(...))`` to ``+(ONE - copier_slippage(...))`` — turning
the execution price into a discount that grows with order size — passed every test in the
repository.

What is generated here is chosen to break the fixture monoculture the hand-computed file runs on.
Those cases use one pool, one quote asset at exactly $1.00, six decimals, and
``sqrt_price_x96 = Q96`` in every concentrated state — a space in which the USD price factor is
multiplication by one and the two virtual reserves are identically equal, so neither can be
observed. Here the quote leg is drawn from all four §4.6 assets at 6, 8 and 18 decimals and prices
from $1 to $40,000, and the square-root price spans twelve orders of magnitude either side of one.

``derandomize=True`` throughout: the house rule forbids unseeded randomness, and a property suite
that fails only on Tuesdays is worse than none.

**Tolerances.** Three properties below compare two algebraically identical expressions that are
*not* numerically identical, because each is a different sequence of roundings at 38 significant
digits. Where that happens the bound is derived from the number of roundings and the magnitude of
the intermediates, and stated in the docstring — never widened until the test goes green.
"""

from decimal import Decimal, localcontext

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from contracts import (
    CALCULATION_CONTEXT,
    USDC,
    USDT,
    WBTC,
    WETH,
    AssetTier,
    PoolState,
    QuarantineRequired,
    add,
    divide,
    mul,
    sub,
    to_canonical_json,
)
from depth import (
    CONCENTRATED_BAND_MAX_SLIPPAGE,
    MIN_FILL_RATIO,
    Q96,
    DepthModel,
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
    execution_price_ratio,
    linear_copier_slippage,
    marginal_impact,
    measure_depth,
    own_price_impact,
    quote_execution,
    raw_to_usd,
    size_to_cost_cap_detail,
    virtual_reserves,
    walk_order_book,
)

D = Decimal

DETERMINISTIC = settings(derandomize=True, max_examples=200, deadline=None)

#: The four §4.6 quote assets, at the decimals and rough prices they actually carry. Nothing else
#: may hold a USD price, and everything downstream of ``raw_to_usd`` is denominated through one of
#: these four conversions.
QUOTE_LEGS = (
    (USDC, 6, D("1")),
    (USDT, 6, D("1")),
    (WETH, 18, D("2500")),
    (WBTC, 8, D("40000")),
)

quote_legs = st.sampled_from(QUOTE_LEGS)

#: Whole units of the quote asset resting in the pool: $1 to $4x10^10 depending on the leg.
whole_quote_units = st.integers(min_value=1, max_value=10 ** 6)

#: Raw quote units, **from one**. The floor of a whole unit was structural, not incidental: the
#: regime this file exists to reach is a reserve so small relative to the liquidity read against it
#: that the ratio between them stops being a measurement, and one whole USDC — 10^6 raw — is
#: already a thousand times larger than the reserve in the traced failure. A wei of WETH and a
#: satoshi of WBTC are ordinary chain values and belong in the space.
raw_quote_units = st.integers(min_value=1, max_value=10 ** 12)

#: USD amounts at micro-dollar granularity — :data:`contracts.SCALE_USD`, the finest scale the
#: reporting boundary can express, so nothing generated here is finer than what can be reported.
usd_micros = st.integers(min_value=0, max_value=10 ** 12)
positive_usd_micros = st.integers(min_value=1, max_value=10 ** 12)

#: Square-root prices spanning 1e-6 .. 1e6 in ``sqrt(P)``, i.e. twelve orders of magnitude in the
#: price itself, on both sides of Q96. At Q96 exactly the two virtual reserves coincide and the
#: quote/asset orientation is unobservable; that point is one draw here rather than the whole space.
sqrt_prices = st.integers(min_value=1, max_value=10 ** 12).map(
    lambda n: max(1, Q96 * n // 10 ** 6)
)

#: The supported understatement band, end to end: 1x at the lower edge, 230x at the upper one.
#:
#: The old range stopped at the measured 23x, which meant the whole of the supported space above
#: the measurement — and the entire unsupported space above *that* — was unreachable by any
#: generated pool. 230 is written as a literal here, not read from
#: :data:`depth.MAX_TVL_UNDERSTATEMENT_FACTOR`, so that a generator which follows a widened
#: constant cannot quietly keep pace with it.
SUPPORTED_MAX_FACTOR = 230

understatement_factors = st.integers(min_value=1, max_value=SUPPORTED_MAX_FACTOR)

#: Ratios the model does not support, from one step past the ceiling to the 5x10^12 of the traced
#: case. The two components are drawn separately because a single wide integer range would put
#: almost every example at the astronomical end, and the value that defeated the previous repair
#: was two hairs past a boundary, not an astronomical one.
unsupported_factors = st.one_of(
    st.integers(min_value=SUPPORTED_MAX_FACTOR + 1, max_value=10 ** 3),
    st.integers(min_value=10 ** 3, max_value=10 ** 13),
)

tiers = st.sampled_from((AssetTier.MAJOR, AssetTier.MID_CAP))
fee_bps = st.integers(min_value=0, max_value=10_000)


def usd(micros):
    return divide(micros, 10 ** 6)


def _quote_asset(leg):
    address, decimals, price = leg
    return QuoteAsset(address=address, decimals=decimals, usd_price=price)


@st.composite
def constant_product_pools(draw, quote_reserve_raw=None):
    leg = draw(quote_legs)
    quote = _quote_asset(leg)
    reserves = st.one_of(
        raw_quote_units,
        whole_quote_units.map(lambda units: units * 10 ** leg[1]),
    )
    raw = quote_reserve_raw if quote_reserve_raw is not None else draw(reserves)
    return PricedPool(
        state=PoolState(
            address="0xcp",
            asset="0xa55e7",
            quote=quote.address,
            asset_reserve_raw=draw(st.integers(min_value=1, max_value=10 ** 24)),
            quote_reserve_raw=raw,
            last_swap_block=18_000_000,
            last_swap_timestamp=1_695_000_000,
            fee_bps=draw(fee_bps),
        ),
        quote=quote,
    )


@st.composite
def concentrated_pools(draw):
    """A v3/v4 state inside the supported understatement band, at every ratio the band allows.

    The **reserve** is solved for and the liquidity drawn, which is the reverse of the obvious
    direction and the only one that keeps the achieved ratio inside the band by construction.
    Solving for ``active_liquidity`` instead leaves the ratio at the mercy of two floors whose
    absolute error is ``sqrt_price / Q96`` raw units — up to 10^6 here — so a pool with a single
    raw unit of reserve came out at a ratio of 10^6 whatever ratio was asked for, and the generator
    could only stay in the supported space by never drawing a small reserve. That is precisely the
    restriction this file has to lose.

        y_v      = L * sqrt(P) / Q96, floored          (exactly what the model will compute)
        reserve  = ceil(y_v / factor)                  ->  factor * reserve >= y_v >= reserve

    so the achieved ratio lands in ``[1, factor]`` with no filtering, and ``reserve`` reaches one
    raw unit whenever ``y_v`` is small. States outside the band are the subject of their own
    properties below; mixing them in here would make every other assertion conditional.
    """
    leg = draw(quote_legs)
    quote = _quote_asset(leg)
    sqrt_price = draw(sqrt_prices)
    liquidity = draw(st.integers(min_value=1, max_value=10 ** 18))
    _asset_virtual, quote_virtual = virtual_reserves(liquidity, sqrt_price)
    assume(quote_virtual >= 1)

    factor = draw(understatement_factors)
    quote_reserve_raw = (quote_virtual + factor - 1) // factor

    return PricedPool(
        state=PoolState(
            address="0xv3",
            asset="0xa55e7",
            quote=quote.address,
            asset_reserve_raw=draw(st.integers(min_value=1, max_value=10 ** 24)),
            quote_reserve_raw=quote_reserve_raw,
            last_swap_block=18_000_000,
            last_swap_timestamp=1_695_000_000,
            fee_bps=draw(fee_bps),
            active_liquidity=liquidity,
            sqrt_price_x96=sqrt_price,
        ),
        quote=quote,
    )


@st.composite
def stale_liquidity_pools(draw):
    """A v3/v4 state whose liquidity read and reserve read disagree by more than the band allows.

    Built the other way round — reserve drawn, liquidity solved — because here the floors can only
    push the achieved ratio *further* out of the band, never back into it, so the construction
    needs no filter and no assumption. Every draw is a state the model must refuse.
    """
    leg = draw(quote_legs)
    quote = _quote_asset(leg)
    quote_reserve_raw = draw(
        st.one_of(raw_quote_units, whole_quote_units.map(lambda u: u * 10 ** leg[1]))
    )
    sqrt_price = draw(sqrt_prices)
    factor = draw(unsupported_factors)

    # L * sqrt > factor * real * Q96, so the floored y_v lands at or above factor * real.
    liquidity = (factor * quote_reserve_raw * Q96) // sqrt_price + 1

    return PricedPool(
        state=PoolState(
            address="0xstale",
            asset="0xa55e7",
            quote=quote.address,
            asset_reserve_raw=draw(st.integers(min_value=1, max_value=10 ** 24)),
            quote_reserve_raw=quote_reserve_raw,
            last_swap_block=18_000_000,
            last_swap_timestamp=1_695_000_000,
            fee_bps=draw(fee_bps),
            active_liquidity=liquidity,
            sqrt_price_x96=sqrt_price,
        ),
        quote=quote,
    )


any_pool = st.one_of(constant_product_pools(), concentrated_pools())


# -- the invariant the whole module rests on ------------------------------------


@DETERMINISTIC
@given(depth=positive_usd_micros, leader=usd_micros, small=usd_micros, extra=usd_micros)
def test_a_larger_order_never_gets_a_better_execution_price(depth, leader, small, extra):
    """Monotone non-decreasing in size, for every pool state and every leader clip.

    This is ``amm.py``'s own stated central invariant, and it is the one a plausible-looking
    implementation can violate without any hand-computed case noticing: a sign flip inside
    ``execution_price_ratio`` turns the ratio into a discount that *grows* with the order, which
    reads downstream as a large order executing better than a small one — free money, reported as
    a measurement.

    Exact, not approximate. Every step from ``s`` to the ratio is a rounding of a monotone
    function, and round-half-even is itself monotone, so the composition cannot invert.
    """
    x, a = usd(depth), usd(leader)
    smaller, larger = usd(small), usd(small + extra)

    assert execution_price_ratio(x, a, larger) >= execution_price_ratio(x, a, smaller)


@DETERMINISTIC
@given(depth=positive_usd_micros, size=usd_micros, small=usd_micros, extra=usd_micros)
def test_a_larger_leader_clip_never_gets_the_follower_a_better_price(depth, size, small, extra):
    """Monotone in the leader's clip too. The follower inherits a worse mid, never a better one."""
    x, s = usd(depth), usd(size)
    smaller, larger = usd(small), usd(small + extra)

    assert execution_price_ratio(x, larger, s) >= execution_price_ratio(x, smaller, s)


@DETERMINISTIC
@given(depth=positive_usd_micros, extra=usd_micros, leader=usd_micros, size=usd_micros)
def test_a_deeper_pool_never_gets_a_worse_price(depth, extra, leader, size):
    """Depth can only help. The ratio is a rounding of a monotone-decreasing function of ``x``."""
    thin, deep = usd(depth), usd(depth + extra)
    a, s = usd(leader), usd(size)

    assert execution_price_ratio(deep, a, s) <= execution_price_ratio(thin, a, s)


@DETERMINISTIC
@given(depth=positive_usd_micros, leader=usd_micros, size=usd_micros)
def test_the_execution_price_is_never_a_discount(depth, leader, size):
    """A ratio below 1 would be a negative execution cost — a subsidy, not a trade."""
    assert execution_price_ratio(usd(depth), usd(leader), usd(size)) >= 1


# -- the copier penalty ---------------------------------------------------------


@DETERMINISTIC
@given(depth=positive_usd_micros, leader=usd_micros, size=usd_micros)
def test_the_copier_penalty_is_never_negative(depth, leader, size):
    """The whole justification for evaluating ``2a + a^2 + as`` in closed form.

    ``copier_slippage - own_price_impact`` is algebraically identical and cancels two 38-digit
    quantities: with no leader it lands on ``-4.4E-38``, a negative execution cost, which reads
    downstream as a subsidy. The closed form is non-negative by construction and this asserts it
    over the whole space rather than at the one reference point.
    """
    assert copier_penalty(usd(depth), usd(leader), usd(size)) >= 0


@DETERMINISTIC
@given(depth=positive_usd_micros, size=usd_micros)
def test_no_leader_means_no_penalty(depth, size):
    """Zero penalty happens exactly when there was no leader to inherit a footprint from.

    The companion claim — with no leader, total slippage *is* the follower's own impact — holds
    only to the frozen precision, and the gap is the whole reason ``copier_penalty`` is evaluated
    in closed form instead of as ``copier_slippage - own_price_impact``. ``(1)(1 + s) - 1`` forms
    ``1 + s`` first, which discards the low digits of ``s``, and then takes the 1 back off; at
    ``x = $0.000003, s = $0.000001`` the round trip returns 37 digits of ``1/3`` where the direct
    division returns 38.

    **Tolerance, derived.** One ulp of ``1 + s`` at 38 significant digits, doubled for the two
    roundings and given a factor of ten of headroom — that is ``(1 + s) x 1E-36``. It scales with
    the intermediate rather than being a fixed absolute, because ``s`` here ranges over twelve
    orders of magnitude.
    """
    x, s = usd(depth), usd(size)
    slippage = average_slippage(x, s)
    ulps = mul(add(D("1"), slippage), D("1e-36"))

    assert copier_penalty(x, 0, s) == 0
    assert abs(sub(copier_slippage(x, 0, s), own_price_impact(x, s))) <= ulps


@DETERMINISTIC
@given(depth=positive_usd_micros, leader=positive_usd_micros, size=usd_micros)
def test_any_leader_at_all_costs_the_follower_something(depth, leader, size):
    """A positive clip always leaves a positive footprint: ``a(2 + a + s) > 0`` for ``a > 0``."""
    assert copier_penalty(usd(depth), usd(leader), usd(size)) > 0


@DETERMINISTIC
@given(depth=positive_usd_micros, small=usd_micros, extra=usd_micros)
def test_the_leader_side_of_the_split_is_the_expensive_one(depth, small, extra):
    """The double weight, as an exact inequality over the whole space.

        T(a,s) - T(s,a) = (2a + s + a^2 + as) - (2s + a + s^2 + as) = (a - s)(1 + a + s)

    which is non-negative whenever ``a >= s``. Exact under rounding as well as in the algebra:
    ``(1 + a + s)`` is symmetric in the two arguments, so the two computations differ only in the
    ordered factor ``(1 + a)`` against ``(1 + s)``, and every subsequent step is monotone.

    This is the claim §4.5 rests on — the leader's size hurts the follower roughly twice as much
    as the follower's own — stated in the direction that does not need a tolerance.
    """
    x = usd(depth)
    smaller, larger = usd(small), usd(small + extra)

    assert copier_slippage(x, larger, smaller) >= copier_slippage(x, smaller, larger)


@DETERMINISTIC
@given(depth=positive_usd_micros, leader=usd_micros, size=usd_micros)
def test_the_two_footprints_partition_the_copier_slippage(depth, leader, size):
    """``copier_slippage == own_price_impact + copier_penalty``, everywhere — not just at 5%/5%.

    The split is the module's entire product: "the copy lost 15%" is not actionable, "10.5 of
    those points were the leader's footprint and 5 were mine" is. If the two halves stopped adding
    up to the whole, the attribution would be arithmetic fiction.

    **Tolerance, derived.** The two sides are not the same sequence of operations.
    ``copier_slippage`` forms ``(1+a)(1+a+s) - 1``, which subtracts two quantities near 1 and so
    loses absolute precision to cancellation; the closed form never cancels. Sizes here are capped
    at the depth, so ``a, s <= 1`` and every intermediate is at most 6. At 38 significant digits
    one ulp of 6 is 6E-38, and the two sides together take fewer than ten rounded operations, so
    they cannot disagree by more than ~6E-37. The bound below is that, rounded up to the next
    power of ten. It is a statement about the frozen precision, not about the formula.
    """
    x = usd(depth)
    a = usd(min(leader, depth))
    s = usd(min(size, depth))

    exact = copier_slippage(x, a, s)
    recombined = add(own_price_impact(x, s), copier_penalty(x, a, s))

    assert abs(sub(exact, recombined)) <= D("1e-36")


@DETERMINISTIC
@given(depth=positive_usd_micros, size=usd_micros)
def test_marginal_impact_always_exceeds_what_the_trader_paid(depth, size):
    """``(1 + S/x)^2 - 1 >= S/x``. The gap *is* the copier penalty at equal size."""
    x, s = usd(depth), usd(size)
    assert marginal_impact(x, s) >= average_slippage(x, s)


@DETERMINISTIC
@given(leader=usd_micros, size=usd_micros, delta=usd_micros, s1=positive_usd_micros)
def test_the_linear_form_moves_twice_as_far_on_the_leaders_size(leader, size, delta, s1):
    """``(2L + C)/S1``: the same increment applied to ``L`` moves the number exactly twice as far
    as applied to ``C``. That visible factor of two is the linear form's only reason to exist.

    **Tolerance, derived.** Each side is a division and a multiplication at 38 significant digits,
    so each carries a few ulps of relative error, and the two sides are built from different
    numerators — they cannot agree bit for bit. The slack is therefore taken **relative to the
    quantities being differenced**, not to the base: with ``s1`` as small as $0.000003 the two
    moved values reach 1E+8 while the base is 0, and a slack scaled to the base would be a
    thousand times tighter than the arithmetic can deliver. 1E-30 relative is seven orders looser
    than an ulp and thirty orders tighter than the claim — a factor of two is not a 30th-digit
    effect.
    """
    unit = usd(s1)
    base = linear_copier_slippage(usd(leader), usd(size), unit)
    leader_moved = linear_copier_slippage(usd(leader + delta), usd(size), unit)
    copier_moved = linear_copier_slippage(usd(leader), usd(size + delta), unit)

    with localcontext(CALCULATION_CONTEXT):
        gap = +((leader_moved - base) - 2 * (copier_moved - base))
        scale = +(abs(base) + abs(leader_moved) + abs(copier_moved) + 1)
        slack = +(scale * D("1e-30"))

    assert abs(gap) <= slack


# -- depth measurement ----------------------------------------------------------


@DETERMINISTIC
@given(pool=any_pool)
def test_near_spot_depth_is_never_below_the_pools_own_reserve(pool):
    """The measured direction, asserted as a floor.

    TVL was measured to *understate* near-spot depth on concentrated pools by 5-23x and never to
    overstate it. A measurement below the real reserve would mean the model had drifted onto the
    other side of the evidence, which is a quarantine and not a number.
    """
    measurement = measure_depth(pool)

    assert measurement.effective_depth_usd >= measurement.quote_reserve_usd
    assert measurement.effective_depth_usd > 0


@DETERMINISTIC
@given(pool=any_pool)
def test_the_understatement_factor_is_none_for_constant_product_and_inside_the_band_otherwise(pool):
    """``None`` means "TVL and near-spot depth coincide by construction", and only that.

    It used to double as "the denominator was zero", which put a pool holding nothing and a pool
    where TVL *is* the depth on the same value with nothing downstream able to separate them.

    For a concentrated pool the factor is bounded on **both** sides. The upper bound is written as
    a literal rather than read from :data:`depth.MAX_TVL_UNDERSTATEMENT_FACTOR`, so that raising
    the constant fails here instead of moving with it.
    """
    measurement = measure_depth(pool)

    if measurement.model is DepthModel.CONSTANT_PRODUCT:
        assert measurement.tvl_understatement_factor is None
        assert measurement.virtual_quote_reserve_raw is None
    else:
        assert measurement.tvl_understatement_factor >= 1
        assert measurement.tvl_understatement_factor <= D("230")
        assert measurement.virtual_quote_reserve_raw > 0


@DETERMINISTIC
@given(pool=stale_liquidity_pools())
def test_a_liquidity_read_that_dwarfs_its_reserve_is_never_priced(pool):
    """The class the previous repair left open, over the whole of it.

    That repair refused ``real_usd <= 0`` — one point on an open ray. One raw unit to the right of
    it the reviewer's entire traced output came back verbatim: $5,000,000 of depth, a $50,000 band
    and $35,000 of copyable capacity against a pool holding a millionth of a dollar, at a ratio of
    5x10^12 that nothing bounded.

    What is generated here is every way of being out of band that the previous suite could not
    express: ratios from 231x to 5x10^12, reserves from a single raw unit to 10^6 whole units, all
    four quote legs at 6, 8 and 18 decimals, and square-root prices spanning twelve orders of
    magnitude. None of it may produce a number, and the refusal must be the typed one — a pool
    read at two different blocks is real chain data, not a programming error.
    """
    with pytest.raises(QuarantineRequired):
        measure_depth(pool)


@DETERMINISTIC
@given(pool=stale_liquidity_pools(), tier=tiers, aum=positive_usd_micros)
def test_an_out_of_band_pool_yields_no_capacity_through_any_entry_point(pool, tier, aum):
    """The consequence, not just the measurement. $35,000 of copyable order was the traced harm.

    ``copyable=False`` would not do here. A pool whose two readings disagree is not a pool that was
    measured and found too thin; it is a pool that was not measured at all, and the failure policy
    puts it in the reconciliation queue rather than in a results table with a reason string.
    """
    with pytest.raises(QuarantineRequired):
        size_to_cost_cap_detail(pool, tier, usd(aum), D("0"), D("0"))
    with pytest.raises(QuarantineRequired):
        quote_execution(pool, usd(aum))


@DETERMINISTIC
@given(leg=quote_legs, liquidity=st.integers(min_value=1, max_value=10 ** 24),
       sqrt_price=sqrt_prices)
def test_a_drained_pool_is_always_quarantined_never_priced(leg, liquidity, sqrt_price):
    """``quote_reserve_raw == 0`` is unsupported data on both branches, at every price.

    The old concentrated guard was ``virtual_usd < real_usd``, which cannot fire when ``real_usd``
    is zero — so a pool holding $0 of the quote asset, carrying stale liquidity, was priced off
    its virtual reserves alone and produced executable capacity. The constant-product branch
    refused the identical input. The property is that the *pool* decides, not the branch.

    This pins the single point ``raw == 0``. The rest of the ray it sits on — every reserve too
    small for the liquidity read against it — is
    :func:`test_a_liquidity_read_that_dwarfs_its_reserve_is_never_priced`, and the reserves that
    are small but *consistent*, which must still be priced, are the property below.
    """
    quote = _quote_asset(leg)
    base = dict(
        address="0xdrained",
        asset="0xa55e7",
        quote=quote.address,
        asset_reserve_raw=10 ** 24,
        quote_reserve_raw=0,
        last_swap_block=18_000_000,
        last_swap_timestamp=1_695_000_000,
        fee_bps=30,
    )

    for extra in ({}, {"active_liquidity": liquidity, "sqrt_price_x96": sqrt_price}):
        state = PoolState(**dict(base, **extra))
        with pytest.raises(QuarantineRequired):
            measure_depth(PricedPool(state=state, quote=quote))


@DETERMINISTIC
@given(leg=quote_legs, raw=raw_quote_units, factor=st.integers(min_value=1, max_value=230))
def test_a_reserve_below_one_whole_unit_is_still_a_measurement(leg, raw, factor):
    """The control on the fix: *small* is not the dangerous condition, *inconsistent* is.

    A guard written against a floor on the reserve — "quarantine anything under a dollar", "under
    a whole unit" — would close the traced case and take every sub-dollar pool out of the
    population with it, for a reason the study never pre-registered and in the direction that
    flatters coverage. So the refusal has to be tested from both sides, and this is the side that
    must keep working: one raw unit of reserve, a liquidity read that agrees with it, and a real,
    tiny depth as the answer.

    At ``sqrt_price_x96 = Q96`` the raw price is one and ``y_v = L`` exactly, so setting
    ``L = factor * raw`` makes the ratio exactly ``factor`` with no flooring anywhere.
    """
    quote = _quote_asset(leg)
    state = PoolState(
        address="0xthin",
        asset="0xa55e7",
        quote=quote.address,
        asset_reserve_raw=10 ** 24,
        quote_reserve_raw=raw,
        last_swap_block=18_000_000,
        last_swap_timestamp=1_695_000_000,
        fee_bps=30,
        active_liquidity=factor * raw,
        sqrt_price_x96=Q96,
    )
    measurement = measure_depth(PricedPool(state=state, quote=quote))

    assert measurement.tvl_understatement_factor == D(factor)
    assert measurement.quote_reserve_usd > 0
    assert measurement.effective_depth_usd == mul(measurement.quote_reserve_usd, factor)


@DETERMINISTIC
@given(leg=quote_legs, units=whole_quote_units, sqrt_price=sqrt_prices,
       shortfall=st.integers(min_value=1, max_value=99))
def test_virtual_depth_below_the_real_reserve_is_quarantined(leg, units, sqrt_price, shortfall):
    """The other side of the same line: the one direction the measured evidence rules out.

    ``shortfall`` percent below the real reserve. Either the sqrt-price orientation is inverted
    for this pool or the reserves and the liquidity were read at different blocks — both are real
    inputs the model does not support.
    """
    quote = _quote_asset(leg)
    quote_reserve_raw = units * 10 ** leg[1]
    assume(quote_reserve_raw * (100 - shortfall) // 100 >= 1)

    target = quote_reserve_raw * (100 - shortfall) // 100
    liquidity = (target * Q96) // sqrt_price
    assume(liquidity >= 1)
    assume(liquidity * sqrt_price // Q96 < quote_reserve_raw)

    state = PoolState(
        address="0xinverted",
        asset="0xa55e7",
        quote=quote.address,
        asset_reserve_raw=10 ** 24,
        quote_reserve_raw=quote_reserve_raw,
        last_swap_block=18_000_000,
        last_swap_timestamp=1_695_000_000,
        fee_bps=30,
        active_liquidity=liquidity,
        sqrt_price_x96=sqrt_price,
    )
    with pytest.raises(QuarantineRequired):
        measure_depth(PricedPool(state=state, quote=quote))


@DETERMINISTIC
@given(liquidity=st.integers(min_value=1, max_value=10 ** 30), sqrt_price=sqrt_prices)
def test_the_quote_leg_is_the_one_that_grows_with_the_price(liquidity, sqrt_price):
    """``x_v = L/sqrt(P)``, ``y_v = L*sqrt(P)`` — so which is which is decided by the price.

    Above ``Q96`` the asset is worth more than one raw quote unit and the quote-side reserve is
    the larger of the two; below it, the smaller. That is the whole content of the orientation
    convention the module's docstring concedes ``contracts.PoolState`` does not pin, and at
    ``sqrt_price_x96 = Q96`` — the value every hand-computed fixture uses — the two coincide and
    it cannot be observed at all.

    The second assertion is the pool's own invariant: the product of the virtual reserves is
    ``L^2``, at or below it after flooring, never above.
    """
    asset_virtual, quote_virtual = virtual_reserves(liquidity, sqrt_price)

    assert (quote_virtual >= asset_virtual) == (sqrt_price >= Q96)
    assert asset_virtual * quote_virtual <= liquidity * liquidity


@DETERMINISTIC
@given(leg=quote_legs, raw=st.integers(min_value=0, max_value=10 ** 30),
       multiplier=st.integers(min_value=1, max_value=10 ** 6))
def test_depth_scales_with_the_quote_assets_price(leg, raw, multiplier):
    """``raw_to_usd`` is homogeneous of degree one in ``usd_price``. Deleting the factor is not.

    Every hand-computed fixture quotes in a $1.00 stablecoin, where ``* quote.usd_price`` is
    multiplication by one and its absence is invisible. WETH and WBTC are both §4.6 quote assets
    and both quote exactly the volatile pairs this experiment is about; a pool holding 400 WETH
    would be measured at $400 of depth and declared uncopyable at every capital level.
    """
    address, decimals, price = leg
    scaled_price = mul(price, multiplier)
    unit_priced = QuoteAsset(address=address, decimals=decimals, usd_price=D("1"))
    scaled = QuoteAsset(address=address, decimals=decimals, usd_price=scaled_price)

    assert raw_to_usd(raw, scaled) == mul(raw_to_usd(raw, unit_priced), scaled_price)


# -- the validity band ----------------------------------------------------------


@DETERMINISTIC
@given(pool=concentrated_pools())
def test_the_band_opens_at_one_percent_of_the_measured_depth(pool):
    """The band edge is a fact about the model, not about the pool: 1% of near-spot depth.

    The 1% is written here as a literal rather than taken from
    :data:`depth.CONCENTRATED_BAND_MAX_SLIPPAGE`, so that widening the constant fails this test
    instead of moving with it. A band that follows its own constant is not a pinned band.
    """
    measurement = measure_depth(pool)
    band = measurement.validity_band

    assert CONCENTRATED_BAND_MAX_SLIPPAGE == D("0.01")
    assert band.max_own_slippage == D("0.01")
    assert band.max_size_usd == mul(measurement.effective_depth_usd, D("0.01"))
    assert measurement.s1_usd == band.max_size_usd
    assert band.contains(band.max_size_usd)
    assert not band.contains(add(band.max_size_usd, D("0.000001")))


@DETERMINISTIC
@given(pool=concentrated_pools())
def test_a_size_past_the_band_is_refused_rather_than_extrapolated(pool):
    """Refusal, not a number. Past ~1% the price leaves the active tick range, and the measured
    10%/1% size ratios were 7.6x and 507x against the model's 10x — two orders of magnitude apart,
    so no correction factor exists to extrapolate with."""
    band = measure_depth(pool).validity_band

    with pytest.raises(OutsideValidityBand):
        quote_execution(
            pool, add(band.max_size_usd, D("0.000001")), allow_partial_fill=False
        )


@DETERMINISTIC
@given(pool=constant_product_pools(), size=positive_usd_micros)
def test_constant_product_imposes_no_ceiling_of_its_own(pool, size):
    """x*y=k is exact at every size; the cost cap and not the model is what bounds the order."""
    band = measure_depth(pool).validity_band

    assert band.max_size_usd is None
    assert band.contains(usd(size))


# -- sizing to the cost cap -----------------------------------------------------


@DETERMINISTIC
@given(pool=any_pool, tier=tiers, aum=positive_usd_micros, leader_share=st.integers(0, 100),
       gas=st.integers(min_value=0, max_value=200_000_000))
def test_a_sized_order_always_honours_the_cap_it_claims_to_respect(
    pool, tier, aum, leader_share, gas
):
    """Everything the sizing search promises, over the whole generated space.

    A pool too thin for any order is a *measured* outcome and must be reported as
    ``copyable=False`` with a reason — never raised, and never as a silent zero that a reader
    could mistake for the §9.5 long-tail finding.
    """
    cap = cost_cap_for(tier)
    band = measure_depth(pool).validity_band
    capital = usd(aum)

    # The leader has to be inside the band before a follower can be priced at all, so it is drawn
    # as a share of whatever ceiling this pool has rather than independently.
    ceiling = band.max_size_usd
    reference = capital if ceiling is None else ceiling
    leader = divide(mul(reference, leader_share), 100)

    result = size_to_cost_cap_detail(pool, tier, capital, leader, usd(gas))

    if result.copyable:
        assert result.order_usd > 0
        assert result.order_usd <= capital
        assert result.execution_cost_pct <= cap
        assert result.rejection_reason is None
        assert result.follower_return is not None
        if ceiling is not None:
            assert result.order_usd <= add(sub(ceiling, leader), D("0.000001"))
    else:
        assert result.order_usd == 0
        assert result.follower_return is None
        assert result.rejection_reason


@DETERMINISTIC
@given(pool=any_pool, tier=tiers, aum=positive_usd_micros)
def test_the_seam_view_reports_the_capital_as_intent_and_the_order_as_fill(pool, tier, aum):
    """§4.5's ``min(cost-cap size, strategy_aum)``: intent is the capital brought to the buy, and
    the filled amount is what the pool could actually take of it. Reading those two fields the
    other way round would turn capital absorption into a number about nothing."""
    capital = usd(aum)
    detail = size_to_cost_cap_detail(pool, tier, capital, D("0"), D("0"))
    simulation = detail.simulation

    assert simulation.intended_order_usd == capital
    assert simulation.filled_order_usd == detail.order_usd
    assert simulation.copyable is detail.copyable


@DETERMINISTIC
@given(pool=any_pool, tier=tiers, aum=positive_usd_micros,
       gas=st.integers(min_value=0, max_value=200_000_000))
def test_sizing_is_a_pure_function_of_its_arguments(pool, tier, aum, gas):
    """Same inputs, byte-identical output. A bisection that depended on ambient state would be
    unreproducible by the Independent Validator, which is the one thing §9 forbids outright."""
    args = (pool, tier, usd(aum), D("0"), usd(gas))
    first = size_to_cost_cap_detail(*args).simulation
    second = size_to_cost_cap_detail(*args).simulation

    assert to_canonical_json(first) == to_canonical_json(second)


# -- order book -----------------------------------------------------------------


@st.composite
def order_books(draw):
    decimals = draw(st.sampled_from((6, 8, 18)))
    count = draw(st.integers(min_value=1, max_value=6))
    price = draw(st.integers(min_value=1, max_value=10 ** 6))
    levels = []
    for _ in range(count):
        levels.append(
            OrderBookLevel(
                price_usd=divide(price, 100),
                quantity_raw=draw(st.integers(min_value=1, max_value=10 ** 6)) * 10 ** decimals,
            )
        )
        price += draw(st.integers(min_value=1, max_value=10 ** 4))
    return OrderBook(asset_decimals=decimals, levels=tuple(levels))


@DETERMINISTIC
@given(book=order_books(), size=positive_usd_micros)
def test_the_book_is_never_extrapolated_past_its_last_level(book, size):
    """Whatever the book cannot supply is a measured shortfall, never a price."""
    fill = walk_order_book(book, usd(size))

    assert fill.filled_usd <= fill.requested_usd
    assert fill.filled_usd <= book.capacity_usd()
    assert fill.levels_consumed <= len(book.levels)
    assert fill.fills == (fill.fill_ratio >= MIN_FILL_RATIO)
    assert (fill.vwap_usd is None) == (fill.acquired_raw == 0)


@DETERMINISTIC
@given(book=order_books(), size=positive_usd_micros)
def test_walking_the_book_never_beats_the_best_resting_price(book, size):
    """The VWAP is a weighted average of the levels actually consumed, so it cannot fall below the
    cheapest of them.

    **Tolerance, derived.** When a single level is partly consumed the VWAP is that level's price
    recovered through a multiply and a divide, so it can sit one or two units in the 38th
    significant digit either side of it. The bound is that, not the ~1e-21 relative effect the
    module attributes to flooring — flooring moves the VWAP *between* two real level prices and
    can never take it below the first.
    """
    fill = walk_order_book(book, usd(size))
    assume(fill.acquired_raw > 0)

    assert fill.slippage_pct >= D("-1e-36")
    assert fill.vwap_usd >= sub(book.best_price_usd, mul(book.best_price_usd, D("1e-36")))


@DETERMINISTIC
@given(book=order_books(), size=positive_usd_micros, extra=usd_micros)
def test_a_larger_order_never_acquires_less(book, size, extra):
    """Monotone in the request. A bigger order cannot come back with fewer tokens."""
    smaller = walk_order_book(book, usd(size))
    larger = walk_order_book(book, usd(size + extra))

    assert larger.acquired_raw >= smaller.acquired_raw
    assert larger.filled_usd >= smaller.filled_usd


# -- choosing a public source ---------------------------------------------------


@st.composite
def execution_sources(draw, count=None):
    n = count if count is not None else draw(st.integers(min_value=1, max_value=6))
    sources = []
    for i in range(n):
        sources.append(
            ExecutionSource(
                name="src_{}".format(i),
                total_cost_pct=divide(draw(st.integers(min_value=0, max_value=10 ** 5)), 10 ** 6),
                fill_ratio=divide(draw(st.integers(min_value=0, max_value=100)), 100),
                is_private=draw(st.booleans()),
            )
        )
    return tuple(sources)


@DETERMINISTIC
@given(sources=execution_sources())
def test_the_chosen_route_is_the_cheapest_public_one_that_fills(sources):
    """§9.4, as three separate claims that a single-candidate test cannot separate.

    With one surviving candidate ``min`` and ``max`` are the same function, which is why the
    direction of the choice was unasserted: a one-character flip would underwrite every trade at
    the *most expensive* public route and no test in the repository would notice.
    """
    public = [s for s in sources if not s.is_private]
    assume(public)

    chosen = best_public_execution(sources)
    fillable = [s for s in public if s.fill_ratio >= MIN_FILL_RATIO]

    if not fillable:
        assert chosen is None
        return

    assert chosen is not None
    assert chosen.is_private is False
    assert chosen.fill_ratio >= MIN_FILL_RATIO
    for candidate in fillable:
        assert chosen.total_cost_pct <= candidate.total_cost_pct


@DETERMINISTIC
@given(sources=execution_sources())
def test_the_route_does_not_depend_on_the_order_the_sources_arrived_in(sources):
    """Determinism across runs and machines: ties are broken by name, never by input order."""
    assume(any(not s.is_private for s in sources))

    forward = best_public_execution(sources)
    backward = best_public_execution(tuple(reversed(sources)))

    assert (forward is None) == (backward is None)
    if forward is not None:
        assert forward.name == backward.name
