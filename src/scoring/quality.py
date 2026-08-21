"""``buy_quality_30d`` — the primary metric (§4.4, §10, ticket 24).

    buy_quality_30d = Σ(w_i · r_i) / Σ(w_i)      w_i = log(1 + trade_value_usd_i)

The headline number is the easy half. The half §10 insists on is the *mix*:

    Realized Share      share of value from actual sells
    Marked Share        share dependent on pool-level marking
    Dead / Zeroed Share share marked to zero

"If only 20% of volume is realized and 80% rests on marking, the gate result lacks credibility even
if it looks strongly positive." So the three travel with the score, and
:class:`contracts.BuyQuality` refuses to be constructed without them summing to one.

**What the three amounts on a** :class:`contracts.BuyOutcome` **mean.** They are the portions of the
buy's accounted value attributable to each basis — realized proceeds for the part that was sold, the
liquidity-bounded mark for the part still open at day 30, and, for a dead pool, the *exposure the
zero verdict decides*. The last one has to be the exposure and not the resulting value, because §4.4
Case 3 marks a dead position at exactly zero: reading ``dead_usd`` as the outcome value would make
the dead share structurally zero and quietly delete the one basis §10 most wants visible.

Three refusals, all of them :class:`UnscorableWallet`, all of them for the same reason: the
alternative is a number nobody measured.

* no buys at all — zero would read as flat performance rather than as absence;
* every buy priced at zero, so ``Σw = 0`` — there is no weighted mean to report;
* no value basis recorded anywhere — the shares cannot be computed, and inventing three that
  happen to sum to one is exactly the failure §10 exists to prevent.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Optional, Tuple

from contracts import (
    CALCULATION_CONTEXT,
    BuyOutcome,
    BuyQuality,
    ClassificationStatus,
    ContractError,
    NetTradeResult,
    TokenAgeBucket,
    calc,
    divide,
    require_finite,
)

from .weights import BUCKET_ORDER, ZERO, trade_weight, weighted_mean


class UnscorableWallet(ContractError):
    """The basket cannot produce a buy quality, and no substitute number will be offered.

    Distinct from a negative finding. "This wallet's buys lost money" is a result; "this wallet has
    no buys" or "its entire volume priced at zero" is the absence of one, and the two must not
    arrive downstream wearing the same clothes.
    """


def buy_outcome(
    buy,
    trade_value_usd,
    return_pct,
    realized_usd=ZERO,
    marked_usd=ZERO,
    dead_usd=ZERO,
    bucket=None,
):
    """Build the seam atom for one buy, with the §4.4 weight computed rather than supplied.

    ``BuyOutcome.weight`` is ``log(1 + trade_value_usd)`` and nothing else. Taking the trade value
    here instead of the weight is the difference between a formula that is applied once and a
    formula every caller re-implements — and a caller that passed the raw USD value as the weight
    would produce a plausible, wrong, whale-dominated score with nothing to flag it.

    ``bucket`` defaults to the trade's own ``token_age_bucket``. §4.7 gives every buy exactly one
    non-overlapping bucket, so an unbucketed trade is refused rather than defaulted into ``D``,
    which is where an unknown-age buy would otherwise silently land — outside the first hour, which
    is precisely the classification §7.1 is trying to test.
    """
    if not isinstance(buy, NetTradeResult):
        raise TypeError("buy_outcome needs a NetTradeResult, got {}".format(type(buy).__name__))
    if buy.status is not ClassificationStatus.VALID_BUY:
        raise ValueError(
            "buy quality is measured on valid buys; {} is {}. A sell is already accounted for as "
            "the realized leg of the buy it closes, and counting it again would double it.".format(
                buy.tx_hash, buy.status.value
            )
        )

    chosen = bucket if bucket is not None else buy.token_age_bucket
    if not isinstance(chosen, TokenAgeBucket):
        raise ValueError(
            "buy {} carries no token-age bucket. §4.7 assigns exactly one to every buy; defaulting "
            "to D would file an unknown-age buy outside the first hour, which is the very "
            "classification the Edge Origin condition tests.".format(buy.tx_hash)
        )

    return BuyOutcome(
        buy=buy,
        return_pct=require_finite(calc(return_pct), "return_pct"),
        weight=trade_weight(trade_value_usd),
        realized_usd=_basis(realized_usd, "realized_usd"),
        marked_usd=_basis(marked_usd, "marked_usd"),
        dead_usd=_basis(dead_usd, "dead_usd"),
        bucket=chosen,
    )


def _basis(value, field):
    amount = require_finite(calc(value), field)
    if amount < 0:
        raise ValueError(
            "{} is {}; a negative value basis would let one buy erase another's provenance from "
            "the §10 mix".format(field, amount)
        )
    return amount


# -- the rich result ------------------------------------------------------------


@dataclass(frozen=True)
class BucketBreakdown:
    """One §4.7 bucket's contribution to a wallet's score.

    ``value`` is ``None`` when the bucket carries no weight — either it holds no buys, or every buy
    in it priced at zero. Both are absences, and a zero would read as "this bucket broke even",
    which is the number the Edge Origin decomposition would then difference against a benchmark.
    """

    bucket: TokenAgeBucket
    n_buys: int
    weight: Decimal
    weight_share: Decimal
    value: Optional[Decimal]


@dataclass(frozen=True)
class WalletScore:
    """The full answer, of which :class:`contracts.BuyQuality` is the seam-shaped summary.

    The seam type carries what the rest of the pipeline consumes; this carries what a reviewer needs
    to reproduce it — the raw weight totals, the per-bucket counts and weights, the USD behind each
    value basis, and how many buys arrived with no basis recorded at all.
    """

    wallet: str
    n_buys: int
    total_weight: Decimal
    value: Decimal
    buckets: Tuple[BucketBreakdown, ...]
    realized_usd: Decimal
    marked_usd: Decimal
    dead_usd: Decimal
    basis_total_usd: Decimal
    #: Buys whose realized/marked/dead amounts were all zero. They still weigh on the score, so a
    #: non-zero count here means the §10 mix describes less volume than the score does.
    basis_unaccounted_buys: int = 0

    @property
    def realized_share(self):
        return divide(self.realized_usd, self.basis_total_usd)

    @property
    def marked_share(self):
        return divide(self.marked_usd, self.basis_total_usd)

    @property
    def dead_share(self):
        return divide(self.dead_usd, self.basis_total_usd)

    @property
    def bucket_weights(self):
        """Each bucket's share of total buy weight. Weightless buckets are absent, not zero."""
        return {b.bucket: b.weight_share for b in self.buckets if b.value is not None}

    @property
    def bucket_values(self):
        """Each bucket's own buy quality. Same keys as :attr:`bucket_weights`, by construction."""
        return {b.bucket: b.value for b in self.buckets if b.value is not None}

    @property
    def quality(self):
        """The frozen-seam view — everything the rest of the pipeline is allowed to read."""
        return BuyQuality(
            wallet=self.wallet,
            value=self.value,
            n_buys=self.n_buys,
            realized_share=self.realized_share,
            marked_share=self.marked_share,
            dead_share=self.dead_share,
            bucket_weights=self.bucket_weights,
            bucket_values=self.bucket_values,
        )


def buy_quality(outcomes, wallet):
    """§4.4's wallet-level score, as :class:`contracts.BuyQuality`.

    Use :func:`buy_quality_detail` for the per-bucket weights, counts, and USD totals behind it.
    """
    return buy_quality_detail(outcomes, wallet).quality


def buy_quality_detail(outcomes, wallet):
    """:func:`buy_quality`, with everything a reviewer needs to reproduce the number."""
    items = tuple(outcomes)
    for item in items:
        if not isinstance(item, BuyOutcome):
            raise TypeError(
                "scoring consumes BuyOutcome, got {}. Build them with buy_outcome() so the log "
                "weight is computed once rather than by every caller.".format(type(item).__name__)
            )
    if not items:
        raise UnscorableWallet(
            "wallet {} has no buys in this window. A buy quality of zero would read as flat "
            "performance; the absence of a measurement is not a measurement of zero.".format(wallet)
        )

    with localcontext(CALCULATION_CONTEXT):
        total_weight = ZERO
        realized = ZERO
        marked = ZERO
        dead = ZERO
        unaccounted = 0
        for item in items:
            total_weight += item.weight
            realized += item.realized_usd
            marked += item.marked_usd
            dead += item.dead_usd
            if item.realized_usd == 0 and item.marked_usd == 0 and item.dead_usd == 0:
                unaccounted += 1
        basis_total = +(realized + marked + dead)
        total_weight = +total_weight

    if total_weight == 0:
        raise UnscorableWallet(
            "every one of wallet {}'s {} buys priced at zero, so the total log weight is zero and "
            "the weighted mean has no denominator. This is a pricing failure to find, not a score "
            "to report.".format(wallet, len(items))
        )
    if basis_total == 0:
        raise UnscorableWallet(
            "wallet {} has {} buys but no realized, marked, or dead value recorded against any of "
            "them. §10 requires the mix reported alongside the score, and the only alternative "
            "here is to invent three shares that sum to one.".format(wallet, len(items))
        )

    value = weighted_mean((item.weight, item.return_pct) for item in items)
    buckets = _bucket_breakdowns(items, total_weight)

    return WalletScore(
        wallet=wallet,
        n_buys=len(items),
        total_weight=total_weight,
        value=value,
        buckets=buckets,
        realized_usd=realized,
        marked_usd=marked,
        dead_usd=dead,
        basis_total_usd=basis_total,
        basis_unaccounted_buys=unaccounted,
    )


def _bucket_breakdowns(items, total_weight):
    """One breakdown per §4.7 bucket, always all four, always in :data:`BUCKET_ORDER`.

    Every bucket appears even when empty, so a reader can tell "no first-hour buys" from "first-hour
    buys not reported". Only the ones carrying weight reach the seam dicts.
    """
    grouped = {bucket: [] for bucket in BUCKET_ORDER}
    for item in items:
        if item.bucket not in grouped:
            raise ValueError(
                "buy {} carries bucket {!r}, which is not one of the four §4.7 buckets".format(
                    item.buy.tx_hash, item.bucket
                )
            )
        grouped[item.bucket].append(item)

    breakdowns = []
    for bucket in BUCKET_ORDER:
        members = grouped[bucket]
        with localcontext(CALCULATION_CONTEXT):
            weight = ZERO
            for member in members:
                weight += member.weight
            weight = +weight
        if weight == 0:
            # No buys, or buys that all priced at zero. Either way there is no bucket-level
            # weighted mean, and the share is zero because the numerator is.
            breakdowns.append(
                BucketBreakdown(
                    bucket=bucket, n_buys=len(members), weight=ZERO, weight_share=ZERO, value=None
                )
            )
            continue
        breakdowns.append(
            BucketBreakdown(
                bucket=bucket,
                n_buys=len(members),
                weight=weight,
                weight_share=divide(weight, total_weight),
                value=weighted_mean((m.weight, m.return_pct) for m in members),
            )
        )
    return tuple(breakdowns)
