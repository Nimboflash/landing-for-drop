"""Assets, statuses, and typed errors — the vocabulary every module shares.

Seam rules, applied everywhere in this package:

    Raw token quantities  -> int only
    USD and ratios        -> Decimal only, never float
    Timestamps            -> UTC seconds, always paired with a block number
    Missing/indeterminate -> explicit None or a typed status, never a sentinel number
    Errors                -> typed exception or a quarantine record, never a silent drop

The fourth rule is the one that earns its keep. A ``$0`` because a pool is dead and a ``$0``
because no model supports the pool are different facts, and collapsing them into the same float
is how a modelling decision gets read downstream as a measurement.
"""

from decimal import Decimal
from enum import Enum

# -- assets ---------------------------------------------------------------------
# Pre-registration §4.6: USD prices are used ONLY for liquid quote assets. No oracle is required
# for long-tail tokens — the single most important robustness decision in the metric, because
# long-tail price data was measured at 21.6% coverage on one vendor and forward-filled for 30 days
# on another.

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
WBTC = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"

#: Native ETH sentinel. §4.2 requires ETH and WETH to be collapsed *before* netting, or a route
#: that enters in ETH and leaves in WETH nets to two endpoints that are really one asset.
NATIVE_ETH = "0x0000000000000000000000000000000000000000"

QUOTE_ASSETS = frozenset({WETH, USDC, USDT, WBTC})


class AssetTier(str, Enum):
    MAJOR = "major"
    MID_CAP = "mid_cap"
    LONG_TAIL = "long_tail"


#: §4.5 / addendum §9.5. Long-tail has no entry on purpose — it is excluded from Ethereum Phase 0,
#: and a missing key raises rather than defaulting.
EXECUTION_COST_CAP = {
    AssetTier.MAJOR: Decimal("0.01"),
    AssetTier.MID_CAP: Decimal("0.02"),
}


def normalise_asset(token):
    """Lowercase and collapse native ETH onto WETH."""
    token = (token or "").lower()
    return WETH if token == NATIVE_ETH else token


def is_quote_asset(token):
    return normalise_asset(token) in QUOTE_ASSETS


# -- statuses -------------------------------------------------------------------


class ClassificationStatus(str, Enum):
    """What netting concluded about one transaction.

    Every transaction lands in exactly one of these. There is no ``None`` outcome and no bare
    boolean, because "we produced no trade" has several distinct causes and they are not
    interchangeable when someone later asks why coverage was 94%.
    """

    VALID_BUY = "VALID_BUY"
    VALID_SELL = "VALID_SELL"
    CIRCULAR_ARBITRAGE = "CIRCULAR_ARBITRAGE"
    NO_CLEAR_ENDPOINT = "NO_CLEAR_ENDPOINT"
    ABOVE_TOLERANCE_RESIDUAL = "ABOVE_TOLERANCE_RESIDUAL"
    FAILED_TRANSACTION = "FAILED_TRANSACTION"
    UNSUPPORTED = "UNSUPPORTED"

    @property
    def is_trade(self):
        return self in (ClassificationStatus.VALID_BUY, ClassificationStatus.VALID_SELL)


class AccountType(str, Enum):
    EOA = "EOA"
    SAFE = "SAFE"
    ERC4337 = "ERC4337"
    OTHER_CONTRACT = "OTHER_CONTRACT"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    UNKNOWN = "UNKNOWN"


class AttributionMethod(str, Enum):
    """How ``portfolio_owner`` was arrived at.

    ``TX_SENDER_FALLBACK`` exists so the fallback is **visible**. Dune's core macro contains
    ``coalesce(base_trades.taker, base_trades.tx_from)``, which silently attributes any unmodelled
    project's trade to the transaction sender — the solver, for solver-settled trades. That single
    line produces phantom mega-wallets and erases real users. A fallback here must be recorded as
    one, and §8 excludes uncertain attribution from the primary metric.
    """

    DIRECT_EOA = "DIRECT_EOA"
    SAFE_EXECUTION = "SAFE_EXECUTION"
    ERC4337_SENDER = "ERC4337_SENDER"
    ROUTER_RECIPIENT = "ROUTER_RECIPIENT"
    TX_SENDER_FALLBACK = "TX_SENDER_FALLBACK"
    UNRESOLVED = "UNRESOLVED"


class PoolStatus(str, Enum):
    LIVE = "LIVE"
    THIN = "THIN"
    QUIET = "QUIET"
    DEAD = "DEAD"
    MIGRATED = "MIGRATED"
    UNMODELLED = "UNMODELLED"


class ValueBasis(str, Enum):
    """How a position's value was arrived at. §10 requires the mix to be reported."""

    REALIZED = "REALIZED"
    POOL_MARKED = "POOL_MARKED"
    LIQUIDITY_BOUND = "LIQUIDITY_BOUND"
    DEAD_ZEROED = "DEAD_ZEROED"


class EdgeOriginStatus(str, Enum):
    """§7.1 condition 3.

    ``INDETERMINATE`` is **not a pass**. A window whose edge origin cannot be measured does not
    count toward the three required successes. This is an enum rather than a boolean precisely so
    that no ``if window.passed:`` can quietly absorb it.
    """

    VALID = "VALID"
    UNCOPYABLE_DOMINATED = "UNCOPYABLE_DOMINATED"
    INDETERMINATE = "INDETERMINATE"

    @property
    def passes(self):
        return self is EdgeOriginStatus.VALID


class TokenAgeBucket(str, Enum):
    """§4.7. Age runs from first usable liquidity plus one real swap — not contract creation —
    and a pool migration does not reset it."""

    A = "A"  # first 10 blocks
    B = "B"  # after 10 blocks, through end of hour 1
    C = "C"  # after hour 1, through hour 24
    D = "D"  # older than 24 hours


FIRST_HOUR_BUCKETS = (TokenAgeBucket.A, TokenAgeBucket.B)


class GateOutcome(str, Enum):
    GO = "GO"
    CONDITIONAL_REVIEW = "CONDITIONAL_REVIEW"
    STOP = "STOP"


class ValidationStatus(str, Enum):
    """Addendum §3. ``NOT_INDEPENDENT`` blocks the main test through governance, not through a note.

    ``MACHINE_INDEPENDENT`` is genuinely better than ``NOT_INDEPENDENT`` and genuinely weaker than
    ``EXTERNALLY_REVIEWED``: two agents from the same base model make *correlated* errors, which is
    exactly the failure class independent validation exists to catch.
    """

    MACHINE_INDEPENDENT = "MACHINE_INDEPENDENT"
    EXTERNALLY_REVIEWED = "EXTERNALLY_REVIEWED"
    NOT_INDEPENDENT = "NOT_INDEPENDENT"

    @property
    def permits_main_test(self):
        return self is not ValidationStatus.NOT_INDEPENDENT


# -- errors ---------------------------------------------------------------------


class ContractError(Exception):
    """Base for every typed refusal in the pipeline."""


class LongTailExcludedError(ContractError):
    """A long-tail asset reached a module that has no model for it.

    Deliberately an exception rather than ``capacity = 0``. **Zero capacity is a valid measured
    result; excluded scope is a modelling decision.** Measured Ethereum long-tail capacity really
    was $0 at every assumed edge level — so a returned zero here would be indistinguishable from a
    finding, and would flow downstream looking like one.
    """


class AttributionUnresolvedError(ContractError):
    """The economic owner could not be established and must not be guessed."""


class QuarantineRequired(ContractError):
    """The input is real but unsupported; it belongs in the reconciliation queue.

    Distinct from a hard error: the failure policy says an *unsupported population event* is
    quarantined and reported, while an *unexplained dropped event* is prohibited outright.
    """


class LookAheadViolation(ContractError):
    """A feature computed after T0 reached a pre-T0 decision.

    The nastiest bug class in the project: it leaves the code perfectly pleased with itself while
    invalidating every number downstream of it.
    """


class FreezeViolation(ContractError):
    """A value was read or written in a way the freeze manifest does not permit."""
