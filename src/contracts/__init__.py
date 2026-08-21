"""The frozen seam.

Every pipeline module consumes and produces these types and nothing else, which is what lets each
be built and tested in isolation — and lets the Independent Validator re-derive the same answers
from a different implementation without sharing a line of interpretation code.

Seam rules:

    Raw token quantities  -> int only
    USD and ratios        -> Decimal only, never float
    Timestamps            -> UTC seconds, always paired with a block number
    Missing/indeterminate -> explicit None or a typed status, never a sentinel number
    Errors                -> typed exception or a quarantine record, never a silent drop

This package is *shared*: it belongs to neither the builder lane nor the validator lane, and it
interprets no chain bytes. ``tests/test_lane_independence.py`` enforces that.
"""

from .core import (  # noqa: F401
    EXECUTION_COST_CAP,
    FIRST_HOUR_BUCKETS,
    NATIVE_ETH,
    QUOTE_ASSETS,
    USDC,
    USDT,
    WBTC,
    WETH,
    AccountType,
    AssetTier,
    AttributionMethod,
    AttributionUnresolvedError,
    ClassificationStatus,
    ContractError,
    EdgeOriginStatus,
    FreezeViolation,
    GateOutcome,
    LongTailExcludedError,
    LookAheadViolation,
    PoolStatus,
    QuarantineRequired,
    TokenAgeBucket,
    ValidationStatus,
    ValueBasis,
    is_quote_asset,
    normalise_asset,
)
from .metrics import (  # noqa: F401
    MATCHING_DIMENSIONS,
    SMD_BALANCE_TARGET,
    BuyOutcome,
    BuyQuality,
    CopySimulation,
    CovariateBalance,
    FreezeManifest,
    GateDecision,
    MatchedSet,
    PermutationResult,
    PoolState,
    PositionValue,
    WindowScore,
)
from .numeric import (  # noqa: F401
    CALCULATION_CONTEXT,
    NUMERIC_POLICY_VERSION,
    REPORTING_SCALES,
    REPORTING_SCHEMA_VERSION,
    COMPARISON_TOLERANCE,
    INTERNAL_PRECISION,
    ROUNDING,
    SCALE_PERCENTAGE_POINTS,
    SCALE_RATIO,
    SCALE_USD,
    add,
    calc,
    divide,
    mul,
    sub,
    is_finite,
    quantize_pp,
    quantize_ratio,
    quantize_usd,
    require_finite,
)
from .serialization import (  # noqa: F401
    ENUM_SCHEMA_VERSION,
    DerivedFieldMismatch,
    verify_redundant_derived,
    TIMESTAMP_FORMAT,
    artifact_envelope,
    canonical_hash,
    canonicalise,
    format_timestamp,
    to_canonical_json,
)
from .trades import (  # noqa: F401
    Attribution,
    FifoResult,
    Lot,
    LotConsumption,
    NetDelta,
    NetTradeResult,
    Transaction,
    Transfer,
)

__all__ = [n for n in dir() if not n.startswith("_")]
