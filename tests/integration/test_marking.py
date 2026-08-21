"""Realistic multi-step scenarios for ``marking``.

These run the module the way the pipeline will: a wallet holding several open positions at the
30-day horizon, marked across pools in different states, then decomposed into the realized /
marked / dead shares §10 requires reported alongside any score.

Units throughout are the real ones. DEGEN-style token at 18 decimals, USDC quote at 6 decimals,
so ``quote_usd`` — USD per **raw** quote unit — is ``0.000001``. Working in raw units the whole
way is the point of the seam: §9.2 requires raw quantities to match a hand trace exactly, and a
decimals conversion anywhere in the chain makes that unsatisfiable.
"""

from decimal import Decimal

import pytest

from contracts import (
    LookAheadViolation,
    PoolState,
    PoolStatus,
    TokenAgeBucket,
    ValueBasis,
    artifact_envelope,
    canonical_hash,
    divide,
    quantize_ratio,
    quantize_usd,
    to_canonical_json,
)
from marking import (
    DAY_SECONDS,
    DEAD_INACTIVITY_SECONDS,
    QuoteAssetMismatch,
    mark_position,
    multiply,
    token_age_bucket,
)

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"

#: USD per raw USDC unit. USDC has 6 decimals, so one raw unit is a millionth of a dollar.
USDC_PER_RAW = Decimal("0.000001")

#: USD per raw WETH unit: $3,000 an ETH spread over 10^18 raw units. Nine orders of magnitude
#: away from ``USDC_PER_RAW``, which is the whole reason a venue change may not carry a price
#: across quote assets.
WETH_PER_RAW = Decimal("3e-15")

#: 30 * 24 * 60 * 60, written out. A case dated ``HORIZON_TS - DEAD_INACTIVITY_SECONDS`` moves
#: with the constant and so pins nothing about it.
THIRTY_DAYS_S = 2_592_000

WINDOW_END_BLOCK = 18_500_000
WINDOW_END_TS = 1_697_500_000

#: §4.4 measures 30 days from the buy, which for a buy near the window edge runs past the end of
#: the evaluation window. The horizon extends; no sample is dropped and no partial return is used.
HORIZON_TS = WINDOW_END_TS + 25 * DAY_SECONDS
HORIZON_BLOCK = WINDOW_END_BLOCK + 180_000

ONE_MILLION_TOKENS = 10 ** 24  # 1,000,000 units of an 18-decimal token


def pool(address, asset, asset_reserve, quote_reserve, last_swap_ts, fee_bps=30,
         last_swap_block=None, quote=USDC):
    return PoolState(
        address=address,
        asset=asset,
        quote=quote,
        asset_reserve_raw=asset_reserve,
        quote_reserve_raw=quote_reserve,
        last_swap_block=last_swap_block if last_swap_block is not None else HORIZON_BLOCK - 10,
        last_swap_timestamp=last_swap_ts,
        fee_bps=fee_bps,
    )


def usd(dollars):
    """Dollars as raw USDC units."""
    return dollars * 10 ** 6


# -- a wallet's whole open book at the horizon ----------------------------------


def deep_pool_position():
    """10% of a $50,000 pool. Depth bites for ~9%, so the bound binds but the pool is healthy."""
    deep = pool("0xdeep", "0xdegen", 10 ** 25, usd(50_000), HORIZON_TS - 300)
    return mark_position(ONE_MILLION_TOKENS, deep, HORIZON_BLOCK, HORIZON_TS, USDC_PER_RAW)


def shallow_pool_position():
    """The §4.4 anecdote at production scale: a nominal $50,000 in a $2,000 pool."""
    thin = pool("0xthin", "0xhoney", 10 ** 25, usd(2_000), HORIZON_TS - 300)
    return mark_position(10 ** 26, thin, HORIZON_BLOCK, HORIZON_TS, USDC_PER_RAW)


def rugged_pool_position():
    """Liquidity pulled, no swap in 30 days, nowhere else to sell."""
    rugged = pool("0xrug", "0xrug", 10 ** 27, usd(1), HORIZON_TS - DEAD_INACTIVITY_SECONDS,
                  last_swap_block=HORIZON_BLOCK - 220_000)
    return mark_position(ONE_MILLION_TOKENS, rugged, HORIZON_BLOCK, HORIZON_TS, USDC_PER_RAW)


def migrated_pool_position():
    """v2 pool abandoned, liquidity live in the v3 pool for the same token."""
    old = pool("0xv2", "0xmigr", 10 ** 25, usd(3), HORIZON_TS - DEAD_INACTIVITY_SECONDS,
               last_swap_block=HORIZON_BLOCK - 220_000)
    new = pool("0xv3", "0xmigr", 10 ** 25, usd(40_000), HORIZON_TS - 120)
    return mark_position(ONE_MILLION_TOKENS, old, HORIZON_BLOCK, HORIZON_TS, USDC_PER_RAW,
                         replacement_pool=new)


def test_a_four_position_book_marks_to_four_different_bases():
    deep = deep_pool_position()
    thin = shallow_pool_position()
    rug = rugged_pool_position()
    migrated = migrated_pool_position()

    assert deep.value_basis is ValueBasis.LIQUIDITY_BOUND
    assert deep.pool_status is PoolStatus.LIVE
    assert Decimal("4500") < deep.value_usd < Decimal("4600"), "10% of a $50k pool, ~9% shortfall"

    assert thin.value_basis is ValueBasis.LIQUIDITY_BOUND
    assert thin.pool_status is PoolStatus.THIN
    assert thin.value_usd < Decimal("2000"), "cannot extract more than the pool holds"

    assert rug.value_basis is ValueBasis.DEAD_ZEROED
    assert rug.pool_status is PoolStatus.DEAD
    assert rug.value_usd == Decimal("0")

    assert migrated.pool_status is PoolStatus.MIGRATED
    assert migrated.value_basis is not ValueBasis.DEAD_ZEROED
    assert migrated.value_usd > Decimal("1000")


def test_the_book_decomposes_into_the_section_ten_shares():
    """§10: realized / marked / dead share, reported per wallet.

    If only 20% of a wallet's value is realized and 80% rests on marking, the score lacks
    credibility however positive it looks — so the mix has to survive alongside the number, and
    ``value_basis`` is what carries it.
    """
    realized_usd = Decimal("12000")  # one position sold inside the horizon, from FIFO
    open_marks = [deep_pool_position(), shallow_pool_position(), rugged_pool_position(),
                  migrated_pool_position()]

    marked_usd = sum((m.value_usd for m in open_marks
                      if m.value_basis in (ValueBasis.POOL_MARKED, ValueBasis.LIQUIDITY_BOUND)),
                     Decimal("0"))
    dead_usd = sum((m.value_usd for m in open_marks
                    if m.value_basis is ValueBasis.DEAD_ZEROED), Decimal("0"))
    total = realized_usd + marked_usd + dead_usd

    shares = [divide(part, total) for part in (realized_usd, marked_usd, dead_usd)]

    # The raw sum is 0.999...9, not 1: three ratios carried at 38 digits, added under Python's
    # ambient 28-digit context. That is the frozen policy working as designed — ratios are never
    # quantized before the final aggregation, and quantization happens exactly once, here, at the
    # reporting boundary.
    assert quantize_ratio(sum(shares)) == Decimal("1")
    assert dead_usd == Decimal("0"), "a zeroed position contributes zero value, by construction"
    assert shares[0] > Decimal("0.5"), "this book is majority realized"
    # The dead *share* is zero here while a dead *position* exists — which is exactly why §10
    # needs the count of zeroed positions too, not only their value.
    assert sum(1 for m in open_marks if m.value_basis is ValueBasis.DEAD_ZEROED) == 1


# -- the rug is not flat --------------------------------------------------------


def test_a_rug_marks_to_zero_rather_than_to_a_forward_filled_price():
    """The failure this module exists to prevent, stated as the difference between two numbers.

    Dune forward-fills daily prices for up to 30 days. A wallet that bought this token and
    watched the pool drain would appear flat instead of -100%, and every wallet that buys garbage
    would be flattered by the same amount.
    """
    last_observed_price_raw = divide(usd(80_000), 10 ** 25)  # before the liquidity was pulled
    forward_filled = multiply(ONE_MILLION_TOKENS, last_observed_price_raw, USDC_PER_RAW)

    rug = rugged_pool_position()

    assert forward_filled > Decimal("7000"), "the stale price would claim thousands of dollars"
    assert rug.value_usd == Decimal("0")
    assert rug.value_basis is ValueBasis.DEAD_ZEROED


def test_the_same_rugged_pool_is_not_zeroed_while_any_one_condition_fails():
    """Walk the conjunction one condition at a time against the same rugged reserves."""
    reserves = (10 ** 27, usd(1))

    still_trading = pool("0xrug", "0xrug", reserves[0], reserves[1], HORIZON_TS - DAY_SECONDS)
    value = mark_position(ONE_MILLION_TOKENS, still_trading, HORIZON_BLOCK, HORIZON_TS,
                          USDC_PER_RAW)
    assert value.value_basis is not ValueBasis.DEAD_ZEROED

    quiet_but_rich = pool("0xrug", "0xrug", 10 ** 25, usd(50_000),
                          HORIZON_TS - DEAD_INACTIVITY_SECONDS,
                          last_swap_block=HORIZON_BLOCK - 220_000)
    value = mark_position(ONE_MILLION_TOKENS, quiet_but_rich, HORIZON_BLOCK, HORIZON_TS,
                          USDC_PER_RAW)
    assert value.value_basis is not ValueBasis.DEAD_ZEROED
    assert value.pool_status is PoolStatus.QUIET

    assert migrated_pool_position().value_basis is not ValueBasis.DEAD_ZEROED


# -- the window-edge rule -------------------------------------------------------


def test_the_thirty_day_horizon_extends_past_the_end_of_the_window():
    """A buy five days before the window end is measured to day 30, twenty-five days past the
    window edge. The sample is not dropped and no partial return is substituted."""
    assert HORIZON_TS > WINDOW_END_TS

    at_window_end = pool("0xdeep", "0xdegen", 10 ** 25, usd(50_000), WINDOW_END_TS,
                         last_swap_block=WINDOW_END_BLOCK)
    value = mark_position(ONE_MILLION_TOKENS, at_window_end, HORIZON_BLOCK, HORIZON_TS,
                          USDC_PER_RAW)

    assert value.value_usd > 0
    assert value.pool_status is PoolStatus.LIVE, "25 days of silence is not yet the 30-day test"
    assert "cond1_no_swap_for_30d=false" in value.evidence
    assert "horizon_ts={}".format(HORIZON_TS) in value.evidence
    assert "horizon_block={}".format(HORIZON_BLOCK) in value.evidence


def test_a_snapshot_from_after_the_extended_horizon_is_still_refused():
    """The extension moves the horizon; it does not relax the look-ahead rule at the new one."""
    after = pool("0xdeep", "0xdegen", 10 ** 25, usd(50_000), HORIZON_TS + 1,
                 last_swap_block=HORIZON_BLOCK + 1)

    with pytest.raises(LookAheadViolation):
        mark_position(ONE_MILLION_TOKENS, after, HORIZON_BLOCK, HORIZON_TS, USDC_PER_RAW)


# -- migration and token age together -------------------------------------------


def test_a_migrated_token_keeps_its_age_and_its_first_hour_buy():
    """A wallet bought in the first 10 blocks of the token's life; the pool migrated on day 20;
    the position is marked at day 30 against the new pool.

    Two things must both hold, and they are easy to get wrong in opposite directions: the mark
    follows the liquidity, and the age does not. If migration reset the age, this first-hour buy
    would be re-classified as bucket D and the wallet's Edge Origin share would silently drop.
    """
    start_block, start_ts = 18_000_000, WINDOW_END_TS - 40 * DAY_SECONDS
    buy_block, buy_ts = start_block + 4, start_ts + 48

    bucket_at_buy = token_age_bucket(buy_block, buy_ts, start_block, start_ts)
    assert bucket_at_buy is TokenAgeBucket.A

    migrated = migrated_pool_position()
    assert migrated.pool_status is PoolStatus.MIGRATED

    # Re-derived after the migration, from the token's own trading start — unchanged.
    assert token_age_bucket(buy_block, buy_ts, start_block, start_ts) is TokenAgeBucket.A

    # A buy made at the migration itself is bucket D: the token is twenty days old.
    migration_block = start_block + 130_000
    migration_ts = start_ts + 20 * DAY_SECONDS
    assert token_age_bucket(migration_block, migration_ts, start_block, start_ts) \
        is TokenAgeBucket.D


def test_two_pools_for_one_token_are_priced_separately_and_the_venue_is_recorded():
    """"Multiple Pools for One Token" (§9.3). The same position is worth different amounts in
    different venues; nothing here silently picks the friendlier one, and the evidence names
    which pool produced the number."""
    shallow = pool("0xshallow", "0xdegen", 10 ** 25, usd(2_000), HORIZON_TS - 60)
    deep = pool("0xdeepest", "0xdegen", 10 ** 25, usd(50_000), HORIZON_TS - 60)

    in_shallow = mark_position(ONE_MILLION_TOKENS, shallow, HORIZON_BLOCK, HORIZON_TS,
                               USDC_PER_RAW)
    in_deep = mark_position(ONE_MILLION_TOKENS, deep, HORIZON_BLOCK, HORIZON_TS, USDC_PER_RAW)

    assert in_deep.value_usd > in_shallow.value_usd
    assert "venue=0xshallow" in in_shallow.evidence
    assert "venue=0xdeepest" in in_deep.evidence


def test_a_migration_into_a_pool_quoted_in_another_asset_is_quarantined():
    """The v2 TOKEN/USDC pool is abandoned; the live v3 pool for the same token is TOKEN/WETH.

    ``mark_position`` is handed one price — USD per raw USDC — so pricing the v3 pool's 100 WETH
    of reserve with it multiplies raw WETH by the raw-USDC price and overstates the mark by
    ``USDC_PER_RAW / WETH_PER_RAW`` = 1e-6 / 3e-15 = 3.33e8:

        exit = 1e24 * 9970 * 1e20 / (10_000 * 1e25 + 9970 * 1e24)
             = 9.066108938801...e18 raw WETH
        at the USDC price   -> $9,066,108,938,801.49        (a plausible-looking LIQUIDITY_BOUND)
        at the WETH price   ->        $27,198.33            (299_100_000 / 10997)

    The reverse pairing divides by 3.33e8 instead and manufactures a -100% rug out of a venue
    change. So the migration is quarantined rather than priced — and it is quarantined rather
    than *rejected*, because a rejected replacement satisfies §9.1 condition 3 and zeroes a
    position whose liquidity is demonstrably alive.
    """
    old = pool("0xv2", "0xmigr", 10 ** 25, usd(3), HORIZON_TS - THIRTY_DAYS_S,
               last_swap_block=HORIZON_BLOCK - 220_000)
    new = pool("0xv3", "0xmigr", 10 ** 25, 100 * 10 ** 18, HORIZON_TS - 120, quote=WETH)

    with pytest.raises(QuoteAssetMismatch):
        mark_position(ONE_MILLION_TOKENS, old, HORIZON_BLOCK, HORIZON_TS, USDC_PER_RAW,
                      replacement_pool=new)

    # Nothing is wrong with the pool — only with the price it was about to be paid at. Handed the
    # venue's own quote price, the very same exit is an ordinary mark, which is what makes this a
    # reconciliation item rather than a modelling gap.
    priced = mark_position(ONE_MILLION_TOKENS, new, HORIZON_BLOCK, HORIZON_TS, WETH_PER_RAW)
    assert quantize_usd(priced.value_usd) == Decimal("27198.326816")
    assert priced.value_basis is ValueBasis.LIQUIDITY_BOUND


def test_the_quarantine_does_not_fire_on_a_second_venue_the_mark_never_uses():
    """A TOKEN/WETH pool alongside a still-trading TOKEN/USDC primary is not a migration.

    The refusal has to be scoped to the venue that actually prices the exit, or every position
    with a second pool in another quote asset would leave the sample — a filter correlated with
    exactly the multi-pool tokens §9.3 says must stay in it.
    """
    live_primary = pool("0xv2", "0xmigr", 10 ** 25, usd(40_000), HORIZON_TS - 60)
    weth_venue = pool("0xv3", "0xmigr", 10 ** 25, 100 * 10 ** 18, HORIZON_TS - 120, quote=WETH)

    value = mark_position(ONE_MILLION_TOKENS, live_primary, HORIZON_BLOCK, HORIZON_TS,
                          USDC_PER_RAW, replacement_pool=weth_venue)

    assert "venue=0xv2" in value.evidence
    assert "venue_quote={}".format(USDC) in value.evidence
    assert value.pool_status is not PoolStatus.MIGRATED


def test_a_live_primary_pool_is_not_abandoned_for_a_replacement():
    """A replacement takes over only once the primary has gone quiet. While the primary still
    trades, that is where a follower would sell — and switching venues would amount to picking
    the friendlier of two prices after the fact."""
    live_but_thin = pool("0xv2", "0xmigr", 10 ** 25, usd(3), HORIZON_TS - 60)
    deeper = pool("0xv3", "0xmigr", 10 ** 25, usd(40_000), HORIZON_TS - 120)

    value = mark_position(ONE_MILLION_TOKENS, live_but_thin, HORIZON_BLOCK, HORIZON_TS,
                          USDC_PER_RAW, replacement_pool=deeper)

    assert "venue=0xv2" in value.evidence
    assert value.pool_status is not PoolStatus.MIGRATED
    assert value.value_usd < Decimal("3")


# -- the audit trail ------------------------------------------------------------


def test_the_whole_book_serializes_canonically_and_hashes_stably():
    """The canonical hash of a builder artifact goes in the freeze manifest, which is what lets
    ``gate_validation`` verify these marks without importing the code that produced them."""
    book = [deep_pool_position(), shallow_pool_position(), rugged_pool_position(),
            migrated_pool_position()]

    first = canonical_hash(book)
    again = canonical_hash([deep_pool_position(), shallow_pool_position(),
                            rugged_pool_position(), migrated_pool_position()])
    assert first == again

    envelope = artifact_envelope("position_values", "marking", book)
    assert envelope["payload_hash"]
    blob = to_canonical_json(envelope)
    assert "DEAD_ZEROED" in blob and "LIQUIDITY_BOUND" in blob and "MIGRATED" in blob


def test_every_mark_carries_enough_evidence_to_be_re_derived():
    """§9.2 reconciles two independent computations to 0.5% "provided both use the same block,
    the same pool, and the same liquidity-bound rule" — so the record has to name all three."""
    for value in (deep_pool_position(), rugged_pool_position(), migrated_pool_position()):
        joined = " ".join(value.evidence)
        assert "venue=" in joined
        assert "model=" in joined
        assert "horizon_block=" in joined
        assert "fee_bps=" in joined
        assert "cond1_no_swap_for_30d=" in joined
        assert "cond2_exit_below_minimum=" in joined
        assert "cond3_no_validated_replacement=" in joined
