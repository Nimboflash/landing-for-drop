"""Invariants FIFO must hold for every input, not only for the worked examples.

The one that matters most is quantity conservation. Lot assignment is a deterministic field with
no tolerance (§9.2), and a matcher that loses or invents a single raw unit produces a position
history that reconciles against nothing — while still looking perfectly healthy in aggregate.
"""

from decimal import Context, Decimal, localcontext

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from contracts import (
    CALCULATION_CONTEXT,
    COMPARISON_TOLERANCE,
    ROUNDING,
    USDC,
    ClassificationStatus,
    NetTradeResult,
    QuarantineRequired,
    canonical_hash,
    to_canonical_json,
)
from fifo import match_fifo

WALLET = "0x" + "11" * 20
TOKEN = "0x" + "aa" * 20

SETTINGS = settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


def _trade(status, block, qty_raw, cents):
    usd = Decimal(cents).scaleb(-2)
    is_buy = status is ClassificationStatus.VALID_BUY
    quote_raw = max(1, int(usd * 1000000))
    return NetTradeResult(
        tx_hash="0x{:064x}".format(block),
        portfolio_owner=WALLET,
        status=status,
        sold_asset=USDC if is_buy else TOKEN,
        bought_asset=TOKEN if is_buy else USDC,
        sold_raw_amount=quote_raw if is_buy else qty_raw,
        bought_raw_amount=qty_raw if is_buy else quote_raw,
        quote_asset=USDC,
        quote_usd=usd,
        block_number=block,
        timestamp=1_600_000_000 + block * 12,
    )


#: (is_buy, quantity, price in cents). Quantities span 1 unit to a whole 18-decimal token, so the
#: pro-rata split is exercised where it divides evenly and where it does not.
STEP = st.tuples(
    st.booleans(),
    st.integers(min_value=1, max_value=10 ** 18),
    st.integers(min_value=1, max_value=10 ** 9),
)

SCHEDULE = st.lists(STEP, min_size=1, max_size=14)

#: The same, at the scale the chain actually permits. A raw quantity is a uint256, and the
#: high-supply long-tail tokens this study is about routinely carry 33 or more digits — a range the
#: schedule above cannot reach and where the closing-slice dust rule behaves differently, because
#: the residue stops being representable alongside the whole at 38 significant digits.
WIDE_STEP = st.tuples(
    st.booleans(),
    st.integers(min_value=1, max_value=2 ** 256 - 1),
    st.integers(min_value=1, max_value=10 ** 9),
)

WIDE_SCHEDULE = st.lists(WIDE_STEP, min_size=1, max_size=8)

#: One unit in the last place of a published return (``contracts.SCALE_RATIO``), which is how far a
#: closing slice may sit from the share the pro-rata rule states. Written out rather than imported
#: from ``fifo`` so that the bound is pinned from outside the code it bounds.
DRIFT_LIMIT = Decimal("1e-8")


def _events(schedule):
    """Turn a schedule into a chronologically ordered, always-satisfiable event stream.

    A sell is capped at the quantity actually open, so over-selling is exercised deliberately in
    its own test rather than arriving by accident in every other one.
    """
    events = []
    block = 10
    open_qty = 0
    for is_buy, qty, cents in schedule:
        if is_buy:
            events.append(_trade(ClassificationStatus.VALID_BUY, block, qty, cents))
            open_qty += qty
        else:
            if open_qty == 0:
                continue
            qty = min(qty, open_qty)
            events.append(_trade(ClassificationStatus.VALID_SELL, block, qty, cents))
            open_qty -= qty
        block += 10
    return events


def _split(events):
    buys = [e for e in events if e.status is ClassificationStatus.VALID_BUY]
    sells = [e for e in events if e.status is ClassificationStatus.VALID_SELL]
    return buys, sells


def _total(values):
    with localcontext(CALCULATION_CONTEXT):
        out = Decimal(0)
        for value in values:
            out += value
        return out


def _close(actual, expected):
    """Equal at the frozen internal precision.

    Not a percentage tolerance: this is 1e-18 *relative*, eighteen orders tighter than the 0.5% the
    golden set allows for USD, and it exists only because a 38-digit context cannot represent every
    intermediate subtraction exactly.

    It was written as ``COMPARISON_TOLERANCE * max(abs(expected), Decimal(1))``, and the ``max``
    made it an absolute floor of 1e-18 for every expectation below a dollar — so on a closing slice
    worth 1e-11 it permitted a relative error of 1e-7, and the tightest-looking check in the suite
    was in fact its loosest. Values below a dollar are exactly where FIFO's dust arithmetic lives.
    """
    with localcontext(CALCULATION_CONTEXT):
        if expected == 0:
            return actual == 0
        return abs(actual - expected) <= COMPARISON_TOLERANCE * abs(expected)


def _drift(actual, expected):
    """Relative distance between a slice and the share the pro-rata rule states for it."""
    with localcontext(CALCULATION_CONTEXT):
        if expected == 0:
            return Decimal(0) if actual == 0 else Decimal(1)
        return abs(actual - expected) / abs(expected)


#: Used only to derive reference values, never by anything under test. 300 digits is not a taste:
#: a raw quantity is a uint256, so a share is a rational whose denominator carries at most 78
#: digits, and such a value is either exactly on a 38-digit rounding midpoint or at least ~1e-120
#: away from one. 300 digits of intermediate precision therefore cannot round across a midpoint,
#: which makes the two-step reduction below equal to a single correct rounding of the exact value.
REFERENCE_CONTEXT = Context(prec=300, rounding=ROUNDING)


def _share(total_usd, taken_raw, whole_raw):
    """``total_usd * taken_raw / whole_raw`` — §4.4's rule, correctly rounded once, derived here.

    Deliberately not a call into ``fifo``, and deliberately not the same arithmetic either. The
    obvious spelling — multiply and divide at the frozen 38 digits — rounds twice, and its answer
    differs from the exact share by one unit in the last place whenever the product overflows 38
    digits, which a $2.29 basis against a 77-digit lot does. A reference value computed that way
    would have agreed with a module doing the same thing and pinned nothing.
    """
    with localcontext(REFERENCE_CONTEXT):
        wide = +(Decimal(total_usd) * Decimal(taken_raw) / Decimal(whole_raw))
    with localcontext(CALCULATION_CONTEXT):
        return +wide


def _annotate(result):
    """Tag each consumption with whether it closes its lot and whether it closes its sell.

    Those two are the slices the dust rule treats specially, and they are recoverable from the
    result alone: a slice closes a lot when the running total consumed from that buy reaches the
    quantity the buy opened.
    """
    consumed = {}
    for c in result.consumptions:
        consumed[c.buy.tx_hash] = consumed.get(c.buy.tx_hash, 0) + c.consumed_raw
    running = {}
    last_of_sell = {}
    for index, c in enumerate(result.consumptions):
        last_of_sell[c.sell.tx_hash] = index

    out = []
    for index, c in enumerate(result.consumptions):
        running[c.buy.tx_hash] = running.get(c.buy.tx_hash, 0) + c.consumed_raw
        closes_lot = running[c.buy.tx_hash] == c.buy.bought_raw_amount
        out.append((c, closes_lot, last_of_sell[c.sell.tx_hash] == index))
    return out


# -- the stated invariant --------------------------------------------------------


@SETTINGS
@given(SCHEDULE)
def test_assigned_quantity_equals_sold_quantity(schedule):
    buys, sells = _split(_events(schedule))
    result = match_fifo(buys, sells)

    assert sum(c.consumed_raw for c in result.consumptions) == sum(
        s.sold_raw_amount for s in sells
    )


@SETTINGS
@given(SCHEDULE)
def test_opened_minus_consumed_equals_remaining_exactly(schedule):
    buys, sells = _split(_events(schedule))
    result = match_fifo(buys, sells)

    opened = sum(b.bought_raw_amount for b in buys)
    consumed = sum(c.consumed_raw for c in result.consumptions)
    remaining = sum(lot.remaining_raw for lot in result.open_lots)

    assert opened - consumed == remaining
    assert all(isinstance(x, int) for x in (opened, consumed, remaining))


@SETTINGS
@given(SCHEDULE)
def test_no_buy_is_over_consumed_and_none_disappears(schedule):
    buys, sells = _split(_events(schedule))
    result = match_fifo(buys, sells)

    consumed_per_buy = {}
    for c in result.consumptions:
        consumed_per_buy[c.buy.tx_hash] = consumed_per_buy.get(c.buy.tx_hash, 0) + c.consumed_raw
    remaining_per_buy = {lot.buy.tx_hash: lot.remaining_raw for lot in result.open_lots}

    for b in buys:
        consumed = consumed_per_buy.get(b.tx_hash, 0)
        remaining = remaining_per_buy.get(b.tx_hash, 0)
        assert 0 <= consumed <= b.bought_raw_amount
        assert consumed + remaining == b.bought_raw_amount
        # Every buy is accounted for by one side or the other; nothing is silently dropped.
        assert b.tx_hash in consumed_per_buy or b.tx_hash in remaining_per_buy


# -- first in, first out ---------------------------------------------------------


@SETTINGS
@given(SCHEDULE)
def test_lots_are_consumed_in_the_order_they_were_opened(schedule):
    buys, sells = _split(_events(schedule))
    result = match_fifo(buys, sells)

    buy_blocks = [c.buy.block_number for c in result.consumptions]
    assert buy_blocks == sorted(buy_blocks)

    sell_blocks = [c.sell.block_number for c in result.consumptions]
    assert sell_blocks == sorted(sell_blocks)


@SETTINGS
@given(SCHEDULE)
def test_a_later_lot_is_never_touched_while_an_earlier_one_is_open(schedule):
    buys, sells = _split(_events(schedule))
    result = match_fifo(buys, sells)

    still_open = {lot.buy.block_number for lot in result.open_lots}
    for c in result.consumptions:
        earlier_open = [b for b in still_open if b < c.buy.block_number]
        assert not earlier_open, (
            "lot from block {} was consumed while lot(s) {} remained open".format(
                c.buy.block_number, sorted(earlier_open)
            )
        )


@SETTINGS
@given(st.data(), SCHEDULE)
def test_matching_a_prefix_gives_a_prefix_of_the_matching(data, schedule):
    """No look-ahead: a later event cannot change an earlier lot assignment.

    If it could, every historical number in the study would depend on where the window happened to
    end — the class of bug §9 calls out as leaving the code perfectly pleased with itself.
    """
    events = _events(schedule)
    assume(events)
    cut = data.draw(st.integers(min_value=0, max_value=len(events)))

    whole = match_fifo(*_split(events))
    prefix = match_fifo(*_split(events[:cut]))

    assert whole.consumptions[: len(prefix.consumptions)] == prefix.consumptions


# -- money ------------------------------------------------------------------------


@SETTINGS
@given(SCHEDULE)
def test_each_sell_hands_out_exactly_its_proceeds(schedule):
    buys, sells = _split(_events(schedule))
    result = match_fifo(buys, sells)

    for s in sells:
        allocated = _total(c.proceeds_usd for c in result.consumptions if c.sell is s)
        assert _close(allocated, s.quote_usd)


@SETTINGS
@given(SCHEDULE)
def test_a_fully_consumed_lot_hands_out_exactly_its_cost(schedule):
    buys, sells = _split(_events(schedule))
    result = match_fifo(buys, sells)

    open_quantity = {lot.buy.tx_hash: lot.remaining_raw for lot in result.open_lots}
    for b in buys:
        allocated = _total(c.allocated_cost_usd for c in result.consumptions if c.buy is b)
        if b.tx_hash not in open_quantity:
            assert _close(allocated, b.quote_usd)
        else:
            # A partly consumed lot keeps the rest of its basis for the day-30 mark (§4.4 case 2).
            assert allocated <= b.quote_usd


@SETTINGS
@given(SCHEDULE)
def test_allocations_are_proportional_to_the_raw_quantity_taken(schedule):
    """Two rules, not one, and the difference is the whole of the dust question.

    A slice that does not close its lot is *exactly* the pro-rata share — no tolerance, because
    there is nothing for a tolerance to absorb. The slice that closes it takes what is left
    instead, so that the basis closes to zero, and what is left may differ from the share by the
    accumulated rounding. That difference is bounded, and the bound is what makes the closing slice
    a number rather than an artefact.
    """
    buys, sells = _split(_events(schedule))
    result = match_fifo(buys, sells)

    for c, closes_lot, closes_sell in _annotate(result):
        cost_share = _share(c.buy.quote_usd, c.consumed_raw, c.buy.bought_raw_amount)
        if closes_lot:
            assert _drift(c.allocated_cost_usd, cost_share) <= DRIFT_LIMIT
        else:
            assert c.allocated_cost_usd == cost_share

        proceeds_share = _share(c.sell.quote_usd, c.consumed_raw, c.sell.sold_raw_amount)
        if closes_sell:
            assert _drift(c.proceeds_usd, proceeds_share) <= DRIFT_LIMIT
        else:
            assert c.proceeds_usd == proceeds_share

        assert c.allocated_cost_usd > 0
        assert c.proceeds_usd >= 0
        # A share of a whole is never more than the whole. It reads as a tautology and is not one:
        # rounding the pro-rata product before dividing puts it one unit in the last place above.
        assert c.allocated_cost_usd <= c.buy.quote_usd
        assert c.proceeds_usd <= c.sell.quote_usd


@SETTINGS
@given(SCHEDULE)
def test_no_value_is_quantized_away(schedule):
    """FIFO is not an output boundary, so nothing here may be rounded to a reporting scale."""
    buys, sells = _split(_events(schedule))
    result = match_fifo(buys, sells)

    for c in result.consumptions:
        assert isinstance(c.allocated_cost_usd, Decimal)
        assert isinstance(c.proceeds_usd, Decimal)
        assert c.allocated_cost_usd.is_finite()
        assert c.proceeds_usd.is_finite()


# -- the same, at the scale a uint256 actually reaches ----------------------------


@SETTINGS
@given(WIDE_SCHEDULE)
def test_at_chain_scale_every_slice_is_either_the_share_or_a_typed_refusal(schedule):
    """The invariant the narrow generator could not reach.

    Above ~10**30 raw units the residue left for a closing slice stops being representable
    alongside the whole at 38 significant digits, and the value the subtraction leaves is made of
    rounding. There are exactly two acceptable outcomes: a slice within the published-precision
    bound of its share, or a typed quarantine. What must never happen is the third one that shipped
    — a positive, plausible number that no independent re-derivation reproduces.
    """
    buys, sells = _split(_events(schedule))
    try:
        result = match_fifo(buys, sells)
    except QuarantineRequired as refusal:
        # The generator caps every sell at the quantity open, uses one owner, one asset and a
        # distinct block per event, so the precision refusal is the only one reachable from here.
        assert "pro-rata rule" in str(refusal)
        return

    for c, closes_lot, closes_sell in _annotate(result):
        cost_share = _share(c.buy.quote_usd, c.consumed_raw, c.buy.bought_raw_amount)
        if closes_lot:
            assert _drift(c.allocated_cost_usd, cost_share) <= DRIFT_LIMIT
        else:
            assert c.allocated_cost_usd == cost_share

        proceeds_share = _share(c.sell.quote_usd, c.consumed_raw, c.sell.sold_raw_amount)
        if closes_sell:
            assert _drift(c.proceeds_usd, proceeds_share) <= DRIFT_LIMIT
        else:
            assert c.proceeds_usd == proceeds_share

        # A share of a whole is never more than the whole. It reads as a tautology and is not one:
        # rounding the pro-rata product before dividing puts it one unit in the last place above,
        # and this generator is where that first showed up.
        assert c.allocated_cost_usd <= c.buy.quote_usd
        assert c.proceeds_usd <= c.sell.quote_usd


@SETTINGS
@given(WIDE_SCHEDULE)
def test_at_chain_scale_quantity_and_money_still_conserve(schedule):
    """A refusal may not be bought at the price of the conservation the module exists for."""
    buys, sells = _split(_events(schedule))
    try:
        result = match_fifo(buys, sells)
    except QuarantineRequired:
        return

    opened = sum(b.bought_raw_amount for b in buys)
    consumed = sum(c.consumed_raw for c in result.consumptions)
    assert opened - consumed == sum(lot.remaining_raw for lot in result.open_lots)
    assert consumed == sum(s.sold_raw_amount for s in sells)

    for s in sells:
        assert _close(_total(c.proceeds_usd for c in result.consumptions if c.sell is s),
                      s.quote_usd)

    still_open = {lot.buy.tx_hash for lot in result.open_lots}
    for b in buys:
        allocated = _total(c.allocated_cost_usd for c in result.consumptions if c.buy is b)
        if b.tx_hash not in still_open:
            assert _close(allocated, b.quote_usd)
        else:
            assert allocated <= b.quote_usd


def test_the_wide_generator_reaches_both_outcomes():
    """A property that only ever saw refusals would assert nothing, so pin both branches here.

    Neither case is drawn: both are written out, because "the generator happened to cover it" is
    not evidence and the point of the two tests above is that the range is reachable at all.
    """
    ok = _split([
        _trade(ClassificationStatus.VALID_BUY, 10, 3 * 10 ** 20, 100000),
        _trade(ClassificationStatus.VALID_SELL, 20, 3 * 10 ** 20 - 1, 90000),
        _trade(ClassificationStatus.VALID_SELL, 30, 1, 100),
    ])
    assert len(match_fifo(*ok).consumptions) == 2

    refused = _split([
        _trade(ClassificationStatus.VALID_BUY, 10, 3 * 10 ** 33, 100000),
        _trade(ClassificationStatus.VALID_SELL, 20, 3 * 10 ** 33 - 1, 90000),
        _trade(ClassificationStatus.VALID_SELL, 30, 1, 100),
    ])
    with pytest.raises(QuarantineRequired):
        match_fifo(*refused)


# -- determinism and the seam ----------------------------------------------------


@SETTINGS
@given(SCHEDULE)
def test_the_same_input_always_produces_the_same_bytes(schedule):
    buys, sells = _split(_events(schedule))
    first = match_fifo(buys, sells)
    second = match_fifo(list(reversed(buys)), list(reversed(sells)))

    assert canonical_hash(first) == canonical_hash(second)


@SETTINGS
@given(SCHEDULE)
def test_every_result_survives_canonical_json(schedule):
    buys, sells = _split(_events(schedule))
    payload = to_canonical_json(match_fifo(buys, sells))

    assert payload.startswith("{")
    assert "e+" not in payload and "E+" not in payload


# -- refusals hold for every input -----------------------------------------------


@SETTINGS
@given(SCHEDULE, st.integers(min_value=1, max_value=10 ** 9))
def test_selling_more_than_is_open_always_quarantines(schedule, excess):
    events = _events(schedule)
    buys, sells = _split(events)
    assume(buys)

    open_raw = sum(b.bought_raw_amount for b in buys) - sum(s.sold_raw_amount for s in sells)
    greedy = _trade(
        ClassificationStatus.VALID_SELL,
        (events[-1].block_number + 10),
        open_raw + excess,
        1000,
    )

    with pytest.raises(QuarantineRequired):
        match_fifo(buys, sells + [greedy])


@SETTINGS
@given(SCHEDULE)
def test_two_events_sharing_a_block_always_quarantine(schedule):
    events = _events(schedule)
    assume(len(events) >= 2)

    collided = list(events)
    collided[1] = _trade(
        collided[1].status,
        collided[0].block_number,
        collided[1].asset_raw_amount,
        1000,
    )
    # Distinct transactions, same block: the seam carries nothing that could order them.
    object.__setattr__(collided[1], "tx_hash", "0x" + "ff" * 32)

    with pytest.raises(QuarantineRequired):
        match_fifo(*_split(collided))
