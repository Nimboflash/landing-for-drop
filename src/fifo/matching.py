"""FIFO lot assignment — pre-registration §4.4, ticket 22.

First in, first out. §4.4 picked it for being reproducible and pre-registrable rather than for
being optimal, and the property that earns its place is that **it cannot be changed mid-analysis to
improve a chart**. So there is no mode, no flag, no configuration lookup and no parameter that
selects another matching rule: :func:`match_fifo` takes exactly the two arguments it needs, and a
future reader can confirm from the signature alone that nothing else was available.

What this module guarantees:

    Quantities   ``int`` end to end. ``sum(consumed) == sum(sold)`` and
                 ``sum(opened) - sum(consumed) == sum(remaining)``, exactly, with no tolerance —
                 §9.2 lists FIFO lot assignment among the deterministic fields that must match the
                 golden set at raw-unit level.
    Cost         allocated pro rata within a lot by raw quantity, at the frozen 38-digit
                 precision, never quantized. FIFO is not an output boundary; a value already
                 rounded to cents has lost the quantity the §8 netting tolerance compares.
    Dust         the slice that closes a lot takes the lot's exact remaining basis, and the slice
                 that closes a sell takes its exact remaining proceeds. Recomputing a share for
                 the final slice instead would leave a residue that is either lost or invented,
                 and a cost basis that does not close to zero moves value between wallets in the
                 aggregate while every individual row looks reasonable. That rule holds only while
                 the residue is still dust; see :data:`MAX_CLOSING_DRIFT` for where it stops and
                 why the answer there is a refusal rather than a number.
    Context      no output, and no refusal message, depends on the caller's ambient decimal
                 context. Every operation here runs at the frozen 38 digits — including the two
                 that have no primitive standing in front of them, magnitude and negation, which
                 round to the ambient context when written bare. See :func:`_magnitude`.
    Refusals     typed. A sell we cannot back with a buy is *quarantined*, never clamped: clamping
                 converts a gap in our record of the chain into a measured position, and §11
                 forbids an unexplained event either way. The same applies to a lot this module
                 cannot divide at the frozen precision: the events are real, the basis is not
                 recoverable, so the book goes to the reconciliation queue whole.

Ordering deserves a note. The seam hands over :class:`~contracts.trades.NetTradeResult`, one per
transaction, carrying a block number but no transaction index and no log index. Two events in the
same block therefore cannot be ordered from anything this module can see, and their order changes
the assignment — so the module refuses instead of picking one. Sorting by transaction hash would
have produced a deterministic answer that is deterministically wrong.
"""

from decimal import Decimal, localcontext
from typing import Dict, List, Sequence, Tuple  # noqa: F401  (3.9-compatible annotations)

from contracts import (
    CALCULATION_CONTEXT,
    SCALE_RATIO,
    AttributionUnresolvedError,
    ClassificationStatus,
    FifoResult,
    Lot,
    LotConsumption,
    NetTradeResult,
    QuarantineRequired,
    calc,
    divide,
    normalise_asset,
    require_finite,
    sub,
)

__all__ = ["match_fifo"]

#: How far a closing slice's accumulated remainder may sit from the share the pro-rata rule states
#: directly, as a fraction of that share, before the slice is refused instead of emitted.
#:
#: The dust rule hands the closing slice whatever is *left* — and what is left is arrived at by
#: subtracting slices that were each rounded to 38 significant digits. Once a lot's raw quantity is
#: enough orders of magnitude above its closing residual, that residual is made entirely of the
#: rounding: at 10^33 raw units (one quadrillion tokens at 18dp, ordinary for a high-supply
#: long-tail asset) the closing basis departs from its true share by ~1e-5 relative, at 10^36 by
#: ~3e-2, and by 10^39 it reaches zero and the seam refuses to construct the consumption at all.
#: None of that looks wrong on inspection — the number is positive, small, and plausible.
#:
#: Such a value is not a measurement, it is an artefact of the order this module happened to
#: subtract in: an Independent Validator applying the same pro-rata rule directly gets a different
#: number, and §9 requires the FIFO fields to re-derive byte-identically. So the lot book is
#: quarantined rather than reported.
#:
#: The bound is SCALE_RATIO, the scale a return is published at. Below it the drift provably cannot
#: move a reported figure; above it the residue has stopped being rounding and become a number.
MAX_CLOSING_DRIFT = SCALE_RATIO


def match_fifo(buys, sells):
    """Assign each sell to the buy lots it consumes, oldest lot first.

    :param buys: ``VALID_BUY`` results for one wallet and one asset, in any order.
    :param sells: ``VALID_SELL`` results for the same wallet and asset, in any order.
    :returns: a :class:`~contracts.trades.FifoResult` whose consumptions are ordered by sell and,
        within a sell, by the age of the lot consumed.

    Refuses, by design:

    * a sell arriving before any buy, or exceeding the open quantity — both mean a buy is missing
      from our record, so they are :class:`~contracts.core.QuarantineRequired` rather than a
      clamped quantity;
    * more than one asset or more than one owner in the same call — a lot book belongs to exactly
      one wallet's holding of exactly one asset;
    * an unresolved owner (§8 excludes uncertain attribution rather than pooling it);
    * two events that cannot be ordered, because the seam carries nothing finer than a block;
    * a lot whose raw quantity runs so far above its closing residual that the residue left for
      the closing slice is accumulated rounding rather than a share (:data:`MAX_CLOSING_DRIFT`).
    """
    buys = tuple(buys)
    sells = tuple(sells)
    _require_only(buys, ClassificationStatus.VALID_BUY, "buys")
    _require_only(sells, ClassificationStatus.VALID_SELL, "sells")

    events = buys + sells
    if not events:
        return FifoResult(consumptions=(), open_lots=())

    _require_one_owner(events)
    asset = _require_one_asset(events)
    _require_a_total_order(events)
    #: Every price is checked before any matching starts, so a refusal never leaves half a book.
    usd = {event.tx_hash: _require_usd(event) for event in events}

    lots = []          # type: List[_OpenLot]
    consumptions = []  # type: List[LotConsumption]
    for event in sorted(events, key=lambda e: e.block_number):
        if event.status is ClassificationStatus.VALID_BUY:
            lots.append(_OpenLot(event, usd[event.tx_hash]))
        else:
            consumptions.extend(_consume(lots, event, usd[event.tx_hash], asset))

    return FifoResult(
        consumptions=tuple(consumptions),
        # A lot consumed down to nothing is fully described by its consumptions; carrying a
        # zero-quantity lot alongside them would invite it to be marked at day 30 as a position.
        open_lots=tuple(
            Lot(buy=lot.buy, remaining_raw=lot.remaining_raw)
            for lot in lots
            if lot.remaining_raw > 0
        ),
    )


# -- the book -------------------------------------------------------------------


class _OpenLot(object):
    """A lot while it is being matched. Mutable here; only frozen contract types escape."""

    __slots__ = ("buy", "quantity_raw", "remaining_raw", "cost_usd", "cost_remaining_usd")

    def __init__(self, buy, cost_usd):
        self.buy = buy
        self.quantity_raw = buy.asset_raw_amount
        self.remaining_raw = self.quantity_raw
        self.cost_usd = cost_usd
        self.cost_remaining_usd = cost_usd


def _consume(lots, sell, proceeds_usd, asset):
    """Match one sell against the open lots, oldest first."""
    wanted = sell.asset_raw_amount
    available = sum(lot.remaining_raw for lot in lots)
    if available < wanted:
        raise _cannot_cover(sell, wanted, available, asset, any_lots=bool(lots))

    # Plan the whole sell before mutating anything, so a refusal cannot leave a partly consumed
    # book behind.
    plan = []
    outstanding = wanted
    for lot in lots:
        if outstanding == 0:
            break
        if lot.remaining_raw == 0:
            continue
        take = lot.remaining_raw if lot.remaining_raw <= outstanding else outstanding
        plan.append((lot, take))
        outstanding -= take

    produced = []
    # Nothing is written back to the book until every slice of this sell has been accepted, so a
    # refusal raised part-way through cannot leave a partly consumed lot behind. A lot appears at
    # most once in a plan, so deferring the write changes no value that the loop reads.
    applied = []
    proceeds_left = proceeds_usd
    last = len(plan) - 1
    for index, (lot, take) in enumerate(plan):
        # The closing slice of a lot takes what is left of that lot's basis, and the closing slice
        # of a sell takes what is left of its proceeds. Recomputing a pro-rata share for either
        # would leave a residue behind — dust that is silently lost or silently invented. What is
        # left is only meaningful while it is still dust, which is what the guard establishes.
        if take == lot.remaining_raw:
            cost = lot.cost_remaining_usd
            _require_the_remainder_is_still_dust(
                cost, lot.cost_usd, take, lot.quantity_raw, "cost basis", lot.buy, sell
            )
        else:
            cost = _pro_rata(lot.cost_usd, take, lot.quantity_raw)
        if index == last:
            proceeds = proceeds_left
            _require_the_remainder_is_still_dust(
                proceeds, proceeds_usd, take, wanted, "proceeds", sell, sell
            )
        else:
            proceeds = _pro_rata(proceeds_usd, take, wanted)

        proceeds_left = sub(proceeds_left, proceeds)
        applied.append((lot, take, cost))

        produced.append(
            LotConsumption(
                buy=lot.buy,
                sell=sell,
                consumed_raw=take,
                allocated_cost_usd=cost,
                proceeds_usd=proceeds,
            )
        )

    for lot, take, cost in applied:
        lot.cost_remaining_usd = sub(lot.cost_remaining_usd, cost)
        lot.remaining_raw -= take
    return produced


def _pro_rata(total_usd, taken_raw, whole_raw):
    """``total_usd * taken_raw / whole_raw``, rounded exactly once, unquantized.

    The multiply is done on the USD figure's integer coefficient rather than on the Decimal,
    because ``Decimal.__mul__`` rounds and a USD amount times a uint256 quantity needs far more
    than 38 digits — a $2.29 basis against a 77-digit lot produces a 78-digit product. Rounding
    there and again in the divide can land a slice one unit in the last place *above* the whole it
    is a share of, even though ``taken_raw < whole_raw`` makes that mathematically impossible: the
    lot then hands out more basis than it holds and its remaining basis goes negative. Multiplying
    two ints is exact, so ``divide`` performs the single rounding step and the share can never
    exceed the total.

    ``whole_raw`` is a trade leg, which the seam guarantees is non-zero, so ``divide`` refusing a
    zero denominator here would indicate a corrupted contract type rather than a data condition.
    """
    sign, digits, exponent = calc(total_usd).as_tuple()
    coefficient = int("".join(str(digit) for digit in digits))
    share = divide(Decimal(coefficient * taken_raw), Decimal(whole_raw))
    with localcontext(CALCULATION_CONTEXT):
        # An exponent shift, not an arithmetic step: the coefficient already fits the frozen
        # precision, so nothing is rounded a second time here.
        share = share.scaleb(exponent)
        # The sign goes back on *inside* the block. ``Decimal.__neg__`` is an arithmetic operation
        # like every other one and rounds to the current context, so a bare ``-share`` out here
        # would hand back a 28-digit share on a 38-digit calculation. See :func:`_magnitude`.
        return -share if sign else share


def _magnitude(value):
    """``abs(value)`` at the frozen precision.

    ``contracts.numeric`` exports ``calc``, ``divide``, ``sub``, ``add`` and ``mul``, and stops
    there — so magnitude and negation are the two operations in the numeric path with no primitive
    standing in front of them. They are not exempt from the reason the primitives exist:
    ``Decimal.__abs__`` and ``Decimal.__neg__`` are arithmetic like ``__sub__``, they consult
    whatever context is current, and used bare they round a 38-digit value down to the caller's
    ambient 28 without saying so. That is precisely the defect that shipped in
    ``LotConsumption.realized_return`` and that ``contracts.numeric.sub`` was written to remove,
    spelled with a different operator.

    So every magnitude in this module comes through here, and the one negation stays inside the
    block in :func:`_pro_rata`. The class is held from the outside as well:
    ``tests/hand_computed/test_fifo.py`` replays every refusal this module can raise under ambient
    contexts of varying precision and rounding mode and requires byte-identical messages, so a new
    bare operator anywhere in the module is a failing test rather than the next review finding.
    """
    with localcontext(CALCULATION_CONTEXT):
        return abs(value)


# -- refusals -------------------------------------------------------------------


def _require_the_remainder_is_still_dust(remainder, total_usd, taken_raw, whole_raw, what,
                                         divided, sell):
    """Refuse a closing slice whose value is accumulated rounding rather than money.

    ``remainder`` is what the running subtraction has left; the same share computed directly from
    the raw quantities is what the pro-rata rule actually states. They agree to within a rounding
    step for as long as the residue really is dust. When they do not, the subtractions have
    consumed the basis rather than divided it, and the difference is not small: at 10^36 raw units
    the remainder is tens of percent adrift, and at 10^39 it is zero, at which point
    ``LotConsumption`` raises a bare ``ValueError`` on the way out of :func:`match_fifo` — a
    refusal this module never typed, for a condition it never named.

    Both failures are refused here, and for the same reason: the module cannot divide this lot's
    basis at the frozen precision, so it has no basis to report. §11 forbids dropping the events,
    and clamping them to the nearest plausible number is what produced the silent regime, so the
    book goes to the reconciliation queue whole.
    """
    share = _pro_rata(total_usd, taken_raw, whole_raw)
    if share == 0:
        # Reachable only for a sell that fetched nothing, where every slice is zero and there is no
        # residue to drift. A non-zero remainder against a zero share is residue that was invented,
        # and is refused on the same grounds.
        if remainder == 0:
            return
        drift = None
    else:
        drift = _magnitude(divide(sub(remainder, share), share))
        if drift <= MAX_CLOSING_DRIFT:
            return

    raise QuarantineRequired(
        "{} takes the last {} raw units of the {} of {}, and the {} left for it ({}) is not the "
        "share the pro-rata rule gives ({}): relative drift {}, limit {}. {} raw units do not "
        "divide into a residue of {} at {} significant digits, so what is left is the accumulated "
        "rounding of the earlier slices rather than a measured value, and a validator re-deriving "
        "the share directly would not reproduce it. Quarantined rather than reported — and rather "
        "than clamped to the plausible-looking number the subtraction happens to leave.".format(
            sell.tx_hash,
            taken_raw,
            what,
            divided.tx_hash,
            what,
            remainder,
            share,
            "unbounded" if drift is None else drift,
            MAX_CLOSING_DRIFT,
            whole_raw,
            taken_raw,
            CALCULATION_CONTEXT.prec,
        )
    )


def _require_only(events, expected, argument):
    for event in events:
        if not isinstance(event, NetTradeResult):
            raise TypeError(
                "{} must contain NetTradeResult values; got {}".format(
                    argument, type(event).__name__
                )
            )
        if event.status is not expected:
            raise ValueError(
                "{} must contain only {} results; {} is {}. A non-trade carries no legs, and "
                "a sell counted as a buy would open a lot that never existed.".format(
                    argument, expected.value, event.tx_hash, event.status.value
                )
            )


def _require_one_owner(events):
    owners = set()
    for event in events:
        if event.portfolio_owner is None:
            raise AttributionUnresolvedError(
                "{} has no portfolio_owner, so it cannot join a lot book. §8 excludes uncertain "
                "owner attribution from the primary metric rather than pooling it under a "
                "guess.".format(event.tx_hash)
            )
        owners.add(event.portfolio_owner.lower())
    if len(owners) > 1:
        raise ValueError(
            "a lot book belongs to one owner; got {}. Matching one wallet's sell against another "
            "wallet's buy would invent a position for both.".format(", ".join(sorted(owners)))
        )


def _require_one_asset(events):
    assets = sorted({normalise_asset(event.asset) for event in events})
    if len(assets) > 1:
        raise ValueError(
            "a lot book holds one asset; got {}. Call match_fifo once per (owner, asset).".format(
                ", ".join(assets)
            )
        )
    return assets[0]


def _require_a_total_order(events):
    """Establish that the events can be put in one unambiguous order.

    Lot assignment is a deterministic field with no tolerance, so an order this module had to
    guess at would produce a golden-set mismatch that looks like an arithmetic bug.
    """
    seen = {}
    by_block = {}
    for event in events:
        if event.block_number is None:
            raise QuarantineRequired(
                "{} carries no block number, so it cannot be placed in sequence; the seam pairs "
                "every stamp with a block for exactly this reason".format(event.tx_hash)
            )
        key = (event.tx_hash or "").lower()
        if key in seen:
            raise QuarantineRequired(
                "transaction {} appears twice in the same lot book (blocks {} and {}). A "
                "transaction hash identifies one transaction, so this book was assembled from an "
                "input that carries it twice: either the caller supplied the same transaction "
                "twice, or a netting output was merged wrongly. match_fifo sees only the book and "
                "cannot tell those apart — and must not pick one of the rows to open the lot, "
                "because whichever it dropped, every sell that follows would be assigned against a "
                "basis the other row also claims.".format(
                    event.tx_hash, seen[key].block_number, event.block_number
                )
            )
        seen[key] = event
        by_block.setdefault(event.block_number, []).append(event)

    for block in sorted(by_block):
        group = by_block[block]
        if len(group) > 1:
            raise QuarantineRequired(
                "{} events share block {} ({}) and NetTradeResult carries no transaction index "
                "or log index, so their order cannot be established. FIFO refuses to guess: the "
                "assignment depends on the order, and a guess would be deterministically "
                "wrong rather than visibly missing.".format(
                    len(group), block, ", ".join(e.tx_hash for e in group)
                )
            )


def _require_usd(event):
    """The USD value of the quote leg: a lot's basis, or a sell's proceeds.

    A buy must carry a strictly positive one. ``LotConsumption`` refuses a zero basis at
    construction on the grounds that deciding what a zero-cost buy *means* is a domain judgement,
    and this is the domain: an unpriceable quote leg is a real trade we cannot value, so it goes
    to the reconciliation queue rather than into the metric with an undefined return. A sell may
    legitimately fetch nothing — that is a total loss, and it is measured, not missing.
    """
    if event.quote_usd is None:
        raise QuarantineRequired(
            "{} carries no quote_usd, so it has no cost basis and no proceeds; the trade is real "
            "but unpriceable here and belongs in the reconciliation queue".format(event.tx_hash)
        )
    value = require_finite(event.quote_usd, "quote_usd of {}".format(event.tx_hash))
    if value < 0:
        raise ValueError(
            "{} has a negative quote_usd ({}); a leg's notional is unsigned, direction lives in "
            "the classification".format(event.tx_hash, value)
        )
    if value == 0 and event.status is ClassificationStatus.VALID_BUY:
        raise QuarantineRequired(
            "{} opens a lot with a zero quote_usd cost basis, which leaves every return on that "
            "lot undefined; quarantined rather than counted from a zero denominator".format(
                event.tx_hash
            )
        )
    return value


def _cannot_cover(sell, wanted, available, asset, any_lots):
    """A sell we cannot back with buys. Quarantine, never a clamp (ticket 22)."""
    if not any_lots or available == 0:
        return QuarantineRequired(
            "{} sells {} raw units of {} before any buy is open (available {}). A sell without a "
            "matching buy means a buy is missing from our record, so it goes to the "
            "reconciliation queue rather than being counted from a zero basis.".format(
                sell.tx_hash, wanted, asset, available
            )
        )
    return QuarantineRequired(
        "{} sells {} raw units of {} but only {} are open. Refusing to clamp: a clamped quantity "
        "would turn a missed buy into a measured position, and §11 forbids dropping the event "
        "instead.".format(sell.tx_hash, wanted, asset, available)
    )
