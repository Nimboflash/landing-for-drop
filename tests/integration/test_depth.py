"""One leader trade, one pool, four capital levels — the way the pipeline will run ``depth``.

The pool is deliberately the shape the hand-computed file never uses: a concentrated WETH-quoted
v3 pool at a square-root price other than one. That is not decoration. Every fixture in
``tests/hand_computed/test_depth.py`` quotes in USDC at exactly $1.00 with six decimals and sets
``sqrt_price_x96 = Q96``, a corner of the input space where the USD price factor is multiplication
by one and the two virtual reserves are identically equal — so two of the module's conversions are
unobservable there and were, until this file, unobservable everywhere.

    real reserve      400 WETH at $2,500        =  $1,000,000     (what TVL would report)
    sqrt_price_x96    2 x Q96                   ->  raw price 4
    active liquidity  10^21                     ->  y_v = 2L = 2,000 WETH = $5,000,000
    understatement    5,000,000 / 1,000,000     =  5x            (inside the measured 5-23x)
    validity band     1% of $5,000,000          =  $50,000       (and S1 is the same number)
    fee               30 bps

Every expectation below is derived from those six lines and written as a literal. Where a value
has no exact decimal form the rational it comes from is named — ``-1/101``, ``24,995,000/1,001`` —
and the assertion is made against that rational to the frozen precision, not against a re-run of
the implementation's own expression.
"""

from decimal import Decimal

import pytest

from contracts import (
    WETH,
    AssetTier,
    PoolState,
    QuarantineRequired,
    artifact_envelope,
    canonical_hash,
    divide,
    to_canonical_json,
)
from depth import (
    MEASURED_PEPE_1PCT_ROUTED_USD,
    MEASURED_PEPE_1PCT_SINGLE_POOL_USD,
    MEASURED_TVL_UNDERSTATEMENT,
    MIN_FILL_RATIO,
    Q96,
    DepthModel,
    ExecutionSource,
    OrderBook,
    OrderBookLevel,
    PricedPool,
    PrivateLiquidityExcluded,
    QuoteAsset,
    best_public_execution,
    measure_depth,
    public_sources,
    size_to_cost_cap,
    size_to_cost_cap_detail,
    walk_order_book,
)

D = Decimal

#: 18 decimals and $2,500 — neither of which the hand-computed fixtures exercise.
WETH_QUOTE = QuoteAsset(address=WETH, decimals=18, usd_price=D("2500"))

TOKEN = "0xdegen"
WINDOW_END_BLOCK = 18_500_000
WINDOW_END_TS = 1_697_500_000

#: 400 WETH. At $2,500 that is $1,000,000 of real quote-side reserve.
REAL_QUOTE_RAW = 400 * 10 ** 18

#: y_v = L * sqrt(P) = 2L = 2,000 WETH = $5,000,000 of near-spot depth.
ACTIVE_LIQUIDITY = 10 ** 21
SQRT_PRICE = 2 * Q96

NEAR_SPOT_DEPTH_USD = D("5000000")
BAND_USD = D("50000")

#: §4.5's four capital levels for this scenario, from a retail follower to a fund.
CAPITAL_LADDER = (D("1000"), D("10000"), D("100000"), D("1000000"))


def live_pool(fee_bps=30, quote_reserve_raw=REAL_QUOTE_RAW, active_liquidity=ACTIVE_LIQUIDITY):
    return PricedPool(
        state=PoolState(
            address="0xv3wethdegen",
            asset=TOKEN,
            quote=WETH,
            asset_reserve_raw=4 * 10 ** 26,
            quote_reserve_raw=quote_reserve_raw,
            last_swap_block=WINDOW_END_BLOCK - 3,
            last_swap_timestamp=WINDOW_END_TS - 40,
            fee_bps=fee_bps,
            active_liquidity=active_liquidity,
            sqrt_price_x96=SQRT_PRICE,
        ),
        quote=WETH_QUOTE,
    )


def drained_pool():
    """The same pool after its quote side is emptied, with the liquidity read left stale."""
    return live_pool(quote_reserve_raw=0)


# -- the measurement the whole scenario rests on --------------------------------


def test_the_pool_measures_at_five_million_of_near_spot_depth():
    """400 WETH of reserve, 2,000 WETH of virtual reserve, and the 5x that separates them.

        real     400 x 10^18 raw / 10^18 x $2,500  =  $1,000,000
        y_v      L * sqrt(P) = 2 x 10^21 raw       =  2,000 WETH  =  $5,000,000
        x_v      L / sqrt(P) = 5 x 10^20 raw
        x_v y_v  = 10^42 = L^2                                     (the pool's own invariant)
        band     1% of $5,000,000                 =  $50,000

    Both conversions that the hand-computed fixtures cannot see are load-bearing here: at $1.00
    the depth would read $2,000 instead of $5,000,000, and with the two virtual reserves swapped
    it would read $1,250,000.
    """
    measurement = measure_depth(live_pool())

    assert measurement.model is DepthModel.CONCENTRATED_VIRTUAL_RESERVES
    assert measurement.quote_reserve_usd == D("1000000")
    assert measurement.virtual_quote_reserve_raw == 2 * 10 ** 21
    assert measurement.effective_depth_usd == NEAR_SPOT_DEPTH_USD
    assert measurement.tvl_understatement_factor == D("5")
    assert measurement.s1_usd == BAND_USD
    assert measurement.validity_band.max_size_usd == BAND_USD

    low, high = MEASURED_TVL_UNDERSTATEMENT
    assert low <= measurement.tvl_understatement_factor <= high


# -- the capital ladder, with no leader in front --------------------------------


def test_the_capital_ladder_shows_where_each_constraint_binds():
    """§4.5's ``min(cost-cap size, strategy_aum)``, walked from $1,000 to $1,000,000.

    Major cap 1%, fee 0.3%, so 0.7% of the $5,000,000 depth — $35,000 — is the largest order the
    cap allows. Below that the follower's own capital is what binds; above it the pool is.

        $1,000      impact 1,000/5,000,000   = 0.02%   total 0.32%   binds: strategy_aum
        $10,000     impact 10,000/5,000,000  = 0.20%   total 0.50%   binds: strategy_aum
        $100,000    capped at $35,000        = 0.70%   total 1.00%   binds: cost_cap
        $1,000,000  capped at $35,000        = 0.70%   total 1.00%   binds: cost_cap

    The last row is the finding this ladder exists to produce: a fund-sized follower deploys 3.5%
    of its capital into this signal, and the other 96.5% has nowhere to go at an acceptable cost.
    """
    expected = (
        (D("1000"), D("1000"), "strategy_aum", D("0.0032"), D("1")),
        (D("10000"), D("10000"), "strategy_aum", D("0.005"), D("1")),
        (D("100000"), D("35000"), "cost_cap", D("0.01"), D("0.35")),
        (D("1000000"), D("35000"), "cost_cap", D("0.01"), D("0.035")),
    )

    for capital, order, binding, cost, absorption in expected:
        result = size_to_cost_cap_detail(
            live_pool(), AssetTier.MAJOR, capital, D("0"), D("0")
        )

        assert result.copyable is True
        assert result.order_usd == order
        assert result.binding_constraint == binding
        assert result.execution_cost_pct == cost
        assert result.capital_absorption == absorption
        assert result.pool_depth_at_trade_usd == NEAR_SPOT_DEPTH_USD
        assert result.s1_at_trade_usd == BAND_USD


def test_the_execution_drag_at_each_rung_is_the_reciprocal_of_its_cost():
    """With the leader's own edge at zero, the follower's return is ``1/(1 + cost) - 1``.

    Each is a repeating decimal, so each is named by the rational it comes from rather than by a
    re-run of the implementation's expression::

        cost 0.32%   ->  -0.0032/1.0032  =  -2/627
        cost 0.50%   ->  -0.005/1.005    =  -1/201
        cost 1.00%   ->  -0.01/1.01      =  -1/101

    The comparison is to 36 significant digits and not to 38. The frozen policy rounds
    operation by operation — divide, then subtract — and that composition lands one unit in the
    39th digit away from the same rational rounded once. Pinning the rational is the claim;
    pinning the 39th digit would only pin the order of the two operations.
    """
    drags = (
        (D("1000"), -2, 627),
        (D("10000"), -1, 201),
        (D("100000"), -1, 101),
        (D("1000000"), -1, 101),
    )

    for capital, numerator, denominator in drags:
        simulation = size_to_cost_cap(
            live_pool(), AssetTier.MAJOR, capital, D("0"), D("0")
        )
        exact = divide(D(numerator), D(denominator))

        assert simulation.follower_return < 0
        assert abs(simulation.follower_return - exact) <= D("1e-36")


def test_a_leader_edge_survives_the_drag_at_every_rung():
    """A 20% leader return at 1% execution cost still leaves 18.8% — deflated, not erased.

    ``1.20/1.01 - 1 = 19/101``, which is what §4.5 means by copying being economically viable at
    this depth. The rows where the follower's own capital binds cost less and keep more.
    """
    nineteen_over_101 = divide(D("19"), D("101"))
    previous = None

    for capital in CAPITAL_LADDER:
        simulation = size_to_cost_cap(
            live_pool(), AssetTier.MAJOR, capital, D("0"), D("0"), leader_return=D("0.20")
        )
        assert D("0.18") < simulation.follower_return < D("0.20")
        if previous is not None:
            # More capital never buys a better per-dollar outcome: the order grows into the pool.
            assert simulation.follower_return <= previous
        previous = simulation.follower_return

    assert abs(previous - nineteen_over_101) <= D("1e-36")


# -- the same ladder with a leader in front -------------------------------------


def test_a_leader_clip_takes_the_follower_size_down_by_a_third():
    """Leader clips $5,000 into $5,000,000 of depth, so ``a = 0.1%``.

        footprint  2a + a^2      = 0.002 + 0.000001      = 0.2001pp
        budget     1% - 0.3% - 0.2001%                   = 0.4999pp
        marginal   (1 + a)/x     = 1.001/5,000,000
        size       0.004999 x 5,000,000 / 1.001          = 24,995,000/1,001

    ``24,995,000/1,001 = 24,970 + 30/1,001``, and ``30/1,001`` repeats on the six-digit block
    ``029970``. So the same pool that took $35,000 with an empty book in front of it takes
    $24,970.03 once a leader has moved the price — a 28.7% reduction for a clip one seventh the
    follower's own size. That asymmetry is the double weight, in dollars.
    """
    result = size_to_cost_cap_detail(
        live_pool(), AssetTier.MAJOR, D("100000"), D("5000"), D("0")
    )
    exact = divide(D("24995000"), D("1001"))

    assert result.copyable is True
    assert abs(result.order_usd - exact) <= D("0.000001")
    assert result.binding_constraint == "cost_cap"
    assert result.execution_cost_pct <= D("0.01")

    # The two footprints, itemised. 0.3pp of fee + 0.2006pp inherited + 0.4994pp own = 1.00pp.
    assert result.costs.dex_fee_pct == D("0.003")
    assert abs(result.costs.copier_penalty_pct - D("0.002005994005994006")) <= D("1e-15")
    assert abs(result.costs.price_impact_pct - D("0.004994005994005994")) <= D("1e-15")
    assert result.costs.liquidity_limitation_pct == 0


def test_a_leader_clip_that_consumes_the_budget_is_reported_and_never_raised():
    """Leader clips $25,000 (``a = 0.5%``): footprint ``2a + a^2`` = 1.0025pp against a 1pp cap.

    This is the exact shape of the measured §9.5 long-tail result — "the leader's own footprint
    consumes the entire slippage budget before a single copier trades". It is a **finding**, so it
    is reported as ``copyable=False`` with a reason at every capital level and must never raise.
    An exception here would remove the row from the results table instead of putting a zero in it.
    """
    for capital in CAPITAL_LADDER:
        simulation = size_to_cost_cap(
            live_pool(), AssetTier.MAJOR, capital, D("25000"), D("0")
        )

        assert simulation.copyable is False
        assert simulation.filled_order_usd == 0
        assert simulation.intended_order_usd == capital
        assert simulation.follower_return is None
        assert "1.0025pp" in simulation.rejection_reason
        assert "footprint" in simulation.rejection_reason


def test_the_mid_cap_cap_is_what_makes_that_same_leader_copyable():
    """The 2% mid-cap cap leaves 0.7975pp after the fee and the 1.0025pp footprint.

        size = 0.007975 x 5,000,000 / 1.005 = 39,875,000/1,005 = 39,676.61...

    but the validity band stops at $50,000 and the leader has already taken $25,000 of it, so the
    band ceiling of $25,000 binds first. The model's limit, not the cap, is what sizes this order
    — and the result says so rather than leaving a reader to infer it.
    """
    result = size_to_cost_cap_detail(
        live_pool(), AssetTier.MID_CAP, D("100000"), D("25000"), D("0")
    )

    assert result.copyable is True
    assert result.order_usd == D("25000")
    assert result.binding_constraint == "validity_band"
    assert result.execution_cost_pct <= D("0.02")


# -- a drained pool in the middle of a portfolio --------------------------------


def test_a_drained_pool_stops_the_run_instead_of_contributing_capacity():
    """The same pool with its quote side emptied and the liquidity read left stale.

    Before the fix this produced $5,000,000 of effective depth and a $35,000 copyable order
    against a pool holding $0 of WETH — a number with no reserve behind it, sitting in a capacity
    table looking exactly like the healthy rows above. The guard was ``virtual_usd < real_usd``,
    which cannot fire when the real reserve is zero.

    Walked as a portfolio, because that is how it will happen: three pools, one of them drained,
    and the run must end with two measurements and one quarantine record — never with three
    measurements.
    """
    portfolio = (live_pool(), drained_pool(), live_pool(fee_bps=100))

    measured = []
    quarantined = []
    for pool in portfolio:
        try:
            measured.append(measure_depth(pool))
        except QuarantineRequired as refusal:
            quarantined.append((pool.state.address, str(refusal)))

    assert len(measured) == 2
    assert len(quarantined) == 1
    assert "no quote-side reserve" in quarantined[0][1]
    assert all(m.effective_depth_usd == NEAR_SPOT_DEPTH_USD for m in measured)

    with pytest.raises(QuarantineRequired):
        size_to_cost_cap(drained_pool(), AssetTier.MAJOR, D("100000"), D("0"), D("0"))


def test_a_nearly_drained_pool_stops_the_run_on_the_same_terms():
    """The pool one raw unit before empty, which the ``real_usd <= 0`` guard priced in full.

    A withdrawal takes the quote side from 400 WETH to 0.04 WETH while the liquidity snapshot is
    still the one read three blocks ago:

        real     4 x 10^16 raw / 10^18 x $2,500   =  $100
        y_v      unchanged at 2 x 10^21 raw       =  $5,000,000
        factor   5,000,000 / 100                  =  50,000x

    50,000x against a measured band of 5-23x. This is the whole of the previous repair's blind
    spot in one row: it refused the pool at exactly zero and priced this one — a pool holding one
    hundred dollars — at $5,000,000 of depth, a $50,000 band and the same $35,000 copyable order
    the healthy rows produce. Nothing about ``real_usd <= 0`` could see it, because there is no
    value of the reserve at which the harm switches on; there is only a ratio.
    """
    stale = live_pool(quote_reserve_raw=4 * 10 ** 16)

    with pytest.raises(QuarantineRequired) as excinfo:
        measure_depth(stale)
    message = str(excinfo.value)
    assert "230" in message
    assert "reconciliation queue" in message

    with pytest.raises(QuarantineRequired):
        size_to_cost_cap(stale, AssetTier.MAJOR, D("100000"), D("0"), D("0"))


def test_the_portfolio_keeps_the_pools_whose_two_readings_agree():
    """The band is two-sided, so the run has to be checked from both sides on the same portfolio.

    Four pools, walked as one run: the healthy 5x, a 230x that sits exactly on the ceiling, a
    231x one step past it, and the drained one. Two measurements, two quarantine records. A fix
    that closed the class by tightening until everything refused would show up here as four
    quarantines and no capacity at all.

        L = 4.6 x 10^22   ->  y_v = 2L = 9.2 x 10^22 raw  =  92,000 WETH  =  $230,000,000  = 230x
        L = 4.62 x 10^22  ->  y_v =      9.24 x 10^22 raw =  92,400 WETH  =  $231,000,000  = 231x
    """
    at_ceiling = live_pool(active_liquidity=46 * 10 ** 21)
    past_ceiling = live_pool(active_liquidity=462 * 10 ** 20)
    portfolio = (live_pool(), at_ceiling, past_ceiling, drained_pool())

    measured, quarantined = [], []
    for pool in portfolio:
        try:
            measured.append(measure_depth(pool))
        except QuarantineRequired as refusal:
            quarantined.append(str(refusal))

    assert len(measured) == 2
    assert len(quarantined) == 2
    assert measured[0].tvl_understatement_factor == D("5")
    assert measured[1].tvl_understatement_factor == D("230")
    assert measured[1].effective_depth_usd == D("230000000")
    assert measured[1].validity_band.max_size_usd == D("2300000")


# -- order-book depth, and choosing between the two -----------------------------


def book():
    """A public ask side for the same token: 200 units at each of $50.00, $50.50, $51.00.

    Capacity 200x50 + 200x50.50 + 200x51 = $10,000 + $10,100 + $10,200 = $30,300.
    """
    return OrderBook(
        asset_decimals=18,
        levels=(
            OrderBookLevel(price_usd=D("50"), quantity_raw=200 * 10 ** 18),
            OrderBookLevel(price_usd=D("50.50"), quantity_raw=200 * 10 ** 18),
            OrderBookLevel(price_usd=D("51"), quantity_raw=200 * 10 ** 18),
        ),
    )


def test_the_book_and_the_pool_are_both_walked_for_the_same_order():
    """Addendum §9.6 requires *both* AMM depth and order-book depth to be considered.

        $20,100 -> 200 units at $50 + 200 at $50.50 -> 400 units, VWAP $50.25
        slippage 50.25/50 - 1 = 0.5%, against the pool's 1.0% for its own largest order

    So for this size the public book is the better route and the pool is not — a conclusion that
    only exists because both were measured.
    """
    fill = walk_order_book(book(), D("20100"))

    assert book().capacity_usd() == D("30300")
    assert fill.filled_usd == D("20100")
    assert fill.acquired_raw == 400 * 10 ** 18
    assert fill.vwap_usd == D("50.25")
    assert fill.slippage_pct == D("0.005")
    assert fill.levels_consumed == 2
    assert fill.fills is True


def test_the_book_cannot_underwrite_the_order_the_pool_can():
    """$40,400 against $30,300 of resting book: 75% filled, and 75% is not a fill.

    The shortfall is recorded as a quantity — ``unfilled_share`` — and never folded into a price.
    Extending the book past its last level would turn a liquidity limitation into a slippage
    number, which is the single easiest way to publish the 240x overstatement §9.4 exists to
    prevent: PEPE at 1% size measured $471 single-pool against $114,000 routed.
    """
    fill = walk_order_book(book(), D("40400"))

    assert fill.filled_usd == D("30300")
    assert fill.fill_ratio == D("0.75")
    assert fill.unfilled_share == D("0.25")
    assert fill.fills is False
    assert fill.levels_consumed == 3
    assert MEASURED_PEPE_1PCT_ROUTED_USD > MEASURED_PEPE_1PCT_SINGLE_POOL_USD * 200


def test_the_route_is_the_cheapest_public_one_and_the_rfq_is_excluded():
    """Three costed routes, one of them private. §9.4 takes the cheapest of the other two.

        amm_single_pool     1.0%   from the $35,000 sizing above
        public_order_book   0.5%   from the $20,100 walk above
        rfq_market_maker    0.1%   private — cannot be relied on by a latency-sensitive follower

    The private route is the cheapest and loses anyway. Both surviving candidates fill, so
    nothing but the cost ordering decides between them, which is what makes this the case that
    distinguishes "cheapest" from "most expensive" at all.
    """
    amm = size_to_cost_cap_detail(live_pool(), AssetTier.MAJOR, D("100000"), D("0"), D("0"))
    fill = walk_order_book(book(), D("20100"))

    routes = (
        ExecutionSource("amm_single_pool", total_cost_pct=amm.execution_cost_pct,
                        fill_ratio=D("1")),
        ExecutionSource("public_order_book", total_cost_pct=fill.slippage_pct,
                        fill_ratio=fill.fill_ratio),
        ExecutionSource("rfq_market_maker", total_cost_pct=D("0.001"), fill_ratio=D("1"),
                        is_private=True),
    )

    assert len(public_sources(routes)) == 2

    chosen = best_public_execution(routes)
    assert chosen.name == "public_order_book"
    assert chosen.total_cost_pct == D("0.005")
    assert chosen.total_cost_pct < amm.execution_cost_pct
    assert chosen.fill_ratio >= MIN_FILL_RATIO


def test_a_route_that_exists_only_on_private_inventory_is_refused_outright():
    """"This trade has no deterministic public execution I am willing to underwrite" is the
    honest answer, and it is an exception rather than a cheap capacity number."""
    with pytest.raises(PrivateLiquidityExcluded) as excinfo:
        best_public_execution((
            ExecutionSource("rfq_a", total_cost_pct=D("0.001"), fill_ratio=D("1"),
                            is_private=True),
            ExecutionSource("rfq_b", total_cost_pct=D("0.002"), fill_ratio=D("1"),
                            is_private=True),
        ))
    assert "private" in str(excinfo.value)


# -- the artifact the rest of the pipeline reads --------------------------------


def test_the_whole_run_serializes_deterministically():
    """§9 requires the Independent Validator to re-derive these numbers from a different
    implementation and get byte-identical output. That is only checkable if this side is
    byte-identical to itself first."""
    def run():
        return [
            size_to_cost_cap(live_pool(), AssetTier.MAJOR, capital, D("5000"), D("2.50"))
            for capital in CAPITAL_LADDER
        ]

    first, second = run(), run()

    assert to_canonical_json(first) == to_canonical_json(second)
    assert canonical_hash(first) == canonical_hash(second)

    envelope = artifact_envelope("copy_simulations", "depth", first)
    assert envelope["kind"] == "copy_simulations"
    assert envelope["produced_by"] == "depth"
    assert len(envelope["payload"]) == len(CAPITAL_LADDER)
    assert envelope["payload_hash"]


def test_every_artifact_in_the_scenario_survives_canonical_json():
    """A float leaking in through any path raises here rather than reaching the freeze manifest."""
    detail = size_to_cost_cap_detail(
        live_pool(), AssetTier.MAJOR, D("100000"), D("5000"), D("2.50")
    )

    for artifact in (
        measure_depth(live_pool()),
        detail,
        detail.simulation,
        detail.costs,
        walk_order_book(book(), D("20100")),
        best_public_execution((
            ExecutionSource("public_order_book", total_cost_pct=D("0.005"), fill_ratio=D("1")),
        )),
    ):
        payload = to_canonical_json(artifact)
        assert payload.startswith("{")
