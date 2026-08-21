"""Worked composed runs whose answers were computed by hand before the code existed.

Every expected number below is arithmetic written out in the comment above it. The pool figures are
derived from the constant-product formulas in ``marking.liquidity`` on paper, not read back from a
run, and the reserves are chosen so that the answers land on exact decimals — a hand-computed test
whose expectation is a repeating fraction is a hand-computed test nobody re-checks.

Price book convention, as everywhere in this repository: **USD per raw unit.** USDC has 6 decimals
at $1, so one raw unit is $0.000001.

The shared pool arithmetic, once, so the individual cases can cite it:

    asset reserve X = 4,000 TOKEN = 4e21 raw       fee_bps = 0
    position q      = 4,000 TOKEN = 4e21 raw       (the whole reserve — a deliberately brutal exit)

    spot price      = R / X                        raw quote per raw asset
    spot value      = q * (R / X) * 1e-6           = R * 1e-6           (since q = X)
    average price   = 10000*R / (10000*X + 10000*q) = R / (X + q) = R / 2X
    exit value      = q * (R / 2X) * 1e-6          = R * 1e-6 / 2

So with a quote reserve of R raw USDC the mark is **half the spot mark**, exactly, and the two are
$R/1e6 and $R/2e6. R = 1e9 gives spot $1,000 and exit $500; R = 1.5e9 gives spot $1,500 and exit
$750; R = 1,000 gives spot $0.001 and exit $0.0005, which is below the $1 minimum exit value and is
one of the three conditions a dead pool needs.
"""

import dataclasses
from decimal import ROUND_DOWN, Context, Decimal, localcontext

import pytest

from contracts import (
    AttributionMethod,
    CALCULATION_CONTEXT,
    ClassificationStatus,
    NATIVE_ETH,
    PoolState,
    PoolStatus,
    TokenAgeBucket,
    Transfer,
    USDC,
    ValueBasis,
    WETH,
    quantize_ratio,
)
from attribution import AttributionContext
from marking import DEAD_INACTIVITY_SECONDS, MINIMUM_EXIT_VALUE_USD
from netting import RESIDUAL_FLOOR_USD
from scoring import trade_weight
from pipeline import (
    MEASUREMENT_HORIZON_SECONDS,
    ObservedTransaction,
    QuarantineQueue,
    QuarantineRecord,
    STAGE_ORDER,
    Stage,
    TokenStart,
    Window,
    WindowConfig,
    run_wallet_window,
)

# -- the shared world -----------------------------------------------------------

WALLET = "0x" + "a1" * 20
WALLET_B = "0x" + "a2" * 20
STRANGER = "0x" + "a9" * 20

POOL_R = "0x" + "b1" * 20   # spot $1,000 / exit $500, live
POOL_M = "0x" + "b2" * 20   # spot $1,000 / exit $500, live
POOL_H = "0x" + "b4" * 20   # spot $1,500 / exit $750, live
POOL_D = "0x" + "b3" * 20   # spot $0.001 / exit $0.0005, silent for 30 days

TOKEN_R = "0x" + "c1" * 20
TOKEN_M = "0x" + "c2" * 20
TOKEN_D = "0x" + "c3" * 20
TOKEN_H = "0x" + "c4" * 20
TOKEN_X = "0x" + "c8" * 20   # long-tail, never priced
TOKEN_Y = "0x" + "c9" * 20   # long-tail, never priced

ONE_USDC = 10 ** 6
ONE_TOKEN = 10 ** 18

START_BLOCK = 18_000_000
START_TS = 1_700_000_000
END_BLOCK = START_BLOCK + 7_200
END_TS = START_TS + 86_400
HORIZON_BLOCK = END_BLOCK + 216_000
HORIZON_TS = END_TS + MEASUREMENT_HORIZON_SECONDS

PRICES = {USDC: Decimal("0.000001")}

WINDOW = Window(index=3, start_block=START_BLOCK, start_ts=START_TS,
                end_block=END_BLOCK, end_ts=END_TS)

CONTEXT = AttributionContext(
    infrastructure=frozenset({POOL_R, POOL_M, POOL_D, POOL_H}),
    eoas=frozenset({WALLET, WALLET_B, STRANGER}),
)


def pool(address, asset, quote_reserve_raw, last_swap_ts=HORIZON_TS,
         last_swap_block=HORIZON_BLOCK, asset_reserve_raw=4_000 * ONE_TOKEN):
    return PoolState(
        address=address, asset=asset, quote=USDC,
        asset_reserve_raw=asset_reserve_raw, quote_reserve_raw=quote_reserve_raw,
        last_swap_block=last_swap_block, last_swap_timestamp=last_swap_ts, fee_bps=0,
    )


POOLS = {
    TOKEN_R: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC),
    TOKEN_M: pool(POOL_M, TOKEN_M, 1_000 * ONE_USDC),
    TOKEN_H: pool(POOL_H, TOKEN_H, 1_500 * ONE_USDC),
    TOKEN_D: pool(POOL_D, TOKEN_D, 1_000,
                  last_swap_ts=HORIZON_TS - DEAD_INACTIVITY_SECONDS,
                  last_swap_block=HORIZON_BLOCK - 216_000),
}

#: §4.7 trading starts. TOKEN_R and TOKEN_H are old (bucket D); TOKEN_M and TOKEN_D start with the
#: window, so buys a few blocks in land in bucket A.
TOKEN_STARTS = {
    TOKEN_R: TokenStart(block=START_BLOCK - 100_000, timestamp=START_TS - 1_000_000),
    TOKEN_H: TokenStart(block=START_BLOCK - 100_000, timestamp=START_TS - 1_000_000),
    TOKEN_M: TokenStart(block=START_BLOCK, timestamp=START_TS),
    TOKEN_D: TokenStart(block=START_BLOCK, timestamp=START_TS),
}

CONFIG = WindowConfig(
    horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS, token_starts=TOKEN_STARTS,
)


def transfer(token, from_addr, to_addr, raw, index, is_fee=False):
    return Transfer(token=token, from_addr=from_addr, to_addr=to_addr, raw_amount=raw,
                    log_index=index, is_fee=is_fee)


def observed(tx_hash, nth, transfers, sender=WALLET, success=True, context=CONTEXT,
             block=None, timestamp=None):
    """One transaction ``nth`` blocks into the window. Block and timestamp move together — the seam
    pairs every stamp with a block and never carries one alone."""
    return ObservedTransaction(
        tx_hash=tx_hash,
        block_number=START_BLOCK + nth if block is None else block,
        timestamp=START_TS + nth * 12 if timestamp is None else timestamp,
        success=success,
        tx_sender=sender,
        transfers=tuple(transfers),
        context=context,
    )


def buy(tx_hash, nth, token, usdc, tokens, wallet=WALLET, venue=None):
    venue = venue or POOL_R
    return observed(tx_hash, nth, [
        transfer(USDC, wallet, venue, usdc, 0),
        transfer(token, venue, wallet, tokens, 1),
    ], sender=wallet)


def sell(tx_hash, nth, token, tokens, usdc, wallet=WALLET, venue=None, timestamp=None,
         block=None):
    venue = venue or POOL_R
    return observed(tx_hash, nth, [
        transfer(token, wallet, venue, tokens, 0),
        transfer(USDC, venue, wallet, usdc, 1),
    ], sender=wallet, timestamp=timestamp, block=block)


def run(transactions, pools=None, prices=None, window=WINDOW, config=CONFIG):
    return run_wallet_window(
        transactions,
        POOLS if pools is None else pools,
        PRICES if prices is None else prices,
        window,
        config,
    )


def uncollapsed_eth_swap(tx_hash, nth, wallet=WALLET):
    """A swap that reaches netting still carrying the native-ETH sentinel, so netting refuses it.

    ``Transfer`` collapses ETH onto WETH at construction (§4.2), so netting's ``QuarantineRequired``
    is reachable only by bypassing the seam — exactly as ``hand_computed/test_netting.py`` does for
    the same branch. It is worth the bypass here: this is the *only* refusal netting raises, so
    without it the composition's handling of a netting-stage quarantine is never executed at all,
    and every assertion about that queue entry is an assertion about a hand-built record instead.

    There were two bypasses, not one. ``object.__setattr__`` on a constructed leg is the one used
    here; the other was a subclass of ``Transfer`` with a no-op ``__post_init__``, which
    ``ObservedTransaction`` used to admit because it checked ``isinstance``. That one is closed —
    see ``test_a_transfer_subclass_that_skips_the_seam_is_refused`` — so this really is the
    remaining route, which it was not when the sentence was first written.
    """
    leg = transfer(WETH, wallet, POOL_R, ONE_TOKEN, 0)
    object.__setattr__(leg, "token", NATIVE_ETH)
    return observed(tx_hash, nth, [
        leg,
        transfer(TOKEN_R, POOL_R, wallet, 4_000 * ONE_TOKEN, 1),
    ], sender=wallet)


def order_of(result):
    """``(block, tx_hash)`` per netted result, in the order the result publishes them."""
    return tuple((r.block_number, r.tx_hash) for r in result.results)


def account(result, tx_hash):
    for item in result.accounts:
        if item.buy.tx_hash == tx_hash:
            return item
    raise AssertionError("no account for {}; accounts are {}".format(
        tx_hash, [a.buy.tx_hash for a in result.accounts]))


# -- the constant that everything else is measured against ----------------------


def test_the_measurement_horizon_is_exactly_thirty_days():
    """§4.4 measures each buy over the following 30 days. Pinned against the literal from both
    sides, because a test that spells this ``30 * 86400`` moves with the constant and pins nothing:
    lengthening the horizon lets a loser recover before it is marked, which is the direction that
    flatters the hypothesis."""
    assert MEASUREMENT_HORIZON_SECONDS == 2_592_000
    assert MEASUREMENT_HORIZON_SECONDS // 86_400 == 30


# -- §4.4 Case 1: sold inside the horizon ---------------------------------------


def test_a_realized_buy_returns_proceeds_over_cost_and_marks_nothing():
    """Buy 4,000 TOKEN_R for 1,000 USDC; sell all of it for 1,500 USDC on the same day.

        realized return = 1,500 / 1,000 - 1 = 0.5

    The whole position is realized, so there is nothing left to mark and the §10 mix is entirely
    realized. ``position`` is ``None`` rather than a zero-valued mark: a fully sold buy has no open
    remainder, and a ``PositionValue`` of $0 would be indistinguishable from a dead pool.
    """
    result = run([
        buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        sell("0xs1", 2, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC),
    ])

    row = account(result, "0xb1")
    assert row.return_pct == Decimal("0.5")
    assert row.realized_raw == 4_000 * ONE_TOKEN
    assert row.open_raw == 0
    assert row.late_sold_raw == 0
    assert row.position is None
    assert row.realized_proceeds_usd == Decimal("1500")
    assert row.marked_usd == Decimal("0")
    assert row.dead_usd == Decimal("0")

    quality = result.qualities[WALLET]
    assert quality.realized_share == Decimal("1")
    assert quality.marked_share == Decimal("0")
    assert quality.dead_share == Decimal("0")
    # One buy, so the weighted mean is that buy's return whatever the weight is — to the last of
    # the 38 digits, where ``weighted_mean`` rounds ``w * r`` before dividing by ``w`` and the
    # trailing zero of the hand answer becomes a one. Both forms are asserted: the exact value so
    # the arithmetic is reproducible, and the value at SCALE_RATIO, the scale a return is actually
    # published at, so the hand answer is the one being checked.
    assert quality.value == Decimal("0.50000000000000000000000000000000000001")
    assert quantize_ratio(quality.value) == Decimal("0.50000000")


# -- §4.4 Case 2: still open at the horizon -------------------------------------


def test_an_open_position_is_marked_at_the_liquidity_bound_not_at_spot():
    """Buy 4,000 TOKEN_M for 1,000 USDC and never sell it.

        spot mark  = 4e21 * (1e9 / 4e21) * 1e-6 = $1,000
        exit mark  = 4e21 * (1e9 / 8e21) * 1e-6 = $500
        §4.4 takes the minimum                  = $500
        return     = 500 / 1,000 - 1            = -0.5

    The spot mark is the number a pool-level OHLCV feed reports and it is exactly twice the truth
    here. §4.4's liquidity bound is mandatory for that reason, and the assertion below is on the
    *bounded* figure — if the ``min()`` ever inverted, the return would read -0.0 instead of -0.5
    and nothing else in the run would look different.
    """
    result = run([buy("0xb2", 2, TOKEN_M, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_M)])

    row = account(result, "0xb2")
    assert row.open_raw == 4_000 * ONE_TOKEN
    assert row.realized_raw == 0
    assert row.position.value_usd == Decimal("500")
    assert row.position.value_basis is ValueBasis.LIQUIDITY_BOUND
    assert row.position.pool_status is PoolStatus.THIN
    assert "spot_usd=1000.00000000000000000000" in row.position.evidence
    assert "extractable_usd=500.000000000000000000000" in row.position.evidence
    assert row.marked_usd == Decimal("500")
    assert row.dead_usd == Decimal("0")
    assert row.return_pct == Decimal("-0.5")

    quality = result.qualities[WALLET]
    assert quality.realized_share == Decimal("0")
    assert quality.marked_share == Decimal("1")
    assert quality.dead_share == Decimal("0")


# -- §4.4 Case 3: dead pool -----------------------------------------------------


def test_a_dead_pool_zeroes_the_value_and_reports_the_exposure_as_the_dead_share():
    """Buy 4,000 TOKEN_D for 500 USDC into a pool that then goes silent for exactly 30 days.

        exit mark = 4e21 * (1000 / 8e21) * 1e-6 = $0.0005   < the $1.00 minimum
        no swap for 2,592,000s, no replacement            -> all three conditions hold
        marked value = $0                                  (§4.4 Case 3)
        return       = 0 / 500 - 1 = -1

    ``dead_usd`` is the **exposure the zero verdict decided** — the $500 of basis that was open —
    not the resulting $0. Reading it as the value would make the dead share structurally zero and
    delete from §10 the one basis it most wants visible: a run that zeroed half its volume would
    report a dead share of 0%.
    """
    result = run([buy("0xb3", 3, TOKEN_D, 500 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_D)])

    row = account(result, "0xb3")
    assert row.position.value_usd == Decimal("0")
    assert row.position.value_basis is ValueBasis.DEAD_ZEROED
    assert row.position.pool_status is PoolStatus.DEAD
    assert row.marked_usd == Decimal("0")
    assert row.dead_usd == Decimal("500")
    assert row.return_pct == Decimal("-1")

    quality = result.qualities[WALLET]
    assert quality.dead_share == Decimal("1")
    assert quality.realized_share == Decimal("0")
    assert quality.marked_share == Decimal("0")


def test_the_dead_exit_is_below_the_pinned_minimum_and_the_live_one_is_far_above_it():
    """The dead case is only a dead case because of a threshold, so the threshold is named here.

    Without this, raising ``MINIMUM_EXIT_VALUE_USD`` a thousandfold would leave the case above
    green while silently converting every thin-but-live position in the run into a rug.
    """
    assert MINIMUM_EXIT_VALUE_USD == Decimal("1.00")
    assert Decimal("0.0005") < MINIMUM_EXIT_VALUE_USD
    assert Decimal("500") > MINIMUM_EXIT_VALUE_USD


# -- §10: the mix survives composition ------------------------------------------


def test_the_three_shares_travel_with_the_score_and_sum_to_one():
    """One wallet, one of each case:

        realized  1,500 (sold TOKEN_R)
        marked      500 (TOKEN_M open, liquidity-bounded)
        dead        500 (TOKEN_D exposure zeroed)
        total     2,500  ->  0.6 / 0.2 / 0.2

    This is the number §10 says decides whether the gate result is credible at all. It is asserted
    at the *top level* rather than per buy, because the failure mode is not a stage computing the
    mix wrongly — no stage does — it is the composition returning a bare number and the mix having
    nowhere to travel.
    """
    result = run([
        buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        buy("0xb2", 2, TOKEN_M, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_M),
        buy("0xb3", 3, TOKEN_D, 500 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_D),
        sell("0xs1", 4, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC),
    ])

    quality = result.qualities[WALLET]
    assert quality.n_buys == 3
    assert quality.realized_share == Decimal("0.6")
    assert quality.marked_share == Decimal("0.2")
    assert quality.dead_share == Decimal("0.2")

    # §4.7 buckets: TOKEN_R started 100,000 blocks before the window (D); TOKEN_M and TOKEN_D
    # started with it, and both buys land within 10 blocks of that start (A).
    assert account(result, "0xb1").bucket is TokenAgeBucket.D
    assert account(result, "0xb2").bucket is TokenAgeBucket.A
    assert account(result, "0xb3").bucket is TokenAgeBucket.A
    assert set(quality.bucket_weights) == {TokenAgeBucket.A, TokenAgeBucket.D}


# -- §4.4 aggregation -----------------------------------------------------------


def test_equal_trade_values_make_the_score_the_plain_mean_of_the_returns():
    """Two $1,000 buys weigh the same whatever the base of the log, so the weight divides out:

        buy 1  sold for $1,500          -> +0.5
        buy 2  open, marked at $750     -> 750/1,000 - 1 = -0.25
        buy_quality = (0.5 + -0.25) / 2 = 0.125

    Hand-computable end to end and independent of ``ln`` entirely, which is what makes it the test
    that would catch a weighting that used raw USD instead of ``log(1 + usd)``: with raw weights the
    two are still equal and this case would pass. The unequal-value case below is the one that
    separates them, and it is why both exist.
    """
    result = run([
        buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        buy("0xb4", 2, TOKEN_H, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_H),
        sell("0xs1", 3, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC),
    ])

    assert account(result, "0xb1").return_pct == Decimal("0.5")
    assert account(result, "0xb4").marked_usd == Decimal("750")
    assert account(result, "0xb4").return_pct == Decimal("-0.25")
    assert quantize_ratio(result.qualities[WALLET].value) == Decimal("0.12500000")


def test_log_weighting_pulls_the_score_toward_the_larger_trade_but_only_logarithmically():
    """Three buys, returns +0.5, -0.5 and -1.0, trade values $1,000, $1,000 and $500.

    The first two cancel exactly, so the score is the third's return shrunk by the weight it holds:

        buy_quality = -ln(501) / (2*ln(1001) + ln(501))

    ln is irrational, so the expected value is the 38-digit evaluation of that expression, pinned as
    a literal. The two assertions after it are the ones that do not depend on the constant at all
    and would survive re-deriving it: the score must sit strictly between the unweighted mean of the
    three returns (-1/3, which the smallest trade would get if every trade weighed the same) and the
    third return itself (-1, which it would get if weights were proportional to nothing). A raw-USD
    weighting puts it at -0.4; equal weighting puts it at -1/3; only the log lands here.
    """
    result = run([
        buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        buy("0xb2", 2, TOKEN_M, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_M),
        buy("0xb3", 3, TOKEN_D, 500 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_D),
        sell("0xs1", 4, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC),
    ])

    value = result.qualities[WALLET].value
    assert value == Decimal("-0.31030099888987092135128045519817795520")

    with localcontext(CALCULATION_CONTEXT):
        equal_weighted = Decimal("-1") / Decimal("3")
    assert equal_weighted < value < Decimal("0")
    assert value != Decimal("-0.4")  # what proportional-to-USD weighting would give


# -- the 30-day boundary --------------------------------------------------------


def test_a_sale_on_the_last_second_of_the_horizon_realizes_the_buy():
    """The boundary from the inside: ``sell_ts - buy_ts == 2,592,000`` is inside the horizon."""
    entry = buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)
    exit_ts = entry.timestamp + MEASUREMENT_HORIZON_SECONDS
    result = run([
        entry,
        sell("0xs1", 0, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC,
             block=START_BLOCK + 200_000, timestamp=exit_ts),
    ])

    row = account(result, "0xb1")
    assert row.realized_raw == 4_000 * ONE_TOKEN
    assert row.late_sold_raw == 0
    assert row.position is None
    assert row.return_pct == Decimal("0.5")


def test_a_sale_one_second_past_the_horizon_does_not_realize_the_buy():
    """The boundary from the outside, and the reason it is a boundary rather than a convenience.

    The same trade one second later was **not** a 30-day outcome. §4.4 Case 2 governs it: the
    position was still held at day 30, so it is marked at day 30's liquidity, and the $1,500 the
    wallet eventually got is not part of this window's measurement. Folding it in would read every
    late recovery as though it had been captured inside the horizon, which flatters exactly the
    wallets that hold losers — and it would do so invisibly, because the realized figure is the one
    nobody re-checks.

        marked at the bound = $500        (the pool, unchanged)
        return              = 500 / 1,000 - 1 = -0.5

    The quantity is still counted: ``late_sold_raw`` is the whole position, so a reader can see that
    the mark stands in for a sale that did happen rather than for a bag still held.
    """
    entry = buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)
    exit_ts = entry.timestamp + MEASUREMENT_HORIZON_SECONDS + 1
    result = run([
        entry,
        sell("0xs1", 0, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC,
             block=START_BLOCK + 200_000, timestamp=exit_ts),
    ])

    row = account(result, "0xb1")
    assert row.realized_raw == 0
    assert row.late_sold_raw == 4_000 * ONE_TOKEN
    assert row.open_raw == 4_000 * ONE_TOKEN
    assert row.realized_proceeds_usd == Decimal("0")
    assert row.marked_usd == Decimal("500")
    assert row.return_pct == Decimal("-0.5")
    # The sell is still a counted trade — it just is not this buy's outcome.
    assert result.census.counts[ClassificationStatus.VALID_SELL] == 1
    assert result.stages.consumptions == 1


def test_each_buy_reports_how_far_the_run_horizon_sits_past_its_own():
    """The one approximation this composition makes, published rather than assumed away.

    §4.4 gives every buy its own day 30; the seam supplies one ``PoolState`` per pool, so the run
    marks at a single window-level horizon. The gap is a number on every account, so a reader can
    see when a mark is really a day-45 mark instead of taking it on trust.
    """
    entry = buy("0xb2", 5, TOKEN_M, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_M)
    result = run([entry])

    row = account(result, "0xb2")
    assert row.buy_horizon_ts == entry.timestamp + MEASUREMENT_HORIZON_SECONDS
    # The window is one day long and the buy is 60 seconds into it, so the run's horizon
    # (window end + 30 days) sits 86,400 - 60 = 86,340 seconds past this buy's own.
    assert row.horizon_lag_seconds == 86_400 - 60


# -- refusals that keep the population honest -----------------------------------


def test_a_buy_with_no_token_trading_start_is_quarantined_rather_than_bucketed_as_D():
    """An unknown-age buy filed as bucket D is filed *outside the first hour* — the exact
    classification §7.1's Edge Origin condition is trying to measure. So it is refused."""
    config = dataclasses.replace(CONFIG, token_starts={})
    result = run([buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)], config=config)

    assert result.stages.buys == 1
    assert result.stages.buys_scored == 0
    assert result.stages.buys_quarantined == 1
    assert len(result.quarantine) == 1
    record = result.quarantine.records[0]
    assert record.stage is Stage.MARKING
    assert record.tx_hashes == ("0xb1",)
    assert record.volume_usd == Decimal("1000")
    assert "token trading start" in record.reason
    assert WALLET in result.unscorable


def test_an_open_position_with_no_pool_is_quarantined_rather_than_zeroed():
    """Zero because a pool is dead is a measurement; zero because no pool was supplied is the
    absence of one, and the two must not arrive downstream wearing the same clothes."""
    result = run([buy("0xb2", 2, TOKEN_M, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_M)],
                 pools={})

    assert result.stages.buys_quarantined == 1
    assert result.quarantine.records[0].stage is Stage.MARKING
    assert "no pool state was supplied" in result.quarantine.records[0].reason
    assert result.quarantine.total_volume_usd == Decimal("1000")


def test_a_sell_with_no_matching_buy_quarantines_the_whole_book_with_its_volume():
    """A book missing half its events is not a smaller book, it is a wrong one.

    The wallet sells 4,000 TOKEN_R it never bought here. FIFO refuses rather than clamping, and the
    composition sends the whole ``(wallet, asset)`` book to the queue — both transactions — with the
    summed volume attached, so the queue can be worked and sorted by how much money is in it.
    """
    result = run([
        buy("0xb4", 1, TOKEN_H, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_H),
        sell("0xs1", 2, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC),
    ])

    fifo_records = result.quarantine.by_stage(Stage.FIFO)
    assert len(fifo_records) == 1
    assert fifo_records[0].tx_hashes == ("0xs1",)
    assert fifo_records[0].asset == TOKEN_R
    assert fifo_records[0].volume_usd == Decimal("1500")
    assert result.stages.fifo_books == 2
    assert result.stages.fifo_books_quarantined == 1
    assert result.stages.sells_quarantined == 1
    # The other book is untouched: one wallet's broken asset does not erase its good one.
    assert result.qualities[WALLET].n_buys == 1


def test_an_unusable_attribution_is_excluded_counted_and_named():
    """A batch settling two typed EOAs has two owners and one owner slot, so attribution refuses.

    §8 excludes it from the primary metric. The composition must not let that be a silent shrink:
    the transaction is counted in ``attributions_excluded``, named in ``excluded`` with the method
    that refused it, and appears in the census as ``UNSUPPORTED`` — split out from the *other*
    reason netting says ``UNSUPPORTED``, which is a missing quote price and calls for entirely
    different work.
    """
    batch = observed("0xbatch", 1, [
        transfer(USDC, WALLET, POOL_R, 1_000 * ONE_USDC, 0),
        transfer(TOKEN_R, POOL_R, WALLET, 4_000 * ONE_TOKEN, 1),
        transfer(USDC, WALLET_B, POOL_R, 1_000 * ONE_USDC, 2),
        transfer(TOKEN_R, POOL_R, WALLET_B, 4_000 * ONE_TOKEN, 3),
    ], sender=STRANGER)
    result = run([batch])

    assert result.stages.attributions_excluded == 1
    assert result.stages.attributions_usable == 0
    assert len(result.excluded) == 1
    assert result.excluded[0].tx_hash == "0xbatch"
    assert result.excluded[0].method is AttributionMethod.UNRESOLVED
    assert result.census.counts[ClassificationStatus.UNSUPPORTED] == 1
    assert result.census.unsupported_from_attribution == 1
    assert result.census.unsupported_from_pricing == 0
    assert result.census.trades == 0


def test_the_two_findings_netting_calls_unsupported_are_counted_apart():
    """``UNSUPPORTED`` covers an owner §8 refused *and* a trade whose quote leg had no price.

    The test above proves the attribution half is counted. It cannot see the split, because the
    other half is zero in its fixture — and a count that is only ever exercised at zero is a count
    nobody has checked. The dangerous condition is **"the two halves are separated by which
    transactions §8 excluded, not by which status they landed in"**, so all three populations are
    run: one of each, and one of both. They call for entirely different work — the first sends
    somebody to attribution, the second to the price book — and a single number covering both is a
    coverage report that cannot be acted on.
    """
    batch = observed("0xbatch", 1, [
        transfer(USDC, WALLET, POOL_R, 1_000 * ONE_USDC, 0),
        transfer(TOKEN_R, POOL_R, WALLET, 4_000 * ONE_TOKEN, 1),
        transfer(USDC, WALLET_B, POOL_R, 1_000 * ONE_USDC, 2),
        transfer(TOKEN_R, POOL_R, WALLET_B, 4_000 * ONE_TOKEN, 3),
    ], sender=STRANGER)
    # WETH is a §4.6 quote asset, so this is a well-formed buy with a resolvable owner. What it
    # does not have is a WETH entry in the price book, so its size is not computable.
    unpriced_quote = observed("0xweth", 2, [
        transfer(WETH, WALLET, POOL_R, ONE_TOKEN, 0),
        transfer(TOKEN_R, POOL_R, WALLET, 4_000 * ONE_TOKEN, 1),
    ])

    attribution_only = run([batch])
    assert attribution_only.census.counts[ClassificationStatus.UNSUPPORTED] == 1
    assert attribution_only.census.unsupported_from_attribution == 1
    assert attribution_only.census.unsupported_from_pricing == 0

    pricing_only = run([unpriced_quote])
    assert pricing_only.census.counts[ClassificationStatus.UNSUPPORTED] == 1
    assert pricing_only.census.unsupported_from_attribution == 0
    assert pricing_only.census.unsupported_from_pricing == 1
    assert pricing_only.stages.attributions_excluded == 0

    both = run([batch, unpriced_quote])
    assert both.census.counts[ClassificationStatus.UNSUPPORTED] == 2
    assert both.census.unsupported_from_attribution == 1
    assert both.census.unsupported_from_pricing == 1
    assert both.stages.attributions_excluded == 1


def test_a_reverted_transaction_is_a_counted_status_not_a_dropped_row():
    """§4.1 requires ``meta.err == null``. The transaction still happened and is still counted."""
    result = run([
        observed("0xfail", 1, [
            transfer(USDC, WALLET, POOL_R, 1_000 * ONE_USDC, 0),
            transfer(TOKEN_R, POOL_R, WALLET, 4_000 * ONE_TOKEN, 1),
        ], success=False),
    ])

    assert result.census.counts[ClassificationStatus.FAILED_TRANSACTION] == 1
    assert result.census.total == 1
    assert result.stages.netted == 1
    assert result.stages.buys == 0


def test_the_census_accounts_for_every_transaction_it_saw():
    """The reconciliation the whole result type exists for: nothing leaves without a line."""
    result = run([
        buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        sell("0xs1", 2, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC),
        observed("0xfail", 3, [
            transfer(USDC, WALLET, POOL_R, 1_000 * ONE_USDC, 0),
            transfer(TOKEN_R, POOL_R, WALLET, 4_000 * ONE_TOKEN, 1),
        ], success=False),
        observed("0xdust", 4, [transfer(USDC, WALLET, STRANGER, ONE_USDC, 0)]),
    ])

    assert result.census.total == 4
    assert sum(result.census.counts.values()) + result.census.quarantined == 4
    assert result.census.counts[ClassificationStatus.VALID_BUY] == 1
    assert result.census.counts[ClassificationStatus.VALID_SELL] == 1
    assert result.census.counts[ClassificationStatus.FAILED_TRANSACTION] == 1
    assert result.census.counts[ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL] == 1
    assert dict(result.reconciliation())["transactions_in"] == 4


# -- configuration refusals -----------------------------------------------------


def test_a_horizon_short_of_thirty_days_past_the_window_end_is_refused():
    """§4.8: the measurement is permitted to run 30 days past the window edge exactly so that no
    sample is dropped and no partial return is used. A shorter horizon leaves the window's last buy
    with fewer than 30 days, and its partial return is indistinguishable from a whole one."""
    short = WindowConfig(horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS - 1,
                         token_starts=TOKEN_STARTS)
    with pytest.raises(ValueError) as refusal:
        run([buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)], config=short)
    assert "partial return" in str(refusal.value)


def test_a_horizon_exactly_thirty_days_past_the_window_end_is_accepted():
    """The other side of the same boundary, so the comparison's strictness cannot drift."""
    assert CONFIG.horizon_ts == END_TS + 2_592_000
    result = run([buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)])
    assert result.stages.buys_scored == 1


def test_a_transaction_after_the_marking_horizon_is_refused():
    """A trade the horizon cannot see would enter the metric as look-ahead."""
    with pytest.raises(ValueError) as refusal:
        run([sell("0xs1", 0, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC,
                  block=HORIZON_BLOCK + 1, timestamp=HORIZON_TS + 1)])
    assert "look-ahead" in str(refusal.value)


def test_a_transaction_before_the_window_starts_is_refused():
    with pytest.raises(ValueError) as refusal:
        run([buy("0xb1", -1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)])
    assert "before window" in str(refusal.value)


def test_a_buy_after_the_window_ends_opens_a_lot_but_is_not_scored():
    """§4.8's measurement tail. The buy belongs to the next window, but it must still open a lot or
    the tail's sell would be matched against a basis that is not the one it consumed — and FIFO
    would then quarantine a book that is in fact perfectly well formed."""
    tail_block = END_BLOCK + 1_000
    tail_ts = END_TS + 12_000
    result = run([
        observed("0xtail", 0, [
            transfer(USDC, WALLET, POOL_R, 1_000 * ONE_USDC, 0),
            transfer(TOKEN_R, POOL_R, WALLET, 4_000 * ONE_TOKEN, 1),
        ], block=tail_block, timestamp=tail_ts),
        observed("0xtailsell", 0, [
            transfer(TOKEN_R, WALLET, POOL_R, 4_000 * ONE_TOKEN, 0),
            transfer(USDC, POOL_R, WALLET, 1_500 * ONE_USDC, 1),
        ], block=tail_block + 10, timestamp=tail_ts + 120),
    ])

    assert result.stages.buys == 1
    assert result.stages.buys_outside_window == 1
    assert result.stages.buys_scored == 0
    assert result.stages.consumptions == 1
    assert len(result.quarantine) == 0
    assert WALLET in result.unscorable


# -- one tx_hash, one transaction -----------------------------------------------
#
# ``tx_hash`` is the identity key the composition counts with: a buy's FIFO consumptions are
# gathered under it, the transactions that left the population are recorded under it, the census
# split is keyed on it, and every queue record names its transactions with it. Two rows sharing a
# hash therefore do not produce a smaller answer, they produce a wrong one that looks plausible —
# one book's sale is handed to a different book's buy, and §10's realized/marked/dead mix reports
# maximum credibility on a number nothing measured.
#
# The control below is the answer the run must not move off. The cases after it are the four shapes
# a shared hash can take, plus the two the shapes hide behind: a normalisation variant that collapses
# at ``ObservedTransaction.__post_init__``, and a pair that only separates once the window filter has
# run. Every one of them is refused at the boundary, which is the only place a single check reaches
# all six.


def _colliding_pair(first_hash, second_hash):
    """Two buys and one sell: TOKEN_R bought and held, TOKEN_H bought and sold at 3x.

    Hand-computed with distinct hashes, and pinned as the control below:

        0xr   buy 4,000 TOKEN_R for $1,000, never sold
              exit mark = 1e9 * 1e-6 / 2 = $500        (POOL_R, the shared arithmetic above)
              return    = 500 / 1,000 - 1  = -0.5
        0xh   buy 4,000 TOKEN_H for $1,000, all of it sold for $3,000 inside the horizon
              return    = 3,000 / 1,000 - 1 = 2

        §10 mix   realized 3,000 · marked 500 · dead 0   ->  6/7 and 1/7
        weights   equal, both buys cost $1,000           ->  (-0.5 + 2) / 2 = 0.75
    """
    return [
        buy(first_hash, 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        buy(second_hash, 2, TOKEN_H, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_H),
        sell("0xsellh", 3, TOKEN_H, 4_000 * ONE_TOKEN, 3_000 * ONE_USDC, venue=POOL_H),
    ]


def test_the_control_two_distinct_hashes_score_three_quarters_on_a_mostly_realized_mix():
    """The correct answer for the shape below, as literals, so the refusal has something to protect.

    Without this the duplicate cases assert only that *something* was refused, and a later repair
    that silently kept the first of two rows would leave every one of them green.
    """
    result = run(_colliding_pair("0xr", "0xh"))

    assert account(result, "0xr").return_pct == Decimal("-0.5")
    assert account(result, "0xh").return_pct == Decimal("2")

    quality = result.qualities[WALLET]
    assert quality.value == Decimal("0.75000000000000000000000000000000000002")
    assert quantize_ratio(quality.value) == Decimal("0.75000000")
    assert quality.realized_share == Decimal("0.85714285714285714285714285714285714286")
    assert quality.marked_share == Decimal("0.14285714285714285714285714285714285714")
    assert quality.dead_share == Decimal("0")


def test_two_buys_of_different_tokens_under_one_hash_are_refused_and_the_hash_is_named():
    """The traced case. Left alone it published buy_quality **2** against a true 0.75.

    ``consumptions_by_buy`` is keyed by the buy's hash, so the TOKEN_H sale is handed to the TOKEN_R
    lot as well: $3,000 of proceeds counted twice, an unsold lot reporting +200%, and — because
    every buy then looks fully realized — ``realized_share`` 1 with ``marked_share`` and
    ``dead_share`` both 0. §10's credibility mix reports the highest confidence it has on a number
    that was fabricated at a join, which is the one failure this repository is built to refuse.
    """
    with pytest.raises(ValueError) as refusal:
        run(_colliding_pair("0xdup", "0xdup"))

    message = str(refusal.value)
    assert "0xdup" in message
    assert "appears 2 times" in message
    # Blames the input, and says why it is not a quarantine.
    assert "no block issues one hash twice" in message
    assert "Refused rather than quarantined" in message


def test_two_buys_of_the_same_token_are_refused_at_the_boundary_not_by_reconciliation():
    """This shape already raised — from ``StageCounts``, three stages downstream.

    ``quarantined_buys`` and ``deferred_buys`` are sets of hashes, so two buys collapsed to one and
    the four-way partition came up short: *"0 + 1 + 0 + 0 = 1 against 2 buys"*. That is an internal
    accounting crash reported against the run's own bookkeeping, and it sends the reader to look for
    a lost buy. The condition is a duplicated input, and the refusal has to say so.
    """
    with pytest.raises(ValueError) as refusal:
        run([
            buy("0xdup", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
            buy("0xdup", 2, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        ])

    message = str(refusal.value)
    assert "0xdup" in message
    assert "no block issues one hash twice" in message
    assert "against 2 buys" not in message


def test_a_hash_shared_between_a_buy_and_a_sell_of_different_tokens_is_refused():
    """Nothing refused this before, and it deleted a healthy buy from the score.

    The TOKEN_H sell has no buy behind it, so FIFO quarantines that book and its hash lands in
    ``quarantined_txs``. The TOKEN_R buy shares the hash, so it is skipped at marking as though it
    had been refused too: the wallet goes unscorable, ``n_buys_quarantined`` reads 1, and the only
    queue record names a $3,000 *sell* of a different token. The buy's $1,000 appears in no queue
    volume and in no score.
    """
    duplicated = [
        buy("0xdup", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        sell("0xdup", 3, TOKEN_H, 4_000 * ONE_TOKEN, 3_000 * ONE_USDC, venue=POOL_H),
    ]
    with pytest.raises(ValueError) as refusal:
        run(duplicated)
    assert "0xdup" in str(refusal.value)

    # The same two transactions under their own hashes: the buy is scored and only the sell's book
    # is quarantined. That is the behaviour the collision was eating.
    control = run([
        buy("0xr", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        sell("0xsh", 3, TOKEN_H, 4_000 * ONE_TOKEN, 3_000 * ONE_USDC, venue=POOL_H),
    ])
    assert control.stages.buys_scored == 1
    assert control.stages.buys_quarantined == 0
    assert account(control, "0xr").return_pct == Decimal("-0.5")
    assert control.quarantine.records[0].tx_hashes == ("0xsh",)


def test_a_hash_shared_by_a_buy_and_a_sell_of_the_same_token_is_refused_before_fifo_sees_it():
    """FIFO used to catch this one, and blamed the wrong thing for it.

    ``_require_a_total_order`` raised ``QuarantineRequired`` saying *"the netting output was merged
    wrongly"* — an upstream code stage accused of a condition that arrived in the caller's input.
    The run then filed a reconciliation queue entry for a book that is not a data problem at all.
    Refusing at entry means no queue entry is written and the message names the real cause.
    """
    with pytest.raises(ValueError) as refusal:
        run([
            buy("0xdup", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
            sell("0xdup", 2, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC),
        ])

    message = str(refusal.value)
    assert "0xdup" in message
    assert "netting output was merged wrongly" not in message


def test_normalisation_variants_of_one_hash_are_one_hash():
    """``"0xDUP  "`` and ``"0xdup"`` are the same transaction and behaved identically.

    ``ObservedTransaction.__post_init__`` strips and lowercases, so the two collapse before any
    stage sees them and the traced defect reproduces verbatim from a pair that does not look like a
    pair. A check written against the caller's spelling rather than against the normalised hash
    would let exactly this through, so the refusal is stated over the value the rest of the run
    uses.
    """
    with pytest.raises(ValueError) as refusal:
        run(_colliding_pair("0xDUP  ", "0xdup"))

    message = str(refusal.value)
    assert "0xdup" in message
    assert "0xDUP" not in message


def test_a_duplicate_that_only_separates_after_the_window_filter_is_refused():
    """One row inside the window, one in the §4.8 measurement tail, both under ``0xdup``.

    Different tokens, so no lot book sees them together and FIFO never looks; different sides of the
    window edge, so one is scored and one is deferred. The wallet published ``n_buys=2`` against one
    account with nothing quarantined, nothing deferred that a reader could find, and no queue entry
    — a buy that is neither in the score nor in the account of what left it.
    """
    tail_block = END_BLOCK + 1_000
    tail_ts = END_TS + 12_000
    with pytest.raises(ValueError) as refusal:
        run([
            buy("0xdup", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
            observed("0xdup", 0, [
                transfer(USDC, WALLET, POOL_H, 1_000 * ONE_USDC, 0),
                transfer(TOKEN_H, POOL_H, WALLET, 4_000 * ONE_TOKEN, 1),
            ], block=tail_block, timestamp=tail_ts),
        ])

    assert "0xdup" in str(refusal.value)


def test_the_refusal_names_every_repeated_hash_and_where_each_one_sat():
    """A caller with a broken extraction has more than one duplicate, and gets all of them at once.

    Reporting only the first turns one fix into as many runs as there are duplicates, and each run
    is a full window. The positions travel with the hash because a hash appearing at 0 and 9 is a
    different bug from one appearing at 4 and 5.
    """
    with pytest.raises(ValueError) as refusal:
        run([
            buy("0xaaa", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
            buy("0xbbb", 2, TOKEN_H, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_H),
            buy("0xaaa", 3, TOKEN_M, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_M),
            buy("0xbbb", 4, TOKEN_D, 500 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_D),
        ])

    message = str(refusal.value)
    assert "4 transactions under 2 distinct tx_hash values" in message
    assert "0xaaa appears 2 times, at input positions 0, 2" in message
    assert "0xbbb appears 2 times, at input positions 1, 3" in message


def test_the_same_transaction_object_supplied_twice_is_still_two_rows():
    """The cheapest way to write the bug: one list extended with itself, or a page fetched twice.

    Identity is not the question — the run counts rows, and two references to one object are two
    rows in ``transactions_in``, two buys in the census and two lots in a book.
    """
    once = buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)
    with pytest.raises(ValueError) as refusal:
        run([once, once])
    assert "0xb1 appears 2 times, at input positions 0, 1" in str(refusal.value)


def test_a_lot_that_hands_out_more_than_it_holds_blames_fifo_and_says_why_it_can(monkeypatch):
    """The other message the duplicate defect made false, now made true by the boundary.

    ``_account_for`` refuses when the consumptions gathered for a buy exceed the lot, and it used to
    call that *"a defect in the join between FIFO and marking rather than a data condition"*. It was
    reachable from duplicated input alone — two buys under one hash, the second one's sale gathered
    against the first — so the message sent the reader to hunt a pipeline bug that did not exist.

    With duplicates refused at entry the claim is now supportable, and the message says what makes
    it supportable rather than asserting it. To reach the guard at all, FIFO has to be replaced with
    one that over-allocates: that is exactly the defect the message now names, and the only one
    left.
    """
    from contracts import FifoResult, LotConsumption
    import pipeline.run

    def over_allocating(book_buys, book_sells):
        lot = book_buys[0]
        return FifoResult(
            consumptions=(LotConsumption(
                buy=lot,
                sell=book_sells[0],
                consumed_raw=lot.asset_raw_amount * 2,
                allocated_cost_usd=Decimal("1000"),
                proceeds_usd=Decimal("3000"),
            ),),
            open_lots=(),
        )

    monkeypatch.setattr(pipeline.run, "match_fifo", over_allocating)

    with pytest.raises(ValueError) as refusal:
        run([
            buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
            sell("0xs1", 2, TOKEN_R, 4_000 * ONE_TOKEN, 3_000 * ONE_USDC),
        ])

    message = str(refusal.value)
    assert "A lot cannot hand out more than it holds" in message
    assert "_require_one_transaction_per_hash" in message
    assert "no different input would avoid it" in message
    assert "rather than a data condition" not in message


def test_the_duplicate_refusal_survives_a_hostile_ambient_decimal_context():
    """The check runs before any Decimal does, and must not become context-dependent later.

    Every other refusal in this file is replayed under a hostile context by
    ``test_every_number_holds_under_a_hostile_ambient_decimal_context``; this one is checked here
    because it fires before that test's run reaches a number at all.
    """
    with localcontext(Context(prec=6, rounding=ROUND_DOWN)):
        with pytest.raises(ValueError) as refusal:
            run(_colliding_pair("0xdup", "0xdup"))
    assert "0xdup appears 2 times" in str(refusal.value)


def test_a_bypassed_hash_normalisation_does_not_reach_the_double_count():
    """The residue this refusal leaves, measured rather than asserted.

    The check compares ``ObservedTransaction``'s normalised hash, and ``run_wallet_window`` admits
    any ``isinstance`` of that type — so a subclass with a no-op ``__post_init__`` gets ``"0xDUP"``
    past it while ``"0xdup"`` sits beside it. Re-normalising inside the check would close that and
    would put a second authority on what a hash is into the pipeline, which is the shape of the
    defect ``WindowConfig`` carried against its asset keys; the residue is stated in
    ``_require_one_transaction_per_hash`` instead. A stated residue is only worth the sentence if
    somebody ran it, so this runs it.

    Two outcomes, and neither is the fabricated number:

    * **different tokens** — every hash-keyed structure below sees two distinct strings, so nothing
      pools. The traced pair scores the control's 0.75 with the control's mix, which is the answer
      two genuinely distinct hashes give. Wrong input, right answer.
    * **one lot book** — ``fifo._require_a_total_order`` lowercases, so the book is refused and
      lands in the queue naming both spellings. Wrong input, loud refusal.
    """
    import dataclasses as dc

    @dc.dataclass(frozen=True)
    class Unnormalised(ObservedTransaction):
        def __post_init__(self):
            pass

    def respelled(item, tx_hash):
        return Unnormalised(
            tx_hash=tx_hash, block_number=item.block_number, timestamp=item.timestamp,
            success=item.success, tx_sender=item.tx_sender, transfers=item.transfers,
            context=item.context,
        )

    pair = _colliding_pair("0xdup", "0xdup")
    apart = run([respelled(pair[0], "0xDUP")] + list(pair[1:]))
    assert apart.qualities[WALLET].value == Decimal("0.75000000000000000000000000000000000002")
    assert account(apart, "0xDUP").return_pct == Decimal("-0.5")
    assert account(apart, "0xdup").return_pct == Decimal("2")

    same_book = [
        buy("0xdup", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        buy("0xdup", 2, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
    ]
    refused = run([respelled(same_book[0], "0xDUP"), same_book[1]])
    assert refused.stages.buys_scored == 0
    assert len(refused.quarantine) == 1
    assert refused.quarantine.records[0].stage is Stage.FIFO
    assert refused.quarantine.records[0].tx_hashes == ("0xDUP", "0xdup")


# -- one spelling, one asset ----------------------------------------------------
#
# ``tx_hash`` is not the only identity key this boundary indexes by, and it was not the only one
# that collapsed silently. The four mappings a run is configured with — the pool book, the price
# book, the §4.7 trading starts and the migration replacements — are all keyed by an *asset*, and
# every one of them normalises that key: ``normalise_asset`` lowercases and collapses the native-ETH
# sentinel onto WETH (§4.2). Two caller keys that normalise to one key therefore arrive as two
# entries and leave as one, and which one survives is decided by the order the caller's dict happens
# to iterate in.
#
# That is the same defect as the duplicated hash, with the same signature: no refusal, no queue
# entry, no census line, and a number that looks exactly like a measurement. The three cases below
# were constructed and run before the guard existed, and each published a different wrong answer:
#
#     pool book, two spellings of one token      return -0.25 against a true -0.5
#     price book, two spellings of USDC          notional $1,000,000,000 against a true $1,000
#                                                — and $1,000 again when the two keys were
#                                                  supplied in the other order
#     replacement pools, checksummed key only    DEAD_ZEROED, return -1, against a true -0.25
#
# The third is the one to read twice. A migration the caller *did* configure was dropped because the
# stored key was never normalised while the lookup was, so the position was marked dead — and §10's
# dead share reported the full exposure as a measured zero.


def one_pool_book(**extra):
    book = dict(POOLS)
    book.update(extra)
    return book


def test_the_control_one_pool_book_entry_per_token_marks_against_the_pool_supplied():
    """Both readings of the collision below, each on its own, as literals.

        POOL_R   quote reserve 1e9 raw USDC   exit = 1e9 * 1e-6 / 2 = $500   -> 500/1000 - 1 = -0.5
        POOL_H   quote reserve 1.5e9          exit = 1.5e9 * 1e-6 / 2 = $750 -> 750/1000 - 1 = -0.25

    Without these the collision test would assert only that *something* was refused, and a repair
    that resolved the collision by keeping either entry would leave it green.
    """
    lot = [buy("0xr", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)]

    against_r = run(lot, pools=one_pool_book(**{TOKEN_R: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)}))
    assert account(against_r, "0xr").return_pct == Decimal("-0.5")

    against_h = run(lot, pools=one_pool_book(**{TOKEN_R: pool(POOL_H, TOKEN_R, 1_500 * ONE_USDC)}))
    assert account(against_h, "0xr").return_pct == Decimal("-0.25")


def test_two_spellings_of_one_token_in_the_pool_book_are_refused():
    """The traced case. Left alone it marked TOKEN_R against whichever entry came last.

    Both spellings name the same token, so the run cannot mark against both and has no ground to
    prefer either. It published -0.25 — the second entry's pool — with nothing in the queue, nothing
    in the census, and no field a reader could consult to discover that a pool book with two entries
    had become a pool book with one.
    """
    with pytest.raises(ValueError) as refusal:
        run(
            [buy("0xr", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)],
            pools=one_pool_book(**{
                TOKEN_R: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC),
                TOKEN_R.upper(): pool(POOL_H, TOKEN_R, 1_500 * ONE_USDC),
            }),
        )

    message = str(refusal.value)
    assert "pools" in message
    assert TOKEN_R in message
    assert TOKEN_R.upper() in message
    assert "the last one supplied would have won" in message


def test_two_spellings_of_one_quote_asset_in_the_price_book_are_refused():
    """$1,000 of notional or $1,000,000,000 of it, decided by the caller's dict order.

    USDC is quoted **per raw unit** and has six decimals, so ``0.000001`` and ``1`` differ by the
    whole decimal shift. The buy's cost, the coverage notional and the §4.4 trade weight all move
    with it; the *return* does not, because the same price scales both legs — which is exactly what
    made this survivable to look at. A run published $1,000,000,000 of notional against $1,000 of
    trade with a perfectly ordinary -0.5.

    Both orders are refused, and both are asserted: a guard that fired only when the wrong entry
    happened to be second would leave the answer order-dependent, and §9.2 requires a run to
    reproduce from its own record rather than from how a caller built a dict.
    """
    lot = [buy("0xr", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)]

    control = run(lot, prices={USDC: Decimal("0.000001")})
    assert control.coverage.notional_usd_total == Decimal("1000")
    assert account(control, "0xr").cost_usd == Decimal("1000")

    for book in (
        {USDC: Decimal("0.000001"), USDC.upper(): Decimal("1")},
        {USDC.upper(): Decimal("1"), USDC: Decimal("0.000001")},
    ):
        with pytest.raises(ValueError) as refusal:
            run(lot, prices=book)
        message = str(refusal.value)
        assert "prices" in message
        assert USDC in message
        assert USDC.upper() in message


def test_a_native_eth_price_and_a_weth_price_are_one_price_and_supplying_both_is_refused():
    """§4.2 collapses the sentinel onto WETH, so these are two names for one entry.

    This one does not look like a duplicate at all — the two keys share no characters — and a caller
    who priced ETH and WETH separately because they are separate rows in their price book would have
    had one of the two silently discarded. The refusal fires at entry whether or not any position in
    the run is quoted in WETH, because the caller's mistake is in the book rather than in its use.
    """
    with pytest.raises(ValueError) as refusal:
        run(
            [buy("0xr", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)],
            prices={
                USDC: Decimal("0.000001"),
                WETH: Decimal("0.000000000000000002"),
                NATIVE_ETH: Decimal("0.000000000000000003"),
            },
        )

    message = str(refusal.value)
    assert WETH in message
    assert NATIVE_ETH in message
    assert "native-ETH sentinel collapsed onto WETH" in message


def test_a_price_book_supplied_as_pairs_cannot_smuggle_a_repeat_past_the_check():
    """``dict([(k, a), (k, b)])`` keeps ``b`` and says nothing, and the mapping was built by us.

    The check reads the caller's pairs rather than a dict built from them, so a repeated key is a
    repeated key whether or not Python would have collapsed it first.
    """
    with pytest.raises(ValueError) as refusal:
        run(
            [buy("0xr", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)],
            prices=[(USDC, Decimal("0.000001")), (USDC, Decimal("1"))],
        )
    assert USDC in str(refusal.value)


def test_two_spellings_carrying_the_same_value_are_still_two_spellings():
    """The guard is on the collision, not on the values disagreeing.

    A caller whose key space is unnormalised has the bug; the two entries agreeing is luck, and
    conditioning the refusal on disagreement is the shape that closes the traced instance and leaves
    the class open. ``_require_one_transaction_per_hash`` refuses ``[once, once]`` on the same
    ground, and this is the same rule one mapping over.
    """
    same = pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)
    with pytest.raises(ValueError) as refusal:
        run(
            [buy("0xr", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)],
            pools=one_pool_book(**{TOKEN_R: same, TOKEN_R.upper(): same}),
        )
    assert TOKEN_R.upper() in str(refusal.value)


def test_a_checksummed_token_start_is_the_same_token_start():
    """The keys were stored verbatim and looked up lowercased, so half the intent was implemented.

    A §4.7 trading start supplied under a checksummed address was never found: the buy was
    quarantined as though no start had been given at all, and the queue said *"no §4.7 token trading
    start was supplied"* about a run that had supplied one. TOKEN_M starts with the window, so a buy
    one block in is bucket A — the first-ten-blocks bucket the Edge Origin condition is measuring.
    """
    starts = {token.upper(): start for token, start in TOKEN_STARTS.items()}
    config = WindowConfig(horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS, token_starts=starts)

    result = run([buy("0xm", 1, TOKEN_M, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_M)],
                 config=config)

    assert result.stages.buys_scored == 1
    assert len(result.quarantine) == 0
    assert account(result, "0xm").bucket is TokenAgeBucket.A


def test_two_spellings_of_one_token_start_are_refused():
    """Two ages for one token is not a smaller answer, it is a bucket decided by dict order."""
    starts = dict(TOKEN_STARTS)
    starts[TOKEN_M.upper()] = TokenStart(block=START_BLOCK - 100_000, timestamp=START_TS - 1_000_000)
    with pytest.raises(ValueError) as refusal:
        WindowConfig(horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS, token_starts=starts)

    message = str(refusal.value)
    assert "token_starts" in message
    assert TOKEN_M in message
    assert TOKEN_M.upper() in message


def _dead_primary_book():
    """TOKEN_R's own pool holding $0.001 and silent for 30 days: the §4.4 Case 3 shape."""
    return one_pool_book(**{
        TOKEN_R: pool(POOL_R, TOKEN_R, 1_000,
                      last_swap_ts=HORIZON_TS - DEAD_INACTIVITY_SECONDS,
                      last_swap_block=HORIZON_BLOCK - 216_000),
    })


def test_a_checksummed_replacement_pool_still_follows_the_migration():
    """The sharpest of the four, because the silent drop produced a *measured-looking zero*.

    The primary pool is dead, so with no replacement the position is ``DEAD_ZEROED`` at -100% and
    §10 reports the whole $1,000 as dead share — the one basis §10 most wants visible, asserted
    about a token whose liquidity had in fact moved. The caller supplied the replacement; it was
    stored under a checksummed key and looked up under a lowercased one, and never found.

        POOL_M   quote reserve 1.5e9 raw USDC   exit = 1.5e9 * 1e-6 / 2 = $750
                                                return = 750/1000 - 1 = -0.25
    """
    replacement = pool(POOL_M, TOKEN_R, 1_500 * ONE_USDC)
    lot = [buy("0xr", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)]

    # The control: no replacement configured at all, and the dead verdict is the honest one.
    bare = run(lot, pools=_dead_primary_book())
    assert account(bare, "0xr").position.value_basis is ValueBasis.DEAD_ZEROED
    assert account(bare, "0xr").return_pct == Decimal("-1")
    assert account(bare, "0xr").dead_usd == Decimal("1000")

    checksummed = WindowConfig(
        horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS, token_starts=TOKEN_STARTS,
        replacement_pools={TOKEN_R.upper(): replacement},
    )
    result = run(lot, pools=_dead_primary_book(), config=checksummed)

    assert account(result, "0xr").position.value_usd == Decimal("750")
    assert account(result, "0xr").return_pct == Decimal("-0.25")
    assert account(result, "0xr").dead_usd == Decimal("0")


def test_two_spellings_of_one_replacement_pool_are_refused():
    with pytest.raises(ValueError) as refusal:
        WindowConfig(
            horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS, token_starts=TOKEN_STARTS,
            replacement_pools={
                TOKEN_R: pool(POOL_M, TOKEN_R, 1_500 * ONE_USDC),
                TOKEN_R.upper(): pool(POOL_H, TOKEN_R, 1_000 * ONE_USDC),
            },
        )

    message = str(refusal.value)
    assert "replacement_pools" in message
    assert TOKEN_R.upper() in message


def test_the_key_collision_refusal_names_every_spelling_and_the_asset_they_name():
    """Three spellings of one token, and a caller who fixes one of them has fixed none of them."""
    checksummed = TOKEN_R[:2] + TOKEN_R[2:].upper()
    assert checksummed != TOKEN_R.upper()

    with pytest.raises(ValueError) as refusal:
        run(
            [buy("0xr", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)],
            pools=one_pool_book(**{
                TOKEN_R: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC),
                TOKEN_R.upper(): pool(POOL_H, TOKEN_R, 1_500 * ONE_USDC),
                checksummed: pool(POOL_M, TOKEN_R, 1_000 * ONE_USDC),
            }),
        )

    message = str(refusal.value)
    assert "is named by 3 keys" in message
    assert TOKEN_R.upper() in message
    assert checksummed in message


def test_a_padded_asset_key_is_refused_rather_than_left_as_a_dead_entry():
    """``normalise_asset`` lowercases and does not strip, so ``"  0xc1…  "`` is a dead entry.

    The first assertion is the one that keeps this test honest, because it makes the reason exact
    rather than convenient: the seam carries the padding straight through, so a padded key is not
    *unmatchable* — it is matchable by one thing, a transfer whose token is padded identically,
    which is the same asset split in two everywhere downstream. Trimming here would give this
    module a key space netting, FIFO and marking do not have; refusing is the only move that does
    not paper over the half of the defect this boundary cannot see.

    Dead to every ordinary input either way, and on the replacement pools a dead entry is a wrong
    number rather than a missing one: the migration is never followed, and the dead primary is
    published at ``DEAD_ZEROED`` — the measurement-shaped zero §10 reports as dead share.
    """
    padded = Transfer(token="  " + TOKEN_R + "  ", from_addr=WALLET, to_addr=POOL_R,
                      raw_amount=ONE_TOKEN, log_index=0)
    assert padded.token == "  " + TOKEN_R + "  "

    with pytest.raises(ValueError) as pool_refusal:
        run(
            [buy("0xr", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)],
            pools={"  " + TOKEN_R + "  ": pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)},
        )
    assert "padded with whitespace" in str(pool_refusal.value)

    with pytest.raises(ValueError) as replacement_refusal:
        WindowConfig(
            horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS, token_starts=TOKEN_STARTS,
            replacement_pools={TOKEN_R + "\n": pool(POOL_M, TOKEN_R, 1_500 * ONE_USDC)},
        )
    assert "replacement_pools" in str(replacement_refusal.value)
    assert "carries the same padding" in str(replacement_refusal.value)


def test_a_malformed_entry_is_named_before_the_collision_across_entries_is():
    """Per-entry well-formedness first, cross-entry invariant second.

    ``run_wallet_window`` orders the transaction checks the same way, and for the same reason: a
    statement about a set of entries that are not yet entries is a statement about the wrong thing.
    """
    with pytest.raises(TypeError) as refusal:
        run(
            [buy("0xr", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)],
            pools=one_pool_book(**{TOKEN_R.upper(): "not a pool"}),
        )
    assert "must be a PoolState" in str(refusal.value)


def test_the_key_collision_refusal_survives_a_hostile_ambient_decimal_context():
    """Like the duplicate-hash refusal, this one fires before the run reaches a number."""
    with localcontext(Context(prec=6, rounding=ROUND_DOWN)):
        with pytest.raises(ValueError) as refusal:
            run(
                [buy("0xr", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)],
                prices={USDC: Decimal("0.000001"), USDC.upper(): Decimal("1")},
            )
    assert USDC.upper() in str(refusal.value)


# -- coverage -------------------------------------------------------------------


def test_coverage_is_weighted_by_notional_and_not_by_count():
    """One $999 trade and one $1 transaction that is not one.

        by count      1 of 2   = 50%
        by notional   999/1000 = 99.9%

    The count is the number a reader most wants and the one that misleads most cheaply — ninety-nine
    dust rows and one seven-figure trade give 99% coverage while missing nearly all of the money, in
    either direction. §10's coverage question is about the money.
    """
    result = run([
        buy("0xb1", 1, TOKEN_R, 999 * ONE_USDC, 4_000 * ONE_TOKEN),
        observed("0xdust", 2, [transfer(USDC, WALLET, STRANGER, ONE_USDC, 0)]),
    ])

    assert result.coverage.notional_usd_total == Decimal("1000")
    assert result.coverage.notional_usd_trades == Decimal("999")
    assert result.coverage.notional_usd_non_trades == Decimal("1")
    assert result.coverage.trade_share == Decimal("0.999")
    assert result.coverage.transactions_priced == 2
    assert result.census.counts[ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL] == 1


def test_an_unpriceable_population_reports_no_share_rather_than_full_coverage():
    """Two long-tail tokens and no quote asset anywhere: nothing is priced, so nothing is covered.

    ``None``, not ``Decimal("1")``. A run in which nothing could be priced has no coverage to
    report, and either constant would read as a measurement — 100% coverage of a population whose
    entire notional is unknown is the most flattering possible way to say "we priced nothing".
    """
    result = run([
        observed("0xswap", 1, [
            transfer(TOKEN_X, WALLET, POOL_R, 5 * ONE_TOKEN, 0),
            transfer(TOKEN_Y, POOL_R, WALLET, 7 * ONE_TOKEN, 1),
        ]),
    ])

    assert result.coverage.is_reportable is False
    assert result.coverage.trade_share is None
    assert result.coverage.scored_share is None
    assert result.coverage.quarantined_share is None
    assert result.coverage.transactions_unpriced == 1
    assert result.census.counts[ClassificationStatus.NO_CLEAR_ENDPOINT] == 1


def test_scored_notional_counts_only_what_reached_a_published_score():
    """$1,000 of buys, $1,500 of sells, and only the buy volume can reach a wallet score."""
    result = run([
        buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        sell("0xs1", 2, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC),
    ])

    assert result.coverage.notional_usd_total == Decimal("2500")
    assert result.coverage.notional_usd_trades == Decimal("2500")
    assert result.coverage.notional_usd_scored == Decimal("1000")
    assert result.coverage.trade_share == Decimal("1")
    assert result.coverage.scored_share == Decimal("0.4")


# -- the queue's own arithmetic -------------------------------------------------


def test_an_unpriceable_queue_entry_is_none_and_not_a_zero():
    """``$0`` of quarantined volume and "we could not price it" are different statements, and only
    one of them says the queue is cheap. ``unpriced`` is what keeps the total honest."""
    queue = QuarantineQueue(records=(
        QuarantineRecord(stage=Stage.NETTING, reason="unpriceable", tx_hashes=("0x1",)),
        QuarantineRecord(stage=Stage.FIFO, reason="broken book", tx_hashes=("0x2", "0x3"),
                         volume_usd=Decimal("250.5")),
    ))

    assert queue.total_volume_usd == Decimal("250.5")
    assert queue.unpriced == 1
    assert queue.transactions == ("0x1", "0x2", "0x3")
    assert len(queue.by_stage(Stage.FIFO)) == 1


def test_a_netting_refusal_reaches_the_queue_carrying_an_unknown_cost():
    """The composed run's own netting quarantine, not a hand-built record.

    ``test_an_unpriceable_queue_entry_is_none_and_not_a_zero`` above constructs the queue directly,
    so it pins :class:`QuarantineQueue`'s arithmetic and says nothing about the branch in
    ``run_wallet_window`` that *produces* the record. Both are needed: the dangerous condition is
    not "``None`` is handled" but **"netting refused before anything priced this transaction, so
    its cost is unknown rather than nil"**, and that condition lives in the composition root.

    Three shapes of it, because the flattering failure is not a particular value:

    * alone, where the queue's total and its unpriced count agree trivially;
    * beside a *priced* quarantine, where the total is $1,500 either way and ``unpriced`` is the
      only figure that can still tell an unknown cost from a zero one;
    * twice, where the count of unknowns has to track them rather than being a flag.
    """
    lone = run([uncollapsed_eth_swap("0xeth1", 1)])
    lone_record, = lone.quarantine.by_stage(Stage.NETTING)
    assert lone_record.volume_usd is None
    assert lone.quarantine.unpriced == 1
    assert lone.stages.netting_quarantined == 1
    assert lone.stages.netted == 0

    mixed = run([
        uncollapsed_eth_swap("0xeth2", 1),
        # A sell with no buy in front of it: the whole book is quarantined, *with* its volume.
        sell("0xs1", 2, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC),
    ])
    netting_record, = mixed.quarantine.by_stage(Stage.NETTING)
    fifo_record, = mixed.quarantine.by_stage(Stage.FIFO)
    assert netting_record.volume_usd is None
    assert fifo_record.volume_usd == Decimal("1500")
    # $1,500 with one entry priced and one unknown. A queue that filed the unknown as $0 would
    # report this identical total, which is exactly why the total cannot be the assertion.
    assert mixed.quarantine.total_volume_usd == Decimal("1500")
    assert mixed.quarantine.unpriced == 1

    two = run([uncollapsed_eth_swap("0xeth3", 1), uncollapsed_eth_swap("0xeth4", 2)])
    assert [r.volume_usd for r in two.quarantine.by_stage(Stage.NETTING)] == [None, None]
    assert two.quarantine.unpriced == 2
    assert two.coverage.transactions_unpriced == 2


def test_a_quarantine_record_must_name_its_transactions_and_its_reason():
    with pytest.raises(ValueError):
        QuarantineRecord(stage=Stage.FIFO, reason="broken", tx_hashes=())
    with pytest.raises(ValueError):
        QuarantineRecord(stage=Stage.FIFO, reason="", tx_hashes=("0x1",))


# -- structure ------------------------------------------------------------------


def test_the_smallest_buy_netting_will_emit_still_carries_a_positive_weight():
    """Why ``StageCounts.buys_unscored`` is structurally zero — pinned, not left as a comment.

    ``run_wallet_window`` counts buys that produced a complete account inside a wallet nobody could
    score, and ``_coverage_report`` excludes their cost from scored notional. Both are correct and
    neither is currently reachable, because scoring refuses a wallet only when its total log weight
    or its whole value basis is zero, and netting will not emit a ``VALID_BUY`` small enough for
    either. The mutation harness records the consequence — a mutation removing the coverage guard
    survives, and cannot do otherwise — so the premise is pinned here rather than assumed:

        residual floor            $0.01           (netting: at or below it, a leg is a residual)
        log weight at the floor   0.00995033...   (scoring: strictly positive)
        log weight vanishes at    ~1e-38          (36 orders of magnitude below the floor)

    Both bounds are absolute literals. If either moves, this fails, and the unreachability claim
    behind that surviving mutation has to be re-argued rather than inherited.
    """
    assert RESIDUAL_FLOOR_USD == Decimal("0.01")
    assert trade_weight(Decimal("0.01")) > 0

    # A price book scaled so the same 1,000 raw USDC lands either side of the floor. At the floor
    # netting calls it a residual; a hair above, it is a buy — and it is scored, not left unscored.
    at_the_floor = run(
        [buy("0xdust", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)],
        prices={USDC: Decimal("1E-11")},
    )
    assert at_the_floor.results[0].quote_usd == Decimal("0.01")
    assert at_the_floor.results[0].status is ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL
    assert at_the_floor.stages.buys == 0

    above_the_floor = run(
        [buy("0xsmall", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)],
        prices={USDC: Decimal("2E-11")},
    )
    assert above_the_floor.results[0].quote_usd == Decimal("0.02")
    assert above_the_floor.results[0].status is ClassificationStatus.VALID_BUY
    assert above_the_floor.stages.wallets_scored == 1
    assert above_the_floor.stages.buys_unscored == 0


def test_the_results_are_published_in_canonical_order_and_not_the_callers():
    """Sorted by ``(block_number, tx_hash)``, whatever order the caller handed them over in.

    ``properties/test_pipeline.py`` already shuffles the input and compares the published
    *aggregates*, which is the consequence; this pins the *cause*. The two are not the same
    assertion, and the aggregate one is the weaker of the pair by construction: every total in the
    coverage report is a sum of 38-digit Decimals, so a run that accumulated in caller order agrees
    with a sorted run on small fixtures and drifts on large ones — the reproducibility failure that
    only appears at the scale where nobody is checking.

    Four transactions arranged so that neither key alone gets the order right: two share a block
    and must be separated by hash, and the two remaining blocks carry hashes in the *opposite*
    order to their blocks, so a sort on ``tx_hash`` alone reverses them. Three callers supply them
    three ways — worst case, descending, and already sorted — and all three publish the same tuple.
    """
    early = buy("0xz1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)     # block +1, hash last
    middle = buy("0xa5", 5, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)    # block +5, hash first
    tie_low = buy("0xa9", 9, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)   # block +9
    tie_high = buy("0xb9", 9, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)  # block +9

    expected = (
        (START_BLOCK + 1, "0xz1"),
        (START_BLOCK + 5, "0xa5"),
        (START_BLOCK + 9, "0xa9"),
        (START_BLOCK + 9, "0xb9"),
    )

    worst = run([tie_high, middle, tie_low, early])
    descending = run([tie_high, tie_low, middle, early])
    sorted_already = run([early, middle, tie_low, tie_high])

    assert order_of(worst) == expected
    assert order_of(descending) == expected
    assert order_of(sorted_already) == expected
    # And the number the order exists to protect: $4,000 of notional, identically, three times.
    assert worst.coverage.notional_usd_total == Decimal("4000")
    assert (worst.coverage.notional_usd_total
            == descending.coverage.notional_usd_total
            == sorted_already.coverage.notional_usd_total)


def test_the_stages_run_in_the_order_section_4_fixes():
    result = run([buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)])
    assert result.stages_run == STAGE_ORDER
    assert [s.value for s in STAGE_ORDER] == [
        "attribution", "netting", "fifo", "marking", "scoring"
    ]


def test_a_result_whose_stages_ran_out_of_order_cannot_be_constructed():
    """Guard the guard. A recorded order that nothing checks is decoration."""
    result = run([buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)])
    swapped = (Stage.NETTING, Stage.ATTRIBUTION, Stage.FIFO, Stage.MARKING, Stage.SCORING)
    with pytest.raises(ValueError) as refusal:
        dataclasses.replace(result, stages_run=swapped)
    assert "§4 fixes the order" in str(refusal.value)


def test_a_wallet_with_no_scorable_buy_reports_the_reason_and_never_a_zero():
    """"This wallet's buys lost money" and "this wallet has no scorable buys" are different facts.

    A ``BuyQuality`` of zero would read as flat performance and would then be differenced against a
    benchmark as though it were one.
    """
    config = dataclasses.replace(CONFIG, token_starts={})
    result = run([buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)], config=config)

    assert result.qualities == {}
    assert WALLET in result.unscorable
    assert "quarantined" in result.unscorable[WALLET]
    assert result.stages.wallets_seen == 1
    assert result.stages.wallets_scored == 0
    assert result.stages.wallets_unscorable == 1


def test_every_number_holds_under_a_hostile_ambient_decimal_context():
    """The run is evaluated at 9 digits, rounding down, and must produce identical values.

    ``abs()``, unary ``-`` and bare ``+ - * /`` on a Decimal all round to whatever context is
    ambient. Every one of them would still return a plausible number here — 38-digit shares
    truncated to 9 look entirely reasonable — so the only way to see it is to move the ambient
    context and require the answers not to move with it. That defect has shipped three times in this
    repository, once inside the fix for itself.
    """
    transactions = [
        buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        buy("0xb2", 2, TOKEN_M, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_M),
        buy("0xb3", 3, TOKEN_D, 500 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_D),
        sell("0xs1", 4, TOKEN_R, 4_000 * ONE_TOKEN, 1_500 * ONE_USDC),
    ]
    baseline = run(transactions)
    with localcontext(Context(prec=9, rounding=ROUND_DOWN)):
        hostile = run(transactions)

    assert hostile.qualities[WALLET].value == baseline.qualities[WALLET].value
    assert hostile.qualities[WALLET].value == Decimal(
        "-0.31030099888987092135128045519817795520")
    for name in ("realized_share", "marked_share", "dead_share"):
        assert getattr(hostile.qualities[WALLET], name) == getattr(
            baseline.qualities[WALLET], name)
    assert hostile.coverage.trade_share == baseline.coverage.trade_share
    for left, right in zip(hostile.accounts, baseline.accounts):
        assert left.return_pct == right.return_pct
        assert left.marked_usd == right.marked_usd
        assert left.dead_usd == right.dead_usd


def test_a_wallet_counts_buys_refused_at_marking_as_well_as_at_fifo():
    """The per-wallet quarantine count has to cover *both* stages that can refuse a buy.

    A count assembled from the FIFO refusals alone reports zero here — a wallet with no score and,
    on its own record, nothing quarantined, which is the shape of an unexplained drop appearing in
    the very field that exists to explain it. The condition is "this buy left the population", not
    "this buy left it at the stage the last reviewer happened to look at".
    """
    config = dataclasses.replace(CONFIG, token_starts={})
    result = run([
        buy("0xb1", 1, TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN),
        buy("0xb2", 2, TOKEN_M, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_M),
    ], config=config)

    outcome = next(w for w in result.wallets if w.wallet == WALLET)
    assert outcome.n_buys == 2
    assert outcome.n_buys_quarantined == 2
    assert outcome.quality is None
    assert "2 quarantined" in outcome.unscorable_reason
    assert len(result.quarantine.by_stage(Stage.FIFO)) == 0
    assert len(result.quarantine.by_stage(Stage.MARKING)) == 2
    assert result.stages.buys_quarantined == 2


# -- the entry type -------------------------------------------------------------
#
# ``ObservedTransaction.transfers`` is the pipeline's front door for §4.2. Everything downstream is
# written against a world where ``Transfer.__post_init__`` has already lowercased both addresses
# and collapsed the native-ETH sentinel onto WETH, so the *only* thing standing between that
# assumption and a leg that never ran it is the type check at the door. Both shapes that walk past
# an attribute check are pinned here, because closing one of them and leaving the other is what
# happened the last time this was reviewed.


def test_a_duck_typed_transfer_is_refused_at_the_door():
    """The same five attribute names, none of the guarantees.

    Every stage's *access* succeeds against this object — ``netting`` reads ``token``,
    ``from_addr``, ``to_addr``, ``raw_amount`` and ``is_fee`` and finds all five. What it does not
    find is normalisation: the addresses are mixed case, so ``_owner_flows`` compares them to the
    lowercased owner, fails to match, and files a leg of the owner's own trade as somebody else's
    money in the same transaction. No refusal fires anywhere downstream — the run simply reports a
    different trade. Deleting the check at the door deletes the only place this is visible.
    """
    class DuckTransfer(object):
        def __init__(self):
            self.token = NATIVE_ETH
            self.from_addr = WALLET.upper()
            self.to_addr = POOL_R.upper()
            self.raw_amount = ONE_TOKEN
            self.log_index = 0
            self.is_fee = False

    with pytest.raises(TypeError) as refusal:
        observed("0xd1", 1, [DuckTransfer()])
    assert "not a contracts.Transfer" in str(refusal.value)
    assert "DuckTransfer" in str(refusal.value)


def test_a_transfer_subclass_that_skips_the_seam_is_refused():
    """``isinstance`` is not the check. A derivation of ``Transfer`` is one, and runs no §4.2.

    ``contracts.Transfer`` is a plain frozen dataclass with no ``__init_subclass__``, so a subclass
    overriding ``__post_init__`` to do nothing satisfies ``isinstance(leg, Transfer)`` exactly and
    keeps the native-ETH sentinel and the mixed-case addresses it was handed. The two assertions
    below are the pair: the object *is* a ``Transfer`` by ``isinstance``, and is refused anyway.
    """
    @dataclasses.dataclass(frozen=True)
    class RawTransfer(Transfer):
        def __post_init__(self):
            pass

    leg = RawTransfer(token=NATIVE_ETH, from_addr=WALLET.upper(), to_addr=POOL_R.upper(),
                      raw_amount=ONE_TOKEN, log_index=0)
    assert isinstance(leg, Transfer)
    assert leg.token == NATIVE_ETH          # §4.2's collapse never ran
    assert leg.from_addr == WALLET.upper()  # nor the lowercasing

    with pytest.raises(TypeError) as refusal:
        observed("0xd2", 1, [leg])
    assert "RawTransfer" in str(refusal.value)


def test_a_transfer_built_by_the_seam_is_accepted():
    """The refusals above are not a blanket refusal — the ordinary case still passes the door."""
    leg = transfer(WETH, WALLET, POOL_R, ONE_TOKEN, 0)
    assert observed("0xd3", 1, [leg]).transfers == (leg,)
