"""Order-book depth at each price level, and the public-execution rule.

Addendum §9.6 requires the engine to consider **both** AMM pool/tick depth and order-book depth at
each price level. §9.4 says which of them may be used: the *best deterministic public* source, no
private RFQ, no market-maker inventory, and at least 90% order fill.

That last pair of rules is one defence, not two. Aggregator quotes overstate executable capacity
because part of the route fills against inventory a latency-sensitive follower cannot rely on —
measured at PEPE 1% size of $471 single-pool against $114,000 routed, a 240x spread. Excluding the
private legs removes the inflation; requiring 90% fill removes what is left of it, because a quote
that can only be partly filled is not a fill.

The book is walked level by level and **never extrapolated past the last level**. Whatever the book
cannot supply is recorded as liquidity limitation, which is a measured shortfall, not a price.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Optional, Tuple

from contracts import CALCULATION_CONTEXT, ContractError, calc, divide, require_finite
from phase0.parameters import PARAMETERS

from .amm import (
    MEASURED_PEPE_1PCT_ROUTED_USD,
    MEASURED_PEPE_1PCT_SINGLE_POOL_USD,
    ONE,
    ZERO,
    _positive_usd,
)

#: §9.4. Below this, the order was not filled — it was partly filled, which is a different fact.
#: Read from the ticket-11 frozen set.
MIN_FILL_RATIO = PARAMETERS.value("execution.minimum_fill_ratio")


class PrivateLiquidityExcluded(ContractError):
    """Every candidate execution source was private RFQ or market-maker inventory.

    A modelling refusal, not a measurement: the honest answer is "this trade has no deterministic
    public execution I am willing to underwrite", and reporting a capacity number derived from
    private inventory would be the single easiest way to publish a 240x overstatement.
    """


@dataclass(frozen=True)
class OrderBookLevel:
    """One price level: a price in USD per whole unit, and the raw quantity resting there."""

    price_usd: Decimal
    quantity_raw: int

    def __post_init__(self):
        object.__setattr__(self, "price_usd", require_finite(calc(self.price_usd), "price_usd"))
        if self.price_usd <= 0:
            raise ValueError("a book level must carry a positive price")
        if not isinstance(self.quantity_raw, int) or isinstance(self.quantity_raw, bool):
            raise TypeError(
                "quantity_raw is a raw token quantity and must be int, got {}".format(
                    type(self.quantity_raw).__name__
                )
            )
        if self.quantity_raw <= 0:
            raise ValueError("a book level with no quantity is not a level")


@dataclass(frozen=True)
class OrderBook:
    """The ask side, ascending in price. Only what is actually resting — no synthetic depth."""

    asset_decimals: int
    levels: Tuple[OrderBookLevel, ...]

    def __post_init__(self):
        object.__setattr__(self, "levels", tuple(self.levels))
        if not isinstance(self.asset_decimals, int) or isinstance(self.asset_decimals, bool):
            raise TypeError("asset_decimals must be int")
        if not 0 <= self.asset_decimals <= 36:
            raise ValueError("implausible token decimals: {}".format(self.asset_decimals))
        if not self.levels:
            raise ValueError("an empty book is not a source of depth; it is an absent one")
        previous = None
        for level in self.levels:
            if previous is not None and level.price_usd <= previous:
                raise ValueError(
                    "ask levels must ascend strictly in price; {} follows {}. An unsorted book "
                    "would be walked cheapest-last and would understate the cost of every "
                    "order".format(level.price_usd, previous)
                )
            previous = level.price_usd

    @property
    def best_price_usd(self):
        return self.levels[0].price_usd

    def capacity_usd(self):
        """Total USD the resting book can absorb. The ceiling on any fill from this source."""
        with localcontext(CALCULATION_CONTEXT):
            total = ZERO
            for level in self.levels:
                total += divide(level.quantity_raw, 10 ** self.asset_decimals) * level.price_usd
            return +total


@dataclass(frozen=True)
class OrderBookFill:
    """What walking the book actually produced.

    ``vwap_usd`` is ``None`` when nothing filled — an explicit absence rather than a zero price,
    which would read as free execution downstream.
    """

    requested_usd: Decimal
    filled_usd: Decimal
    acquired_raw: int
    best_price_usd: Decimal
    vwap_usd: Optional[Decimal]
    slippage_pct: Optional[Decimal]
    levels_consumed: int

    def __post_init__(self):
        if self.filled_usd > self.requested_usd:
            raise ValueError("a fill cannot exceed the order it fills")
        if (self.vwap_usd is None) != (self.acquired_raw == 0):
            raise ValueError("vwap is None exactly when nothing was acquired")

    @property
    def fill_ratio(self):
        if self.requested_usd == 0:
            return ZERO
        return divide(self.filled_usd, self.requested_usd)

    @property
    def unfilled_share(self):
        """The liquidity-limitation component: a *quantity* shortfall, never a price."""
        with localcontext(CALCULATION_CONTEXT):
            return +(ONE - self.fill_ratio)

    @property
    def fills(self):
        """§9.4's 90% rule. A partial fill below this is unexecutable, not a smaller trade."""
        return self.fill_ratio >= MIN_FILL_RATIO


def walk_order_book(book, size_usd):
    """Consume ascending levels until the order is filled or the book runs out.

    Raw units acquired are floored at each level, and the amount spent is recomputed from the
    floored quantity, so the fill reports what was actually paid for what was actually received.

    Note the direction, because flooring is easy to justify as conservative when it is not: the
    floored leg is the *more expensive* one, so the average tips very slightly toward the cheap
    level and the VWAP comes out marginally lower, not higher. The effect is ~1e-21 relative.

    The book is not extended past its last level under any circumstance: the shortfall is the
    answer.
    """
    if not isinstance(book, OrderBook):
        raise TypeError("walk_order_book needs an OrderBook, got {}".format(type(book).__name__))
    requested = _positive_usd(size_usd, "size_usd")

    scale = 10 ** book.asset_decimals
    with localcontext(CALCULATION_CONTEXT):
        remaining = requested
        spent = ZERO
        acquired_raw = 0
        consumed = 0

        for level in book.levels:
            if remaining <= 0:
                break
            level_capacity = +(divide(level.quantity_raw, scale) * level.price_usd)
            if level_capacity <= remaining:
                spent += level_capacity
                acquired_raw += level.quantity_raw
                remaining -= level_capacity
                consumed += 1
            else:
                units = divide(remaining, level.price_usd)
                # int() truncates toward zero: floor, for a positive quantity. Spent is
                # recomputed from the floored quantity, so the pair stays consistent — the
                # fill reports what was actually paid for what was actually received.
                taken_raw = int(units * scale)
                if taken_raw > 0:
                    acquired_raw += taken_raw
                    spent += +(divide(taken_raw, scale) * level.price_usd)
                    consumed += 1
                remaining = ZERO

        if acquired_raw == 0:
            return OrderBookFill(
                requested_usd=requested,
                filled_usd=ZERO,
                acquired_raw=0,
                best_price_usd=book.best_price_usd,
                vwap_usd=None,
                slippage_pct=None,
                levels_consumed=0,
            )

        filled = +spent
        vwap = divide(filled, divide(acquired_raw, scale))
        slippage = +(divide(vwap, book.best_price_usd) - ONE)
        return OrderBookFill(
            requested_usd=requested,
            filled_usd=filled,
            acquired_raw=acquired_raw,
            best_price_usd=book.best_price_usd,
            vwap_usd=vwap,
            slippage_pct=slippage,
            levels_consumed=consumed,
        )


# -- choosing a source ----------------------------------------------------------


@dataclass(frozen=True)
class ExecutionSource:
    """One candidate route, costed. ``is_private`` marks RFQ / market-maker inventory."""

    name: str
    total_cost_pct: Decimal
    fill_ratio: Decimal
    is_private: bool = False

    def __post_init__(self):
        object.__setattr__(
            self, "total_cost_pct", require_finite(calc(self.total_cost_pct), "total_cost_pct")
        )
        object.__setattr__(
            self, "fill_ratio", require_finite(calc(self.fill_ratio), "fill_ratio")
        )
        if not self.name:
            raise ValueError("an execution source must be named; an anonymous route is unauditable")
        if not ZERO <= self.fill_ratio <= ONE:
            raise ValueError("fill_ratio must be in [0, 1], got {}".format(self.fill_ratio))

    @property
    def fills(self):
        return self.fill_ratio >= MIN_FILL_RATIO


def public_sources(sources):
    """Drop every private leg (§9.4). Raises when nothing public is left."""
    candidates = tuple(sources)
    if not candidates:
        raise ValueError("no execution sources were supplied")
    public = tuple(s for s in candidates if not s.is_private)
    if not public:
        raise PrivateLiquidityExcluded(
            "all {} candidate source(s) are private RFQ or market-maker inventory; §9.4 permits "
            "only the best deterministic public source. Underwriting capacity on private "
            "inventory is what produced the measured ${} single-pool versus ${} routed spread for "
            "PEPE.".format(
                len(candidates),
                _fmt_usd(MEASURED_PEPE_1PCT_SINGLE_POOL_USD),
                _fmt_usd(MEASURED_PEPE_1PCT_ROUTED_USD),
            )
        )
    return public


def best_public_execution(sources):
    """The cheapest public source that actually fills, or ``None`` if none does.

    The asymmetry is deliberate. "Every route was private" is a modelling refusal and raises;
    "public routes exist but none fills 90% of the order" is a measured outcome and returns
    ``None`` for the caller to record as ``copyable=False``.
    """
    fillable = [s for s in public_sources(sources) if s.fills]
    if not fillable:
        return None
    # Ties broken by name so the choice is deterministic across runs and machines.
    return min(fillable, key=lambda s: (s.total_cost_pct, s.name))


def _fmt_usd(value):
    return format(calc(value), "f")
