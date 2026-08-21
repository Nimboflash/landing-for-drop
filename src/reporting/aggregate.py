"""Aggregation at full frozen precision, upstream of the boundary.

Every function here returns an **unquantized** Decimal. Quantization belongs to
:mod:`reporting.boundary` and happens once, when a record is constructed — so an aggregate is
computed from the inputs as they arrived, not from their rendered forms.

The mean and the median are deliberately *not* imported from :mod:`scoring`. ``reporting`` is a
leaf: it imports the frozen seam and nothing else in the builder lane. A shared aggregation helper
would be a shared bug that both the score and the report inherit through a dependency each believes
to be neutral, and the two would then agree — which is precisely what makes such a bug invisible.

Every accumulation runs in the order it is given. At 38 digits each addition rounds, so a different
order can move the answer in the 38th place, and §9.2 requires the published number to be
reproducible. Callers supply a deterministic order; this module does not sort for them, except in
:func:`median`, where sorting *is* the definition.
"""

from decimal import Decimal, localcontext

from contracts import (
    CALCULATION_CONTEXT,
    ContractError,
    add,
    calc,
    divide,
    require_finite,
)

ZERO = Decimal("0")


class EmptyPopulation(ContractError):
    """An aggregate was requested over nothing, and no substitute number will be offered.

    A mean over no wallets is not zero, a rate over no trades is not zero, and a churn rate over no
    selected wallets is not zero. Each of those zeros would read as a measured result — "the basket
    broke even", "no trade was profitable", "nobody churned" — when what actually happened is that
    there was nothing to measure.
    """


def _finite_sequence(values, field):
    items = tuple(require_finite(calc(v), field) for v in values)
    if not items:
        raise EmptyPopulation(
            "no {} values were supplied; an empty population has no mean and no median, and a "
            "zero would read as a measured flat result".format(field)
        )
    return items


def total(values, field="amount"):
    """Sum in the order supplied, at full precision."""
    items = _finite_sequence(values, field)
    with localcontext(CALCULATION_CONTEXT):
        running = ZERO
        for item in items:
            running += item
        return +running


def mean(values, field="value"):
    """Arithmetic mean, unquantized, accumulated in the order supplied."""
    items = _finite_sequence(values, field)
    with localcontext(CALCULATION_CONTEXT):
        running = ZERO
        for item in items:
            running += item
        running = +running
    return divide(running, len(items))


def median(values, field="value"):
    """Median, unquantized. An even count takes the midpoint of the two middle values.

    §7.1 leans on the median because long-tail return distributions are severely skewed: one token
    returning 1000% can carry a basket in which 90% of buys lost money. The same reasoning applies
    to every §10 figure computed across wallets, which is why the mean never travels alone.
    """
    items = sorted(_finite_sequence(values, field))
    middle = len(items) // 2
    if len(items) % 2:
        return items[middle]
    return divide(add(items[middle - 1], items[middle]), 2)


def share(part, whole, field="share"):
    """``part / whole`` at full precision, refusing a denominator that cannot support a share.

    A zero or negative denominator is not a share of zero. It is the absence of a population, and
    the caller must decide whether that is ``N/A`` or an error — this module will not decide it by
    returning a number.
    """
    numerator = require_finite(calc(part), field)
    denominator = require_finite(calc(whole), "{} denominator".format(field))
    if denominator <= 0:
        raise EmptyPopulation(
            "{} has a denominator of {}; a share of a population that does not exist is not zero, "
            "and returning one would put an absence into a results table wearing the clothes of a "
            "measurement".format(field, denominator)
        )
    return divide(numerator, denominator)


def rate(count, population, field="rate"):
    """``count / population`` over integer counts, at full precision.

    Separate from :func:`share` because the failure modes differ: a count outside ``[0,
    population]`` is a bookkeeping error that must surface here rather than as a rate above 1
    somewhere in a report, where it reads as a rounding artefact.
    """
    for name, value in (("count", count), ("population", population)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(
                "{} for {} must be an int, got {}. A Decimal count would let a fractional "
                "population reach a rate that is reported as a headcount.".format(
                    name, field, type(value).__name__
                )
            )
    if population <= 0:
        raise EmptyPopulation(
            "{} over a population of {}; a rate over nobody is not zero".format(field, population)
        )
    if not 0 <= count <= population:
        raise ValueError(
            "{}: {} of {} is not a rate — the count must lie within the population it is a "
            "count of".format(field, count, population)
        )
    return divide(count, population)
