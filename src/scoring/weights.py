"""Trade weighting, and the three aggregations §4.4 and §7.1 are assembled from.

    Trade Weight = log(1 + trade_value_usd)

Log weighting is what stops one whale purchase from being the wallet's score: at $100 the weight is
4.6, at $1,000,000 it is 13.8 — a factor of three across a factor of ten thousand.

**The base of the logarithm cannot change any published number**, and that is worth stating because
§4.4 writes ``log`` without one. Changing base multiplies every weight by the same constant, and the
constant divides out of both places a weight is ever used: the weighted mean ``Σwr / Σw`` and the
bucket share ``Σ_bucket w / Σ_all w``. Natural log is used because :meth:`decimal.Decimal.ln` is
correctly rounded under the frozen 38-digit context, so the choice is settled on reproducibility
rather than on taste.

**Every aggregation here accumulates in the order it is given.** At 38 digits each addition rounds,
so a different order can move the answer in the 38th place. The order is therefore part of the
contract rather than an implementation detail, and callers must supply a deterministic one — §9.2
requires the number to be reproducible, and "reproducible" cannot depend on how a dict happened to
iterate.
"""

from decimal import Decimal, localcontext

from contracts import CALCULATION_CONTEXT, FIRST_HOUR_BUCKETS, TokenAgeBucket, calc, divide, require_finite

ZERO = Decimal("0")
ONE = Decimal("1")

#: §4.7's four buckets in age order. Fixed here, once, because it is simultaneously the reporting
#: order, the accumulation order for the Edge Origin total, and the reason the first-hour figure is
#: a *prefix* of that accumulation rather than a separate sum that might not agree with it.
BUCKET_ORDER = (
    TokenAgeBucket.A,
    TokenAgeBucket.B,
    TokenAgeBucket.C,
    TokenAgeBucket.D,
)

# The seam names the first hour; scoring must not re-derive its own. Checked at import rather than
# asserted, because ``python -O`` strips an assert and this is a structural invariant: if the two
# ever disagree, the gate condition and the reported decomposition measure different populations.
if BUCKET_ORDER[: len(FIRST_HOUR_BUCKETS)] != tuple(FIRST_HOUR_BUCKETS):
    raise ImportError(
        "FIRST_HOUR_BUCKETS must be a prefix of BUCKET_ORDER, or the first-hour contribution "
        "stops being a prefix of the total accumulation and the two can disagree in the last digit"
    )


def trade_weight(trade_value_usd):
    """``ln(1 + trade_value_usd)`` under the frozen context.

    A trade worth nothing weighs nothing — ``ln(1) = 0`` exactly — which is the right limit: a leg
    that priced at zero cannot be allowed to pull a weighted mean toward its own return. A wallet
    whose *entire* volume prices at zero has no weighted mean at all, and
    :func:`scoring.quality.buy_quality` refuses it rather than dividing.
    """
    value = require_finite(calc(trade_value_usd), "trade_value_usd")
    if value < 0:
        raise ValueError(
            "trade_value_usd is {}; a negative trade value has no log weight, and clamping it to "
            "zero would silently give the trade the weight of a worthless one".format(value)
        )
    with localcontext(CALCULATION_CONTEXT):
        return +((ONE + value).ln())


def weighted_mean(weighted_values):
    """``Σ(w·x) / Σw`` over ``(weight, value)`` pairs, accumulated in the order supplied.

    Refuses a zero total weight through :func:`contracts.divide` rather than returning zero or one:
    what an unweighted basket means is a domain question, and the two callers here answer it
    differently — a wallet is unscorable, a bucket contributes nothing.
    """
    pairs = tuple(weighted_values)
    if not pairs:
        raise ValueError("a weighted mean over no values is not zero; it is undefined")

    with localcontext(CALCULATION_CONTEXT):
        total_weight = ZERO
        total_weighted = ZERO
        for weight, value in pairs:
            w = require_finite(calc(weight), "weight")
            x = require_finite(calc(value), "value")
            if w < 0:
                raise ValueError("a trade weight cannot be negative, got {}".format(w))
            total_weight += w
            total_weighted += w * x
        return +divide(total_weighted, total_weight)


def arithmetic_mean(values):
    """Mean Buy Quality Advantage (§7.1 condition 1). Accumulated in the order supplied."""
    items = _finite_sequence(values, "advantage")
    with localcontext(CALCULATION_CONTEXT):
        total = ZERO
        for item in items:
            total += item
        return +divide(total, len(items))


def median(values):
    """Median Buy Quality Advantage (§7.1 condition 2).

    §7.1 requires the median because long-tail return distributions are severely skewed: one token
    returning 1000% can carry a basket in which 90% of buys lost money. An even count takes the
    midpoint of the two middle values, so the statistic is defined for every basket size.
    """
    items = sorted(_finite_sequence(values, "advantage"))
    middle = len(items) // 2
    if len(items) % 2:
        return items[middle]
    with localcontext(CALCULATION_CONTEXT):
        return +divide(items[middle - 1] + items[middle], 2)


def _finite_sequence(values, field):
    items = tuple(require_finite(calc(v), field) for v in values)
    if not items:
        raise ValueError(
            "no {} values were supplied; an empty basket has no mean and no median, and a zero "
            "would read as a measured flat result".format(field)
        )
    return items
