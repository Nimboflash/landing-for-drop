"""Edge Origin — where the advantage actually came from (§7.1 condition 3, ticket 32).

    Bucket Edge Contribution = max(0, Bucket Weight x (Selected BQ - Matched Benchmark BQ))
    First-Hour Edge Share    = (A + B) / (A + B + C + D)

**Bucket granularity, never per trade.** A per-trade decomposition would let one enormous first-hour
winner and one enormous first-hour loser cancel, and the condition exists to catch exactly the
population that produces both.

**Only positive contributions enter, and they enter both the numerator and the denominator.** A
bucket where the selected basket lost to the benchmark contributes zero, not a negative number: a
negative term in the denominator would inflate the share, and a negative term in a *later* bucket
would deflate it, so allowing them would make the answer depend on which direction the losses fell.

Three outcomes, and the middle one is the trap:

    share > 40%              UNCOPYABLE_DOMINATED   window FAILS
    total positive < 5pp     INDETERMINATE          window FAILS, share is None
    otherwise                VALID

The 5pp guard is checked **first**, because below it the ratio is a ratio of noise and reporting it
would be worse than reporting nothing. And the status it produces is not a pass. Returning
``Decimal("0")`` for the share instead of ``None`` would silently convert an unmeasurable window
into a passing one — the single most dangerous possible bug in this path.
:meth:`contracts.WindowScore.__post_init__` refuses the inconsistent combination at construction;
nothing here may route around it.

The 40% boundary is inclusive: ``> 40%`` fails, so exactly 40% passes. It is a **cheap backstop and
not the primary defence** (§7.1, as resolved 2026-07-31) — the addendum's exclusion of long-tail
assets removed most of what it was built to catch, and Gate 2 tests economic copyability directly.
It is kept at 40% rather than tightened because a new number would be chosen by intuition rather
than measurement, which trades one uncalibrated threshold for another.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Optional, Tuple

from contracts import (
    CALCULATION_CONTEXT,
    FIRST_HOUR_BUCKETS,
    BuyQuality,
    ContractError,
    EdgeOriginStatus,
    TokenAgeBucket,
    divide,
)
from phase0.parameters import PARAMETERS

from .weights import BUCKET_ORDER, ZERO

#: §7.1 condition 3. ``> 40%`` fails; exactly 40% passes. Read from the ticket-11 frozen set: this
#: is the threshold ticket 09 resolved, and the resolution is only binding if there is one copy of
#: it. The strictness of the comparison is this module's business; the number is not.
FIRST_HOUR_EDGE_SHARE_MAX = PARAMETERS.value("gate.first_hour_edge_share_max")

#: The small-denominator guard, in the units buy quality itself uses — a return of ``0.05`` is
#: five percentage points. Below this the share is unmeasurable and the window fails as
#: ``INDETERMINATE``.
MIN_TOTAL_POSITIVE_EDGE = PARAMETERS.value("gate.minimum_total_positive_edge")

#: §12.6, carried in the output because ticket 32 requires the limitation to travel with the number
#: rather than live only in a document nobody reads next to the result.
EDGE_ORIGIN_LIMITATIONS = (
    "The Edge Origin condition is a partial defence against adversarial targeting, not a complete "
    "one (§12.6). Wallets engineered to attract copy traders and then dump on them are documented "
    "behaviour; past-PnL rank is an adversarially targeted ranking, not merely a noisy one.",
    "The 40% threshold was calibrated against a universe that included long-tail tokens, where most "
    "first-hour sniping happens. Addendum §9.5 excludes long-tail from Ethereum Phase 0, so this is "
    "a cheap backstop; Gate 2 (§7.2) is the primary defence against uncopyable behaviour.",
)


class BenchmarkBucketMissing(ContractError):
    """The benchmark has no buy quality for a bucket the selected basket actually traded.

    Refused rather than defaulted. A zero here would assert that the matched benchmark broke even in
    that bucket — a measurement nobody made — and it would land in the numerator of the first-hour
    share, which is the number the whole condition turns on. The caller decides: re-match, or record
    the window as unmeasurable.
    """


@dataclass(frozen=True)
class BucketEdge:
    """One bucket's row of the decomposition, with both sides of the difference kept.

    ``selected_value`` and ``benchmark_value`` are ``None`` exactly when the bucket carries no
    weight in the selected basket. There is nothing to compare, the contribution is zero by
    construction, and no benchmark value is required — which is why a benchmark that never traded
    the first block is only a problem when the selected basket did.
    """

    bucket: TokenAgeBucket
    weight_share: Decimal
    selected_value: Optional[Decimal]
    benchmark_value: Optional[Decimal]
    raw_advantage: Optional[Decimal]
    contribution: Decimal

    @property
    def clipped(self):
        """True when ``max(0, ...)`` actually bit — the bucket lost to the benchmark."""
        return self.raw_advantage is not None and self.raw_advantage < 0


@dataclass(frozen=True)
class EdgeOrigin:
    """The full decomposition, of which three fields reach :class:`contracts.WindowScore`.

    ``share`` is ``Optional`` and ``INDETERMINATE`` is the only status that may carry ``None``. The
    pairing is enforced at construction here as well as at the seam, because the two ways to break
    it — a zero share on an unmeasurable window, or a live status with no share — are the same bug
    seen from opposite sides.
    """

    selected: str
    benchmark: str
    buckets: Tuple[BucketEdge, ...]
    total_positive_contribution: Decimal
    first_hour_contribution: Decimal
    share: Optional[Decimal]
    status: EdgeOriginStatus
    limitations: Tuple[str, ...] = EDGE_ORIGIN_LIMITATIONS

    def __post_init__(self):
        object.__setattr__(self, "buckets", tuple(self.buckets))
        object.__setattr__(self, "limitations", tuple(self.limitations))
        if tuple(b.bucket for b in self.buckets) != BUCKET_ORDER:
            raise ValueError(
                "the decomposition must carry all four §4.7 buckets in age order; a missing bucket "
                "cannot be told apart from one that contributed nothing"
            )
        if (self.status is EdgeOriginStatus.INDETERMINATE) != (self.share is None):
            raise ValueError(
                "share is None exactly when the status is INDETERMINATE. A share of zero on an "
                "unmeasurable window converts a failure into a pass, which is the one outcome this "
                "module exists to prevent."
            )

    @property
    def bucket_a_contribution(self):
        """Bucket A alone — first 10 blocks. Ticket 32 reports it beside the first-hour aggregate,
        which is what the gate condition actually uses."""
        return self.buckets[0].contribution

    @property
    def bucket_a_share(self):
        """Diagnostic only. ``None`` whenever the share itself is unmeasurable."""
        if self.share is None:
            return None
        return divide(self.bucket_a_contribution, self.total_positive_contribution)

    @property
    def dominated(self):
        return self.status is EdgeOriginStatus.UNCOPYABLE_DOMINATED


def edge_origin(selected, benchmark):
    """Decompose the selected basket's advantage over its matched benchmark, bucket by bucket.

    ``selected`` supplies the weights: §7.1 defines bucket weight as "that bucket's share of total
    **selected**-portfolio buy weight". The benchmark supplies only its per-bucket buy qualities.
    Using the benchmark's weights instead would answer a different question — where the *control*
    traded — and would make a control-heavy bucket dilute a selected-heavy one.

    All comparisons are against the activity-matched benchmark. The naive random basket and
    buy-and-hold ETH are reported as context and cannot enter this computation (ticket 32): beating
    a set of low-activity, low-capital addresses proves nothing, and a June 2026 study of 166,098
    launches found activity-matched placebos returning +216.3% against a "skilled" cohort's +132.3%.
    """
    for name, value in (("selected", selected), ("benchmark", benchmark)):
        if not isinstance(value, BuyQuality):
            raise TypeError(
                "edge_origin needs a contracts.BuyQuality for {}, got {}".format(
                    name, type(value).__name__
                )
            )

    first_hour = set(FIRST_HOUR_BUCKETS)
    rows = []
    with localcontext(CALCULATION_CONTEXT):
        running = ZERO
        first_hour_total = ZERO
        for bucket in BUCKET_ORDER:
            rows.append(_bucket_edge(bucket, selected, benchmark))
            # Accumulated in BUCKET_ORDER, once, so the first-hour figure is a genuine prefix of
            # the total rather than a second sum that could disagree with it in the last digit.
            running += rows[-1].contribution
            if bucket in first_hour:
                first_hour_total = running
        total = +running
        first_hour_total = +first_hour_total

    if total < MIN_TOTAL_POSITIVE_EDGE:
        # Checked before the share, and reported without one. Below 5pp the ratio is a ratio of
        # noise; a number here would be read as a measurement.
        share = None
        status = EdgeOriginStatus.INDETERMINATE
    else:
        share = divide(first_hour_total, total)
        status = (
            EdgeOriginStatus.UNCOPYABLE_DOMINATED
            if share > FIRST_HOUR_EDGE_SHARE_MAX
            else EdgeOriginStatus.VALID
        )

    return EdgeOrigin(
        selected=selected.wallet,
        benchmark=benchmark.wallet,
        buckets=tuple(rows),
        total_positive_contribution=total,
        first_hour_contribution=first_hour_total,
        share=share,
        status=status,
    )


def _bucket_edge(bucket, selected, benchmark):
    """One row, at the frozen precision whatever context the caller is in.

    The docstring used to say "must be called inside the frozen context" and leave it there. That
    made the row's precision a property of ``edge_origin``'s ``with`` block rather than of this
    function: called from anywhere else, both the subtraction and the multiply round to the
    ambient 28 digits, and a ten-digit-shorter advantage — which looks entirely reasonable — goes
    straight into the numerator of the first-hour edge share. Opening the block here costs a
    save/restore and turns a sentence into a guarantee.
    """
    weight = selected.bucket_weights.get(bucket)
    if weight is None or weight == 0:
        return BucketEdge(
            bucket=bucket,
            weight_share=ZERO,
            selected_value=None,
            benchmark_value=None,
            raw_advantage=None,
            contribution=ZERO,
        )

    selected_value = selected.bucket_values.get(bucket)
    if selected_value is None:
        raise ValueError(
            "the selected basket carries weight {} in bucket {} but no buy quality for it. A "
            "BuyQuality whose bucket_weights and bucket_values disagree cannot be "
            "decomposed.".format(weight, bucket.value)
        )

    benchmark_value = benchmark.bucket_values.get(bucket)
    if benchmark_value is None:
        raise BenchmarkBucketMissing(
            "the selected basket carries {} of its buy weight in bucket {}, but the matched "
            "benchmark {} has no buy quality there. Substituting zero would assert the benchmark "
            "broke even in that bucket — a measurement nobody made — and it would land in the "
            "numerator of the first-hour share.".format(weight, bucket.value, benchmark.wallet)
        )

    with localcontext(CALCULATION_CONTEXT):
        advantage = +(selected_value - benchmark_value)
        contribution = +(weight * advantage)
    if contribution <= 0:
        # max(0, ...). The comparison is <= rather than < so that a negative zero, which Decimal
        # produces from a negative advantage times a zero weight, is normalised away before it can
        # serialize as "-0".
        contribution = ZERO

    return BucketEdge(
        bucket=bucket,
        weight_share=weight,
        selected_value=selected_value,
        benchmark_value=benchmark_value,
        raw_advantage=advantage,
        contribution=contribution,
    )
