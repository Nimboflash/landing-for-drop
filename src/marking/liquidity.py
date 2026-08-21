"""What a position could actually be sold for, walked along the real pool curve.

The one rule this file exists to enforce: **never spot x quantity**. A constant-product pool
quotes a marginal price at the margin only. Selling a quantity comparable to the reserve moves
the price the whole way down, and the difference is not a rounding detail — with 88% of new
Uniswap V2 tokens reported as honeypots, a thin-but-live pool marked at spot is fiction rather
than an approximation.

Everything here is exact rational arithmetic over ints, rendered into Decimal exactly once per
quantity by :func:`contracts.divide`. That matters for more than tidiness. Rounding to nearest is
a monotone map, so a single rounding of a monotone-decreasing exact quantity is still monotone —
which is what makes the per-unit price invariant hold *bit-exactly* rather than approximately. An
earlier shape of this code floored the pool output to an int; at dust scale that made a 2-unit
sale realise a *higher* per-unit price than a 1-unit sale, breaking the invariant on integer
truncation alone.
"""

from decimal import Decimal, localcontext
from typing import Tuple

from contracts import CALCULATION_CONTEXT, PoolState, QuarantineRequired, calc, divide, sub

#: Basis-point denominator for the AMM fee.
BPS = 10_000

#: Uniswap v3/v4 fixed-point scale for ``sqrt_price_x96``.
Q96 = 1 << 96

#: Model tags recorded in ``PositionValue.evidence`` so a mark can be re-derived from the record
#: alone, without re-running this code — §9.2 compares two independent computations and needs to
#: know they used the same depth model before a 0.5% difference means anything.
MODEL_CONSTANT_PRODUCT = "model=constant_product_reserves"
MODEL_VIRTUAL_RESERVES = "model=v3_virtual_reserves_active_band"

#: Range over which total TVL was measured to *understate* near-spot depth on concentrated pools
#: (amendment A10.4). The same measurement ``depth.amm`` bounds its own ratio against; declared
#: again here rather than imported because every module in this layer imports ``contracts`` and
#: nothing else, and ``tests/hand_computed/test_marking.py`` pins the two spellings equal so they
#: cannot drift apart in silence.
MEASURED_TVL_UNDERSTATEMENT = (Decimal("5"), Decimal("23"))

#: The ceiling on virtual/real quote reserve above which the two readings are no longer describing
#: the same pool: ten times the 23x maximum ever measured. Below it a state is priced; above it,
#: quarantined. See :data:`depth.MAX_TVL_UNDERSTATEMENT_FACTOR` for why ten and not one or a
#: hundred — the argument is the measurement's, not this module's.
MAX_TVL_UNDERSTATEMENT_FACTOR = Decimal("230")


class UnmodelledPoolError(QuarantineRequired):
    """No supported depth model fits this pool.

    Deliberately an exception, and deliberately **not** a zero. ``$0`` because a pool is dead is a
    measurement; ``$0`` because nothing here can price the pool is the absence of one. Collapsing
    them would let a modelling gap travel downstream wearing the costume of a -100% return, and
    §10's dead-share diagnostic would report it as an observed rug.

    Subclasses :class:`contracts.QuarantineRequired` because the input is real and belongs in the
    reconciliation queue, not in the bin.
    """


def _require_the_two_readings_agree(pool, virtual_quote):
    # type: (PoolState, int) -> None
    """Bound ``virtual_quote / quote_reserve_raw`` to the measured band, or refuse.

    Raw quote units on both sides, so no price is needed and no rounding enters before the
    comparison. The ratio that is guarded is the ratio that is computed — one expression, checked
    once — because guarding one and reporting another would let a mark carry a factor the guard
    never saw.

    Guarantees that a mark taken on virtual reserves rests on a pool whose two readings are within
    the evidence. Guarantees nothing about the reading being *right*: both can be stale together,
    and nothing here can tell.
    """
    real_quote = pool.quote_reserve_raw
    if not isinstance(real_quote, int) or isinstance(real_quote, bool) or real_quote <= 0:
        raise UnmodelledPoolError(
            "pool {} states active_liquidity={!r} and sqrt_price_x96={!r} but holds "
            "quote_reserve_raw={!r}: a drained pool carrying a stale liquidity snapshot. There is "
            "no depth to sell into, and pricing the position off the stale band would convert the "
            "staleness into a mark. PoolStatus.UNMODELLED — this is not PoolStatus.DEAD, and the "
            "caller must not convert it into one.".format(
                pool.address, pool.active_liquidity, pool.sqrt_price_x96, real_quote
            )
        )

    if virtual_quote < real_quote:
        raise UnmodelledPoolError(
            "pool {}: virtual quote depth {} raw is below its real quote reserve {} raw. Total "
            "TVL was measured to *understate* near-spot depth on concentrated pools by 5-23x, "
            "never to overstate it, so either the sqrt_price_x96 orientation is inverted for this "
            "pool or the reserve and the liquidity were read at different heights. Both are real "
            "inputs this model does not support.".format(
                pool.address, virtual_quote, real_quote
            )
        )

    factor = divide(virtual_quote, real_quote)
    if factor > MAX_TVL_UNDERSTATEMENT_FACTOR:
        raise UnmodelledPoolError(
            "pool {}: virtual quote depth {} raw is {}x its real quote reserve {} raw, past the "
            "{}x ceiling on the {}-{}x measured understatement band. A ratio that far above "
            "anything measured does not describe a tighter pool; it describes an "
            "active_liquidity / sqrt_price_x96 read that no longer belongs to the reserve it is "
            "being divided by.".format(
                pool.address, virtual_quote, factor, real_quote,
                MAX_TVL_UNDERSTATEMENT_FACTOR,
                MEASURED_TVL_UNDERSTATEMENT[0], MEASURED_TVL_UNDERSTATEMENT[1],
            )
        )


def effective_reserves(pool):
    # type: (PoolState) -> Tuple[int, int, str]
    """The reserve pair this pool's exit curve is walked along, plus the model tag.

    Two supported shapes, and **which one applies is decided by whether the pool declares
    concentrated liquidity, never by whether it happens to hold reserves**:

    * **Virtual reserves in the active band** (v3/v4) — ``x_v = L/sqrt(P)``, ``y_v = L*sqrt(P)``,
      per amendment A10.4, whenever ``active_liquidity`` or ``sqrt_price_x96`` is stated;
    * **Real reserves** (v2 and clones) — used directly, when neither is.

    An earlier shape of this function tried the real reserves first and fell back to the virtual
    pair only when they were absent or zero. That reads A10.4 as conditional, and it is not: it
    says a v3/v4 pool *is* priced on virtual reserves. Since a real v3 pool always holds token
    balances, the fallback ordering made the concentrated branch unreachable on every real
    concentrated input — the branch was exercised only by test states someone had set to
    ``(0, 0)``. Measured on Uniswap v3 USDC/WETH 0.05% at block 16943478, reading the balances
    instead of the band is wrong in two directions at once: the depth is 13.35x too shallow, and
    the *spot* term becomes ``y_real / x_real``, the ratio of whatever the LPs left across all
    ticks, which sat 3.19% away from the pool's actual price — six times ``MARKING_TOLERANCE``,
    with no bound on its sign.

    The virtual pair is a single-band approximation, and the direction of *its* error is the
    reason it is allowed. Total TVL *understates* near-spot depth for concentrated pools by a
    measured 5-23x; ignoring liquidity outside the active band therefore models a pool as
    **shallower** than it is. A mark that is too low is conservative. A mark that is too high is
    the failure this whole module exists to prevent, so the approximation is only acceptable
    because it cannot go that way.

    **The two readings are cross-checked, because the approximation's safe direction is an
    argument about a live pool and not about a stale snapshot.** ``y_v`` and ``y_real`` are two
    independent readings of one pool at one block, and the 5-23x measurement is everything known
    about how far apart they may sit. A ratio below 1 means an inverted ``sqrt_price`` orientation
    or two reads taken at different heights; a ratio above
    :data:`MAX_TVL_UNDERSTATEMENT_FACTOR`, or a quote reserve of zero under a live ``L``, means a
    drained or migrated pool still carrying its old liquidity snapshot. ``depth.measure_depth``
    traced that last case turning a pool holding $0 into $5,000,000 of depth; the identical hole
    was open here, one module further along, where the number becomes §10's marked share. All
    three raise :class:`UnmodelledPoolError` — quarantine, never a zero, because none of them is a
    measurement that the pool is worthless.

    The two floor divisions below do **not** both round the mark in that safe direction, and
    saying that they do would be a false comfort. Flooring the quote side lowers the exit, which
    is conservative; flooring the asset side shrinks the denominator of
    :func:`average_exit_price` and therefore *raises* it. What bounds the second is size rather
    than direction — under one raw unit against reserves that are normally 10^18 and up, against a
    band approximation that understates depth by 5-23x. It stops being negligible only where the
    virtual asset reserve is itself a handful of raw units (``L=5, sqrt(P)=3`` floors 1.67 to 1,
    overstating depth by 67%), a regime whose entire mark is a few raw units of quote. Rounding
    the asset side up would be conservative on both legs; it is left alone here because it changes
    a pre-registered valuation, and the change belongs in a freeze, not in a bug fix.

    Anything else raises. There is no third branch that guesses.
    """
    if not isinstance(pool, PoolState):
        raise TypeError("expected a PoolState, got {}".format(type(pool).__name__))

    fee = pool.fee_bps
    if isinstance(fee, bool) or not isinstance(fee, int) or not 0 <= fee < BPS:
        raise UnmodelledPoolError(
            "pool {} has fee_bps={!r}; PoolStatus.UNMODELLED. A fee outside [0, {}) is not a "
            "constant-product pool this module can price, and a 100% fee would price every exit "
            "at zero — which would be indistinguishable from a dead pool.".format(
                pool.address, fee, BPS
            )
        )

    x, y = pool.asset_reserve_raw, pool.quote_reserve_raw
    liquidity, sqrt_price = pool.active_liquidity, pool.sqrt_price_x96
    concentrated = liquidity is not None or sqrt_price is not None

    if concentrated:
        if (
            isinstance(liquidity, int) and isinstance(sqrt_price, int)
            and not isinstance(liquidity, bool) and not isinstance(sqrt_price, bool)
            and liquidity > 0 and sqrt_price > 0
        ):
            # sqrt_price_x96 is sqrt(quote_raw per asset_raw) * 2^96, matching this pool's own
            # (asset, quote) orientation rather than v3's token0/token1 ordering — PoolState names
            # the two sides, so there is nothing to infer.
            virtual_asset = liquidity * Q96 // sqrt_price
            virtual_quote = liquidity * sqrt_price // Q96
            if virtual_asset > 0 and virtual_quote > 0:
                _require_the_two_readings_agree(pool, virtual_quote)
                return virtual_asset, virtual_quote, MODEL_VIRTUAL_RESERVES
    elif isinstance(x, int) and isinstance(y, int) and x > 0 and y > 0:
        return x, y, MODEL_CONSTANT_PRODUCT

    raise UnmodelledPoolError(
        "pool {} has no usable depth model: reserves=({!r}, {!r}), active_liquidity={!r}, "
        "sqrt_price_x96={!r}. PoolStatus.UNMODELLED — this is not PoolStatus.DEAD, and the "
        "caller must not convert it into one. Zero because dead and zero because unmodelled are "
        "different facts.".format(
            pool.address, pool.asset_reserve_raw, pool.quote_reserve_raw,
            pool.active_liquidity, pool.sqrt_price_x96,
        )
    )


def spot_exit_price(asset_reserve, quote_reserve):
    """The pool's marginal price: raw quote units per raw asset unit, no fee, no impact.

    This is the "Pool-Level Exit Price" of §4.4 — what a pool-level OHLCV feed reports. It is one
    half of the ``min()``; on its own it is the number that claims $50,000 for a position sitting
    in a $2,000 pool.
    """
    return divide(quote_reserve, asset_reserve)


def average_exit_price(quantity_raw, asset_reserve, quote_reserve, fee_bps):
    """Average raw-quote-per-raw-asset actually realised by selling ``quantity_raw``.

    Constant product with the fee taken on the way in::

        out = dx * f * y / (x + dx * f)          f = (BPS - fee_bps) / BPS
        avg = out / dx = f * y / (x + dx * f)

    Expressed over integers so a single division carries the whole quantity::

        avg = (BPS - fee) * y / (BPS * x + (BPS - fee) * dx)

    Strictly decreasing in ``quantity_raw``: the denominator grows with the quantity and the
    numerator does not. That is the property invariant — a larger position never realises a better
    per-unit price — and here it is arithmetic rather than a hope.
    """
    net = BPS - fee_bps
    return divide(net * quote_reserve, BPS * asset_reserve + net * quantity_raw)


def multiply(*values):
    """Multiply under the frozen 38-digit ROUND_HALF_EVEN context, left to right.

    The order is fixed rather than incidental: ``spot_value`` and ``exit_value`` must apply the
    same operations in the same sequence, or the ``min()`` between them could invert on rounding
    alone at the boundary where they are nearly equal.
    """
    result = calc(values[0])
    with localcontext(CALCULATION_CONTEXT):
        for value in values[1:]:
            result = +(result * calc(value))
    return result


def spot_value_usd(quantity_raw, asset_reserve, quote_reserve, quote_usd):
    """``Remaining x Pool Exit Price`` — the first term of the §4.4 minimum."""
    return multiply(quantity_raw, spot_exit_price(asset_reserve, quote_reserve), quote_usd)


def exit_value_usd(quantity_raw, asset_reserve, quote_reserve, fee_bps, quote_usd):
    """``Extractable Given Real Liquidity`` — the second, mandatory term of the minimum."""
    return multiply(
        quantity_raw,
        average_exit_price(quantity_raw, asset_reserve, quote_reserve, fee_bps),
        quote_usd,
    )


def shortfall_vs_spot(spot_usd, marked_usd):
    """How far the bounded mark falls below the spot mark, as a fraction of spot.

    Through the seam's primitives, **not** ``(spot - marked) / spot``. Both the subtraction and
    the division in that expression run in the caller's ambient 28-digit context while every value
    they consume was produced at 38, and this ratio is what ``MARKING_TOLERANCE`` and
    ``THIN_SHORTFALL_RATIO`` are compared against. A shortfall of

        (10^31 + 1) / (2 * 10^33) = 0.0050000000000000000000000000000005

    is above the 0.5% line at 38 digits and rounds to exactly 0.005 — not above it — at 28, so the
    ambient form decides ``value_basis`` by the caller's ``decimal`` settings. Nothing about the
    result looks wrong afterwards, which is the whole difficulty: both labels are plausible and
    only one is the pre-registered one.

    A spot of zero is not a division to guard: it means a position of zero size, where "how far
    below spot" has no content. Zero rather than an exception, because the caller is about to
    report the mark itself as zero.
    """
    if spot_usd == 0:
        return Decimal("0")
    return divide(sub(spot_usd, marked_usd), spot_usd)
