"""Marking — what an open or dead position is actually worth. §4.4 Case 2/3, §4.7, addendum §9.

    Marked Value = min(Remaining x Pool Exit Price, Extractable Given Real Liquidity)

Three rules do all the work here, and each exists because the obvious alternative is wrong in a
specific, measured way:

**The liquidity bound is mandatory.** With 88% of new Uniswap V2 tokens reported as honeypots, a
thin-but-live pool marked at spot is fiction. $50,000 of a token whose pool holds $2,000 is not
$50,000. So the exit is walked along the real curve for the actual quantity, never spot x
quantity.

**A dead pool is zero, and death needs all three conditions.** No successful swap for 30 days AND
an executable exit below the minimum threshold AND no validated replacement pool. Never a stale
or forward-filled price: Dune forward-fills up to 30 days, showing a rugged token as flat rather
than -100%, which systematically flatters wallets that buy garbage. Each condition failing alone
must not zero — a pool can be quiet and still exitable, and a token can migrate to a live pool.

**Unmodelled is not dead.** A pool no depth model fits raises
:class:`~marking.liquidity.UnmodelledPoolError` rather than returning zero. Zero because dead is a
measurement; zero because unmodelled is the absence of one.

Token age (§4.7) runs from first usable liquidity plus one real swap, not contract creation, and
**migration does not reset it**.

Everything in this package is a pure function of its arguments: no network, no file I/O, no
clock, no global state.
"""

from .age import BUCKET_A_BLOCKS, DAY_SECONDS, HOUR_SECONDS, token_age_bucket
from .liquidity import (
    BPS,
    MODEL_CONSTANT_PRODUCT,
    MODEL_VIRTUAL_RESERVES,
    Q96,
    UnmodelledPoolError,
    average_exit_price,
    effective_reserves,
    exit_value_usd,
    multiply,
    shortfall_vs_spot,
    spot_exit_price,
    spot_value_usd,
)
from .mark import mark_position
from .pools import (
    DEAD_INACTIVITY_SECONDS,
    MARKING_TOLERANCE,
    MINIMUM_EXIT_VALUE_USD,
    THIN_SHORTFALL_RATIO,
    QuoteAssetMismatch,
    inactivity_seconds,
    is_inactive,
    require_no_lookahead,
    require_same_quote_asset,
    validate_replacement,
)

__all__ = [
    "BPS",
    "BUCKET_A_BLOCKS",
    "DAY_SECONDS",
    "DEAD_INACTIVITY_SECONDS",
    "HOUR_SECONDS",
    "MARKING_TOLERANCE",
    "MINIMUM_EXIT_VALUE_USD",
    "MODEL_CONSTANT_PRODUCT",
    "MODEL_VIRTUAL_RESERVES",
    "Q96",
    "THIN_SHORTFALL_RATIO",
    "QuoteAssetMismatch",
    "UnmodelledPoolError",
    "average_exit_price",
    "effective_reserves",
    "exit_value_usd",
    "inactivity_seconds",
    "is_inactive",
    "mark_position",
    "multiply",
    "require_no_lookahead",
    "require_same_quote_asset",
    "shortfall_vs_spot",
    "spot_exit_price",
    "spot_value_usd",
    "token_age_bucket",
    "validate_replacement",
]
