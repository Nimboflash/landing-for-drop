"""Realistic multi-step FIFO scenarios: 18-decimal tokens, interleaved partial sells, re-entry.

Ticket 22 asks for a wallet with interleaved buys and multiple partial sells producing "a correct
running open quantity at every point", reconciling to raw balance deltas. That is what the walk
below checks, step by step, rather than only at the end.
"""

from decimal import Decimal, localcontext

import pytest

from contracts import (
    CALCULATION_CONTEXT,
    USDC,
    WETH,
    ClassificationStatus,
    DerivedFieldMismatch,
    NetTradeResult,
    QuarantineRequired,
    TokenAgeBucket,
    artifact_envelope,
    canonical_hash,
    divide,
    sub,
    to_canonical_json,
    verify_redundant_derived,
)
from fifo import match_fifo

WALLET = "0x" + "11" * 20
TOKEN = "0x" + "aa" * 20
POOL = "0x" + "cc" * 20

UNIT = 10 ** 18  # an ordinary 18-decimal ERC-20


def _trade(status, block, qty_raw, usd, quote=USDC, bucket=None):
    is_buy = status is ClassificationStatus.VALID_BUY
    usd = Decimal(usd)
    quote_raw = int(usd * (10 ** (18 if quote == WETH else 6)))
    return NetTradeResult(
        tx_hash="0x{:064x}".format(block),
        portfolio_owner=WALLET,
        status=status,
        sold_asset=quote if is_buy else TOKEN,
        bought_asset=TOKEN if is_buy else quote,
        sold_raw_amount=quote_raw if is_buy else qty_raw,
        bought_raw_amount=qty_raw if is_buy else quote_raw,
        quote_asset=quote,
        quote_usd=usd,
        block_number=block,
        timestamp=1_600_000_000 + block * 12,
        token_age_bucket=bucket,
        pool=POOL,
    )


def buy(block, tokens, usd, quote=USDC, bucket=None):
    return _trade(ClassificationStatus.VALID_BUY, block, tokens * UNIT, usd, quote, bucket)


def sell(block, tokens, usd, quote=USDC):
    return _trade(ClassificationStatus.VALID_SELL, block, tokens * UNIT, usd, quote)


def split(events):
    return (
        [e for e in events if e.status is ClassificationStatus.VALID_BUY],
        [e for e in events if e.status is ClassificationStatus.VALID_SELL],
    )


def total(values):
    with localcontext(CALCULATION_CONTEXT):
        out = Decimal(0)
        for value in values:
            out += value
        return out


# The story: three entries and two partial exits, leaving a position open at the end of the window.
#
#   blk 1000  buy  1000 tokens for $2,000     ($2.00)
#   blk 2000  buy   500 tokens for $1,500     ($3.00)
#   blk 3000  sell 1200 tokens for $4,800     ($4.00)  -> 1000 of lot 1, 200 of lot 2
#   blk 4000  buy   300 tokens for $1,200     ($4.00)
#   blk 5000  sell  400 tokens for $1,000     ($2.50)  ->  300 of lot 2, 100 of lot 3
#   open:     200 tokens of lot 3, $800 of basis
WALLET_STORY = [
    buy(1000, 1000, "2000", bucket=TokenAgeBucket.D),
    buy(2000, 500, "1500", bucket=TokenAgeBucket.D),
    sell(3000, 1200, "4800"),
    buy(4000, 300, "1200", bucket=TokenAgeBucket.C),
    sell(5000, 400, "1000"),
]


def test_interleaved_buys_and_partial_sells_assign_lots_by_hand_computed_expectation():
    result = match_fifo(*split(WALLET_STORY))

    assert [(c.buy.block_number, c.sell.block_number, c.consumed_raw // UNIT)
            for c in result.consumptions] == [
        (1000, 3000, 1000),
        (2000, 3000, 200),
        (2000, 5000, 300),
        (4000, 5000, 100),
    ]
    assert [c.allocated_cost_usd for c in result.consumptions] == [
        Decimal("2000"), Decimal("600"), Decimal("900"), Decimal("400"),
    ]
    assert [c.proceeds_usd for c in result.consumptions] == [
        Decimal("4000"), Decimal("800"), Decimal("750"), Decimal("250"),
    ]
    # Hand-computed, at the frozen 38-digit precision. Written as literals rather than by
    # re-running the implementation's own expression: the previous version did the latter and
    # thereby blessed a real defect — the subtraction fell outside the frozen context and
    # truncated 4/3 - 1 to 28 digits, and the test agreed with it because it made the same
    # mistake. A test that recomputes the implementation cannot detect the implementation.
    #
    #   800/600 = 1.333... at 38 significant digits, minus 1 -> 37 digits after the point
    #   750/900 = 0.8333... at 38 significant digits, minus 1 -> 38 digits, final digit
    #   rounded HALF_EVEN to ...67
    assert [c.realized_return for c in result.consumptions] == [
        Decimal("1"),
        Decimal("0.3333333333333333333333333333333333333"),
        Decimal("-0.16666666666666666666666666666666666667"),
        Decimal("-0.375"),
    ]

    assert len(result.open_lots) == 1
    assert result.open_lots[0].buy.block_number == 4000
    assert result.open_lots[0].remaining_raw == 200 * UNIT


def test_the_realized_and_open_split_reconciles_to_the_raw_balance_delta():
    buys, sells = split(WALLET_STORY)
    result = match_fifo(buys, sells)

    bought = sum(b.bought_raw_amount for b in buys)
    sold = sum(s.sold_raw_amount for s in sells)
    consumed = sum(c.consumed_raw for c in result.consumptions)
    open_raw = sum(lot.remaining_raw for lot in result.open_lots)

    assert consumed == sold
    assert open_raw == bought - sold
    assert open_raw == 200 * UNIT

    # Cost basis splits the same way: $3,900 realized against $800 still carried into the day-30
    # mark (§4.4 case 2 prices the *remaining* quantity, so the basis behind it must be exact).
    assert total(c.allocated_cost_usd for c in result.consumptions) == Decimal("3900")
    assert sub(total(b.quote_usd for b in buys), Decimal("3900")) == Decimal("800")


def test_the_running_open_quantity_is_correct_at_every_point_in_the_window():
    """Replay the window one event at a time; each prefix must agree with the raw delta and with
    the assignment the full window produced."""
    whole = match_fifo(*split(WALLET_STORY))

    for cut in range(len(WALLET_STORY) + 1):
        prefix_events = WALLET_STORY[:cut]
        buys, sells = split(prefix_events)
        step = match_fifo(buys, sells)

        expected_open = (sum(b.bought_raw_amount for b in buys)
                         - sum(s.sold_raw_amount for s in sells))
        assert sum(lot.remaining_raw for lot in step.open_lots) == expected_open

        # And no later event rewrote an earlier lot assignment.
        assert whole.consumptions[: len(step.consumptions)] == step.consumptions


def test_a_full_exit_and_re_entry_starts_a_fresh_lot():
    events = [
        buy(100, 10, "100"),
        sell(200, 10, "150"),
        buy(300, 10, "120"),
        sell(400, 10, "90"),
    ]
    result = match_fifo(*split(events))

    assert len(result.consumptions) == 2
    assert result.open_lots == ()
    assert [c.buy.block_number for c in result.consumptions] == [100, 300]
    assert [c.realized_return for c in result.consumptions] == [Decimal("0.5"), Decimal("-0.25")]


def test_a_sell_in_a_different_quote_asset_is_still_matched():
    """§4.6 allows any liquid quote asset. The buy legs are USDC, the exit is WETH, and the return
    comes from the USD value of the legs actually used — no oracle for the traded token."""
    events = [buy(100, 100, "1000", quote=USDC), sell(200, 100, "1500", quote=WETH)]
    result = match_fifo(*split(events))

    assert result.consumptions[0].allocated_cost_usd == Decimal("1000")
    assert result.consumptions[0].proceeds_usd == Decimal("1500")
    assert result.consumptions[0].realized_return == Decimal("0.5")


def test_many_small_sells_against_one_awkward_lot_conserve_every_unit_and_every_cent():
    """7 tokens bought for $10 and sold one at a time: neither the quantity nor the basis divides
    evenly, and both must still close to zero."""
    events = [buy(100, 7, "10")]
    events += [sell(200 + 100 * i, 1, "2") for i in range(7)]

    result = match_fifo(*split(events))

    assert len(result.consumptions) == 7
    assert sum(c.consumed_raw for c in result.consumptions) == 7 * UNIT
    assert result.open_lots == ()
    assert total(c.allocated_cost_usd for c in result.consumptions) == Decimal("10")
    assert total(c.proceeds_usd for c in result.consumptions) == Decimal("14")

    with localcontext(CALCULATION_CONTEXT):
        pro_rata = Decimal("10") / Decimal("7")
    assert result.consumptions[0].allocated_cost_usd == pro_rata
    # Only the closing slice differs, and only by the last digit the frozen precision carries.
    assert result.consumptions[-1].allocated_cost_usd != pro_rata


def test_a_missed_buy_surfaces_as_an_actionable_quarantine_rather_than_a_clamp():
    """The sell is real; our record of the buys is not complete. §11 forbids dropping it silently,
    and a clamped quantity would flow downstream as a measured position."""
    events = [buy(100, 300, "600"), sell(200, 500, "1500")]

    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo(*split(events))

    message = str(excinfo.value)
    assert str(500 * UNIT) in message and str(300 * UNIT) in message
    assert TOKEN in message
    assert "0x{:064x}".format(200) in message  # the offending transaction, for the queue


def test_a_quadrillion_supply_position_is_queued_rather_than_valued():
    """The long-tail shape this study is built to look at, at the supply those tokens actually run.

    3 quadrillion tokens at 18 decimals is 3 * 10**33 raw units — SHIB territory, not a contrived
    number. Sell all but one raw unit and the basis left for the closing slice is no longer a share
    of anything: at 38 significant digits it comes out as 3.3333E-31 against a true share of
    3.3333333333333333333333333333333333333E-31, wrong by one part in 100,000 and positive, small
    and plausible in every report it would have reached.

    So the book goes to the reconciliation queue whole, and the message has to carry enough for
    someone to act on it: which transaction, how many units, and both numbers.
    """
    events = [
        buy(1000, 3 * 10 ** 15, "1000"),
        # Sold down to a single raw unit — 1e-18 of one token, worth about 3e-31 dollars.
        _trade(ClassificationStatus.VALID_SELL, 2000, 3 * 10 ** 33 - 1, "900"),
        _trade(ClassificationStatus.VALID_SELL, 3000, 1, "1"),
    ]

    with pytest.raises(QuarantineRequired) as excinfo:
        match_fifo(*split(events))

    message = str(excinfo.value)
    assert "0x{:064x}".format(3000) in message
    assert "3.3333E-31" in message
    assert "3.3333333333333333333333333333333333333E-31" in message
    assert "quarantined" in message.lower()


def test_a_long_tail_position_at_ordinary_supply_is_still_valued_to_the_last_raw_unit():
    """The counterpart: refusing the case above must not cost us the ordinary one.

    300 tokens at 18 decimals is 3 * 10**20 raw units. The same walk closes the same way, and the
    closing slice keeps 18 significant digits of its share, ten orders below the point at which any
    published figure could notice.
    """
    events = [
        buy(1000, 300, "1000"),
        _trade(ClassificationStatus.VALID_SELL, 2000, 3 * 10 ** 20 - 1, "900"),
        _trade(ClassificationStatus.VALID_SELL, 3000, 1, "1"),
    ]

    result = match_fifo(*split(events))

    assert [c.consumed_raw for c in result.consumptions] == [300 * UNIT - 1, 1]
    assert result.consumptions[1].allocated_cost_usd == Decimal("3.33333333333333333E-18")
    assert total(c.allocated_cost_usd for c in result.consumptions) == Decimal("1000")
    assert result.open_lots == ()


def test_the_whole_result_travels_as_a_canonical_artifact():
    result = match_fifo(*split(WALLET_STORY))
    envelope = artifact_envelope("fifo_result", "fifo", result)

    assert envelope["kind"] == "fifo_result"
    assert envelope["payload"]["consumptions"][0]["consumed_raw"] == str(1000 * UNIT)
    assert envelope["payload"]["consumptions"][0]["allocated_cost_usd"] == "2000"
    assert envelope["payload"]["open_lots"][0]["remaining_raw"] == str(200 * UNIT)

    # Raw quantities exceed 2^53, so they must have crossed as strings.
    assert '"' + str(1000 * UNIT) + '"' in to_canonical_json(result)
    assert canonical_hash(result) == canonical_hash(match_fifo(*split(WALLET_STORY)))


#: What a consumer of the artifact must do to get a return out of it: divide the two primitives
#: the envelope carries and subtract one, all of it at the frozen precision. ``divide(...) - 1``
#: would land the subtraction in the caller's ambient context, which is the defect this module's
#: primary metric shipped with; a consumer written that way gets a different number from the one
#: the freeze manifest hashed.
def _return_from_primitives(row):
    return sub(divide(Decimal(row["proceeds_usd"]), Decimal(row["allocated_cost_usd"])),
               Decimal("1"))


def test_the_artifact_carries_primitives_and_a_consumer_recomputes_the_return():
    """A derived field is never authoritative in an artifact — the cost and the proceeds are.

    So the envelope must not claim a return on any row, and recomputing one from what it does
    carry has to land on the hand-computed value. Every expectation below is a literal:

        row 0   $2,000 -> $4,000    4000/2000 - 1 =  1
        row 1     $600 ->   $800     800/600  - 1 =  0.333...  37 digits after the point
        row 2     $900 ->   $750     750/900  - 1 = -0.166...  38 digits, last one HALF_EVEN to 7
        row 3     $400 ->   $250     250/400  - 1 = -0.375

    Rows 1 and 2 are the load-bearing ones and the reason the list is checked whole. A version of
    this test that looked only at row 0 asserted a recomputation against a recomputation on the one
    row where both sides are exactly 1, so it agreed with any arithmetic at all.
    """
    result = match_fifo(*split(WALLET_STORY))
    payload = artifact_envelope("fifo_result", "fifo", result)["payload"]
    rows = payload["consumptions"]

    assert [("realized_return" in row) for row in rows] == [False, False, False, False]
    assert [(row["allocated_cost_usd"], row["proceeds_usd"]) for row in rows] == [
        ("2000", "4000"), ("600", "800"), ("900", "750"), ("400", "250"),
    ]

    expected = [
        Decimal("1"),
        Decimal("0.3333333333333333333333333333333333333"),
        Decimal("-0.16666666666666666666666666666666666667"),
        Decimal("-0.375"),
    ]
    assert [_return_from_primitives(row) for row in rows] == expected
    # And the in-memory projection lands on the same literals, so the artifact and the object it
    # came from are not two different answers.
    assert [c.realized_return for c in result.consumptions] == expected


def test_a_return_claimed_in_an_artifact_is_checked_against_its_primitives():
    """The other half of the rule, which the absence above makes it easy to leave unasserted.

    ``verify_redundant_derived`` skips a field the payload does not contain, so handing it a
    recomputation for ``realized_return`` against a row that has none runs the lambda zero times
    and asserts nothing. It has to be given a row that claims one.

    The wrong value used here is not arbitrary: 0.3333333333333333333333333333 is what row 1's
    return became when the subtraction ran at the ambient 28 digits instead of the frozen 38. It
    is off in the 29th decimal and correct everywhere a human would look, which is the whole
    argument for checking a derived field rather than reading it.
    """
    result = match_fifo(*split(WALLET_STORY))
    row = artifact_envelope("fifo_result", "fifo", result)["payload"]["consumptions"][1]
    recomputation = {"realized_return": _return_from_primitives}

    honest = dict(row, realized_return="0.3333333333333333333333333333333333333")
    assert verify_redundant_derived(honest, recomputation) is True

    truncated = dict(row, realized_return="0.3333333333333333333333333333")
    with pytest.raises(DerivedFieldMismatch) as excinfo:
        verify_redundant_derived(truncated, recomputation)
    assert "realized_return" in str(excinfo.value)
