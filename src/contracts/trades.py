"""Attribution, raw movements, netting output, and FIFO lots."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional, Tuple

from .numeric import divide, sub
from .core import (
    AccountType,
    AttributionMethod,
    ClassificationStatus,
    TokenAgeBucket,
    normalise_asset,
)


@dataclass(frozen=True)
class Attribution:
    """Who a transaction economically belongs to, and how confident we are.

    ``tx_sender`` and ``portfolio_owner`` are separate fields and neither may overwrite the other
    (amendment A6.1). Allium keeps ``from_address`` and ``swapper_address`` apart; Dune collapses
    them in one direction and CoW's model collapses them in the other. Both directions of that
    error exist in the same public dataset.
    """

    tx_hash: str
    tx_sender: str
    portfolio_owner: Optional[str]
    account_type: AccountType
    method: AttributionMethod
    confidence: Decimal
    evidence: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "tx_sender", (self.tx_sender or "").lower())
        if self.portfolio_owner is not None:
            object.__setattr__(self, "portfolio_owner", self.portfolio_owner.lower())
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if not (Decimal("0") <= self.confidence <= Decimal("1")):
            raise ValueError("confidence must be in [0, 1]")
        if self.method is AttributionMethod.UNRESOLVED and self.portfolio_owner is not None:
            raise ValueError("UNRESOLVED attribution must not carry an owner")

    @property
    def is_fallback(self):
        """True when the owner is only the transaction sender by default.

        §8 excludes uncertain owner attribution from the primary metric. Callers must branch on
        this rather than treating a fallback owner as established.
        """
        return self.method is AttributionMethod.TX_SENDER_FALLBACK

    @property
    def is_usable_for_primary_metric(self):
        return (
            self.portfolio_owner is not None
            and not self.is_fallback
            and self.account_type is not AccountType.INFRASTRUCTURE
            and self.account_type is not AccountType.UNKNOWN
        )


@dataclass(frozen=True)
class Transfer:
    """One token movement inside a transaction, from a log or a trace.

    ``raw_amount`` is unsigned; direction lives in from/to. Raw units end to end — §9.2 requires
    raw quantities to match a hand trace exactly, and a float anywhere in the chain makes that
    unsatisfiable.
    """

    token: str
    from_addr: str
    to_addr: str
    raw_amount: int
    log_index: int
    is_fee: bool = False

    def __post_init__(self):
        object.__setattr__(self, "token", normalise_asset(self.token))
        object.__setattr__(self, "from_addr", (self.from_addr or "").lower())
        object.__setattr__(self, "to_addr", (self.to_addr or "").lower())
        if not isinstance(self.raw_amount, int):
            raise TypeError("raw_amount must be int, not {}".format(type(self.raw_amount).__name__))
        if self.raw_amount < 0:
            raise ValueError("Transfer.raw_amount is unsigned; direction is from/to")


@dataclass(frozen=True)
class Transaction:
    tx_hash: str
    block_number: int
    timestamp: int  # UTC seconds, paired with block_number
    success: bool
    attribution: Attribution
    transfers: Tuple[Transfer, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "transfers", tuple(self.transfers))

    @property
    def portfolio_owner(self):
        return self.attribution.portfolio_owner


@dataclass(frozen=True)
class NetDelta:
    """Signed net movement of one token for one owner across one transaction."""

    token: str
    raw: int  # positive = received, negative = sent
    usd: Optional[Decimal] = None


@dataclass(frozen=True)
class NetTradeResult:
    """What netting concluded about one transaction.

    Always returned — there is no path that produces nothing. When ``status`` is not a trade, the
    leg fields are ``None`` and ``reason`` says why, so a coverage report can account for every
    transaction it saw rather than for the ones that happened to succeed.
    """

    tx_hash: str
    portfolio_owner: Optional[str]
    status: ClassificationStatus
    sold_asset: Optional[str] = None
    bought_asset: Optional[str] = None
    sold_raw_amount: Optional[int] = None
    bought_raw_amount: Optional[int] = None
    quote_asset: Optional[str] = None
    quote_usd: Optional[Decimal] = None
    residuals: Tuple[NetDelta, ...] = ()
    block_number: Optional[int] = None
    timestamp: Optional[int] = None
    token_age_bucket: Optional[TokenAgeBucket] = None
    pool: Optional[str] = None
    reason: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "residuals", tuple(self.residuals))
        if self.status.is_trade:
            missing = [
                name for name in ("sold_asset", "bought_asset", "sold_raw_amount",
                                  "bought_raw_amount", "quote_asset")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(
                    "{} requires {}".format(self.status.value, ", ".join(missing))
                )
            if self.sold_raw_amount <= 0 or self.bought_raw_amount <= 0:
                raise ValueError("both legs of a trade must be non-zero")
        elif self.reason is None:
            raise ValueError(
                "{} must carry a reason — an unexplained non-trade is indistinguishable "
                "from a dropped event, which the failure policy prohibits".format(self.status.value)
            )

    @property
    def asset(self):
        """The non-quote side of the trade."""
        if not self.status.is_trade:
            return None
        return (self.bought_asset if self.status is ClassificationStatus.VALID_BUY
                else self.sold_asset)

    @property
    def asset_raw_amount(self):
        if not self.status.is_trade:
            return None
        return (self.bought_raw_amount if self.status is ClassificationStatus.VALID_BUY
                else self.sold_raw_amount)


# -- FIFO -----------------------------------------------------------------------


@dataclass(frozen=True)
class Lot:
    """An open parcel of an asset, created by a buy."""

    buy: NetTradeResult
    remaining_raw: int

    def __post_init__(self):
        if self.remaining_raw < 0:
            raise ValueError("a lot cannot hold a negative quantity")


@dataclass(frozen=True)
class LotConsumption:
    """One sell consuming part or all of one lot — the unit FIFO produces."""

    buy: NetTradeResult
    sell: NetTradeResult
    consumed_raw: int
    allocated_cost_usd: Decimal
    proceeds_usd: Decimal

    def __post_init__(self):
        if self.consumed_raw <= 0:
            raise ValueError("a consumption must consume something")
        # The derived field below must not have to decide what a zero denominator means. That is
        # a domain judgement — mispriced leg? unsupported quote? — and it belongs at construction
        # or in the module that knows. Guaranteeing it here keeps the projection pure algebra.
        if self.allocated_cost_usd <= 0:
            raise ValueError(
                "allocated_cost_usd must be > 0; a zero or negative buy cost makes the return "
                "undefined, and that is a classification the domain module must make rather "
                "than something realized_return silently absorbs"
            )
        if self.proceeds_usd < 0:
            raise ValueError("proceeds_usd cannot be negative")

    @property
    def realized_return(self):
        """Algebraic projection over validated stored fields.

        Contract for a shared ``derived_field``: own immutable fields only, shared numeric
        primitives only, no quantization, no threshold, no branch, no fallback. Identical stored
        fields always yield an identical value. Shared defines mathematical identity; what that
        identity *means* is the domain module's business.
        """
        return sub(divide(self.proceeds_usd, self.allocated_cost_usd), Decimal("1"))


@dataclass(frozen=True)
class FifoResult:
    consumptions: Tuple[LotConsumption, ...]
    open_lots: Tuple[Lot, ...]
    unmatched_sell_raw: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "consumptions", tuple(self.consumptions))
        object.__setattr__(self, "open_lots", tuple(self.open_lots))
