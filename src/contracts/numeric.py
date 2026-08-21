"""Frozen decimal policy.

"Never float" is correct but incomplete. Two agents can both obey it and still disagree, because
one rounds a ratio before aggregating and the other does not. This module fixes the remaining
degrees of freedom so that any correct implementation produces bit-identical numbers.

    Internal precision      38 significant digits
    Rounding                ROUND_HALF_EVEN (banker's), everywhere, no exceptions
    Raw token quantities    int, never Decimal, never rounded
    USD accounting          Decimal at full internal precision
    Ratios and returns      NEVER quantized before final aggregation
    Reporting               quantized exactly once, at the output boundary

The rule that does the most work is the third one. A single global two-decimal USD quantization
would silently destroy residual and fee arithmetic — the netting tolerance is ``max($0.01, 0.01%
of notional)``, so a value rounded to cents before that comparison has already lost the quantity
being compared.

This module contains **no substantive calculation**. It defines what a valid number looks like and
how to render one. How a lane arrives at a number is that lane's business, and deliberately not
shared — a shared formula is a shared bug that both lanes would inherit through a dependency they
each believe to be neutral.
"""

from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext

#: Enough headroom for raw token quantities (up to 2^256 is ~78 digits, but those stay ``int``)
#: alongside USD values carried at full precision through long weighted aggregations.
INTERNAL_PRECISION = 38

ROUNDING = ROUND_HALF_EVEN

#: The context every calculation runs under. Traps are left at their defaults so that division by
#: zero and invalid operations raise rather than producing NaN — a NaN reaching a gate comparison
#: would evaluate False against every threshold and read as an ordinary failure.
CALCULATION_CONTEXT = Context(prec=INTERNAL_PRECISION, rounding=ROUNDING)

# -- output scales --------------------------------------------------------------
# Quantization happens once, here, at the reporting boundary. Never mid-calculation.

SCALE_USD = Decimal("0.000001")       # 6dp — small fees and residuals survive
SCALE_RATIO = Decimal("0.00000001")   # 8dp — returns and shares
SCALE_PERCENTAGE_POINTS = Decimal("0.0001")
SCALE_SMD = Decimal("0.0001")

#: Equality tolerance for reconciling two independently derived values. §9.2 sets 0.5% for USD
#: values and exact match for raw quantities, so this is for internal consistency checks only,
#: never for a golden-set comparison.
COMPARISON_TOLERANCE = Decimal("1e-18")


def calc(value):
    """Coerce to Decimal under the frozen context. Refuses float on sight.

    A float argument is a bug, not a convenience: it has already lost precision before this
    function sees it, so accepting it would launder the loss.
    """
    if isinstance(value, float):
        raise TypeError(
            "float is not permitted in the numeric path; got {!r}. Construct from str or int — "
            "a float has already lost precision before it reaches here.".format(value)
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            raise ValueError("not a valid decimal: {!r}".format(value))
    raise TypeError("cannot build a Decimal from {}".format(type(value).__name__))


def divide(numerator, denominator):
    """Division under the frozen context, with a legible refusal on zero.

    Ratios are not quantized here. §"reporting" is the only place quantization is permitted, and a
    ratio rounded before aggregation biases the weighted mean it feeds.
    """
    n, d = calc(numerator), calc(denominator)
    if d == 0:
        raise ZeroDivisionError(
            "division by zero in the numeric path; the caller must decide whether this is an "
            "INDETERMINATE status or an error, and must not receive a silent zero"
        )
    with localcontext(CALCULATION_CONTEXT):
        return +(n / d)


def sub(left, right):
    """Subtraction under the frozen context.

    Exists because ``divide(a, b) - Decimal("1")`` is a trap: the division runs under the frozen
    38-digit context and the subtraction that follows lands back in the ambient 28-digit one, so
    the result is silently truncated. That defect shipped in ``LotConsumption.realized_return``
    and was caught by review, not by a test — the value looked entirely reasonable.

    Any arithmetic that must hold the frozen precision goes through these primitives, or through
    an explicit ``localcontext(CALCULATION_CONTEXT)`` block.
    """
    with localcontext(CALCULATION_CONTEXT):
        return +(calc(left) - calc(right))


def add(left, right):
    """Addition under the frozen context. See :func:`sub`."""
    with localcontext(CALCULATION_CONTEXT):
        return +(calc(left) + calc(right))


def mul(left, right):
    """Multiplication under the frozen context. See :func:`sub`."""
    with localcontext(CALCULATION_CONTEXT):
        return +(calc(left) * calc(right))


def quantize_usd(value):
    return calc(value).quantize(SCALE_USD, rounding=ROUNDING)


def quantize_ratio(value):
    return calc(value).quantize(SCALE_RATIO, rounding=ROUNDING)


def quantize_pp(value):
    return calc(value).quantize(SCALE_PERCENTAGE_POINTS, rounding=ROUNDING)


def is_finite(value):
    d = calc(value)
    return d.is_finite()


def require_finite(value, field):
    """Refuse NaN and infinity at the boundary.

    A NaN compares False against every threshold, so it does not raise — it reads as an ordinary
    failed condition and disappears into the result.
    """
    d = calc(value)
    if not d.is_finite():
        raise ValueError(
            "{} is {} — non-finite values are refused at the boundary because they compare "
            "False against every threshold and would read as an ordinary negative result".format(
                field, d
            )
        )
    return d


# -- policy versioning ----------------------------------------------------------
#
# Numeric identity and output presentation are versioned separately on purpose.
#
# The canonical hash normalises cosmetic scale, so Decimal("2") and Decimal("2.00") hash
# identically — that is correct for *identity*. But it means the hash cannot also carry the
# display requirement. If it did, changing a report from "2.0" to "2.00" would either perturb the
# experiment hash for no substantive reason, or the display change would vanish unrecorded.
#
# So: NUMERIC_POLICY_VERSION governs how values are computed and compared.
# REPORTING_SCHEMA_VERSION governs how they are rendered. Both go in the freeze manifest.

NUMERIC_POLICY_VERSION = "decimal-v1"
REPORTING_SCHEMA_VERSION = "report-v1"

#: How each class of value must be quantized *at output only*. Never applied mid-calculation.
REPORTING_SCALES = {
    "usd": SCALE_USD,
    "ratio": SCALE_RATIO,
    "percentage_points": SCALE_PERCENTAGE_POINTS,
    "smd": SCALE_SMD,
}
