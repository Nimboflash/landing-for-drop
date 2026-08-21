"""Worked FIFO examples with expectations computed by hand before the module existed.

§9.3 lists "FIFO Allocation" and "Multiple Buys + Partial Sell" as known-answer cases, and §9.2
puts *FIFO Lot Assignment* among the deterministic fields that must match exactly, "with no
percentage tolerance". So every number below is written out in full rather than derived from a
helper — a helper that shares the module's arithmetic would agree with the module's bugs.
"""

import inspect
import os
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Context, Decimal, localcontext

import pytest

from contracts import (
    CALCULATION_CONTEXT,
    USDC,
    WETH,
    AttributionUnresolvedError,
    ClassificationStatus,
    QuarantineRequired,
    to_canonical_json,
)
from fifo import match_fifo

WALLET = "0x" + "11" * 20
OTHER_WALLET = "0x" + "22" * 20
TOKEN = "0x" + "aa" * 20
OTHER_TOKEN = "0x" + "bb" * 20
POOL = "0x" + "cc" * 20


def _tx(n):
    return "0x{:064x}".format(n)


def _timestamp(block):
    # Seam rule: a timestamp is always paired with a block number. 12s slots from a fixed epoch.
    return 1_600_000_000 + block * 12


def buy(block, qty_raw, usd, asset=TOKEN, quote=USDC, owner=WALLET, tx=None):
    """A VALID_BUY of ``qty_raw`` raw units of ``asset`` costing ``usd`` in the quote asset."""
    return _trade(
        ClassificationStatus.VALID_BUY, block, qty_raw, usd, asset, quote, owner, tx
    )


def sell(block, qty_raw, usd, asset=TOKEN, quote=USDC, owner=WALLET, tx=None):
    """A VALID_SELL of ``qty_raw`` raw units of ``asset`` yielding ``usd`` in the quote asset."""
    return _trade(
        ClassificationStatus.VALID_SELL, block, qty_raw, usd, asset, quote, owner, tx
    )


def _trade(status, block, qty_raw, usd, asset, quote, owner, tx):
    from contracts import NetTradeResult

    usd = None if usd is None else Decimal(usd)
    # A plausible raw quote leg: 6-decimal USDC / 18-decimal WETH. Never zero — the seam rejects
    # a trade with a zero leg.
    scale = 10 ** (18 if quote == WETH else 6)
    quote_raw = max(1, int((usd or Decimal("1")) * scale))
    is_buy = status is ClassificationStatus.VALID_BUY
    return NetTradeResult(
        tx_hash=tx or _tx(block),
        portfolio_owner=owner,
        status=status,
        sold_asset=quote if is_buy else asset,
        bought_asset=asset if is_buy else quote,
        sold_raw_amount=quote_raw if is_buy else qty_raw,
        bought_raw_amount=qty_raw if is_buy else quote_raw,
        quote_asset=quote,
        quote_usd=usd,
        block_number=block,
        timestamp=_timestamp(block),
        pool=POOL,
    )


def total(values):
    """Sum at the frozen internal precision, not at the ambient 28 digits."""
    with localcontext(CALCULATION_CONTEXT):
        out = Decimal(0)
        for value in values:
            out += value
        return out


# -- the reference case, §4.4 ---------------------------------------------------


def test_section_4_4_reference_case():
    """Buy 100 @ $1, buy 100 @ $2, sell 150 @ $3 -> 100 from buy 1, 50 from buy 2.

    Hand-computed, all four money figures:

        consumption 1   100 raw from buy 1   cost 100 * (100/100) = $100   proceeds 450 * (100/150) = $300
        consumption 2    50 raw from buy 2   cost 200 * ( 50/100) = $100   proceeds 450 * ( 50/150) = $150
        open lot         50 raw of  buy 2
    """
    buy_one = buy(block=100, qty_raw=100, usd="100")
    buy_two = buy(block=200, qty_raw=100, usd="200")
    the_sell = sell(block=300, qty_raw=150, usd="450")

    result = match_fifo([buy_one, buy_two], [the_sell])

    assert len(result.consumptions) == 2

    first, second = result.consumptions
    assert first.buy is buy_one
    assert first.sell is the_sell
    assert first.consumed_raw == 100
    assert first.allocated_cost_usd == Decimal("100")
    assert first.proceeds_usd == Decimal("300")

    assert second.buy is buy_two
    assert second.sell is the_sell
    assert second.consumed_raw == 50
    assert second.allocated_cost_usd == Decimal("100")
    assert second.proceeds_usd == Decimal("150")

    # $1 -> $3 is a tripling; $2 -> $3 is a half.
    assert first.realized_return == Decimal("2")
    assert second.realized_return == Decimal("0.5")

    assert len(result.open_lots) == 1
    assert result.open_lots[0].buy is buy_two
    assert result.open_lots[0].remaining_raw == 50
    assert result.unmatched_sell_raw == {}


def test_reference_case_is_unchanged_when_the_buys_arrive_out_of_order():
    """Order comes from the block number, not from the caller's list order.

    A caller that hands the buys over newest-first must not silently invert the lot assignment —
    that is exactly the "changed mid-analysis to improve a chart" failure §4.4 chose FIFO to
    prevent.
    """
    buy_one = buy(block=100, qty_raw=100, usd="100")
    buy_two = buy(block=200, qty_raw=100, usd="200")
    the_sell = sell(block=300, qty_raw=150, usd="450")

    result = match_fifo([buy_two, buy_one], [the_sell])

    assert [c.buy for c in result.consumptions] == [buy_one, buy_two]
    assert [c.consumed_raw for c in result.consumptions] == [100, 50]


# -- multi-sell walk ------------------------------------------------------------


def test_a_second_sell_resumes_from_the_partially_consumed_lot():
    """Three buys, two partial sells. Hand-computed lot assignment:

        buy 1  blk 10   100 raw   $100      buy 2  blk 20   100 raw   $200
        buy 3  blk 30   100 raw   $600

        sell 1 blk 40   150 raw   $450   -> 100 of buy 1 (cost $100, proceeds $300)
                                            50 of buy 2 (cost $100, proceeds $150)
        sell 2 blk 50   100 raw   $700   ->  50 of buy 2 (cost $100, proceeds $350)
                                            50 of buy 3 (cost $300, proceeds $350)

        open: 50 raw of buy 3
    """
    buys = [
        buy(block=10, qty_raw=100, usd="100"),
        buy(block=20, qty_raw=100, usd="200"),
        buy(block=30, qty_raw=100, usd="600"),
    ]
    sells = [sell(block=40, qty_raw=150, usd="450"), sell(block=50, qty_raw=100, usd="700")]

    result = match_fifo(buys, sells)

    assert [(c.buy.block_number, c.sell.block_number, c.consumed_raw)
            for c in result.consumptions] == [
        (10, 40, 100),
        (20, 40, 50),
        (20, 50, 50),
        (30, 50, 50),
    ]
    assert [c.allocated_cost_usd for c in result.consumptions] == [
        Decimal("100"), Decimal("100"), Decimal("100"), Decimal("300"),
    ]
    assert [c.proceeds_usd for c in result.consumptions] == [
        Decimal("300"), Decimal("150"), Decimal("350"), Decimal("350"),
    ]

    assert len(result.open_lots) == 1
    assert result.open_lots[0].buy is buys[2]
    assert result.open_lots[0].remaining_raw == 50

    # Realized versus open, as ticket 22 requires per position.
    assert sum(c.consumed_raw for c in result.consumptions) == 250
    assert sum(lot.remaining_raw for lot in result.open_lots) == 50
    assert 250 + 50 == sum(b.bought_raw_amount for b in buys)


def test_a_fully_sold_position_leaves_no_open_lot():
    buys = [buy(block=10, qty_raw=100, usd="50")]
    sells = [sell(block=20, qty_raw=40, usd="30"), sell(block=30, qty_raw=60, usd="60")]

    result = match_fifo(buys, sells)

    # 50 * 40/100 = 20 ; the closing consumption takes the exact remainder, 50 - 20 = 30.
    assert [c.allocated_cost_usd for c in result.consumptions] == [Decimal("20"), Decimal("30")]
    assert [c.proceeds_usd for c in result.consumptions] == [Decimal("30"), Decimal("60")]
    assert [c.realized_return for c in result.consumptions] == [Decimal("0.5"), Decimal("1")]
    assert result.open_lots == ()


# -- dust ------------------------------------------------------------------------


def test_cost_allocation_is_pro_rata_and_the_closing_slice_conserves_the_dust():
    """$10 spread over 3 raw units does not divide evenly, and none of it may go missing.

        10 / 3 at 38 significant digits = 3.3333333333333333333333333333333333333
        remaining after two such slices  = 3.3333333333333333333333333333333333334

    The third slice takes the lot's exact remaining cost rather than a third recomputation, so the
    three allocations sum to exactly $10. A lot whose cost basis does not close to zero would
    quietly move value between wallets in the aggregate.
    """
    one_third = Decimal("3.3333333333333333333333333333333333333")
    closing = Decimal("3.3333333333333333333333333333333333334")

    buys = [buy(block=10, qty_raw=3, usd="10")]
    sells = [
        sell(block=20, qty_raw=1, usd="4"),
        sell(block=30, qty_raw=1, usd="5"),
        sell(block=40, qty_raw=1, usd="6"),
    ]

    result = match_fifo(buys, sells)

    assert [c.allocated_cost_usd for c in result.consumptions] == [one_third, one_third, closing]
    assert total(c.allocated_cost_usd for c in result.consumptions) == Decimal("10")

    # Each sell is satisfied by a single lot, so each takes its whole proceeds.
    assert [c.proceeds_usd for c in result.consumptions] == [
        Decimal("4"), Decimal("5"), Decimal("6"),
    ]
    assert result.open_lots == ()


def test_proceeds_split_across_lots_conserve_the_dust_too():
    """One $10 sell across three 1-unit lots: 10/3, 10/3, and the exact remainder."""
    one_third = Decimal("3.3333333333333333333333333333333333333")
    closing = Decimal("3.3333333333333333333333333333333333334")

    buys = [
        buy(block=10, qty_raw=1, usd="1"),
        buy(block=20, qty_raw=1, usd="2"),
        buy(block=30, qty_raw=1, usd="3"),
    ]
    result = match_fifo(buys, [sell(block=40, qty_raw=3, usd="10")])

    assert [c.proceeds_usd for c in result.consumptions] == [one_third, one_third, closing]
    assert total(c.proceeds_usd for c in result.consumptions) == Decimal("10")
    assert [c.allocated_cost_usd for c in result.consumptions] == [
        Decimal("1"), Decimal("2"), Decimal("3"),
    ]


def test_allocation_is_never_quantized_to_cents():
    """A two-decimal rounding here would destroy the §8 netting tolerance downstream.

    ``max($0.01, 0.01% of notional)`` cannot be compared against a value already rounded to cents.
    """
    result = match_fifo([buy(block=10, qty_raw=3, usd="10")], [sell(block=20, qty_raw=1, usd="4")])
    allocated = result.consumptions[0].allocated_cost_usd

    assert allocated != Decimal("3.33")
    assert -allocated.as_tuple().exponent > 30


# -- dust that has stopped being dust ---------------------------------------------
#
# The rule above hands the closing slice whatever is *left* of the lot's basis, and what is left is
# arrived at by subtracting slices that were each rounded to 38 significant digits. That is sound
# only while the residue is genuinely dust. Once a lot's raw quantity runs far enough above its
# closing residual, the residue is made entirely of the rounding, and the number it produces is an
# artefact of the order this module happened to subtract in rather than a share of anything.
#
# For a lot of 3 * 10**k raw units closing out its last raw unit, the accumulated remainder keeps
# 38 - k significant digits of the true share, so the drift is about 10**(k-38):
#
#     k = 20   remainder 3.33333333333333333E-18    drift ~1e-18   reported
#     k = 30   remainder 3.3333333E-28              drift ~1e-8    reported, at the limit
#     k = 31   remainder 3.333333E-29               drift ~1e-7    refused
#     k = 33   remainder 3.3333E-31                 drift ~1e-5    refused
#     k = 39   remainder 0                          drift  1       refused
#
# 10**33 raw units is one quadrillion tokens at 18 decimals — ordinary for the high-supply long-tail
# assets this study is about, not a contrived number.

#: One unit in the last place of a published return (``contracts.SCALE_RATIO``). Written out here
#: rather than imported from the module so that the limit is pinned from outside: a test that reads
#: the constant it is checking moves with it and pins nothing.
DRIFT_LIMIT = Decimal("1e-8")


def test_a_lot_too_large_to_split_leaves_no_basis_and_is_quarantined_not_crashed():
    """10**39 raw units, $1,000 basis, closing out the last raw unit.

        first slice, exact   1000 * (10**39 - 1) / 10**39 = 999.999...999  (39 significant digits)
        at 38 digits                                      = 1000  exactly
        basis left                                        = 1000 - 1000 = 0
        the share the rule states  1000 * 1 / 10**39      = 1E-36

    A zero basis is refused by ``LotConsumption`` at construction, so before the guard this escaped
    :func:`match_fifo` as a bare ``ValueError`` — an untyped refusal for a condition nobody named.
    """
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo(
            [buy(block=10, qty_raw=10 ** 39, usd="1000")],
            [sell(block=20, qty_raw=10 ** 39 - 1, usd="900"),
             sell(block=30, qty_raw=1, usd="1")],
        )

    message = str(excinfo.value)
    assert "cost basis" in message
    assert "1E-36" in message          # the share the pro-rata rule states
    assert _tx(30) in message          # the transaction the queue has to act on


def test_a_zero_basis_is_never_a_bare_value_error_out_of_match_fifo():
    """The refusal has to be this module's typed one, not the seam's construction check.

    ``QuarantineRequired`` is not a ``ValueError``, so this distinguishes the two.
    """
    with pytest.raises(QuarantineRequired):
        match_fifo(
            [buy(block=10, qty_raw=10 ** 39, usd="1000")],
            [sell(block=20, qty_raw=10 ** 39 - 1, usd="900"),
             sell(block=30, qty_raw=1, usd="1")],
        )


def test_a_closing_slice_made_of_rounding_is_refused_rather_than_reported():
    """3 * 10**33 raw units — 3 quadrillion tokens at 18dp — for $1,000, closing its last unit.

        first slice, exact   1000 * (3*10**33 - 1) / (3*10**33) = 999.999...9996666...
        at 38 digits                                = 999.99999999999999999999999999999966667
        basis left           1000 - that            = 3.3333E-31      (5 significant digits)
        the share the rule states  1000 / (3*10**33) = 3.3333333333333333333333333333333333333E-31

    3.3333E-31 is positive, small and entirely plausible; it is also wrong by one part in 100,000,
    and no test in any of the three suites saw it. It is refused because it is not reproducible:
    a validator applying the same pro-rata rule directly gets the 38-digit share, and §9 requires
    the FIFO fields to re-derive byte-identically.
    """
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo(
            [buy(block=10, qty_raw=3 * 10 ** 33, usd="1000")],
            [sell(block=20, qty_raw=3 * 10 ** 33 - 1, usd="900"),
             sell(block=30, qty_raw=1, usd="1")],
        )

    message = str(excinfo.value)
    assert "3.3333E-31" in message                                        # what was left
    assert "3.3333333333333333333333333333333333333E-31" in message       # what it should be


def test_the_drift_limit_is_pinned_from_both_sides():
    """One order of magnitude of raw quantity separates the last accepted case from the first
    refused one, and the limit itself is written out rather than read from the module.

        3 * 10**30 raw units, $1,000:  basis left 3.3333333E-28,  drift 9.99...E-9  -> reported
        3 * 10**31 raw units, $1,000:  basis left 3.333333E-29,   drift 9.99...E-8  -> refused

    Below the limit the drift cannot move a return at its published 8dp scale, so refusing there
    would discard ordinary positions for a difference nobody could ever see. Above it the residue
    has stopped being rounding and become a number.
    """
    accepted = match_fifo(
        [buy(block=10, qty_raw=3 * 10 ** 30, usd="1000")],
        [sell(block=20, qty_raw=3 * 10 ** 30 - 1, usd="900"),
         sell(block=30, qty_raw=1, usd="1")],
    )
    closing = accepted.consumptions[-1]
    assert closing.consumed_raw == 1
    assert closing.allocated_cost_usd == Decimal("3.3333333E-28")

    exact_share = Decimal("3.3333333333333333333333333333333333333E-28")
    with localcontext(CALCULATION_CONTEXT):
        drift = abs(closing.allocated_cost_usd - exact_share) / exact_share
    assert drift < DRIFT_LIMIT

    with pytest.raises(QuarantineRequired):
        match_fifo(
            [buy(block=10, qty_raw=3 * 10 ** 31, usd="1000")],
            [sell(block=20, qty_raw=3 * 10 ** 31 - 1, usd="900"),
             sell(block=30, qty_raw=1, usd="1")],
        )


# -- the drift figure the refusal reports ------------------------------------------
#
# The drift is not decoration. It is the number the reconciliation queue reads to decide how far
# off the book is, and §9 requires a validator re-deriving it to get the same bytes. So it is
# hand-derived here from the rule stated in the block comment above, and not from the module.
#
# For a lot of 3 * 10**k raw units closing its last raw unit against a $1,000 basis, the remainder
# left by the running subtraction keeps 38 - k significant digits of the true share, and both are
# threes all the way down:
#
#     remainder = 3.33...3E-(k-2)   with d = 38 - k threes
#     share     = 3.33...3E-(k-2)   with 38 threes
#
# A run of n threes is exactly (10**n - 1) / 3 / 10**(n-1), so the threes divide out of the ratio
# and the drift is a ratio of two repunits:
#
#     drift = (share - remainder) / share
#           = 1 - (10**d - 1) * 10**(38-d) / (10**38 - 1)
#           = (10**k - 1) / (10**38 - 1)
#
#     k = 31 -> (10**31 - 1) / (10**38 - 1) = 9.9999999999999999999999999999990000001E-8
#     k = 33 -> (10**33 - 1) / (10**38 - 1) = 0.0000099999999999999999999999999999999900001
#
# Both figures carry 38 significant digits, which is the point. Rounded to the ambient 28 the first
# of them reads 1.000000000000000000000000000E-7: a repunit ratio that is provably below 1e-7 gets
# reported as being exactly on it, on the wrong side of a decade boundary, in the audit record a
# validator is supposed to re-derive byte for byte.

#: k = 31, written out. Not ``DRIFT_LIMIT * 10`` and not a ``divide`` call: an expectation that
#: shares the module's arithmetic agrees with the module's mistakes.
DRIFT_AT_3E31 = Decimal("9.9999999999999999999999999999990000001E-8")

#: k = 33, written out. ``str`` renders this one without an exponent, so the literal below is the
#: form the refusal message actually carries.
DRIFT_AT_3E33 = Decimal("0.0000099999999999999999999999999999999900001")


def test_the_reported_drift_carries_the_frozen_precision_on_the_cost_leg():
    """3 * 10**31 raw units for $1,000. The refusal must state the drift the policy computes.

    ``Decimal.__abs__`` consults the *ambient* context, so taking the magnitude of the ratio
    outside a frozen block truncates it to whatever precision the caller happens to be in — 28 by
    default. Here that also moves it across a decade: 9.99...E-8 becomes 1.00...E-7.
    """
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo(
            [buy(block=10, qty_raw=3 * 10 ** 31, usd="1000")],
            [sell(block=20, qty_raw=3 * 10 ** 31 - 1, usd="900"),
             sell(block=30, qty_raw=1, usd="1")],
        )

    message = str(excinfo.value)
    assert "relative drift {}".format(DRIFT_AT_3E31) in message
    assert "1.000000000000000000000000000E-7" not in message


def test_the_reported_drift_carries_the_frozen_precision_at_quadrillion_supply_too():
    """The same, an order of magnitude of drift higher: 3 * 10**33 raw units for $1,000."""
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo(
            [buy(block=10, qty_raw=3 * 10 ** 33, usd="1000")],
            [sell(block=20, qty_raw=3 * 10 ** 33 - 1, usd="900"),
             sell(block=30, qty_raw=1, usd="1")],
        )

    message = str(excinfo.value)
    assert "cost basis" in message
    assert "relative drift {}".format(DRIFT_AT_3E33) in message
    assert "0.00001000000000000000000000000000" not in message


def test_the_reported_drift_carries_the_frozen_precision_on_the_proceeds_leg():
    """The other leg of the same rule, and the third input of the class.

    A $1,000 sell of 3 * 10**33 raw units split across two lots: the first lot closes untouched and
    the second is only nicked, so the cost side is exact and only the proceeds guard can fire. The
    drift is the same hand-derived figure, because the shape of the division is the same.
    """
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo(
            [buy(block=10, qty_raw=3 * 10 ** 33 - 1, usd="2000"),
             buy(block=20, qty_raw=10 ** 20, usd="50")],
            [sell(block=30, qty_raw=3 * 10 ** 33, usd="1000")],
        )

    message = str(excinfo.value)
    assert "proceeds" in message
    assert "relative drift {}".format(DRIFT_AT_3E33) in message
    assert "0.00001000000000000000000000000000" not in message


# A lot quantity and a basis for which the drift lands just above the limit. Found by search
# rather than by derivation — the point of it is the knife edge, and a knife edge cannot be picked
# out of the air — but every number asserted below is written out.
#
#     lot            27,073,229,666,717,931,550,795,333,135,022 raw units, $8,104.29 basis
#     first slice    8104.2899999999999999999999999997006530      (38 significant digits)
#     basis left     8104.29 - that = 2.993470E-28                 ( 7 significant digits)
#     the share      8104.29 / N     = 2.9934699700652586877859860494577103212E-28
#     drift          1.0000013900777974454019961111223857617E-8    vs a limit of 1E-8
#
# Nine parts in ten million over the line. Rounded to six significant digits it is exactly the
# limit, and the book is reported instead of queued.
KNIFE_EDGE_QUANTITY = 27073229666717931550795333135022
KNIFE_EDGE_BASIS = "8104.29"
KNIFE_EDGE_DRIFT = Decimal("1.0000013900777974454019961111223857617E-8")
KNIFE_EDGE_CLOSING_BASIS = Decimal("2.993470E-28")


def _knife_edge():
    return (
        [buy(block=10, qty_raw=KNIFE_EDGE_QUANTITY, usd=KNIFE_EDGE_BASIS)],
        [sell(block=20, qty_raw=KNIFE_EDGE_QUANTITY - 1, usd="900"),
         sell(block=30, qty_raw=1, usd="1")],
    )


def test_the_callers_precision_cannot_turn_a_quarantine_into_a_reported_book():
    """The consequence, in the only currency that matters: a book that changes verdict.

    The hostile context here differs from the frozen one in one respect only — six significant
    digits instead of thirty-eight, same ROUND_HALF_EVEN — which is an ordinary thing for a caller
    formatting a report to have set. Under it, a drift nine parts in ten million above the limit
    rounds to exactly the limit, ``drift <= MAX_CLOSING_DRIFT`` becomes true, and a closing basis of
    2.993470E-28 that no validator can re-derive is emitted as a measured value instead of being
    queued.
    """
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo(*_knife_edge())
    assert "relative drift {}".format(KNIFE_EDGE_DRIFT) in str(excinfo.value)

    with pytest.raises(QuarantineRequired):
        with localcontext(Context(prec=6, rounding=ROUND_HALF_EVEN)):
            match_fifo(*_knife_edge())


def test_no_refusal_message_depends_on_the_callers_ambient_decimal_context():
    """The class, rather than the three instances above.

    Every refusal this module can raise, replayed under contexts that vary precision and rounding
    mode in both directions. A single Decimal operation anywhere in the module that reads the
    ambient context instead of the frozen one changes one of these strings, whether or not anyone
    has yet thought of an input that makes it change a verdict.
    """
    cases = [
        _knife_edge(),
        ([buy(block=10, qty_raw=3 * 10 ** 31, usd="1000")],
         [sell(block=20, qty_raw=3 * 10 ** 31 - 1, usd="900"),
          sell(block=30, qty_raw=1, usd="1")]),
        ([buy(block=10, qty_raw=3 * 10 ** 33, usd="1000")],
         [sell(block=20, qty_raw=3 * 10 ** 33 - 1, usd="900"),
          sell(block=30, qty_raw=1, usd="1")]),
        ([buy(block=10, qty_raw=10 ** 39, usd="1000")],
         [sell(block=20, qty_raw=10 ** 39 - 1, usd="900"),
          sell(block=30, qty_raw=1, usd="1")]),
        ([buy(block=10, qty_raw=3 * 10 ** 33 - 1, usd="2000"),
          buy(block=20, qty_raw=10 ** 20, usd="50")],
         [sell(block=30, qty_raw=3 * 10 ** 33, usd="1000")]),
    ]
    hostile = [
        Context(prec=6, rounding=ROUND_HALF_EVEN),
        Context(prec=6, rounding=ROUND_UP),
        Context(prec=9, rounding=ROUND_DOWN),
        Context(prec=60, rounding=ROUND_HALF_EVEN),
    ]

    for buys, sells in cases:
        with pytest.raises(QuarantineRequired) as excinfo:
            match_fifo(buys, sells)
        baseline = str(excinfo.value)

        for context in hostile:
            with pytest.raises(QuarantineRequired) as hostile_info:
                with localcontext(context):
                    match_fifo(buys, sells)
            assert str(hostile_info.value) == baseline, (
                "prec={} rounding={} changed the refusal".format(
                    context.prec, context.rounding
                )
            )


def test_the_pro_rata_sign_is_applied_at_the_frozen_precision_too():
    """The same class, on the branch no input can reach.

    ``_pro_rata`` splits the USD figure into sign and coefficient so the multiply can run on
    integers, and puts the sign back afterwards. A bare unary minus there rounds to the ambient
    context exactly as ``abs()`` does — ``Decimal.__neg__`` takes the same path — and truncates a
    38-digit share to 28 on its way out.

    No public call can reach it: the seam refuses a negative ``quote_usd`` outright, so a lot's
    basis and a sell's proceeds are both non-negative and the branch is dead today. It is pinned at
    the helper because a latent instance of a defect class is still an instance, and the day a
    signed figure legitimately reaches this function is not the day to discover it.
    """
    from fifo.matching import _pro_rata

    positive = _pro_rata(Decimal("10"), 1, 3)
    negative = _pro_rata(Decimal("-10"), 1, 3)

    assert positive == Decimal("3.3333333333333333333333333333333333333")
    assert negative == Decimal("-3.3333333333333333333333333333333333333")
    assert len(negative.as_tuple().digits) == 38

    with localcontext(Context(prec=6, rounding=ROUND_UP)):
        assert _pro_rata(Decimal("-10"), 1, 3) == negative


def test_an_ordinary_three_hundred_token_position_still_closes_on_its_last_raw_unit():
    """The guard must not refuse the ordinary case it was added to bound.

        3 * 10**20 raw units is 300 tokens at 18 decimals.
        first slice, exact   1000 * (3*10**20 - 1) / (3*10**20)
        at 38 digits         = 999.99999999999999999666666666666666667
        basis left           = 3.33333333333333333E-18   (18 significant digits)
        the share            = 3.3333333333333333333333333333333333333E-18
        drift ~ 1e-18, which is ten orders below the limit.
    """
    result = match_fifo(
        [buy(block=10, qty_raw=3 * 10 ** 20, usd="1000")],
        [sell(block=20, qty_raw=3 * 10 ** 20 - 1, usd="900"),
         sell(block=30, qty_raw=1, usd="1")],
    )

    assert [c.consumed_raw for c in result.consumptions] == [3 * 10 ** 20 - 1, 1]
    assert result.consumptions[0].allocated_cost_usd == Decimal(
        "999.99999999999999999666666666666666667"
    )
    assert result.consumptions[1].allocated_cost_usd == Decimal("3.33333333333333333E-18")
    # The dust rule still closes the lot to exactly zero.
    assert total(c.allocated_cost_usd for c in result.consumptions) == Decimal("1000")
    assert result.open_lots == ()


def test_the_proceeds_side_of_the_dust_rule_is_guarded_too():
    """The same shape on the other leg: the last slice of a *sell* takes what is left of the
    proceeds, and that remainder decays exactly as the basis one does.

        sell of 3 * 10**33 raw units for $1,000, split 3*10**33 - 1 from lot 1 and 1 from lot 2
        first slice, exact   1000 * (3*10**33 - 1) / (3*10**33)
        at 38 digits         = 999.99999999999999999999999999999966667
        proceeds left        = 3.3333E-31
        the share the rule states = 3.3333333333333333333333333333333333333E-31

    Both lots hand out a clean basis here — lot 1 closes untouched and lot 2 is only nicked — so
    the cost side is exact and this can only be the proceeds guard firing. The reviewer flagged the
    basis leg; this leg has the identical defect and the additional failure mode that the residue
    can cross zero, which ``LotConsumption`` refuses as a bare ``ValueError`` too.
    """
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo(
            [buy(block=10, qty_raw=3 * 10 ** 33 - 1, usd="2000"),
             buy(block=20, qty_raw=10 ** 20, usd="50")],
            [sell(block=30, qty_raw=3 * 10 ** 33, usd="1000")],
        )

    message = str(excinfo.value)
    assert "proceeds" in message
    assert "3.3333E-31" in message
    assert "3.3333333333333333333333333333333333333E-31" in message


def test_the_pro_rata_product_is_exact_and_the_share_is_rounded_once():
    """``total_usd * taken_raw`` must not be rounded — only the division may round.

        1000 * (10**30 - 1)        = 999999999999999999999999999999000   (33 significant digits)
        at the ambient 28 digits   = 1.000000000000000000000000000E+33
        divided by 10**30, exactly = 999.999999999999999999999999999
        divided by 10**30, rounded = 1000  exactly

    ``contracts.divide`` holds the 38-digit context for itself, so an implementation that computes
    the product with ``Decimal.__mul__`` outside a frozen block hands the division a number already
    truncated to whatever precision the caller happened to be in — the same shape as the defect the
    seam fixed in ``realized_return``, and invisible unless the product needs more than 28 digits.
    Every case that existed before this one multiplies numbers that fit, so all of them agree
    either way.
    """
    result = match_fifo(
        [buy(block=10, qty_raw=10 ** 30, usd="1000")],
        [sell(block=20, qty_raw=10 ** 30 - 1, usd="900")],
    )

    allocated = result.consumptions[0].allocated_cost_usd
    assert allocated == Decimal("999.999999999999999999999999999")
    assert allocated != Decimal("1000")


def test_a_slice_can_never_allocate_more_basis_than_the_lot_holds():
    """2**128 raw units for $3, all but one unit sold. The share is the whole $3, never more.

        exact share   3 * (2**128 - 1) / 2**128 = 3 - 3/2**128 = 3 - 8.8...E-39
        at 38 significant digits                                = 3  exactly

    Rounding the intermediate product gives a different answer. 3 * (2**128 - 1) is a 39-digit
    integer; at 38 digits it rounds *up* to 3 * 2**128, and dividing that by 2**128 rounds up
    again, to 3.0000000000000000000000000000000000001 — one unit in the last place above the
    entire basis the lot holds, from a share the arithmetic guarantees is smaller than the whole.
    The lot then hands out more than it has and its remaining basis goes negative, which nothing
    downstream can see because an open lot carries a quantity and no basis at all.

    So the product is taken on the integer coefficient, where it is exact, and the division is the
    only rounding step.
    """
    result = match_fifo(
        [buy(block=10, qty_raw=2 ** 128, usd="3")],
        [sell(block=20, qty_raw=2 ** 128 - 1, usd="5")],
    )

    consumption = result.consumptions[0]
    assert consumption.allocated_cost_usd == Decimal("3")
    assert consumption.allocated_cost_usd <= consumption.buy.quote_usd
    assert result.open_lots[0].remaining_raw == 1


def test_no_output_depends_on_the_callers_ambient_decimal_context():
    """The whole class of defect the seam's ``sub``/``add``/``mul`` primitives exist to prevent.

    ``LotConsumption.realized_return`` shipped computing ``divide(...) - Decimal("1")``: the divide
    held the frozen 38-digit context and the subtraction landed back in the caller's, so the
    primary metric's value depended on who called it. Nothing looked wrong. Running the same
    matching inside a deliberately hostile context is the check that catches it structurally rather
    than one expression at a time — a caller in an aggregation loop may legitimately be anywhere.
    """
    buys = [buy(block=10, qty_raw=3, usd="10")]
    sells = [sell(block=20, qty_raw=1, usd="4"), sell(block=30, qty_raw=2, usd="9")]

    baseline = match_fifo(buys, sells)
    with localcontext(Context(prec=6, rounding=ROUND_UP)):
        hostile = match_fifo(buys, sells)

    assert [c.allocated_cost_usd for c in hostile.consumptions] == [
        c.allocated_cost_usd for c in baseline.consumptions
    ]
    assert [c.proceeds_usd for c in hostile.consumptions] == [
        c.proceeds_usd for c in baseline.consumptions
    ]
    assert [c.realized_return for c in hostile.consumptions] == [
        c.realized_return for c in baseline.consumptions
    ]
    # And the values really are precision-sensitive, so agreement means something.
    assert hostile.consumptions[0].allocated_cost_usd == Decimal(
        "3.3333333333333333333333333333333333333"
    )

    # Again where the pro-rata product needs more digits than an ambient context carries, so a
    # multiply that escaped the frozen precision would show up as a different number rather than
    # as the same one.
    with localcontext(Context(prec=6, rounding=ROUND_UP)):
        wide = match_fifo(
            [buy(block=10, qty_raw=10 ** 30, usd="1000")],
            [sell(block=20, qty_raw=10 ** 30 - 1, usd="900")],
        )
    assert wide.consumptions[0].allocated_cost_usd == Decimal("999.999999999999999999999999999")


# -- refusals --------------------------------------------------------------------


def test_a_sell_before_any_buy_is_quarantined():
    """Not clamped to zero, not dropped: it means a buy was missed (ticket 22)."""
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo([buy(block=200, qty_raw=100, usd="100")], [sell(block=100, qty_raw=10, usd="30")])

    message = str(excinfo.value)
    assert "before any buy" in message
    assert "10" in message


def test_a_sell_with_no_buys_at_all_is_quarantined():
    with pytest.raises(QuarantineRequired):
        match_fifo([], [sell(block=100, qty_raw=10, usd="30")])


def test_a_sell_exceeding_the_open_quantity_is_quarantined_not_clamped():
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo([buy(block=10, qty_raw=100, usd="100")], [sell(block=20, qty_raw=150, usd="450")])

    message = str(excinfo.value)
    assert "150" in message and "100" in message
    assert "clamp" in message


def test_the_second_of_two_sells_may_exhaust_the_book_and_is_quarantined():
    with pytest.raises(QuarantineRequired):
        match_fifo(
            [buy(block=10, qty_raw=100, usd="100")],
            [sell(block=20, qty_raw=60, usd="60"), sell(block=30, qty_raw=60, usd="60")],
        )


def test_mixed_assets_are_refused():
    with pytest.raises(ValueError) as excinfo:
        match_fifo(
            [buy(block=10, qty_raw=100, usd="100"),
             buy(block=20, qty_raw=100, usd="100", asset=OTHER_TOKEN)],
            [],
        )
    assert TOKEN in str(excinfo.value) and OTHER_TOKEN in str(excinfo.value)


def test_mixed_owners_are_refused():
    with pytest.raises(ValueError) as excinfo:
        match_fifo(
            [buy(block=10, qty_raw=100, usd="100"),
             buy(block=20, qty_raw=100, usd="100", owner=OTHER_WALLET)],
            [],
        )
    assert "owner" in str(excinfo.value)


def test_an_unresolved_owner_is_refused_rather_than_pooled():
    """§8: uncertain owner attribution is excluded from the primary metric, never guessed."""
    with pytest.raises(AttributionUnresolvedError):
        match_fifo([buy(block=10, qty_raw=100, usd="100", owner=None)], [])


def test_two_events_in_one_block_are_ambiguous_and_quarantined():
    """NetTradeResult carries no transaction or log index, so intra-block order is unknowable."""
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo(
            [buy(block=10, qty_raw=100, usd="100", tx=_tx(1)),
             buy(block=10, qty_raw=100, usd="500", tx=_tx(2))],
            [],
        )
    assert "order" in str(excinfo.value)
    assert "10" in str(excinfo.value)


def test_a_buy_and_a_sell_in_one_block_are_ambiguous_too():
    with pytest.raises(QuarantineRequired):
        match_fifo(
            [buy(block=10, qty_raw=100, usd="100", tx=_tx(1))],
            [sell(block=10, qty_raw=50, usd="200", tx=_tx(2))],
        )


def test_the_same_transaction_twice_is_refused():
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo(
            [buy(block=10, qty_raw=100, usd="100", tx=_tx(7)),
             buy(block=20, qty_raw=100, usd="100", tx=_tx(7))],
            [],
        )
    assert "twice" in str(excinfo.value) or "duplicate" in str(excinfo.value)


def test_the_duplicate_refusal_names_both_causes_and_diagnoses_neither():
    """It said *"the netting output was merged wrongly"*, and that is a claim it cannot support.

    A duplicated transaction reaches a lot book from two directions — a caller that supplied the
    same transaction twice, and a netting output merged wrongly — and ``match_fifo`` is handed the
    book, not the pipeline that built it. Naming one of the two sends a reader to audit a stage
    that may be blameless while the actual defect sits in the input; ``pipeline.run_wallet_window``
    refuses the duplicate before FIFO ever sees it precisely because *it* can tell.

    The weaker message is the accurate one. The refusal still says what it refused and why it will
    not pick a row, which is what a reader needs to act.
    """
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo(
            [buy(block=10, qty_raw=100, usd="100", tx=_tx(7)),
             buy(block=20, qty_raw=100, usd="100", tx=_tx(7))],
            [],
        )
    message = str(excinfo.value)

    assert _tx(7) in message
    assert "the caller supplied the same transaction twice" in message
    assert "a netting output was merged wrongly" in message
    assert "cannot tell those apart" in message
    # The claim that was there before, as a diagnosis rather than as one of two candidates.
    assert "so a duplicate means the netting output was merged wrongly" not in message


def test_a_missing_block_number_is_refused():
    from contracts import NetTradeResult

    orphan = NetTradeResult(
        tx_hash=_tx(1), portfolio_owner=WALLET, status=ClassificationStatus.VALID_BUY,
        sold_asset=USDC, bought_asset=TOKEN, sold_raw_amount=100, bought_raw_amount=100,
        quote_asset=USDC, quote_usd=Decimal("100"), block_number=None, timestamp=_timestamp(10),
    )
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo([orphan], [])
    assert "block" in str(excinfo.value)


def test_a_non_trade_result_is_refused():
    from contracts import NetTradeResult

    not_a_trade = NetTradeResult(
        tx_hash=_tx(1), portfolio_owner=WALLET, status=ClassificationStatus.NO_CLEAR_ENDPOINT,
        block_number=10, timestamp=_timestamp(10), reason="three non-zero endpoints",
    )
    with pytest.raises(ValueError) as excinfo:
        match_fifo([not_a_trade], [])
    assert "VALID_BUY" in str(excinfo.value)


def test_a_sell_passed_in_the_buys_argument_is_refused():
    with pytest.raises(ValueError):
        match_fifo([sell(block=10, qty_raw=100, usd="100")], [])


def test_a_buy_passed_in_the_sells_argument_is_refused():
    with pytest.raises(ValueError):
        match_fifo([], [buy(block=10, qty_raw=100, usd="100")])


def test_a_buy_without_a_usd_cost_basis_is_quarantined():
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo([buy(block=10, qty_raw=100, usd=None)], [])
    assert "quote_usd" in str(excinfo.value)


def test_a_buy_with_a_zero_cost_basis_is_quarantined_by_this_module():
    """The seam refuses a zero denominator and says the domain must classify it. This is that
    classification: unpriceable, so it goes to the queue rather than into the metric."""
    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo([buy(block=10, qty_raw=100, usd="0")], [sell(block=20, qty_raw=100, usd="5")])
    assert "undefined" in str(excinfo.value)


def test_a_sell_for_nothing_is_a_measured_total_loss_not_a_refusal():
    """-100% is a finding. Refusing here would delete the worst outcomes from the study."""
    result = match_fifo(
        [buy(block=10, qty_raw=100, usd="500")], [sell(block=20, qty_raw=100, usd="0")]
    )
    assert result.consumptions[0].proceeds_usd == Decimal("0")
    assert result.consumptions[0].realized_return == Decimal("-1")


def test_a_float_usd_value_is_refused_by_the_numeric_policy():
    from contracts import NetTradeResult

    tainted = NetTradeResult(
        tx_hash=_tx(1), portfolio_owner=WALLET, status=ClassificationStatus.VALID_BUY,
        sold_asset=USDC, bought_asset=TOKEN, sold_raw_amount=100, bought_raw_amount=100,
        quote_asset=USDC, quote_usd=100.0, block_number=10, timestamp=_timestamp(10),
    )
    with pytest.raises(TypeError) as excinfo:
        match_fifo([tainted], [])
    assert "float" in str(excinfo.value)


def test_something_that_is_not_a_trade_result_is_refused():
    with pytest.raises(TypeError):
        match_fifo(["0xdeadbeef"], [])


# -- shape -----------------------------------------------------------------------


def test_empty_inputs_produce_an_empty_result():
    result = match_fifo([], [])
    assert result.consumptions == ()
    assert result.open_lots == ()
    assert result.unmatched_sell_raw == {}


def test_a_buy_with_no_sell_stays_wholly_open():
    a_buy = buy(block=10, qty_raw=100, usd="100")
    result = match_fifo([a_buy], [])
    assert result.consumptions == ()
    assert len(result.open_lots) == 1
    assert result.open_lots[0].remaining_raw == 100


def test_there_is_no_switch_that_selects_another_matching_method():
    """Ticket 22: no configuration option, environment variable, or parameter may select one.

    The rule's whole value is that it cannot be changed mid-analysis to improve a chart, so the
    absence of a lever is part of the contract rather than a stylistic preference.
    """
    parameters = inspect.signature(match_fifo).parameters
    assert list(parameters) == ["buys", "sells"]
    assert all(p.default is inspect.Parameter.empty for p in parameters.values())
    assert all(p.kind is not inspect.Parameter.KEYWORD_ONLY for p in parameters.values())


def test_the_module_reads_no_configuration_and_touches_no_outside_world():
    """Pure function: no environment, no clock, no randomness, no I/O."""
    import fifo

    package = os.path.dirname(os.path.abspath(fifo.__file__))
    sources = []
    for name in sorted(os.listdir(package)):
        if name.endswith(".py"):
            with open(os.path.join(package, name), "r", encoding="utf-8") as handle:
                sources.append(handle.read())
    text = "\n".join(sources)

    for forbidden in ("environ", "getenv", "argv", "random", "time.", "datetime", "open("):
        assert forbidden not in text, "{} must not appear in the FIFO module".format(forbidden)


def test_every_output_survives_canonical_json():
    """A float leaking in through any path raises here rather than reaching a report."""
    result = match_fifo(
        [buy(block=10, qty_raw=3, usd="10")],
        [sell(block=20, qty_raw=1, usd="4"), sell(block=30, qty_raw=1, usd="5")],
    )
    payload = to_canonical_json(result)

    # A quoted string, never a JSON number — a JSON number is read back as a double.
    assert '"3.3333333333333333333333333' in payload
    assert to_canonical_json(result) == payload
    assert "3.33," not in payload and '"3.33"' not in payload


def test_the_in_memory_value_carries_the_full_frozen_precision():
    """Serialization renders at the ambient context; the value itself must not be pre-truncated.

    ``canonicalise`` calls ``Decimal.normalize()``, which runs under whatever context the caller
    is in — 28 digits by default — so the canonical JSON is narrower than the 38 digits this
    module computes at. That is the seam's boundary behaviour to decide on, not something FIFO may
    pre-empt by rounding its own output.
    """
    result = match_fifo([buy(block=10, qty_raw=3, usd="10")], [sell(block=20, qty_raw=1, usd="4")])
    allocated = result.consumptions[0].allocated_cost_usd

    assert allocated == Decimal("3.3333333333333333333333333333333333333")
    assert len(allocated.as_tuple().digits) == 38
