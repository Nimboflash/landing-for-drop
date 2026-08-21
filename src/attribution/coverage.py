"""The standing attribution metrics — above all, the fallback rate.

Amendment A15 makes ``attribution_fallback_rate`` a monitored metric rather than a one-time check,
because it is the specific failure that produces phantom whales and erases real users. A run whose
fallback rate is rising is a run whose universe is quietly turning into a handful of solvers.

Rates are ``Optional[Decimal]`` and are ``None`` over an empty population. A 0% fallback rate
across zero transactions reads as a clean run, which is the sentinel-number failure the seam rules
forbid. They are also left unquantized: quantization happens once, at the reporting boundary, and
this is not it.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional

from contracts import AccountType, AttributionMethod, divide


@dataclass(frozen=True)
class AttributionCoverage:
    """What attribution concluded across a population of transactions.

    Every transaction lands in exactly one of ``resolved``, ``fallback``, ``unresolved`` — so a
    coverage report accounts for everything it saw, not for the part that happened to work.
    """

    total: int
    resolved: int
    fallback: int
    unresolved: int
    usable_for_primary_metric: int
    by_method: Dict[AttributionMethod, int]
    by_account_type: Dict[AccountType, int]
    fallback_rate: Optional[Decimal]
    unresolved_rate: Optional[Decimal]
    usable_rate: Optional[Decimal]

    def __post_init__(self):
        parts = self.resolved + self.fallback + self.unresolved
        if parts != self.total:
            raise ValueError(
                "coverage does not account for every transaction: {} of {}".format(
                    parts, self.total
                )
            )
        if self.usable_for_primary_metric > self.resolved:
            raise ValueError(
                "a fallback or unresolved attribution cannot be usable for the primary metric"
            )
        rates = (self.fallback_rate, self.unresolved_rate, self.usable_rate)
        if self.total == 0 and any(r is not None for r in rates):
            raise ValueError(
                "an empty population has no rate; a zero rate over zero transactions reads as a "
                "clean run"
            )
        if self.total and any(r is None for r in rates):
            raise ValueError("a non-empty population must carry its rates")


def attribution_coverage(attributions):
    """Aggregate resolved attributions into the reportable coverage record."""
    attributions = tuple(attributions)
    total = len(attributions)

    by_method = {}
    by_account_type = {}
    fallback = unresolved = usable = 0

    for attribution in attributions:
        by_method[attribution.method] = by_method.get(attribution.method, 0) + 1
        by_account_type[attribution.account_type] = (
            by_account_type.get(attribution.account_type, 0) + 1
        )
        if attribution.method is AttributionMethod.UNRESOLVED:
            unresolved += 1
        elif attribution.is_fallback:
            fallback += 1
        if attribution.is_usable_for_primary_metric:
            usable += 1

    resolved = total - fallback - unresolved
    return AttributionCoverage(
        total=total,
        resolved=resolved,
        fallback=fallback,
        unresolved=unresolved,
        usable_for_primary_metric=usable,
        by_method=by_method,
        by_account_type=by_account_type,
        fallback_rate=_rate(fallback, total),
        unresolved_rate=_rate(unresolved, total),
        usable_rate=_rate(usable, total),
    )


def attribution_fallback_rate(attributions):
    """Share of attributions whose owner is only the transaction sender. ``None`` when empty."""
    attributions = tuple(attributions)
    return _rate(sum(1 for a in attributions if a.is_fallback), len(attributions))


def _rate(count, total):
    if total == 0:
        return None
    return divide(count, total)
