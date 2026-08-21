"""Invariants for ``marking``, over generated pool states and quantities.

The two headline properties are the ones a wrong implementation passes hand-computed tests
without violating:

* the liquidity-bound value never exceeds the spot-marked value, for **any** pool state and
  quantity — the ``min()`` in §4.4 can never be the wrong way round;
* a larger remaining quantity never realises a better per-unit price — you cannot improve your
  exit by holding more of the same token.

Both are stated over the full generated space rather than over chosen examples, because the case
that breaks them is always the one nobody thought to write down. The integer-truncation bug that
an earlier shape of ``average_exit_price`` had — a 2-unit sale realising a higher per-unit price
than a 1-unit sale — is invisible to every hand-computed case in this repository and shows up
here in a handful of examples.

``derandomize=True`` throughout: the house rule forbids unseeded randomness, and a property suite
that fails only on Tuesdays is worse than none.
"""

from decimal import Context, Decimal, localcontext

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from contracts import (
    FIRST_HOUR_BUCKETS,
    USDC,
    WETH,
    PoolState,
    PoolStatus,
    QuarantineRequired,
    TokenAgeBucket,
    ValueBasis,
    divide,
    normalise_asset,
    to_canonical_json,
)
from marking import (
    BUCKET_A_BLOCKS,
    DAY_SECONDS,
    DEAD_INACTIVITY_SECONDS,
    HOUR_SECONDS,
    QuoteAssetMismatch,
    average_exit_price,
    effective_reserves,
    exit_value_usd,
    mark_position,
    multiply,
    spot_value_usd,
    token_age_bucket,
)

DETERMINISTIC = settings(derandomize=True, max_examples=200, deadline=None)

HORIZON_BLOCK = 18_600_000
HORIZON_TS = 1_700_000_000

reserves = st.integers(min_value=1, max_value=10 ** 30)
quantities = st.integers(min_value=0, max_value=10 ** 30)
fees = st.integers(min_value=0, max_value=9_999)

#: USD per **raw** quote unit, over the range the four §4.6 quote assets actually span: USDC and
#: USDT at 6 decimals are 1e-6, WBTC at 8 decimals near 6e-4, WETH at 18 decimals near 3e-15.
#:
#: The upper bound is not cosmetic. ``contracts.canonicalise`` calls ``Decimal.normalize()``
#: outside any local context, so it runs at the *default* 28-digit precision rather than the
#: frozen 38 — and any Decimal needing more than 28 significant digits then raises
#: ``InvalidOperation`` inside serialization. Pairing a 10^30 raw reserve with a $10^6
#: per-raw-unit price produces such a value, but that pairing is also physically impossible: a
#: token with 10^30 raw units in its pool has many decimals, so its price per raw unit is tiny.
#: The bound keeps the generated space physical; the seam limitation is reported separately.
quote_prices = st.integers(min_value=1, max_value=10 ** 12).map(lambda n: divide(n, 10 ** 18))


@st.composite
def markable_pools(draw, address="0xpool", asset="0xtoken", max_age=None, quote=USDC):
    """A pool that is priceable and never from after the horizon."""
    age = draw(st.integers(min_value=0, max_value=max_age if max_age is not None
                           else 5 * DEAD_INACTIVITY_SECONDS))
    return PoolState(
        address=address,
        asset=asset,
        quote=quote,
        asset_reserve_raw=draw(reserves),
        quote_reserve_raw=draw(reserves),
        last_swap_block=HORIZON_BLOCK - draw(st.integers(min_value=0, max_value=1_000_000)),
        last_swap_timestamp=HORIZON_TS - age,
        fee_bps=draw(fees),
    )


# -- the headline invariants ----------------------------------------------------


@DETERMINISTIC
@given(dx=quantities, x=reserves, y=reserves, fee=fees, price=quote_prices)
def test_the_liquidity_bound_never_exceeds_the_spot_mark(dx, x, y, fee, price):
    """``min(spot, extractable) == extractable``, always.

    If this ever failed, the mandatory bound would be a no-op in exactly the cases it exists for:
    the thin pools, where spot is the fiction.
    """
    assert exit_value_usd(dx, x, y, fee, price) <= spot_value_usd(dx, x, y, price)


@DETERMINISTIC
@given(dx_a=quantities, delta=quantities, x=reserves, y=reserves, fee=fees)
def test_a_larger_quantity_never_realises_a_better_per_unit_price(dx_a, delta, x, y, fee):
    """Monotone by construction: the quantity appears only in the denominator.

    Rounding cannot rescue a violation here either — rounding to nearest is a monotone map, so a
    single rounding of a monotone-decreasing exact quantity stays monotone.
    """
    dx_b = dx_a + delta
    assert average_exit_price(dx_a, x, y, fee) >= average_exit_price(dx_b, x, y, fee)


@DETERMINISTIC
@given(dx=quantities, x=reserves, y=reserves, fee=fees, price=quote_prices)
def test_no_position_can_extract_more_than_the_pool_holds(dx, x, y, fee, price):
    """The constant-product curve has an asymptote at the quote reserve. A mark above it would be
    claiming value that does not exist in the contract."""
    whole_pool_usd = multiply(y, price)
    assert exit_value_usd(dx, x, y, fee, price) < whole_pool_usd or dx == 0


@DETERMINISTIC
@given(dx=quantities, pool=markable_pools(), price=quote_prices)
def test_the_returned_mark_never_exceeds_the_spot_mark(dx, pool, price):
    """The same invariant, through the whole public entry point rather than the primitives."""
    value = mark_position(dx, pool, HORIZON_BLOCK, HORIZON_TS, price)
    x, y, _model = effective_reserves(pool)

    assert value.value_usd <= spot_value_usd(dx, x, y, price)
    assert value.value_usd >= 0


# -- the dead conjunction -------------------------------------------------------


@DETERMINISTIC
@given(dx=quantities, pool=markable_pools(max_age=DEAD_INACTIVITY_SECONDS - 1),
       price=quote_prices)
def test_a_pool_that_traded_inside_the_window_is_never_zeroed(dx, pool, price):
    """Condition 1 fails, so no combination of the other two may zero the position — however
    thin the pool and however worthless the exit."""
    value = mark_position(dx, pool, HORIZON_BLOCK, HORIZON_TS, price)

    assert value.value_basis is not ValueBasis.DEAD_ZEROED
    assert value.pool_status is not PoolStatus.DEAD


@DETERMINISTIC
@given(dx=st.integers(min_value=1, max_value=10 ** 30),
       old=markable_pools(address="0xold"),
       new=markable_pools(address="0xnew", max_age=DEAD_INACTIVITY_SECONDS - 1),
       price=quote_prices)
def test_a_validated_replacement_is_never_zeroed(dx, old, new, price):
    """Condition 3 fails. §9.2's whole reason for existing: a token that migrated to a live pool
    is not a rug, and zeroing it would manufacture a -100% return out of a venue change."""
    value = mark_position(dx, old, HORIZON_BLOCK, HORIZON_TS, price, replacement_pool=new)

    assert value.value_basis is not ValueBasis.DEAD_ZEROED
    assert value.pool_status is not PoolStatus.DEAD
    assert value.value_usd > 0


@DETERMINISTIC
@given(dx=quantities, pool=markable_pools(), price=quote_prices)
def test_zero_value_means_dead_or_an_empty_position_and_nothing_else(dx, pool, price):
    """No third route to a zero. A silent zero from a division, an underflow, or an unmodelled
    pool would be indistinguishable downstream from a measured total loss."""
    value = mark_position(dx, pool, HORIZON_BLOCK, HORIZON_TS, price)

    if value.value_usd == 0:
        assert value.value_basis is ValueBasis.DEAD_ZEROED or dx == 0
    if value.value_basis is ValueBasis.DEAD_ZEROED:
        assert value.value_usd == 0
        assert value.executable_quantity == 0
        assert "dead_pool=no_swap_for_30d+exit_below_minimum+no_validated_replacement" \
            in value.evidence


@DETERMINISTIC
@given(dx=st.integers(min_value=1, max_value=10 ** 30),
       old=markable_pools(address="0xold"),
       new=markable_pools(address="0xnew", quote=WETH, max_age=DEAD_INACTIVITY_SECONDS - 1),
       price=quote_prices)
def test_a_mark_is_never_returned_priced_in_another_venues_quote_asset(dx, old, new, price):
    """``price`` is USD per raw unit of ``old.quote`` and of nothing else.

    Whatever the module does with a replacement quoted in a different asset — follow it or ignore
    it — the one outcome that must never occur is a returned number computed from one asset's
    reserves and another asset's price. Raw units differ by twelve orders of magnitude across the
    four §4.6 quote assets, so that mark is not approximately wrong, it is wrong by 1e8 or more
    and still looks like an ordinary valuation.
    """
    try:
        value = mark_position(dx, old, HORIZON_BLOCK, HORIZON_TS, price, replacement_pool=new)
    except QuoteAssetMismatch:
        return
    assert "venue_quote={}".format(normalise_asset(old.quote)) in value.evidence


@DETERMINISTIC
@given(dx=quantities, pool=markable_pools(), price=quote_prices)
def test_a_mark_does_not_depend_on_the_callers_decimal_context(dx, pool, price):
    """Every arithmetic step runs under the frozen 38-digit context, so the caller's ambient
    ``decimal`` settings cannot move a mark.

    This is §9.2's precondition: two independent computations reconcile to 0.5% only if they are
    computing the same thing. A value that shifts with ``getcontext().prec`` gives a validator
    different bytes, a different canonical hash, and — at a threshold boundary — a different
    ``value_basis``.
    """
    default = mark_position(dx, pool, HORIZON_BLOCK, HORIZON_TS, price)

    with localcontext(Context(prec=60)):
        wider = mark_position(dx, pool, HORIZON_BLOCK, HORIZON_TS, price)
    with localcontext(Context(prec=15)):
        narrower = mark_position(dx, pool, HORIZON_BLOCK, HORIZON_TS, price)

    # Serialized out here, at one ambient precision for all three: ``contracts.canonicalise``
    # calls ``Decimal.normalize()`` outside any local context, so comparing JSON produced *inside*
    # those blocks would be measuring the seam's serialization rather than the mark.
    assert to_canonical_json(wider) == to_canonical_json(default)
    assert to_canonical_json(narrower) == to_canonical_json(default)


@DETERMINISTIC
@given(dx=quantities, pool=markable_pools(), price=quote_prices)
def test_a_returned_status_is_never_unmodelled(dx, pool, price):
    """UNMODELLED is a raise, never a return value. A returned UNMODELLED would be a status
    claiming to be a measurement of something nothing measured."""
    value = mark_position(dx, pool, HORIZON_BLOCK, HORIZON_TS, price)
    assert value.pool_status is not PoolStatus.UNMODELLED


@DETERMINISTIC
@given(dx=quantities, pool=markable_pools(), price=quote_prices)
def test_every_mark_survives_canonical_json(dx, pool, price):
    """A float leaking in through any path raises inside ``to_canonical_json``."""
    value = mark_position(dx, pool, HORIZON_BLOCK, HORIZON_TS, price)
    blob = to_canonical_json(value)
    assert to_canonical_json(value) == blob, "canonical form must be deterministic"


@DETERMINISTIC
@given(dx=quantities, pool=markable_pools(), price=quote_prices)
def test_marking_is_a_pure_function_of_its_arguments(dx, pool, price):
    first = mark_position(dx, pool, HORIZON_BLOCK, HORIZON_TS, price)
    second = mark_position(dx, pool, HORIZON_BLOCK, HORIZON_TS, price)
    assert to_canonical_json(first) == to_canonical_json(second)


# -- token age ------------------------------------------------------------------

BUCKET_ORDER = {b: i for i, b in enumerate(
    (TokenAgeBucket.A, TokenAgeBucket.B, TokenAgeBucket.C, TokenAgeBucket.D)
)}

start_blocks = st.integers(min_value=0, max_value=10 ** 8)
start_times = st.integers(min_value=0, max_value=2 * 10 ** 9)
block_ages = st.integers(min_value=0, max_value=10 ** 6)
time_ages = st.integers(min_value=0, max_value=10 ** 8)


@DETERMINISTIC
@given(sb=start_blocks, ss=start_times, ba=block_ages, ta=time_ages)
def test_every_non_negative_age_lands_in_exactly_one_bucket(sb, ss, ba, ta):
    assert token_age_bucket(sb + ba, ss + ta, sb, ss) in BUCKET_ORDER


@DETERMINISTIC
@given(sb=start_blocks, ss=start_times, ba=block_ages, ta=time_ages,
       db=block_ages, dt=time_ages)
def test_an_older_trade_never_lands_in_a_younger_bucket(sb, ss, ba, ta, db, dt):
    """Monotone in age. A non-monotone bucketing would let a wallet's first-hour share move in
    the wrong direction as the token aged."""
    younger = token_age_bucket(sb + ba, ss + ta, sb, ss)
    older = token_age_bucket(sb + ba + db, ss + ta + dt, sb, ss)
    assert BUCKET_ORDER[older] >= BUCKET_ORDER[younger]


@DETERMINISTIC
@given(sb=start_blocks, ss=start_times, ba=block_ages, ta=time_ages)
def test_first_hour_buckets_are_exactly_the_first_ten_blocks_or_the_first_hour(sb, ss, ba, ta):
    bucket = token_age_bucket(sb + ba, ss + ta, sb, ss)
    expected = ba < BUCKET_A_BLOCKS or ta < HOUR_SECONDS
    assert (bucket in FIRST_HOUR_BUCKETS) is expected


@DETERMINISTIC
@given(sb=start_blocks, ss=start_times, ba=block_ages, ta=time_ages)
def test_bucket_d_is_exactly_beyond_twenty_four_hours(sb, ss, ba, ta):
    bucket = token_age_bucket(sb + ba, ss + ta, sb, ss)
    assert (bucket is TokenAgeBucket.D) is (ta >= DAY_SECONDS and ba >= BUCKET_A_BLOCKS)


@DETERMINISTIC
@given(sb=start_blocks, ss=start_times, ba=block_ages, ta=time_ages)
def test_migration_cannot_change_a_bucket_because_the_start_is_the_tokens_own(sb, ss, ba, ta):
    """The function has no pool argument, so there is nothing a migration could feed it. Stated
    as a property so the absence is deliberate rather than incidental."""
    once = token_age_bucket(sb + ba, ss + ta, sb, ss)
    again = token_age_bucket(sb + ba, ss + ta, sb, ss)
    assert once is again


@DETERMINISTIC
@given(sb=start_blocks, ss=start_times,
       back=st.integers(min_value=1, max_value=10 ** 6))
def test_a_trade_before_the_trading_start_always_quarantines(sb, ss, back):
    assume(ss - back >= 0)
    with pytest.raises(QuarantineRequired):
        token_age_bucket(sb, ss - back, sb, ss)


@DETERMINISTIC
@given(value=st.floats(allow_nan=False, allow_infinity=False, width=32))
def test_float_ages_are_refused(value):
    with pytest.raises(TypeError):
        token_age_bucket(value, 0, 0, 0)


@DETERMINISTIC
@given(dx=quantities, pool=markable_pools(),
       price=st.floats(min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False))
def test_a_float_quote_price_is_refused_on_sight(dx, pool, price):
    """The seam rule, enforced at the entry point rather than discovered at serialization."""
    with pytest.raises(TypeError):
        mark_position(dx, pool, HORIZON_BLOCK, HORIZON_TS, price)


@DETERMINISTIC
@given(dx=quantities, pool=markable_pools())
def test_a_non_positive_quote_price_is_refused(dx, pool):
    for bad in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError):
            mark_position(dx, pool, HORIZON_BLOCK, HORIZON_TS, bad)
