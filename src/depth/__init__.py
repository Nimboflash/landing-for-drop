"""Depth, the copier penalty, and the largest economically executable follower order.

Pre-registration §4.5 · addendum §9.4, §9.5, §9.6 · ticket 30.

This package converts a leader's trade into a follower's outcome, on pool states whose answers are
known before the code runs. Three things it deliberately does not do:

* it never prices the token being bought — only the quote asset carries a USD price (§4.6);
* it never returns a number for a size its depth model does not support (:class:`OutsideValidityBand`);
* it never returns ``capacity = 0`` for a long-tail asset (:class:`contracts.LongTailExcludedError`).

The last one is the sharpest line in the package. **Zero capacity is a measured result; excluded
scope is a modelling decision.** Measured Ethereum long-tail capacity really was $0 at every
assumed edge level, so returning a zero for an out-of-scope asset would place a modelling choice in
a results table wearing the clothes of a finding.

A pool that is merely too thin for the requested size is the opposite case, and is reported as
``copyable=False`` with a ``rejection_reason``: that *is* a measurement, and it must never raise.
"""

from .amm import (  # noqa: F401
    CONCENTRATED_BAND_MAX_SLIPPAGE,
    MAX_TVL_UNDERSTATEMENT_FACTOR,
    MEASURED_PEPE_1PCT_ROUTED_USD,
    MEASURED_PEPE_1PCT_SINGLE_POOL_USD,
    MEASURED_SIZE_RATIO_10PCT_OVER_1PCT,
    MEASURED_TVL_UNDERSTATEMENT,
    MODEL_SIZE_RATIO_10PCT_OVER_1PCT,
    Q96,
    DepthMeasurement,
    DepthModel,
    OutsideValidityBand,
    PricedPool,
    QuoteAsset,
    ValidityBand,
    average_slippage,
    copier_penalty,
    copier_slippage,
    execution_price_ratio,
    linear_copier_slippage,
    marginal_impact,
    measure_depth,
    own_price_impact,
    raw_to_usd,
    size_for_slippage,
    virtual_reserves,
)
from .execution import (  # noqa: F401
    BISECTION_TOLERANCE_USD,
    MAX_BISECTION_ITERATIONS,
    CostBreakdown,
    ExecutionQuote,
    SizingDidNotConverge,
    SizingResult,
    cost_cap_for,
    quote_execution,
    size_to_cost_cap,
    size_to_cost_cap_detail,
)
from .orderbook import (  # noqa: F401
    MIN_FILL_RATIO,
    ExecutionSource,
    OrderBook,
    OrderBookFill,
    OrderBookLevel,
    PrivateLiquidityExcluded,
    best_public_execution,
    public_sources,
    walk_order_book,
)

__all__ = [n for n in dir() if not n.startswith("_")]
