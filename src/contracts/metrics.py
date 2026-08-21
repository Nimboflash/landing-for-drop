"""Marking, scoring, copy simulation, matching, the null, and the gate decision."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional, Tuple

from .core import (
    AssetTier,
    EdgeOriginStatus,
    GateOutcome,
    PoolStatus,
    TokenAgeBucket,
    ValidationStatus,
    ValueBasis,
)
from .numeric import NUMERIC_POLICY_VERSION, REPORTING_SCHEMA_VERSION, add, divide, sub
from .trades import NetTradeResult

# -- marking --------------------------------------------------------------------


@dataclass(frozen=True)
class PoolState:
    """Enough of a pool to price an exit and bound it by real liquidity."""

    address: str
    asset: str
    quote: str
    asset_reserve_raw: int
    quote_reserve_raw: int
    last_swap_block: int
    last_swap_timestamp: int
    fee_bps: int = 30
    #: Uniswap v3/v4 only. Total TVL *understates* near-spot depth for concentrated pools —
    #: by 5-23x measured — it does not overstate it, which is the opposite of the usual assumption.
    active_liquidity: Optional[int] = None
    sqrt_price_x96: Optional[int] = None


@dataclass(frozen=True)
class PositionValue:
    """The value of a position, and how that value was arrived at.

    Never return only a number. ``$0`` because the pool is dead and ``$0`` because no model
    supports the pool are not the same fact, and ``value_basis`` plus ``pool_status`` is what keeps
    them apart downstream.
    """

    value_usd: Decimal
    value_basis: ValueBasis
    executable_quantity: int
    pool_status: PoolStatus
    evidence: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if self.value_usd < 0:
            raise ValueError("a position value cannot be negative")
        if self.executable_quantity < 0:
            raise ValueError("executable quantity cannot be negative")
        if self.value_basis is ValueBasis.DEAD_ZEROED and self.value_usd != 0:
            raise ValueError("DEAD_ZEROED must carry exactly zero value")
        if not self.evidence:
            raise ValueError(
                "a position value must carry evidence; an unexplained mark cannot be audited "
                "against the golden set"
            )


# -- scoring --------------------------------------------------------------------


@dataclass(frozen=True)
class BuyOutcome:
    """One buy's 30-day outcome — the atom ``buy_quality`` is built from."""

    buy: NetTradeResult
    return_pct: Decimal
    weight: Decimal  # log(1 + trade_value_usd)
    realized_usd: Decimal
    marked_usd: Decimal
    dead_usd: Decimal
    bucket: TokenAgeBucket

    def __post_init__(self):
        if self.weight < 0:
            raise ValueError("weight cannot be negative")


@dataclass(frozen=True)
class BuyQuality:
    """A wallet's ``buy_quality_30d`` plus the shares §10 requires reported.

    The shares are not decoration. If only 20% of volume is realized and 80% rests on marking,
    the gate result lacks credibility however positive it looks — and the only way to know is to
    carry the mix alongside the score.
    """

    wallet: str
    value: Decimal
    n_buys: int
    realized_share: Decimal
    marked_share: Decimal
    dead_share: Decimal
    bucket_weights: Dict[TokenAgeBucket, Decimal] = field(default_factory=dict)
    bucket_values: Dict[TokenAgeBucket, Decimal] = field(default_factory=dict)

    def __post_init__(self):
        # Summed and compared under the frozen context. Bare ``+`` and ``abs()`` round to the
        # ambient 28 digits, so this invariant would be checked on a truncated value — the same
        # shape as the defect that shipped in ``realized_return``. No realistic flip here (the
        # tolerance is 1e-4, twenty-four orders of magnitude above the truncation), but the rule
        # is that the seam does not contain the pattern it exists to forbid.
        total = add(add(self.realized_share, self.marked_share), self.dead_share)
        if self.n_buys and sub(total, Decimal("1")).copy_abs() > Decimal("0.0001"):
            raise ValueError("value-basis shares must sum to 1, got {}".format(total))


@dataclass(frozen=True)
class WindowScore:
    """One walk-forward window's result for one column (leader or follower-adjusted).

    ``first_hour_edge_share`` is ``Optional`` on purpose. Returning ``Decimal("0")`` when the
    denominator is too small would silently convert an unmeasurable window into a passing one —
    the single most dangerous possible bug in the scoring path.
    """

    window: int
    column: str  # "leader" | "follower_adjusted"
    mean_advantage: Decimal
    median_advantage: Decimal
    first_hour_edge_share: Optional[Decimal]
    positive_edge_contribution: Decimal
    edge_origin_status: EdgeOriginStatus

    def __post_init__(self):
        if self.edge_origin_status is EdgeOriginStatus.INDETERMINATE:
            if self.first_hour_edge_share is not None:
                raise ValueError("INDETERMINATE must not carry a share value")
        elif self.first_hour_edge_share is None:
            raise ValueError(
                "a measurable window must carry a share; None is reserved for INDETERMINATE"
            )

    def passes(self, mean_threshold):
        """All three §7.1 conditions. INDETERMINATE can never satisfy this."""
        return (
            self.edge_origin_status.passes
            and self.mean_advantage >= mean_threshold
            and self.median_advantage > 0
        )


# -- copy simulation ------------------------------------------------------------


@dataclass(frozen=True)
class CopySimulation:
    """What a follower at one capital level would actually have got.

    ``copyable=False`` with a ``rejection_reason`` is a *measured* outcome. A long-tail asset is
    not — that raises ``LongTailExcludedError``, because excluded scope is a modelling decision and
    must never be reported as a measurement.
    """

    capital_level: Decimal
    tier: AssetTier
    intended_order_usd: Decimal
    filled_order_usd: Decimal
    execution_cost_pct: Decimal
    follower_return: Optional[Decimal]
    copyable: bool
    rejection_reason: Optional[str] = None

    def __post_init__(self):
        if self.tier is AssetTier.LONG_TAIL:
            raise ValueError(
                "long-tail assets are excluded from Ethereum Phase 0; raise "
                "LongTailExcludedError rather than constructing a simulation for one"
            )
        if not self.copyable and self.rejection_reason is None:
            raise ValueError("a non-copyable simulation must say why")
        if self.copyable and self.follower_return is None:
            raise ValueError("a copyable simulation must carry a return")
        # Guaranteed here so ``fill_ratio`` stays pure algebra. A derived field that clamped, or
        # returned 1 on a zero denominator, would be encoding a policy about what an impossible
        # order means — and that policy belongs in depth, where it can be frozen and mutated.
        if self.intended_order_usd <= 0:
            raise ValueError(
                "intended_order_usd must be > 0; an order of zero size is not a simulation "
                "outcome, it is a caller error"
            )
        if not (Decimal("0") <= self.filled_order_usd <= self.intended_order_usd):
            raise ValueError(
                "filled_order_usd must lie in [0, intended_order_usd]; got {} against {}. "
                "Over-fill is rejected at construction rather than clamped, because a clamp "
                "would hide the modelling error that produced it.".format(
                    self.filled_order_usd, self.intended_order_usd
                )
            )

    @property
    def fill_ratio(self):
        """Algebraic projection over validated stored fields. See ``LotConsumption`` for the
        shared ``derived_field`` contract."""
        return divide(self.filled_order_usd, self.intended_order_usd)


# -- matching and the null ------------------------------------------------------

#: §6.6. Matching uses pre-T0 information only. A single forward-period feature here creates
#: look-ahead bias while leaving the code perfectly pleased with itself.
MATCHING_DIMENSIONS = (
    "account_type",
    "capital_deployed",
    "valid_buy_count",
    "buy_volume",
    "active_days",
    "wallet_age",
    "median_trade_size",
    "trade_frequency",
    "liquidity_band_exposure",
    "first_hour_purchase_share",
)

#: §6.6 target. Borrowed from the causal-inference literature, where it is the standard bar.
SMD_BALANCE_TARGET = Decimal("0.10")


@dataclass(frozen=True)
class MatchedSet:
    """One selected wallet and its controls. The unit the permutation null shuffles within."""

    selected: str
    primary_controls: Tuple[str, ...]
    robustness_controls: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "primary_controls", tuple(self.primary_controls))
        object.__setattr__(self, "robustness_controls", tuple(self.robustness_controls))
        if self.selected in self.primary_controls:
            raise ValueError("a wallet cannot be its own control")

    @property
    def members(self):
        return (self.selected,) + self.primary_controls


@dataclass(frozen=True)
class CovariateBalance:
    """Per-dimension standardised mean differences, plus whether the set clears the target."""

    smd: Dict[str, Decimal]
    unique_controls: int
    control_reuse_rate: Decimal
    effective_sample_size: Decimal
    unmatched_selected: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "unmatched_selected", tuple(self.unmatched_selected))
        unknown = set(self.smd) - set(MATCHING_DIMENSIONS)
        if unknown:
            raise ValueError("unknown matching dimension(s): {}".format(", ".join(sorted(unknown))))

    @property
    def balanced(self):
        # ``copy_abs()`` rather than ``abs()``: it copies the sign without consulting the ambient
        # context, so a 38-digit SMD is compared to the target at full precision. ``abs()`` would
        # round to 28 first, and a value within 1e-28 of the target would flip.
        return all(v.copy_abs() < SMD_BALANCE_TARGET for v in self.smd.values())

    @property
    def worst_dimension(self):
        if not self.smd:
            return None
        return max(self.smd.items(), key=lambda kv: abs(kv[1]))


@dataclass(frozen=True)
class PermutationResult:
    """The null distribution for one column, and the observed result's position in it."""

    column: str
    observed_statistic: Decimal
    null_statistics: Tuple[Decimal, ...]
    n_runs: int
    percentile_95: Decimal
    empirical_p: Decimal
    null_pass_rate: Decimal

    def __post_init__(self):
        object.__setattr__(self, "null_statistics", tuple(self.null_statistics))
        if len(self.null_statistics) != self.n_runs:
            raise ValueError(
                "n_runs is {} but {} statistics were supplied".format(
                    self.n_runs, len(self.null_statistics)
                )
            )

    @property
    def significant(self):
        """§7.3: the observed result must clear the 95th percentile, p <= 0.05."""
        return self.observed_statistic > self.percentile_95 and self.empirical_p <= Decimal("0.05")


# -- the gate -------------------------------------------------------------------


@dataclass(frozen=True)
class FreezeManifest:
    """§9.6. Everything pinned before the null runs."""

    source_commit: str
    dataset_snapshot: str
    golden_set_version: str
    protocol_coverage_version: str
    decoder_version: str
    model_version: str
    config_hash: str
    master_seed: str
    known_answer_fixture_hash: str
    validation_report_hash: str
    #: Versioned separately from the reporting schema: one governs how numbers are computed and
    #: compared, the other how they are displayed. Collapsing them makes a formatting change look
    #: like a substantive one, or hides it entirely.
    numeric_policy_version: str = NUMERIC_POLICY_VERSION
    reporting_schema_version: str = REPORTING_SCHEMA_VERSION


@dataclass(frozen=True)
class GateDecision:
    """The terminal output. Emitted by ``gate_validation`` and by nothing else.

    No module returns a gate decision independently. The decision is produced only after every
    required module version, validation status, dataset hash, and threshold has been confirmed
    against the freeze manifest — which is why the manifest is a required field rather than a
    reference.
    """

    outcome: GateOutcome
    windows_passed: int
    windows_total: int
    leader_significant: bool
    follower_significant: bool
    validation_status: ValidationStatus
    manifest: FreezeManifest
    capital_feasibility_failed: bool = False
    reasons: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "reasons", tuple(self.reasons))
        if not self.validation_status.permits_main_test:
            raise ValueError(
                "a gate decision cannot be emitted while validation status is NOT_INDEPENDENT; "
                "the main test was not authorised to run"
            )
        if self.outcome is GateOutcome.GO and self.capital_feasibility_failed:
            raise ValueError(
                "capital feasibility failed, so the outcome is CONDITIONAL_REVIEW, not GO — a "
                "positive raw edge may not conceal an execution-capacity failure"
            )
        if not self.reasons:
            raise ValueError("a gate decision must carry its reasons")
