"""§10's per-wallet and per-basket block.

    Realized Share          share of value from actual sells
    Marked Share            share dependent on pool-level marking
    Dead / Zeroed Share     share marked to zero

    "If only 20% of volume is realized and 80% rests on marking, the gate result lacks credibility
    even if it looks strongly positive."

Two things in here are less obvious than the formulas.

**The basket aggregate is value-weighted, and it cannot be computed from the per-wallet reports.**
A wallet's shares are quantized when its report is built; averaging quantized shares would carry
each wallet's rounding error into the aggregate, and the error is a function of that wallet's
magnitude, so a basket of small wallets is biased differently from a basket of large ones. So
:func:`report_basket` takes the **USD amounts**, aggregates them at full precision, and quantizes
the resulting shares once. It refuses to work from :class:`WalletReport` objects at all — the
weights are not in them, and an aggregate of shares without their weights is an unweighted mean
wearing the clothes of a value share.

**The shares that arrive on a** :class:`contracts.BuyQuality` **are checked, not trusted.** When the
caller supplies the USD amounts too, the shares are re-derived from them and a disagreement refuses
the report. This is the same discipline as
:func:`contracts.verify_redundant_derived`: a derived value exported for convenience is a redundant
assertion, and an artifact claiming 20% realized while carrying amounts that imply 80% must be
invalidated rather than reinterpreted.

The basket's buy quality is reported as a plain mean *and* a median across wallets, equal-weighted
per wallet. §7.1 evaluates the mean and the median of the per-wallet advantage for the same reason:
one token returning 1000% can carry a basket in which most buys lost money, and only the pair shows
it.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Tuple

from contracts import (
    COMPARISON_TOLERANCE,
    BuyQuality,
    ContractError,
    TokenAgeBucket,
    add,
    calc,
    require_finite,
    sub,
)

from .aggregate import mean, median, share, total
from .boundary import output_ratio, output_usd

#: §4.7's four buckets in age order — the reporting order, pinned rather than derived so a change
#: to the enum's declaration order cannot silently reorder a published table.
BUCKET_ORDER = (
    TokenAgeBucket.A,
    TokenAgeBucket.B,
    TokenAgeBucket.C,
    TokenAgeBucket.D,
)

if BUCKET_ORDER != tuple(TokenAgeBucket):
    raise ImportError(
        "reporting's bucket order {} disagrees with contracts.TokenAgeBucket {}; the seam owns "
        "the buckets and a report that omits or reorders one is describing a different "
        "population".format(BUCKET_ORDER, tuple(TokenAgeBucket))
    )


class UnreportableBasket(ContractError):
    """The value basis cannot support the §10 shares, and three that sum to one will not be invented."""


class InconsistentValueBasis(ContractError):
    """A score's shares disagree with the USD amounts they claim to summarise."""


@dataclass(frozen=True)
class ValueBasisAmounts:
    """The USD behind §10's three shares, at full precision.

    Amounts rather than shares, because shares cannot be aggregated without them. Kept unquantized
    on purpose: this is an *input* to the boundary, not an output of it.

    The three are the portions of accounted value attributable to each basis — realized proceeds,
    the liquidity-bounded mark for what is still open, and, for a dead pool, the exposure the zero
    verdict decides. The last one is the exposure and not the resulting value, because §4.4 Case 3
    marks a dead position at exactly zero: reading it as the outcome value would make the dead share
    structurally zero and delete the one basis §10 most wants visible.
    """

    realized_usd: Decimal
    marked_usd: Decimal
    dead_usd: Decimal

    def __post_init__(self):
        for name in ("realized_usd", "marked_usd", "dead_usd"):
            amount = require_finite(calc(getattr(self, name)), name)
            if amount < 0:
                raise UnreportableBasket(
                    "{} is {}; a negative value basis would let one position erase another's "
                    "provenance from the §10 mix".format(name, amount)
                )
            object.__setattr__(self, name, amount)
        if self.total_usd == 0:
            raise UnreportableBasket(
                "no realized, marked, or dead value was recorded. §10 requires the mix reported "
                "alongside the score, and the only alternative here is to invent three shares "
                "that sum to one."
            )

    @property
    def total_usd(self):
        return add(add(self.realized_usd, self.marked_usd), self.dead_usd)

    @property
    def realized_share(self):
        return share(self.realized_usd, self.total_usd, "realized share")

    @property
    def marked_share(self):
        return share(self.marked_usd, self.total_usd, "marked share")

    @property
    def dead_share(self):
        return share(self.dead_usd, self.total_usd, "dead share")


@dataclass(frozen=True)
class WalletReport:
    """One wallet's §10 line. Every figure here has been through the boundary exactly once."""

    wallet: str
    n_buys: int
    buy_quality: Decimal
    realized_share: Decimal
    marked_share: Decimal
    dead_share: Decimal
    bucket_weights: Dict[TokenAgeBucket, Decimal]
    bucket_values: Dict[TokenAgeBucket, Decimal]


@dataclass(frozen=True)
class BasketReport:
    """§10 aggregated over the selected basket.

    The USD totals travel with the shares. Without them a reader cannot tell a basket that is 80%
    marked because one large position is open from one that is 80% marked because every position is
    — and those are different findings about the same headline number.
    """

    n_wallets: int
    mean_buy_quality: Decimal
    median_buy_quality: Decimal
    realized_share: Decimal
    marked_share: Decimal
    dead_share: Decimal
    realized_usd: Decimal
    marked_usd: Decimal
    dead_usd: Decimal
    total_usd: Decimal
    wallets: Tuple[WalletReport, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "wallets", tuple(self.wallets))
        if len(self.wallets) != self.n_wallets:
            raise ValueError(
                "{} wallet reports were carried for a basket of {}".format(
                    len(self.wallets), self.n_wallets
                )
            )


def _check_shares_against_amounts(quality, amounts):
    """Refuse a score whose shares disagree with the amounts behind them.

    ``copy_abs()`` rather than ``abs()``: it copies the sign without consulting the ambient
    context, so a 38-digit difference is compared to the tolerance at full precision. ``abs()``
    would round to 28 first and admit a disagreement that shows up in the 29th digit — which is
    exactly the size of disagreement this check exists to find, since a large one would have been
    noticed by eye.
    """
    for name, claimed, derived in (
        ("realized_share", quality.realized_share, amounts.realized_share),
        ("marked_share", quality.marked_share, amounts.marked_share),
        ("dead_share", quality.dead_share, amounts.dead_share),
    ):
        if sub(claimed, derived).copy_abs() > COMPARISON_TOLERANCE:
            raise InconsistentValueBasis(
                "wallet {} claims {} = {} while its USD amounts imply {}. A derived value carried "
                "in an artifact is a redundant assertion, not the authority: the artifact is "
                "internally inconsistent and must be invalidated rather than "
                "reinterpreted.".format(quality.wallet, name, claimed, derived)
            )


def report_wallet(quality, value_basis=None):
    """§10's per-wallet line from a :class:`contracts.BuyQuality`.

    :param quality: the wallet's score, carrying the three shares at full precision.
    :param value_basis: optional :class:`ValueBasisAmounts`. When supplied, the shares on
        ``quality`` are re-derived from the amounts and a disagreement refuses the report.

    The shares are taken from ``quality`` in both cases. Supplying the amounts adds a check; it
    does not add a second source of truth.
    """
    if not isinstance(quality, BuyQuality):
        raise TypeError(
            "report_wallet consumes a contracts.BuyQuality, got {}. The seam type is what "
            "guarantees the three shares sum to one and that the score is not a bare number "
            "somebody computed a different way.".format(type(quality).__name__)
        )
    if value_basis is not None:
        if not isinstance(value_basis, ValueBasisAmounts):
            raise TypeError(
                "value_basis must be a ValueBasisAmounts, got {}".format(type(value_basis).__name__)
            )
        _check_shares_against_amounts(quality, value_basis)

    return WalletReport(
        wallet=quality.wallet,
        n_buys=quality.n_buys,
        buy_quality=output_ratio(quality.value, "buy_quality for {}".format(quality.wallet)),
        realized_share=output_ratio(quality.realized_share, "realized_share"),
        marked_share=output_ratio(quality.marked_share, "marked_share"),
        dead_share=output_ratio(quality.dead_share, "dead_share"),
        bucket_weights={
            bucket: output_ratio(quality.bucket_weights[bucket], "bucket weight")
            for bucket in BUCKET_ORDER
            if bucket in quality.bucket_weights
        },
        bucket_values={
            bucket: output_ratio(quality.bucket_values[bucket], "bucket value")
            for bucket in BUCKET_ORDER
            if bucket in quality.bucket_values
        },
    )


def report_basket(entries):
    """§10 aggregated over the selected basket, value-weighted.

    :param entries: an iterable of ``(BuyQuality, ValueBasisAmounts)`` pairs, in a deterministic
        order.

    The amounts are mandatory. A basket share computed from the per-wallet *shares* would be an
    unweighted mean of already-rounded numbers, which is a different statistic reported under §10's
    name — and the difference grows with the spread of wallet sizes, so it is smallest exactly in
    the test fixtures where someone would notice it.
    """
    pairs = tuple(entries)
    if not pairs:
        raise UnreportableBasket(
            "the selected basket is empty. Zero realized share over no wallets reads as 'nothing "
            "was ever sold', which is a finding, and an empty basket is not one."
        )

    seen = set()
    qualities = []
    amounts = []
    for entry in pairs:
        if isinstance(entry, WalletReport):
            raise TypeError(
                "report_basket cannot aggregate WalletReport objects: their shares are already "
                "quantized and their weights are not carried. An aggregate of shares without "
                "their weights is an unweighted mean wearing the clothes of a value share. Pass "
                "(BuyQuality, ValueBasisAmounts) pairs instead."
            )
        try:
            quality, basis = entry
        except (TypeError, ValueError):
            raise TypeError(
                "report_basket consumes (BuyQuality, ValueBasisAmounts) pairs, got {}".format(
                    type(entry).__name__
                )
            )
        if not isinstance(quality, BuyQuality):
            raise TypeError(
                "report_basket consumes contracts.BuyQuality, got {}".format(type(quality).__name__)
            )
        if not isinstance(basis, ValueBasisAmounts):
            raise TypeError(
                "report_basket needs the USD amounts behind each wallet's shares, got {}. Without "
                "them the aggregate cannot be value-weighted.".format(type(basis).__name__)
            )
        if quality.wallet in seen:
            raise UnreportableBasket(
                "wallet {} appears twice in the basket; it would be counted twice in every share "
                "and the duplication is invisible in the result".format(quality.wallet)
            )
        seen.add(quality.wallet)
        _check_shares_against_amounts(quality, basis)
        qualities.append(quality)
        amounts.append(basis)

    realized = total((a.realized_usd for a in amounts), "realized_usd")
    marked = total((a.marked_usd for a in amounts), "marked_usd")
    dead = total((a.dead_usd for a in amounts), "dead_usd")
    basis_total = add(add(realized, marked), dead)

    return BasketReport(
        n_wallets=len(qualities),
        mean_buy_quality=output_ratio(
            mean((q.value for q in qualities), "buy_quality"), "mean_buy_quality"
        ),
        median_buy_quality=output_ratio(
            median((q.value for q in qualities), "buy_quality"), "median_buy_quality"
        ),
        realized_share=output_ratio(share(realized, basis_total, "realized share"), "realized_share"),
        marked_share=output_ratio(share(marked, basis_total, "marked share"), "marked_share"),
        dead_share=output_ratio(share(dead, basis_total, "dead share"), "dead_share"),
        realized_usd=output_usd(realized, "realized_usd"),
        marked_usd=output_usd(marked, "marked_usd"),
        dead_usd=output_usd(dead, "dead_usd"),
        total_usd=output_usd(basis_total, "total_usd"),
        wallets=tuple(
            report_wallet(quality, basis) for quality, basis in zip(qualities, amounts)
        ),
    )


def value_basis(realized_usd, marked_usd, dead_usd):
    """Convenience constructor, so callers do not import the dataclass to build one."""
    return ValueBasisAmounts(
        realized_usd=realized_usd, marked_usd=marked_usd, dead_usd=dead_usd
    )
