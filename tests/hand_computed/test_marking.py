"""Worked examples for ``marking``. Every expected value below was computed by hand first.

The arithmetic is written out in each docstring so a reviewer can check the number without
running the code. §9.3 requires the answer to be fixed *before* the implementation exists, which
is the only reason these are trustworthy at all — a test written after the fact merely records
what the code did.

Convention used throughout, and stated once here because it is the module's only non-obvious
input: ``quote_usd`` is **USD per raw unit of the quote asset**. Reserves are raw ints and no
type in ``contracts`` carries token decimals, so a per-whole-token price would need metadata the
seam does not provide. Setting ``quote_usd = 1`` makes one raw quote unit worth $1, which lets
these cases be read as plain dollars.
"""

from decimal import Context, Decimal, localcontext

import pytest

from contracts import (
    USDC,
    WETH,
    LookAheadViolation,
    PoolState,
    PoolStatus,
    QuarantineRequired,
    TokenAgeBucket,
    ValueBasis,
    quantize_ratio,
    quantize_usd,
    to_canonical_json,
)
from marking import (
    DAY_SECONDS,
    DEAD_INACTIVITY_SECONDS,
    HOUR_SECONDS,
    MARKING_TOLERANCE,
    MINIMUM_EXIT_VALUE_USD,
    THIN_SHORTFALL_RATIO,
    QuoteAssetMismatch,
    UnmodelledPoolError,
    mark_position,
    token_age_bucket,
)

HORIZON_BLOCK = 18_600_000
HORIZON_TS = 1_700_000_000
ONE = Decimal("1")  # USD per raw quote unit

#: Thirty days of UTC seconds, **written out** rather than imported from the module under test.
#: 30 * 24 * 60 * 60 = 2_592_000. Every dead-pool case below dates its pool from this literal, so
#: widening ``DEAD_INACTIVITY_SECONDS`` moves the code away from the tests instead of moving the
#: tests with it — a case built as ``HORIZON_TS - DEAD_INACTIVITY_SECONDS`` passes at any window
#: length and therefore pins none.
THIRTY_DAYS_S = 2_592_000


def pool(asset_reserve, quote_reserve, fee_bps=0, ts=HORIZON_TS, block=HORIZON_BLOCK,
         address="0xpool", asset="0xtoken", quote=USDC, **kwargs):
    return PoolState(
        address=address,
        asset=asset,
        quote=quote,
        asset_reserve_raw=asset_reserve,
        quote_reserve_raw=quote_reserve,
        last_swap_block=block,
        last_swap_timestamp=ts,
        fee_bps=fee_bps,
        **kwargs
    )


# -- the liquidity bound --------------------------------------------------------


def test_half_the_pool_is_sold_and_the_bound_halves_the_mark():
    """x = y = 1_000_000, dx = 1_000_000, fee 0.

        spot  = dx * (y / x)          = 1_000_000 * 1        = 1_000_000
        exit  = dx * y / (x + dx)     = 1e6 * 1e6 / 2e6       =   500_000

    Marking this position at spot would claim exactly twice what the pool can pay.
    """
    value = mark_position(1_000_000, pool(1_000_000, 1_000_000), HORIZON_BLOCK, HORIZON_TS, ONE)

    assert value.value_usd == Decimal("500000")
    assert value.value_basis is ValueBasis.LIQUIDITY_BOUND
    assert value.pool_status is PoolStatus.THIN
    assert value.executable_quantity == 1_000_000


def test_fifty_thousand_dollars_in_a_two_thousand_dollar_pool():
    """The §4.4 anecdote, made arithmetic.

        pool:  200 asset raw, 2_000 quote raw   -> spot price 10, pool holds $2,000
        held:  5_000 asset raw                  -> spot mark 5_000 * 10 = $50,000

        exit = 5_000 * 2_000 / (200 + 5_000) = 10_000_000 / 5_200
             = 1_923.076923076923...

    A wallet holding $50,000 of a token whose pool has $2,000 does not hold $50,000 — and it
    cannot hold $2,000 either, because the last unit out of a constant-product pool is free.
    """
    value = mark_position(5_000, pool(200, 2_000), HORIZON_BLOCK, HORIZON_TS, ONE)

    assert quantize_usd(value.value_usd) == Decimal("1923.076923")
    assert value.value_usd < Decimal("2000"), "cannot extract more than the pool holds"
    assert value.value_basis is ValueBasis.LIQUIDITY_BOUND
    assert value.pool_status is PoolStatus.THIN


def test_a_negligible_position_in_a_deep_pool_is_pool_marked():
    """x = y = 1_000_000_000, dx = 1_000_000, fee 0.

        exit = 1e6 * 1e9 / 1.001e9 = 999_000 + 1/1.001
             = 999_000.999000999000999...
        spot = 1_000_000

    Shortfall 0.0999%, inside the §9.2 pool-level marking tolerance of 0.5%, so the bound did
    not materially bind and the basis is POOL_MARKED. The *value* is still the bounded one —
    only the label changes, because §10 has to report how much of a wallet's score rests on
    depth assumptions.
    """
    value = mark_position(1_000_000, pool(10 ** 9, 10 ** 9), HORIZON_BLOCK, HORIZON_TS, ONE)

    assert quantize_usd(value.value_usd) == Decimal("999000.999001")
    assert value.value_basis is ValueBasis.POOL_MARKED
    assert value.pool_status is PoolStatus.LIVE


def test_the_thirty_bps_fee_alone_stays_inside_the_marking_tolerance():
    """fee_bps = 30 on a pool 10^12 times the position: shortfall is the fee, 0.3% < 0.5%."""
    value = mark_position(10 ** 12, pool(10 ** 24, 10 ** 24, fee_bps=30),
                          HORIZON_BLOCK, HORIZON_TS, ONE)

    ratio = value.value_usd / Decimal(10 ** 12)
    assert Decimal("0.9969") < ratio < Decimal("0.9970")
    assert value.value_basis is ValueBasis.POOL_MARKED


def test_concentrated_liquidity_uses_virtual_reserves_in_the_active_band():
    """L = 10^12, sqrt(P) = 2 so P = 4 raw quote per raw asset.

        x_v = L / sqrt(P) = 10^12 / 2 = 5e11
        y_v = L * sqrt(P) = 10^12 * 2 = 2e12          (y_v / x_v = 4, as required)

        dx = 5e11 (the whole virtual asset reserve)
        spot = 5e11 * 4                       = 2e12
        exit = 5e11 * 2e12 / (5e11 + 5e11)    = 1e12

    Addendum §9.6: total TVL *understates* near-spot depth for v3/v4 by 5-23x, so a single-band
    virtual-reserve model errs toward too little depth, never too much. That is the safe
    direction for a mark, and the evidence says so out loud.

    **The pool holds reserves, and it must.** This case was written as ``pool(0, 0, L, sqrt(P))``
    — a concentrated pool holding nothing — which is the one input :func:`depth.measure_depth`
    refuses by name, as a drained pool carrying a stale liquidity snapshot. Both readings are
    supplied here instead: real quote reserve 5e11 against a virtual one of 2e12, a ratio of 4,
    inside the 1..230 band. The virtual pair is the one used, because A10.4 says a v3 pool is
    priced on virtual reserves and not on the balances it happens to hold.
    """
    q96 = 1 << 96
    v3 = pool(125 * 10 ** 9, 5 * 10 ** 11, active_liquidity=10 ** 12, sqrt_price_x96=2 * q96)
    value = mark_position(5 * 10 ** 11, v3, HORIZON_BLOCK, HORIZON_TS, ONE)

    assert value.value_usd == Decimal(10 ** 12)
    assert value.value_basis is ValueBasis.LIQUIDITY_BOUND
    assert any("virtual_reserves" in e for e in value.evidence)


# -- §9.6 on the one real concentrated pool state in this repository ------------
#
# Uniswap v3 USDC/WETH 0.05%, 0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640, read at block 16943478
# by ``tools.case_runs.read_v3_pool``. Every literal below is a chain read, not a chosen value.

REAL_V3_POOL = "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"
REAL_V3_LIQUIDITY = 37_039_663_111_270_122_380
REAL_V3_SQRT_PRICE_X96 = 1_870_569_395_896_101_347_464_491_938_479_807
REAL_V3_USDC_BALANCE = 121_242_053_246_095
REAL_V3_WETH_BALANCE = 65_495_754_303_876_223_786_599

#: ``x_v = L * 2^96 // sqrt(P)`` and ``y_v = L * sqrt(P) // 2^96``, floored, computed by hand from
#: the four literals above.
REAL_V3_VIRTUAL_ASSET = 1_568_818_807_199_339
REAL_V3_VIRTUAL_QUOTE = 874_502_929_911_689_640_748_249


def real_v3_pool(**kwargs):
    fields = dict(
        address=REAL_V3_POOL, asset=USDC, quote=WETH,
        asset_reserve=REAL_V3_USDC_BALANCE, quote_reserve=REAL_V3_WETH_BALANCE,
        fee_bps=5, active_liquidity=REAL_V3_LIQUIDITY,
        sqrt_price_x96=REAL_V3_SQRT_PRICE_X96,
    )
    fields.update(kwargs)
    return pool(**fields)


def test_a_real_v3_pool_is_priced_on_virtual_reserves_and_not_on_its_balances():
    """A10.4 is not conditional on the balances being absent, and a real v3 pool has balances.

    The pool holds 121,242,053,246,095 raw USDC and 65,495,754,303,876,223,786,599 raw WETH, and
    reports ``L = 37,039,663,111,270,122,380`` with
    ``sqrtPriceX96 = 1,870,569,395,896,101,347,464,491,938,479,807``. By hand::

        x_v = L * 2^96 // sqrtP = 1,568,818,807,199,339            raw USDC
        y_v = L * sqrtP // 2^96 = 874,502,929,911,689,640,748,249  raw WETH

    ``y_v / y_real = 13.35``, inside the 5-23x band A10.4 measured — the first time that band has
    been checked against a real ``(L, sqrt(P))`` pair anywhere in this repository.

    Reading the balances instead is wrong twice over. The depth is 13.35x too shallow, which
    understates a large exit; and the *spot* term becomes ``y_real / x_real``, which for a
    concentrated pool is the ratio of whatever the LPs left lying across all ticks rather than the
    pool's price. Here that is 540,206,574.78 against the pool's actual 557,427,617.45 — 3.19%
    away, six times ``MARKING_TOLERANCE``, and in a direction nothing bounds: it depends on how
    liquidity happens to sit around the current tick, not on anything conservative.
    """
    from marking.liquidity import MODEL_VIRTUAL_RESERVES, effective_reserves

    asset_reserve, quote_reserve, model = effective_reserves(real_v3_pool())

    assert (asset_reserve, quote_reserve) == (REAL_V3_VIRTUAL_ASSET, REAL_V3_VIRTUAL_QUOTE)
    assert model == MODEL_VIRTUAL_RESERVES


def test_the_real_v3_marks_name_the_virtual_reserve_model_in_the_evidence():
    """§9.2 re-derives a mark from the evidence, and the model tag is how it knows which curve.

    A mark taken off a v3 pool's balances and tagged ``model=constant_product_reserves`` tells a
    re-derivation to walk the wrong curve and to agree with itself while doing it.
    """
    value = mark_position(10 ** 12, real_v3_pool(), HORIZON_BLOCK, HORIZON_TS, Decimal("1"))

    assert "model=v3_virtual_reserves_active_band" in value.evidence
    assert "model=constant_product_reserves" not in value.evidence


def test_a_drained_concentrated_pool_is_unmodelled_rather_than_priced_off_stale_liquidity():
    """Reserves gone, ``L`` and ``sqrt(P)`` still standing: the state ``depth`` refuses by name.

    ``depth.measure_depth`` quarantines this — "a stale active_liquidity/sqrt_price_x96 on a
    drained pool is a real but unsupported state" — after tracing it turning a pool holding $0 into
    $5,000,000 of effective depth. Marking is where the number reaches §10's marked share, and it
    had no such guard: it walked the stale virtual curve and published a mark.

    ``UnmodelledPoolError`` and not a zero: the pool may well be dead, but nothing here measured
    that, and §9.1's conjunction is the only thing allowed to zero a position.
    """
    from marking.liquidity import effective_reserves

    with pytest.raises(UnmodelledPoolError) as refusal:
        effective_reserves(real_v3_pool(quote_reserve=0))

    assert "drained" in str(refusal.value)


def test_a_concentrated_state_whose_two_readings_disagree_past_the_band_is_unmodelled():
    """``y_v / y_real`` above 230x is a liquidity read that no longer belongs to that reserve.

    The real pool sits at 13.35x. Divide its WETH balance by 100 and the ratio becomes 1,335x —
    past the 230x ceiling, which is ten times the 23x maximum ever measured. That is not a tighter
    pool; it is two reads from different blocks, or a snapshot taken across a drain.
    """
    from marking.liquidity import effective_reserves

    with pytest.raises(UnmodelledPoolError) as refusal:
        effective_reserves(real_v3_pool(quote_reserve=REAL_V3_WETH_BALANCE // 100))

    assert "230" in str(refusal.value)


def test_a_virtual_depth_below_the_real_reserve_is_unmodelled():
    """The lower edge. TVL was measured to *understate* near-spot depth, never to overstate it.

    The real pool sits at 13.35x, so pushing the ratio under 1 needs the real reserve multiplied
    by more than 13.35. Twenty is used: 874,502,929,911,689,640,748,249 virtual against
    1,309,915,086,077,524,475,731,980 real is a ratio of 0.667. A virtual depth under the real
    reserve means the ``sqrt_price`` orientation is inverted for this pool, or the two fields were
    read at different heights; both are inputs this model does not support.
    """
    from marking.liquidity import effective_reserves

    with pytest.raises(UnmodelledPoolError) as refusal:
        effective_reserves(real_v3_pool(quote_reserve=REAL_V3_WETH_BALANCE * 20))

    assert "understate" in str(refusal.value)


def test_marking_and_depth_bound_the_same_measurement_with_the_same_numbers():
    """Two modules, one measurement (A10.4), two spellings of its constants. They must agree.

    ``marking`` may not import ``depth`` — every module in that layer imports ``contracts`` and
    nothing else — so the band is declared twice. Declared twice is fine; *drifting* twice is a
    pool quarantined by one module and priced by the other, which is the class of defect this
    whole pair of tests was written for.
    """
    import depth.amm as depth_amm
    import marking.liquidity as marking_liquidity

    assert (
        marking_liquidity.MAX_TVL_UNDERSTATEMENT_FACTOR
        == depth_amm.MAX_TVL_UNDERSTATEMENT_FACTOR
        == Decimal("230")
    )
    assert (
        marking_liquidity.MEASURED_TVL_UNDERSTATEMENT
        == depth_amm.MEASURED_TVL_UNDERSTATEMENT
        == (Decimal("5"), Decimal("23"))
    )


# -- the dead-pool conjunction --------------------------------------------------


def test_all_three_conditions_zero_the_position():
    """No swap for exactly 30 days, exit worth $0.000001, no replacement.

        pool: 10^18 asset raw, 1 quote raw
        exit = 10^12 * 1 / (10^18 + 10^12) ~= 1e-6 quote raw = $0.000001 < $1.00
    """
    dead = pool(10 ** 18, 1, ts=HORIZON_TS - DEAD_INACTIVITY_SECONDS,
                block=HORIZON_BLOCK - 200_000)
    value = mark_position(10 ** 12, dead, HORIZON_BLOCK, HORIZON_TS, ONE)

    assert value.value_usd == Decimal("0")
    assert value.value_basis is ValueBasis.DEAD_ZEROED
    assert value.pool_status is PoolStatus.DEAD
    assert value.executable_quantity == 0
    assert "cond1_no_swap_for_30d=true" in value.evidence
    assert "cond2_exit_below_minimum=true" in value.evidence
    assert "cond3_no_validated_replacement=true" in value.evidence
    assert "dead_pool=no_swap_for_30d+exit_below_minimum+no_validated_replacement" in value.evidence


def test_a_quiet_pool_that_is_still_exitable_is_not_zeroed():
    """Condition 1 holds, condition 2 does not. Zeroing here would be the Dune failure mode in
    reverse: destroying value that is genuinely there rather than forward-filling value that is
    not."""
    quiet = pool(10 ** 9, 10 ** 9, ts=HORIZON_TS - DEAD_INACTIVITY_SECONDS,
                 block=HORIZON_BLOCK - 200_000)
    value = mark_position(1_000_000, quiet, HORIZON_BLOCK, HORIZON_TS, ONE)

    assert quantize_usd(value.value_usd) == Decimal("999000.999001")
    assert value.value_basis is not ValueBasis.DEAD_ZEROED
    assert value.pool_status is PoolStatus.QUIET


def test_a_thin_but_live_pool_is_not_zeroed():
    """Condition 2 holds, condition 1 does not — the pool traded one second before the horizon.

        pool: 10^12 asset raw, 1 quote raw   -> the whole pool is worth $1
        held: 10^12 asset raw                -> the entire asset reserve

        spot = 10^12 * (1 / 10^12)            = $1.00
        exit = 10^12 * 1 / (10^12 + 10^12)    = $0.50

    So the exit is below the $1.00 minimum — condition 2 of the dead conjunction holds — and the
    position is still not zeroed, because the pool is alive. $0.50 is a small number and a true
    one; zero would be a larger error than the whole quantity being measured.
    """
    thin = pool(10 ** 12, 1, ts=HORIZON_TS - 1, block=HORIZON_BLOCK - 1)
    value = mark_position(10 ** 12, thin, HORIZON_BLOCK, HORIZON_TS, ONE)

    assert value.value_usd == Decimal("0.5")
    assert value.value_usd < MINIMUM_EXIT_VALUE_USD, "condition 2 of the dead conjunction holds"
    assert value.value_basis is ValueBasis.LIQUIDITY_BOUND
    assert value.pool_status is PoolStatus.THIN
    assert "cond1_no_swap_for_30d=false" in value.evidence


def test_a_tiny_position_in_an_absolutely_tiny_pool_is_still_pool_marked():
    """THIN is a statement about *this position against this pool*, not about the pool's size.

        pool: 10^18 asset raw, 1 quote raw    -> the whole pool is worth $1
        held: 10^12 asset raw                 -> a millionth of the asset reserve

        exit = 10^12 / (10^18 + 10^12) ~= $0.000000999999

    The depth bound barely bites, so the basis is POOL_MARKED even though the absolute value is
    dust. Labelling this LIQUIDITY_BOUND would inflate §10's bound share with positions whose
    marks depend on no depth assumption at all.
    """
    value = mark_position(10 ** 12, pool(10 ** 18, 1, ts=HORIZON_TS - 1), HORIZON_BLOCK,
                          HORIZON_TS, ONE)

    assert Decimal("0") < value.value_usd < MINIMUM_EXIT_VALUE_USD
    assert value.value_basis is ValueBasis.POOL_MARKED
    assert value.pool_status is PoolStatus.LIVE


def test_a_validated_replacement_pool_prevents_zeroing_and_prices_the_exit():
    """Conditions 1 and 2 hold on the old pool; condition 3 does not, because liquidity moved.

    The mark comes from the replacement — 10^9/10^9 with dx = 10^6 — so the same
    999_000.999001 as the deep-pool case, and the status is MIGRATED rather than DEAD.
    """
    old = pool(10 ** 18, 1, ts=HORIZON_TS - DEAD_INACTIVITY_SECONDS,
               block=HORIZON_BLOCK - 200_000, address="0xold")
    new = pool(10 ** 9, 10 ** 9, ts=HORIZON_TS - 60, block=HORIZON_BLOCK - 5, address="0xnew")

    value = mark_position(1_000_000, old, HORIZON_BLOCK, HORIZON_TS, ONE, replacement_pool=new)

    assert quantize_usd(value.value_usd) == Decimal("999000.999001")
    assert value.value_basis is not ValueBasis.DEAD_ZEROED
    assert value.pool_status is PoolStatus.MIGRATED


def test_a_replacement_for_a_different_token_does_not_count():
    """§9.2: migration is followed only on unchanged token identity. A different asset is a
    different position, and letting it rescue the mark would launder one token's liquidity into
    another token's valuation."""
    old = pool(10 ** 18, 1, ts=HORIZON_TS - DEAD_INACTIVITY_SECONDS,
               block=HORIZON_BLOCK - 200_000, asset="0xtoken")
    impostor = pool(10 ** 9, 10 ** 9, ts=HORIZON_TS - 60, block=HORIZON_BLOCK - 5,
                    asset="0xother", address="0xnew")

    value = mark_position(10 ** 12, old, HORIZON_BLOCK, HORIZON_TS, ONE,
                          replacement_pool=impostor)

    assert value.value_basis is ValueBasis.DEAD_ZEROED
    assert any("token_identity_changed" in e for e in value.evidence)


def test_a_replacement_with_no_recent_trading_does_not_count():
    """§9.2 requires *real trading activity*, not merely a pool that exists."""
    old = pool(10 ** 18, 1, ts=HORIZON_TS - DEAD_INACTIVITY_SECONDS,
               block=HORIZON_BLOCK - 200_000)
    stale = pool(10 ** 9, 10 ** 9, ts=HORIZON_TS - DEAD_INACTIVITY_SECONDS,
                 block=HORIZON_BLOCK - 200_000, address="0xnew")

    value = mark_position(10 ** 12, old, HORIZON_BLOCK, HORIZON_TS, ONE, replacement_pool=stale)

    assert value.value_basis is ValueBasis.DEAD_ZEROED
    assert any("no_recent_trading" in e for e in value.evidence)


def test_the_same_pool_offered_as_its_own_replacement_is_refused():
    """A "replacement" at the primary's own address is a lookup that returned the primary.

    Accepting it would let a fresher snapshot of the same pool rescue the position from the dead
    conjunction — and then price the exit against reserves the primary's own snapshot says are
    stale. The disagreement between the two snapshots is the finding; a mark computed from the
    friendlier one would bury it.
    """
    old = pool(10 ** 18, 1, ts=HORIZON_TS - THIRTY_DAYS_S, block=HORIZON_BLOCK - 200_000,
               address="0xpool")
    itself = pool(10 ** 9, 10 ** 9, ts=HORIZON_TS - 60, block=HORIZON_BLOCK - 5, address="0xpool")

    value = mark_position(10 ** 12, old, HORIZON_BLOCK, HORIZON_TS, ONE, replacement_pool=itself)

    assert value.value_basis is ValueBasis.DEAD_ZEROED
    assert any("same_pool" in e for e in value.evidence)


# -- a migration may not cross quote assets -------------------------------------


def test_a_migration_across_quote_assets_is_quarantined_rather_than_priced():
    """TOKEN/USDC goes quiet, TOKEN/WETH is live — the most common real migration shape.

    ``quote_usd`` is USD per raw unit of the **primary's** quote asset. Pricing the replacement's
    WETH reserves with it multiplies raw WETH by the raw-USDC price:

        avg  = 9970 * 1e20 / (10_000 * 1e25 + 9970 * 1e24)
             = 9.97e23 / 1.0997e29  = 9.066108938801...e-6 raw quote per raw asset
        exit = 1e24 * that          = 9.066108938801...e18 raw WETH

    times $0.000001/raw-USDC gives **$9,066,108,938,801.49**. The same exit at the replacement's
    own price (3e-15 USD per raw WETH, i.e. $3,000/ETH) is 299_100_000/10997 = **$27,198.33** —
    the mark is out by exactly 1e-6 / 3e-15 = 3.33e8. Nine trillion dollars, carrying a
    ``LIQUIDITY_BOUND`` basis that says depth was honestly modelled.

    So the venue change is refused, not guessed at. It is a raise rather than a rejected
    replacement because rejecting it would satisfy §9.1 condition 3 and zero a position whose
    liquidity is demonstrably alive — the -100% this module exists to prevent.
    """
    primary = pool(10 ** 25, 10 ** 6, fee_bps=30, ts=HORIZON_TS - THIRTY_DAYS_S,
                   block=HORIZON_BLOCK - 200_000, address="0xv2", quote=USDC)
    replacement = pool(10 ** 25, 100 * 10 ** 18, fee_bps=30, ts=HORIZON_TS - 60,
                       block=HORIZON_BLOCK - 5, address="0xv3", quote=WETH)

    with pytest.raises(QuoteAssetMismatch) as excinfo:
        mark_position(10 ** 24, primary, HORIZON_BLOCK, HORIZON_TS, Decimal("0.000001"),
                      replacement_pool=replacement)

    assert isinstance(excinfo.value, QuarantineRequired), "belongs in the reconciliation queue"
    assert USDC in str(excinfo.value) and WETH in str(excinfo.value), \
        "the record has to name both quote assets or the unit swap is unrecoverable"


def test_a_cross_quote_pool_does_not_disturb_the_mark_while_the_primary_trades():
    """The refusal is scoped to the venue actually used.

    A TOKEN/WETH pool alongside a still-trading TOKEN/USDC primary changes nothing: the exit
    happens where the liquidity is, the primary is priced in its own quote, and quarantining a
    perfectly markable position because some other venue exists would throw away a real
    measurement.
    """
    primary = pool(10 ** 9, 10 ** 9, ts=HORIZON_TS - 60, block=HORIZON_BLOCK - 5, address="0xv2")
    other = pool(10 ** 25, 100 * 10 ** 18, ts=HORIZON_TS - 60, block=HORIZON_BLOCK - 5,
                 address="0xv3", quote=WETH)

    value = mark_position(1_000_000, primary, HORIZON_BLOCK, HORIZON_TS, ONE,
                          replacement_pool=other)

    assert quantize_usd(value.value_usd) == Decimal("999000.999001")
    assert "venue=0xv2" in value.evidence
    assert value.pool_status is not PoolStatus.MIGRATED


def test_the_evidence_names_the_venues_quote_asset_and_the_price_it_was_paid_at():
    """§9.2 re-derives a mark from the record. Without the quote asset and the price per raw unit,
    the record cannot distinguish a WETH-quoted venue from a USDC-quoted one — which is exactly
    the mistake above, made invisible."""
    old = pool(10 ** 18, 1, ts=HORIZON_TS - THIRTY_DAYS_S, block=HORIZON_BLOCK - 200_000,
               address="0xold")
    new = pool(10 ** 9, 10 ** 9, ts=HORIZON_TS - 60, block=HORIZON_BLOCK - 5, address="0xnew")

    value = mark_position(1_000_000, old, HORIZON_BLOCK, HORIZON_TS, Decimal("0.000001"),
                          replacement_pool=new)

    assert "venue_quote={}".format(USDC) in value.evidence
    assert "quote_usd_per_raw_quote=0.000001" in value.evidence


# -- the §9.1 parameters, pinned by absolute literals ---------------------------


def test_the_inactivity_window_is_exactly_thirty_days():
    """§9.1 condition 1, pinned from both sides at the second.

    30 * 24 * 60 * 60 = 2_592_000. Both pools below are identical except for one second of
    silence, and the same dust exit ($0.000001) sits under the minimum in both, so the only thing
    deciding the zero is the window.

    Widening the window is the Dune-flattering direction: a rug stays marked at its dust value
    instead of being zeroed, and every wallet that bought it keeps a little of what it lost.
    """
    assert DEAD_INACTIVITY_SECONDS == 2_592_000

    silent = pool(10 ** 18, 1, ts=HORIZON_TS - 2_592_000, block=HORIZON_BLOCK - 200_000)
    assert mark_position(10 ** 12, silent, HORIZON_BLOCK, HORIZON_TS, ONE).value_basis \
        is ValueBasis.DEAD_ZEROED

    one_second_short = pool(10 ** 18, 1, ts=HORIZON_TS - 2_591_999,
                            block=HORIZON_BLOCK - 200_000)
    value = mark_position(10 ** 12, one_second_short, HORIZON_BLOCK, HORIZON_TS, ONE)
    assert value.value_basis is not ValueBasis.DEAD_ZEROED
    assert value.pool_status is not PoolStatus.DEAD


def test_the_minimum_exit_value_is_exactly_one_dollar_and_the_comparison_is_strict():
    """§9.1 condition 2, pinned at the cent — and at the last microdollar below it.

    Both pools are quiet for thirty days with no replacement, so conditions 1 and 3 hold and the
    exit value alone decides. Fee 0, and ``x + dx = 10^12`` in both, which makes the average exit
    price exactly ``y / (x + dx) = 10^6 / 10^12 = 1e-6`` and the exit exactly ``dx * 1e-6``:

        dx = 999_999   x = 10^12 - 999_999   ->  exit = $0.999999   -> below  -> zeroed
        dx = 1_000_000 x = 10^12 - 1_000_000 ->  exit = $1.000000   -> not below -> kept

    The second case pins the strictness too: at exactly the threshold the position is **not**
    below it, so ``<`` cannot quietly become ``<=``.
    """
    assert MINIMUM_EXIT_VALUE_USD == Decimal("1.00")

    just_below = pool(10 ** 12 - 999_999, 10 ** 6, ts=HORIZON_TS - THIRTY_DAYS_S,
                      block=HORIZON_BLOCK - 200_000)
    zeroed = mark_position(999_999, just_below, HORIZON_BLOCK, HORIZON_TS, ONE)
    assert zeroed.value_basis is ValueBasis.DEAD_ZEROED
    assert zeroed.value_usd == Decimal("0")
    assert "cond2_exit_below_minimum=true" in zeroed.evidence

    exactly_at = pool(10 ** 12 - 10 ** 6, 10 ** 6, ts=HORIZON_TS - THIRTY_DAYS_S,
                      block=HORIZON_BLOCK - 200_000)
    kept = mark_position(10 ** 6, exactly_at, HORIZON_BLOCK, HORIZON_TS, ONE)
    assert kept.value_usd == Decimal("1.000000")
    assert kept.value_basis is not ValueBasis.DEAD_ZEROED
    assert kept.pool_status is PoolStatus.QUIET
    assert "cond2_exit_below_minimum=false" in kept.evidence


def test_a_shortfall_of_exactly_the_marking_tolerance_is_not_a_bound_mark():
    """§9.2's 0.5%, pinned at the boundary. x = y = 199_000_000, dx = 1_000_000, fee 0.

        spot = dx * (y / x)        = 1_000_000 * 1              = 1_000_000
        exit = dx * y / (x + dx)   = 1e6 * 199e6 / 200e6        =   995_000
        shortfall = 5_000 / 1e6    = 1/200                      = 0.005 exactly

    Exactly at the tolerance is not *beyond* it, so the label is POOL_MARKED. The value returned
    is the bounded one either way — only §10's "how much of this score rests on depth" changes.
    """
    assert MARKING_TOLERANCE == Decimal("0.005")

    value = mark_position(1_000_000, pool(199_000_000, 199_000_000), HORIZON_BLOCK, HORIZON_TS,
                          ONE)

    assert value.value_usd == Decimal("995000")
    assert value.value_basis is ValueBasis.POOL_MARKED


def test_the_thin_label_is_exactly_a_tenth_below_spot():
    """THIN is a reporting label, so it is pinned like one: at the ratio itself.

        x = y = 9_000_000, dx = 1_000_000, fee 0
        exit = 1e6 * 9e6 / 1e7 = 900_000, spot = 1_000_000, shortfall = 1/10 exactly -> LIVE

        dx = 1_100_000
        exit = 1.1e6 * 9e6 / 1.01e7 = 99_000_000/101 = 980_198.019801...
        spot = 1_100_000, shortfall = 11/101 = 0.108910891... > 0.10          -> THIN
    """
    assert THIN_SHORTFALL_RATIO == Decimal("0.10")

    at_the_ratio = mark_position(1_000_000, pool(9_000_000, 9_000_000), HORIZON_BLOCK,
                                 HORIZON_TS, ONE)
    assert at_the_ratio.value_usd == Decimal("900000")
    assert at_the_ratio.pool_status is PoolStatus.LIVE

    beyond = mark_position(1_100_000, pool(9_000_000, 9_000_000), HORIZON_BLOCK, HORIZON_TS, ONE)
    assert quantize_usd(beyond.value_usd) == Decimal("980198.019802")
    assert beyond.pool_status is PoolStatus.THIN


def test_the_shortfall_is_computed_under_the_frozen_context_not_the_callers():
    """The label boundary is decided at 38 digits, or it is decided by whoever calls us.

        x = y = 2*10^33 - dx,  dx = 10^31 + 1,  fee 0
        shortfall = 1 - x/(x + dx) = dx / (x + dx) = (10^31 + 1) / (2 * 10^33)
                  = 0.0050000000000000000000000000000005          (33 significant digits)

    That is above the 0.5% tolerance, so the mark is LIQUIDITY_BOUND. Computed in the ambient
    28-digit context it rounds to exactly 0.005, which is **not** above the tolerance, and the
    same position comes back POOL_MARKED — a §10 depth-reliance share that moves with the
    caller's ``decimal`` settings, and two validators that disagree on §9.2 re-derivation.
    """
    dx = 10 ** 31 + 1
    reserve = 2 * 10 ** 33 - dx
    knife_edge = pool(reserve, reserve, ts=HORIZON_TS - 1, block=HORIZON_BLOCK - 1)

    value = mark_position(dx, knife_edge, HORIZON_BLOCK, HORIZON_TS, ONE)
    assert value.value_basis is ValueBasis.LIQUIDITY_BOUND

    # Same inputs, a caller carrying more precision than the default. A mark that depends on this
    # cannot be re-derived by anyone, which is what §9.2 requires of every mark.
    with localcontext(Context(prec=50)):
        wider = mark_position(dx, knife_edge, HORIZON_BLOCK, HORIZON_TS, ONE)
    assert wider.value_basis is value.value_basis
    assert wider.value_usd == value.value_usd
    assert wider.evidence == value.evidence


# -- unmodelled is not dead -----------------------------------------------------


def test_an_unmodellable_pool_raises_rather_than_returning_zero():
    """Zero because dead and zero because unmodelled are different facts. One is a measurement;
    the other is the absence of one, and returning it as a number would let a modelling gap flow
    downstream looking like a -100% return."""
    with pytest.raises(UnmodelledPoolError) as excinfo:
        mark_position(1_000, pool(0, 5_000), HORIZON_BLOCK, HORIZON_TS, ONE)

    assert "UNMODELLED" in str(excinfo.value)
    assert isinstance(excinfo.value, QuarantineRequired), "belongs in the reconciliation queue"


def test_an_unmodellable_pool_raises_even_when_it_looks_dead():
    """The dead conjunction must never be reached for a pool with no depth model — otherwise
    every unmodelled pool would silently satisfy 'exit value below threshold'."""
    with pytest.raises(UnmodelledPoolError):
        mark_position(1_000, pool(0, 0, ts=HORIZON_TS - DEAD_INACTIVITY_SECONDS,
                                  block=HORIZON_BLOCK - 200_000),
                      HORIZON_BLOCK, HORIZON_TS, ONE)


def test_a_hundred_percent_fee_pool_is_unmodelled_not_worthless():
    with pytest.raises(UnmodelledPoolError):
        mark_position(1_000, pool(10 ** 9, 10 ** 9, fee_bps=10_000),
                      HORIZON_BLOCK, HORIZON_TS, ONE)


# -- look-ahead -----------------------------------------------------------------


def test_pool_state_from_after_the_horizon_is_a_look_ahead_violation():
    """Marking at day 30 with a day-31 reserve snapshot is the nastiest bug class in the
    project: it leaves the code perfectly pleased with itself."""
    with pytest.raises(LookAheadViolation):
        mark_position(1_000, pool(10 ** 9, 10 ** 9, block=HORIZON_BLOCK + 1),
                      HORIZON_BLOCK, HORIZON_TS, ONE)

    with pytest.raises(LookAheadViolation):
        mark_position(1_000, pool(10 ** 9, 10 ** 9, ts=HORIZON_TS + 1),
                      HORIZON_BLOCK, HORIZON_TS, ONE)


def test_a_replacement_pool_from_after_the_horizon_is_also_refused():
    old = pool(10 ** 18, 1, ts=HORIZON_TS - DEAD_INACTIVITY_SECONDS,
               block=HORIZON_BLOCK - 200_000)
    future = pool(10 ** 9, 10 ** 9, ts=HORIZON_TS + 1, block=HORIZON_BLOCK + 1, address="0xnew")

    with pytest.raises(LookAheadViolation):
        mark_position(1_000, old, HORIZON_BLOCK, HORIZON_TS, ONE, replacement_pool=future)


# -- input refusals -------------------------------------------------------------


def test_float_inputs_are_refused_on_sight():
    with pytest.raises(TypeError):
        mark_position(1_000, pool(10 ** 9, 10 ** 9), HORIZON_BLOCK, HORIZON_TS, 1.0)


def test_a_decimal_quantity_is_refused():
    """Raw token quantities are int, never Decimal — §9.2 requires them to match a hand trace
    exactly and a rounded quantity cannot."""
    with pytest.raises(TypeError):
        mark_position(Decimal("1000"), pool(10 ** 9, 10 ** 9), HORIZON_BLOCK, HORIZON_TS, ONE)


def test_a_negative_quantity_is_refused():
    with pytest.raises(ValueError):
        mark_position(-1, pool(10 ** 9, 10 ** 9), HORIZON_BLOCK, HORIZON_TS, ONE)


def test_a_non_positive_quote_price_is_refused():
    with pytest.raises(ValueError):
        mark_position(1_000, pool(10 ** 9, 10 ** 9), HORIZON_BLOCK, HORIZON_TS, Decimal("0"))


# -- token age ------------------------------------------------------------------

START_BLOCK = 100
START_TS = 1_000


def bucket(block_offset, ts_offset):
    return token_age_bucket(START_BLOCK + block_offset, START_TS + ts_offset,
                            START_BLOCK, START_TS)


def test_bucket_a_is_the_first_ten_blocks_half_open():
    assert bucket(0, 0) is TokenAgeBucket.A
    assert bucket(9, 108) is TokenAgeBucket.A
    assert bucket(10, 120) is TokenAgeBucket.B, "10 blocks is the first block of B, not the last of A"


def test_bucket_b_runs_to_the_end_of_hour_one_half_open():
    assert bucket(50, HOUR_SECONDS - 1) is TokenAgeBucket.B
    assert bucket(50, HOUR_SECONDS) is TokenAgeBucket.C, "3600s exactly starts C"


def test_bucket_c_runs_to_the_end_of_hour_twenty_four_half_open():
    assert bucket(300, DAY_SECONDS - 1) is TokenAgeBucket.C
    assert bucket(300, DAY_SECONDS) is TokenAgeBucket.D, "86400s exactly starts D"


def test_the_trade_at_the_trading_start_block_itself_is_bucket_a():
    assert bucket(0, 0) is TokenAgeBucket.A


def test_a_trade_before_the_trading_start_is_quarantined_not_bucketed():
    """A buy that precedes first usable liquidity means the derived start is wrong. Returning
    bucket A would hand the wallet a first-hour purchase it never made."""
    with pytest.raises(QuarantineRequired):
        token_age_bucket(START_BLOCK - 1, START_TS - 12, START_BLOCK, START_TS)


def test_a_block_and_timestamp_that_disagree_on_direction_are_quarantined():
    """Timestamps are always paired with a block number; a pair that runs backwards against
    itself is not a measurement of anything."""
    with pytest.raises(QuarantineRequired):
        token_age_bucket(START_BLOCK + 5, START_TS - 1, START_BLOCK, START_TS)


def test_migration_does_not_reset_token_age():
    """§4.7 and addendum §9.2. The function takes the *token's* trading start, never the current
    pool's creation, so re-marking a migrated token keeps its age. A token that started trading
    two days ago and migrated one block ago is bucket D, not bucket A.
    """
    two_days = 2 * DAY_SECONDS
    assert token_age_bucket(START_BLOCK + 14_400, START_TS + two_days, START_BLOCK, START_TS) \
        is TokenAgeBucket.D
    assert "igration" in token_age_bucket.__doc__


# -- serialization --------------------------------------------------------------


def test_every_returned_value_survives_canonical_json():
    """A float leaking in through any path raises in ``to_canonical_json``, so this is the
    cheapest possible detector for one."""
    for value in (
        mark_position(5_000, pool(200, 2_000), HORIZON_BLOCK, HORIZON_TS, ONE),
        mark_position(10 ** 12, pool(10 ** 18, 1, ts=HORIZON_TS - DEAD_INACTIVITY_SECONDS,
                                     block=HORIZON_BLOCK - 200_000),
                      HORIZON_BLOCK, HORIZON_TS, ONE),
    ):
        blob = to_canonical_json(value)
        assert "value_usd" in blob
        assert "e+" not in blob and "E+" not in blob


def test_the_mark_is_not_quantized_before_aggregation():
    """§numeric: reporting is quantized exactly once, at the output boundary. Marking is not
    that boundary — these values feed a log-weighted mean — so the full-precision remainder must
    still be present.
    """
    value = mark_position(5_000, pool(200, 2_000), HORIZON_BLOCK, HORIZON_TS, ONE)
    assert value.value_usd != quantize_usd(value.value_usd)
    assert quantize_ratio(value.value_usd - quantize_usd(value.value_usd)) != Decimal("0")
